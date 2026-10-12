"""
What our modules ask of the line to a machine, in one place.

A Ruida goes through our own transport (`ruida/`); every other laser goes through the
engine's device, spooler and console as before. The modules that talk to a machine —
`machine.py`, `status.py`, `busy.py`, `ruida_upload.py` and `commands.py` — ask a
`MachineLink` and do not care which one answers. See the plan in the working record,
`plannen/2026-10-11-eigen-ruida-verbinding.md`.

Phase 2 is connecting and status, phase 3 a file into the controller's memory
(`send_file`), phase 4 moving the head and the realtime verbs (pause, resume, stop),
phase 5 burning (`start_job`, `job`).
"""

from __future__ import annotations

import threading
import time
import weakref
from typing import Literal, Protocol

#: How a link reads the line. The same three words `StatusReader.connection` has always
#: answered with, plus "connecting" for the moment between asking and knowing.
ConnectionState = Literal["connected", "connecting", "disconnected", "unknown"]

#: What the machine says it is doing, where the link can tell; "unknown" where it cannot.
MachineState = Literal["idle", "moving", "running", "paused", "unknown"]

#: What our own line is carrying, as `busy.the_line_is_in_use` answers it.
LineUse = Literal["burning", "queued", "uploading"]


class SendInterrupted(Exception):
    """
    `send_file` stopped at packet `index` (0-based) and sent nothing after it.

    `on_line` says whether that packet itself went out — handed to the transport, its
    acknowledgement then missing or late — or never left. `stalled` separates "it did
    not come back within the wait" (`True`) from "the line said no or went away"
    (`False`). The caller turns these into its own sentence; `ruida_upload.py` into the
    "N of M blocks" refusals.
    """

    def __init__(self, index: int, *, on_line: bool, stalled: bool, why: str = ""):
        super().__init__(why or f"The file stopped at packet {index}.")
        self.index = index
        self.on_line = on_line
        self.stalled = stalled


class LineTaken(Exception):
    """Another file holds this line, and did not let go within the wait."""


class MachineLink(Protocol):
    #: "ruida" for our own transport, "engine" for the engine's.
    kind: str

    def connect(self) -> dict:
        """Open the line; returns `connection()` once it is known or after a bounded wait."""

    def disconnect(self) -> dict:
        """Close the line and keep it closed until `connect()`; returns `connection()`."""

    def connection(self) -> dict:
        """
        `{"state": ConnectionState, "detail": str | None}` — never raises. A `RuidaLink`
        adds `"warning"` (`{"code", "message", ...}`) only while one stands: today
        `ruida.secondClient`, another program on the same controller (`ruida/monitor.py`).
        """

    def position(self) -> tuple[float, float] | None:
        """
        The head in the device's native units, as `device.native` gives them for the
        engine; `None` when nothing has been read. `StatusReader` converts to mm.
        """

    def machine_state(self) -> MachineState:
        """Never raises; "unknown" when nothing has been read."""

    def line_in_use(self) -> LineUse | None:
        """What our own line is carrying right now, or `None`."""

    #: Whether `send_file` confirms every packet; only then may a file go down it.
    carries_files: bool

    def send_file(self, packets, *, packet_seconds: float = 10.0,
                  claim_seconds: float = 2.0) -> None:
        """
        Send `packets` in order, as one file, each confirmed before the next goes out.

        Returns when the last one is confirmed. Otherwise raises `SendInterrupted` at
        the packet where it stopped — nothing after it is sent, and a packet whose
        acknowledgement went missing is never sent again — or `LineTaken` when another file has held the line for `claim_seconds`.
        `packet_seconds` bounds the wait for one packet. The payloads are the caller's:
        the link frames each as one datagram and knows nothing of what a file is made of.
        While it runs, `line_in_use()` answers "uploading".
        """

    def close(self) -> None:
        """Release everything; bounded, idempotent. Called at shutdown and on a switch."""

    # -- phase 4: moving the head, and the realtime verbs ---------------------------------
    #
    # Coordinates are the design's millimetres, exactly what `machine.py` passed to the
    # console before (`move_absolute 10mm 20mm`); the link converts to the machine. Each
    # call returns once the controller has acknowledged what was sent — not once the head
    # has arrived. A refusal or a lost line raises `ConnectionError` (or `TimeoutError`
    # for an unconfirmed packet); `machine.py` turns that into a coded sentence.

    def motion_capabilities(self) -> dict:
        """
        `{"home", "physical_home", "move", "jog", "frame", "focus", "lock", "unlock",
        "pause", "resume", "stop": bool}` — what this machine can be asked. Replaces
        asking the console whether a command exists.
        """

    def home(self, physical: bool = False) -> None: ...

    def move_to(self, x_mm: float, y_mm: float) -> None: ...

    def move_by(self, dx_mm: float, dy_mm: float) -> None: ...

    def trace(self, corners: list[tuple[float, float]]) -> None:
        """The head along these points in order, laser off: the frame."""

    def focus(self, dz_mm: float) -> None: ...

    def lock(self) -> None: ...

    def unlock(self) -> None: ...

    def pause(self) -> None:
        """Ahead of anything still queued on the line."""

    def resume(self) -> None: ...

    def stop(self) -> None:
        """Ahead of anything still queued on the line; must work while a file is going out."""

    # -- phase 5: burning -------------------------------------------------------------------
    #
    # Only for a link with `carries_jobs`; `EngineLink` keeps today's plan-and-spool path in
    # `CommandRunner` and says False here, so a K40 burns exactly as before.

    carries_jobs: bool

    def start_job(self, rd: bytes, name: str | None = None,
                  estimate_seconds: float | None = None) -> None:
        """
        Stream a complete RD file (`CommandRunner.build_job_bytes()`) to the machine, which
        burns it as it arrives. Returns once streaming has *started* — the file goes out on
        a worker of the link's own — or raises `ConnectionError` with a sentence when it
        cannot start (no line, a file or job already on it). Never resumes a stream that a
        reconnect broke.

        `estimate_seconds` is how long the job's own cut plan says the burn takes
        (`CommandRunner.build_job_bytes`); the link keeps it with the job and hands it
        back in `job()`, so the estimate belongs to the job it was made for.
        """

    def job(self) -> dict | None:
        """
        The job this link last started, or `None` if none:
        `{"name", "phase", "sent", "total", "detail", "started", "finished",
        "estimate_seconds", "running_seconds"}` where `phase` is "sending" | "running" |
        "paused" | "done" | "stopped" | "failed", `sent`/`total` count confirmed packets,
        `started`/`finished` are `time.time()` stamps, `detail` is a sentence for
        "failed"/"stopped", `estimate_seconds` is what `start_job` was given and
        `running_seconds` the time the job has spent in "running" (`BurnClock`). Never
        raises.
        """


