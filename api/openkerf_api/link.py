"""
What our modules ask of the line to a machine, in one place.

A Ruida goes through our own transport (`ruida/`); every other laser goes through the
engine's device, spooler and console as before. The modules that talk to a machine —
`machine.py`, `status.py`, `busy.py`, `ruida_upload.py`, and later `commands.py` — ask
a `MachineLink` and do not care which one answers. See the plan in the working record,
`plannen/2026-10-11-eigen-ruida-verbinding.md`.

Phase 2 is connecting and status, phase 3 a file into the controller's memory
(`send_file`). Sending a job and a realtime command come in the phases after it, as
methods added here.
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
        """`{"state": ConnectionState, "detail": str | None}` — never raises."""

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
        state = self.connection()
        session = _attr(self.device, "active_session")
        if getattr(session, "supports_write_completion", False):
            # The patched engine session's `open()` only asks its worker for the
            # handshake. No engine device reaches here with one today — a Ruida takes
            # `RuidaLink` — but the wait is the engine's behaviour and stays with it.
            deadline = time.monotonic() + 3.0
            while state["state"] == "disconnected" and time.monotonic() < deadline:
                time.sleep(0.02)
                state = self.connection()
        return state

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

    def close(self) -> None:
        pass


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


def refuse_what_the_link_does_not_carry_yet(kernel) -> None:
    """
    Moving the head, burning, pausing and resuming on a Ruida, until our line carries them.

    The engine's Ruida device is kept closed (`ruida/closed.py`), so these would go
    through the engine into nothing. Measured before this refusal, with the session
    closed: a jog, a home and a move each answered as if done, their bytes refused by
    `ClosedSession.write` 19 times between them, and the move's job stood in the
    spooler as Running for more than 6 s with the burn queued behind it. A press that
    seems to work and moves nothing is the one answer a laser must not give.

    Stop is not refused: it clears the engine's spooler, which is the way out of
    exactly that state, and it must stay reachable in one call.
    """
    from .edits import DesignError

    if is_ruida(_attr(kernel, "device")):
        raise DesignError(
            "This does not reach a Ruida yet. OpenKerf now keeps the line to the "
            "controller itself, and moving the head, burning and pausing over that "
            "line are still being built. Nothing has been sent.",
            code="machine.notOnTheLineYet",
        )