class BurnClock:
    """
    The seconds a job has spent burning: in phase "running", and nowhere else.

    What a link that carries jobs counts its job's progress against
    (`StatusReader.line_job_snapshot`). The clock starts at the first "running" — on a
    Ruida the stream's end, 0.1 s after the start for a 12,177-byte raster on the
    KH-5030, which is where the controller is already burning — and stands still
    through "sending" and "paused", so a pause does not eat the estimate. A final
    phase stops it for good. Not thread-safe on its own: the link changes the phase
    under its own lock.
    """

    def __init__(self, clock=None):
        self._now = clock or time.monotonic
        self._ran = 0.0
        self._since: float | None = None
        self._final = False

    def phase(self, phase: str) -> None:
        """The job is now in `phase`; only "running" lets the clock run."""
        if self._final:
            return
        now = self._now()
        if self._since is not None:
            self._ran += max(0.0, now - self._since)
            self._since = None
        if phase == "running":
            self._since = now
        elif phase not in JOB_UNDER_WAY:
            self._final = True

    def seconds(self) -> float:
        """Burning time so far, in seconds."""
        if self._since is None:
            return self._ran
        return self._ran + max(0.0, self._now() - self._since)


#: The phases of `MachineLink.job()` in which the job is still on the line: the machine
#: is burning it, or holding it on a pause. One tuple, read by `busy.py`, `status.py`
#: and `commands.py`, so "is a job on this Ruida" has one answer.
JOB_UNDER_WAY = ("sending", "running", "paused")


def job_on(link) -> dict | None:
    """
    `link.job()` for a link that carries jobs, `None` for any other; never raises.

    `EngineLink` says `carries_jobs = False`: its jobs are the spooler's, read where they
    always were. A link whose `job()` breaks reads as no job, the same rule as a spooler
    that cannot answer in `busy.a_job_is_running`.
    """
    if not _attr(link, "carries_jobs", False):
        return None
    try:
        job = link.job()
    except Exception:
        return None
    return job if isinstance(job, dict) else None


def job_under_way(link) -> dict | None:
    """The link's job while it is still on the line (`JOB_UNDER_WAY`), else `None`."""
    job = job_on(link)
    if job is not None and job.get("phase") in JOB_UNDER_WAY:
        return job
    return None


# ------------------------------------------------------------------ which link


def is_ruida(device) -> bool:
    """
    Whether this device's line is ours.

    Asked as "is it the engine's `RuidaDevice`", and not by the driver's name or by
    `CommandRunner.keeps_files` (a controller holding an `RDJob`): that class is the one
    whose session `ruida/closed.py` keeps shut, so "the engine cannot reach this machine"
    and "our link does" are true of exactly the same devices, by construction. A test
    double with a `connected` flag is not one, and keeps the engine's reading.
    """
    if device is None:
        return False
    try:
        from meerk40t.ruida.device import RuidaDevice
    except ImportError:  # pragma: no cover - an engine without its Ruida module
        return False
    return isinstance(device, RuidaDevice)


#: Verbinden en verbreken through the engine's console.
#:
#: Every driver family calls it something different and marks it `hidden=True`: lihuiyu,
#: moshi, newly and balor have `usb_connect`. Grbl registers none — it opens its
#: connection itself as soon as data has to go there. So the active device is asked what
#: it knows, in this order, and a machine that does not know it gets no button either.
#: `ruida_connect` stays first for a device that only *looks* like a Ruida (a test double);
#: the engine's real Ruida device never gets here, see `is_ruida`.
CONNECTS = ("ruida_connect", "usb_connect")
DISCONNECTS = ("ruida_disconnect", "usb_disconnect")


def _attr(obj, name, default=None):
    """getattr that also survives a property raising; a link's readings never raise."""
    try:
        return getattr(obj, name, default)
    except Exception:
        return default


class EngineLink:
    """
    Today's line, for every laser that is not a Ruida: the engine's device, console and
    spooler, exactly as `machine.py`, `status.py` and `busy.py` used them before.

    Stateless: made per question, and `close()` has nothing to release.
    """

    kind = "engine"

    def __init__(self, device, runner=None):
        self.device = device
        self.runner = runner
        #: What the console said to the last `connect()`/`disconnect()`, echo included.
        self.output: list = []

    # -- connecting --------------------------------------------------------------

    def command(self, names) -> str | None:
        """The first of these console commands the active device knows, or `None`."""
        if self.runner is None:
            return None
        for name in names:
            if self.runner.supports(name):
                return name
        return None

    def connect(self) -> dict:
        self._run(CONNECTS)
        return self.connection()

    def disconnect(self) -> dict:
        self._run(DISCONNECTS)
        return self.connection()

    def _run(self, names) -> None:
        command = self.command(names)
        self.output = list(self.runner.run(command)) if command is not None else []

    def connection(self) -> dict:
        """
        Where each family keeps it; "unknown" where none does. See
        `StatusReader.connection` for why a guess at "connected" is the fault itself.
        """
        device = self.device
        flag = _attr(device, "connected")
        if isinstance(flag, bool):
            return {"state": "connected" if flag else "disconnected", "detail": None}

        # Lihuiyu (K40 boards): the controller keeps a connection and a readable state
        # ("connected", "Not Connected", "Unknown"...).
        controller = _attr(device, "controller")
        if controller is not None:
            link = _attr(controller, "connection")
            if link is not None and hasattr(link, "is_connected"):
                try:
                    open_ = link.is_connected()
                except Exception:
                    open_ = None
                if isinstance(open_, bool):
                    return {
                        "state": "connected" if open_ else "disconnected",
                        "detail": _attr(controller, "state"),
                    }
            # No connection object = never opened.
            if hasattr(controller, "connection"):
                return {"state": "disconnected", "detail": _attr(controller, "state")}

        return {"state": "unknown", "detail": None}

    # -- reading -------------------------------------------------------------------

    def position(self):
        native = _attr(self.device, "native")
        if isinstance(native, (tuple, list)) and len(native) >= 2:
            return (native[0], native[1])
        return None

    def machine_state(self) -> str:
        return "unknown"

    def line_in_use(self):
        """The spooler's half of `busy.the_line_is_in_use`: `'burning'`, `'queued'`."""
        from .busy import spooler_use

        return spooler_use(_attr(self.device, "spooler"))

    #: Only a Ruida keeps files, and a Ruida always takes `RuidaLink` (`is_ruida`).
    carries_files = False

    def send_file(self, packets, *, packet_seconds=10.0, claim_seconds=2.0):
        raise SendInterrupted(
            0, on_line=False, stalled=False,
            why="The engine's line does not carry files; nothing has been sent.")

    #: A K40, a GRBL and every other engine laser burn through `CommandRunner`'s plan and
    #: spool, exactly as before phase 5; their job is the spooler's, read by `status.py`.
    carries_jobs = False

    def start_job(self, rd: bytes, name: str | None = None,
                  estimate_seconds: float | None = None) -> None:
        raise ConnectionError(
            "The engine's line does not take an RD file; this machine burns through "
            "the spooler. Nothing has been sent.")

    def job(self) -> dict | None:
        return None

    def close(self) -> None:
        pass

    # -- phase 4: moving and the realtime verbs, through the console as before ----------
    #
    # Each runs exactly the console line `machine.py` and `commands.py` ran before these
    # moved here, and returns its output: a route hands that back as "output". The
    # console's own failures stay `CommandError`, which the routes answer as before.

    def _console(self, line: str) -> list:
        return self.runner.run(line)

    def motion_capabilities(self) -> dict:
        """What the console of the active device knows, asked the way it always was."""
        knows = self.runner.supports if self.runner is not None else (lambda _n: False)
        return {
            "home": knows("home"),
            "physical_home": knows("physical_home"),
            "move": knows("move_absolute"),
            "jog": knows("move_relative"),
            "frame": knows("move_absolute"),
            "focus": knows(FOCUS),
            "lock": knows("lock"),
            "unlock": knows("unlock"),
            "pause": knows("pause"),
            "resume": knows("resume"),
            "stop": knows("estop") or knows("abort"),
        }

    def home(self, physical: bool = False) -> list:
        return self._console("physical_home" if physical else "home")

    def move_to(self, x_mm: float, y_mm: float) -> list:
        return self._console(f"move_absolute {_mm(x_mm)} {_mm(y_mm)}")

    def move_by(self, dx_mm: float, dy_mm: float) -> list:
        return self._console(f"move_relative {_mm(dx_mm)} {_mm(dy_mm)}")

    def trace(self, corners) -> list:
        """
        The corners one after the other, each with `move_absolute -f`.

        `-f` (force) is the whole repair here. Without that flag `move_absolute` refuses
        as soon as the spooler is not idle (`core/spoolers.py:243`), and after the first
        corner the head is of course on its way: measured on a real machine the head
        went to the top left and the next four corners came back as "Busy Error". With
        the flag they go into the queue and follow each other neatly. Nothing can jump
        the queue: that no job is running is checked by the caller.
        """
        output: list = []
        for hx, hy in corners:
            said = self._console(f"move_absolute -f {_mm(hx)} {_mm(hy)}")
            output.extend(said if isinstance(said, list) else [said])
        return output

    def focus(self, dz_mm: float) -> list:
        return self._console(f"{FOCUS} {_mm(dz_mm)}")

    def lock(self) -> list:
        return self._console("lock")

    def unlock(self) -> list:
        return self._console("unlock")

    def _driver_paused(self):
        """`driver.paused` of the device, or None when nobody says."""
        try:
            flag = self.device.driver.paused
        except Exception:
            return None
        return flag if isinstance(flag, bool) else None

    def pause(self) -> list:
        """
        Pausing, and nothing else.

        On lihuiyu, ruida *and* grbl `pause` is a *toggle*: if the driver is already
        paused, the same command resumes (lihuiyu/device.py:844, ruida/device.py:425,
        grbl/device.py:982). So pressing Pause twice sets the machine burning again, and
        that is exactly the opposite of what is on the button.
        """
        if self._driver_paused() is True:
            return ["already paused"]
        return self._console("pause")

    def resume(self) -> list:
        """
        Resuming, and checking that it has actually happened.

        Measured on a lihuiyu device: `resume` reports "Lihuiyu Channel Resumed." and
        the machine stays put. The device registers `resume` twice, first as a realtime
        resume (device.py:855) and later again as "Resume Controller" (device.py:1045).
        The second wins, and that starts the controller instead of the driver:
        `driver.paused` stays True and `hold_work()` holds the work back. So the result
        is checked: still paused afterwards, and the toggle takes it off. For grbl
        nothing changes; there the flag is already gone after the first attempt.
        """
        if self._driver_paused() is False:
            return ["not paused"]
        output = self._console("resume")
        if self._driver_paused() is True:
            output = output + self._console("pause")
        return output

    def stop(self) -> list:
        """
        Abort the running job. `estop` is realtime and empties the spooler on the
        families that register it; `abort` is the fallback.
        """
        if self.runner.supports("estop"):
            return self._console("estop")
        return self._console("abort")


#: Focusing sits on the Ruida (`focusz`), not on every device; asked, not assumed.
FOCUS = "focusz"


def _mm(value: float) -> str:
    return f"{value:.4f}mm"


def busy_notice(output) -> str | None:
    """
    The frame's safety net: the console said busy or error while the corners went out.

    Should no longer go off since the corners go into the queue with `-f`; kept because
    a frame that stopped half-way and said nothing is the check you thought you made.
    """
    if any("busy" in str(r).lower() or "error" in str(r).lower() for r in output or []):
        return (
            "The machine reported it was busy; the frame may not have run "
            "all the way. Try again when the head is standing still."
        )
    return None


def on_the_line(call, *args):
    """
    Ask a link one of the phase 4 verbs; a lost or refusing line becomes a refusal.

    Returns what the link returned as a list — the console's output for `EngineLink`,
    nothing for our own line, which has no console to echo.
    """
    from .edits import DesignError

    try:
        said = call(*args)
    except TimeoutError as error:
        raise DesignError(
            "The machine did not confirm this in time, so it is not known whether it "
            "arrived. Look at the machine before trying again.",
            code="machine.unconfirmed",
        ) from error
    except ConnectionError as error:
        raise DesignError(
            "There is no working line to the machine, so this did not reach it. "
            "Connect first, then try again.",
            code="machine.notConnected",
        ) from error
    return list(said) if isinstance(said, (list, tuple)) else []


def stop_on_the_line(call):
    """
    Stop, where a failure has one remedy left: the machine's own button.

    Its own sentence and not `on_the_line`'s, because "try again" is the wrong advice
    for a stop that did not arrive.
    """
    from .edits import DesignError

    try:
        said = call()
    except (TimeoutError, ConnectionError) as error:
        raise DesignError(
            "Stopping was not confirmed by the machine. Press the stop button on the "
            "machine itself.",
            code="machine.stopUnconfirmed",
        ) from error
    return list(said) if isinstance(said, (list, tuple)) else []


class Links:
    """
    The links of one kernel: one `RuidaLink` per Ruida device path, an `EngineLink`
    for anything else.

    A `RuidaLink` is cached because it is a line — a session and a monitor once
    connected. It is closed and dropped when its device goes (`forget`), when the slot
    is handed to a different device object (the kernel recycles paths), and when
    another machine is activated (`only`): one line to a controller, never two.
    """

    def __init__(self, factory=None):
        self._factory = factory
        self._ruida: dict = {}
        self._lock = threading.RLock()

    def _make(self, device):
        if self._factory is not None:
            return self._factory(device)
        # Lazily: `ruida/link.py` pulls in our session and monitor, which a K40 user
        # never needs.
        from .ruida.link import RuidaLink

        return RuidaLink(device)

    def for_device(self, device, runner=None):
        if not is_ruida(device):
            return EngineLink(device, runner)
        path = _attr(device, "path")
        stale = None
        with self._lock:
            held = self._ruida.get(path)
            if held is not None and held[0] is not device:
                stale, held = held[1], None
            if held is None:
                held = (device, self._make(device))
                self._ruida[path] = held
        if stale is not None:
            stale.close()
        return held[1]

    def forget(self, path) -> None:
        """The device at `path` is gone: close its line."""
        with self._lock:
            held = self._ruida.pop(path, None)
        if held is not None:
            held[1].close()

    def only(self, device) -> None:
        """Close every Ruida line but this device's. On a switch of machine."""
        with self._lock:
            others = [
                path for path, held in self._ruida.items() if held[0] is not device
            ]
        for path in others:
            self.forget(path)

    def close(self) -> None:
        """Close every line. At shutdown."""
        with self._lock:
            paths = list(self._ruida)
        for path in paths:
            self.forget(path)


#: One `Links` per kernel, so a `StatusReader` or a `MachineControl` built fresh for a
#: request finds the same line the last request opened. Weak, like `busy._CLAIMS`: a
#: kernel that goes away takes its links with it, and tests build a great many.
_LINKS: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()
_LINKS_GUARD = threading.Lock()


def links_for(kernel) -> Links:
    """
    The links of this kernel, made on first use.

    A kernel that cannot be weakly referenced — a `SimpleNamespace` in a test — gets a
    `Links` of its own each time. That costs nothing for the engine's devices, which is
    all such a kernel can carry.
    """
    with _LINKS_GUARD:
        try:
            links = _LINKS.get(kernel)
        except TypeError:
            return Links()
        if links is None:
            links = Links()
            _LINKS[kernel] = links
        return links


def link_for(kernel, device=None, runner=None):
    """The link for `device`, or for the kernel's active device."""
    if device is None:
        device = _attr(kernel, "device")
    return links_for(kernel).for_device(device, runner)
