"""
Read-only status snapshots of the MeerK40t kernel.

Everything in this module reads; nothing commands the machine. All access to
engine internals is defensive: the driver interface only guarantees `status()`,
`get()`, `set()` and `hold_work()` (see meerk40t/core/drivers.py), so every
other attribute is probed with getattr/try.
"""

import time

from meerk40t.core.units import UNITS_PER_MM, Length

from .link import JOB_UNDER_WAY, is_ruida, job_on, link_for

#: What `connection()` may answer; anything else from a link reads as "unknown".
STATES = ("connected", "connecting", "disconnected", "unknown")

#: Per machine, the reading last seen and the moment we first saw it.
#:
#: Keyed on the device's path, because `StatusReader` is built fresh for every
#: request and there is more than one machine in the list. A device without a
#: path — which in practice is a test double — gets its object identity instead,
#: so two of them in one test do not share a stopwatch.
_CONNECTION_SINCE: dict = {}


def forget_connection_history() -> None:
    """Drop the how-long-has-it-held memory. For tests."""
    _CONNECTION_SINCE.clear()


def _safe(fn, default=None):
    """Call fn() and swallow engine-side breakage — status must never raise."""
    try:
        return fn()
    except Exception:
        return default


def _attr(obj, name, default=None):
    """
    getattr that also survives a property raising. Device attributes are often
    properties that touch hardware, so a plain getattr is not safe here.
    """
    try:
        return getattr(obj, name, default)
    except Exception:
        return default


class StatusReader:
    """Builds JSON-serialisable snapshots of kernel, devices and spoolers."""

    def __init__(self, kernel):
        self.kernel = kernel

    def snapshot(self) -> dict:
        active = _safe(lambda: self.kernel.device, None)
        active_path = getattr(active, "path", None)
        devices = [
            self.device_snapshot(device, active_path)
            for device in _safe(lambda: list(self.kernel.services("device")), []) or []
        ]
        return {
            "kernel": {
                "name": getattr(self.kernel, "name", None),
                "version": getattr(self.kernel, "version", None),
            },
            "devices": devices,
        }

    def device_snapshot(self, device, active_path=None) -> dict:
        return {
            "label": _attr(device, "label"),
            "path": _attr(device, "path"),
            "active": _attr(device, "path") == active_path,
            "laser_status": self.laser_status(device),
            "paused": self.paused(device),
            "connection": self.connection(device),
            "line": self.line(device),
            "bed": self.bed(device),
            "position": self.position(device),
            "spooler": self.spooler_snapshot(device),
        }

    #: A Ruida's `machine_state()` in the words the engine's families put in
    #: `laser_status`, which is what the interface reads (`machineState` in `api.ts`).
    _LASER_STATUS = {"idle": "idle", "moving": "active", "running": "active",
                     "paused": "paused"}

    def laser_status(self, device):
        """
        The engine families set `device.laser_status` from their controllers (grbl,
        newly, balor). The engine's Ruida never does, and its driver no longer runs
        anything since phase 4, so a Ruida answers from our own line; "unknown" there
        is `None` here.
        """
        if is_ruida(device):
            link = _safe(lambda: link_for(self.kernel, device), None)
            state = _safe(link.machine_state, "unknown") if link is not None else "unknown"
            return self._LASER_STATUS.get(state)
        return _attr(device, "laser_status")

    def paused(self, device):
        """
        Staat de machine stil op verzoek?

        This was missing, and it is the only source there is. `LaserJob.status` knows only
        four values — Running, Queued, Waiting, Disabled
        (core/laserjob.py:66) — and `is_running()` is `not self._stopped`, which pausing
        does not touch. So in the spooler a paused job looks exactly the same as a running
        one. The consequence in the app: you press Pause, the machine stops, and the screen
        goes on showing "Busy" with a pause button beside it. The resume button never
        appeared, because there was nothing for it to go by.

        `driver.paused` *is* set by all three families, in the same way:
        lihuiyu/driver.py:325, ruida/driver.py:494, grbl/driver.py:869. No driver or no flag =
        `None`, because claiming "not paused" about a device that does not tell us is the same
        guess we already refuse to make about the connection.

        A Ruida answers from our own line instead: the engine's driver no longer pauses
        it, so its flag would say False through every pause. `machine_state()` is what
        the controller last reported; "unknown" there is `None` here, for the same
        reason as above.
        """
        if is_ruida(device):
            link = _safe(lambda: link_for(self.kernel, device), None)
            state = _safe(link.machine_state, "unknown") if link is not None else "unknown"
            if state == "unknown":
                return None
            return state == "paused"
        driver = _attr(device, "driver")
        if driver is None:
            return None
        flag = _attr(driver, "paused")
        return flag if isinstance(flag, bool) else None

    def connection(self, device) -> dict:
        """
        Is a machine really attached, or are we talking to nobody?

        This was missing, and it is the most expensive lie this app can tell: the top bar said
        "Ready" with a green dot while no cable was plugged in, purely because our own
        WebSocket was working. LightBurn puts "Disconnected" here and that is exactly the
        difference somebody beside the machine has to see.

        There is no shared driver interface for it: MeerK40t only guarantees `status()`,
        `get()`, `set()` and `hold_work()` (core/drivers.py). So every family reports it
        somewhere else, and where no source exists at all we say "unknown" instead of
        guessing. A guess at "connected" is the very fault we are repairing.

        `state` is er één van: "connected", "disconnected", "unknown" — and, for a
        Ruida on our own link, "connecting" between asking and knowing.

        And it says how long it has read that way, because one reading is not
        enough to tell a machine that is off from one that is between two
        breaths. Measured on a KH-5030 over three minutes of an idle connection:
        four gaps in which the controller answered nothing, of 3.9, 4.5 and
        4.6 s and one shorter than a single poll — with, on the wire, seven of
        our ENQ packets going out in one of them and not one answer coming back,
        and then replies again with nothing in between to explain it. The flag
        alone therefore makes the bar flash "not connected" at a machine that is
        standing there; `held_ms` is what lets one rule decide the difference,
        in `machineState`, instead of every surface guessing.

        The age is of *our readings*, not of the machine's own state: it starts
        at the first snapshot after a change we saw. Between two snapshots the
        flag can go and come back unseen, and then the age carries on counting.
        That is the honest thing it can say from here, and it is enough for the
        question it is asked.
        """
        # A Ruida from our own link (`link.py`); every other laser from where its family
        # keeps it, which `EngineLink.connection` reads exactly as this method used to.
        link = _safe(lambda: link_for(self.kernel, device), None)
        reading = _safe(link.connection, None) if link is not None else None
        if not isinstance(reading, dict) or reading.get("state") not in STATES:
            reading = {"state": "unknown", "detail": None}
        aged = self._aged(
            device, {"state": reading["state"], "detail": reading.get("detail")}
        )
        # A link may add a warning beside a working line — a Ruida with a second
        # program talking to it (`ruida/monitor.py`, `SecondClient`). Present only
        # while it stands, and only whole: a code and a sentence.
        warning = reading.get("warning")
        if (isinstance(warning, dict) and isinstance(warning.get("code"), str)
                and isinstance(warning.get("message"), str)):
            aged["warning"] = dict(warning)
        return aged

    @staticmethod
    def _aged(device, reading: dict) -> dict:
        """Stamp a reading with how long it has read that way."""
        key = _attr(device, "path", None) or id(device)
        now = time.monotonic()
        seen, since = _CONNECTION_SINCE.get(key, (None, now))
        if seen != reading["state"]:
            since = now
        _CONNECTION_SINCE[key] = (reading["state"], since)
        reading["held_ms"] = int((now - since) * 1000)
        return reading

    def line(self, device) -> dict | None:
        """
        What the flow control sees on the line. `None` where there is no session.

        A stalled upload says "the machine stopped taking the file" after ten
        seconds of a line that never read free, and that one sentence covers two
        different faults: packets still queued, or a flag left standing. From
        outside the process they are indistinguishable — twice in one afternoon a
        cause was reasoned out from the symptom here and twice it was wrong. These
        are the fields the upload's flow control decided on (for a Ruida now
        `session.busy`, which `RuidaLink.send_file` waits on), plus the
        counters the engine already keeps and calls "Stats for test and debug"
        (`ruida/ruidasession.py:64`), so a measurement can replace the reasoning.

        Reading only, and defensively: this is a live object of the engine's, on a
        thread of its own, and a snapshot may never raise.
        """
        if is_ruida(device):
            return self._our_line(device)
        session = _attr(device, "active_session")
        if session is None:
            return None
        queue = _attr(session, "send_q")
        return {
            "busy": _attr(session, "is_busy"),
            "queued": _safe(queue.qsize) if queue is not None else None,
            "ack_pending": _attr(session, "_ack_pending"),
            "reply_pending": _attr(session, "_reply_pending"),
            "sends": _attr(session, "sends"),
            "acks": _attr(session, "acks"),
            "naks": _attr(session, "naks"),
            "replies": _attr(session, "replies"),
            "enqs": _attr(session, "enqs"),
            "dropped": _attr(session, "dropped_packets"),
        }

    def _our_line(self, device) -> dict | None:
        """
        The same fields off our own session (`ruida/session.py`), for a Ruida.

        The engine's session on that device is `ClosedSession` and has nothing to say.
        Ours keeps the counters under the same names, except `probes` for the engine's
        `enqs` and `dropped` for its `dropped_packets`; its ACK and reply flags are not
        exposed, so those two read `None`. `None` as a whole while nothing is open.
        """
        link = _safe(lambda: link_for(self.kernel, device), None)
        session = _attr(link, "session")
        if session is None:
            return None
        return {
            "busy": _attr(session, "busy"),
            "queued": _attr(session, "queued"),
            "ack_pending": None,
            "reply_pending": None,
            "sends": _attr(session, "sends"),
            "acks": _attr(session, "acks"),
            "naks": _attr(session, "naks"),
            "replies": _attr(session, "replies"),
            "enqs": _attr(session, "probes"),
            "dropped": _attr(session, "dropped"),
        }

    def bed(self, device) -> dict:
        """Bed size in mm. Devices store these as strings like "320mm"."""
        return {
            "width_mm": self._length_mm(_attr(device, "bedwidth")),
            "height_mm": self._length_mm(_attr(device, "bedheight")),
        }

    @staticmethod
    def _length_mm(value):
        if value is None:
            return None
        return _safe(lambda: Length(value).mm)

    def position(self, device) -> dict:
        """
        Current head position.

        `device.native` (device units) and `device.current` (scene units) are
        implemented by every driver — dummy, ruida, grbl and lihuiyu all expose
        them — so they are the primary source. `driver.status()` is the only
        guaranteed driver method and supplies the state flags; it returns
        ((native_x, native_y), state_major, state_minor).
        """
        if is_ruida(device):
            # From our own monitor, in the controller's micrometres — the units
            # `device.native` gives for the engine's Ruida driver — so the device's own
            # view turns it into millimetres as before. Not `device.current`: that is the
            # engine driver's idea of the head, and the engine no longer moves it.
            link = _safe(lambda: link_for(self.kernel, device), None)
            native = self._as_pair(_safe(link.position) if link is not None else None)
            return {
                "native": native,
                "mm": self._to_mm(device, native),
                "state": None,
            }

        native = self._as_pair(_attr(device, "native"))
        scene = self._as_pair(_attr(device, "current"))
        state = None

        driver = _attr(device, "driver")
        if driver is not None and hasattr(driver, "status"):
            status = _safe(driver.status)
            if isinstance(status, (tuple, list)) and status:
                if native is None:
                    native = self._as_pair(status[0])
                state = list(status[1:]) or None
        if native is None and driver is not None:
            native = self._as_pair(
                (_attr(driver, "native_x"), _attr(driver, "native_y"))
            )

        return {
            "native": native,
            "mm": self._to_mm(device, native, scene),
            "state": state,
        }

    @staticmethod
    def _as_pair(value):
        if not isinstance(value, (tuple, list)) or len(value) < 2:
            return None
        if any(not isinstance(v, (int, float)) for v in value[:2]):
            return None
        return [value[0], value[1]]

    def _to_mm(self, device, native, scene=None):
        """Scene units (Tats) → millimetres, converting from device units first."""
        if scene is None:
            if native is None:
                return None
            view = _attr(device, "view")
            if view is None or not hasattr(view, "iposition"):
                return None
            scene = self._as_pair(_safe(lambda: view.iposition(native[0], native[1])))
        if scene is None:
            return None
        return [scene[0] / UNITS_PER_MM, scene[1] / UNITS_PER_MM]

    def spooler_snapshot(self, device) -> dict:
        link = _safe(lambda: link_for(self.kernel, device), None)
        if _attr(link, "carries_jobs", False):
            return self._line_snapshot(device, link)
        spooler = _attr(device, "spooler")
        if spooler is None:
            return {"present": False, "idle": None, "queue_length": 0, "jobs": [],
                    "ended": None}

        queue = _safe(lambda: list(spooler.queue), []) or []
        # The pause sits on the driver, not on the job (see `paused`). Passing it along here
        # saves the frontend a second source: whoever reads the job also reads whether it is
        # standing still.
        paused = self.paused(device)
        return {
            "present": True,
            "idle": _safe(lambda: bool(spooler.is_idle)),
            # Only a link that carries jobs knows how its last job ended; the engine's
            # spooler drops a job when it is through, whichever way.
            "ended": None,
            "queue_length": len(queue),
            # Only the first in the queue is the job the driver is working on; what is
            # behind it is waiting its turn and is not paused.
            "jobs": [
                self.job_snapshot(job, paused if index == 0 else False)
                for index, job in enumerate(queue)
            ],
        }

    def _line_snapshot(self, device, link) -> dict:
        """
        The spooler's shape, read off a link that carries jobs (a Ruida, phase 5).

        In the same fields so that every surface keeps reading one thing: `currentJob`,
        `jobPhase` and the watchdog in the interface do not learn a second source. The
        engine drops a job from its queue once it is through, so a link's job is listed
        only while it is on the line (`JOB_UNDER_WAY`); how it ended is `ended`, for
        "stopped" and "failed" with the link's sentence, so the interface can say why
        a burn ended without a "done".
        """
        job = job_on(link) or {}
        phase = job.get("phase")
        ended = None
        if phase in ("stopped", "failed"):
            ended = {
                "name": job.get("name"),
                "phase": phase,
                "detail": job.get("detail"),
                "finished": job.get("finished"),
            }
        if phase not in JOB_UNDER_WAY:
            return {"present": True, "idle": True, "queue_length": 0, "jobs": [],
                    "ended": ended}
        return {
            "present": True,
            "idle": False,
            "queue_length": 1,
            "jobs": [self.line_job_snapshot(job, self.paused(device))],
            "ended": None,
        }

    #: Where a progress made of the estimate stops until the link says "done". Below
    #: the interface's `DONE` (0.995 in `api.ts`), so a burn that outlasts its
    #: estimate never reads as finished while the machine is still at it.
    ESTIMATE_CAP = 0.99

    #: A link's phase in the words `LaserJob.status` uses, which `jobStatusLabel` reads.
    _LINE_STATUS = {"sending": "Running", "running": "Running", "paused": "Paused"}

    def line_job_snapshot(self, job: dict, device_paused=None) -> dict:
        """
        `job_snapshot`'s fields for a link's `job()`.

        `steps_done`/`steps_total` are the file's packets the controller confirmed —
        what the line can count, and nothing more: a Ruida burns the file as it arrives
        and takes it in far faster than it burns it (12,177 bytes in 13 blocks within
        0.1 s, then a 77 s burn, on the KH-5030), so packets are not work on the
        material and no percentage is made of them.

        The progress is the **estimate's**: burning time so far (`running_seconds`,
        the link's `BurnClock`, which stands still while sending and while paused)
        over the cut plan's estimate the job was started with (`estimate_seconds`),
        held at `ESTIMATE_CAP` until the link says "done" — a burn slower than its
        estimate waits at 99 % rather than reading finished. `progress_basis` says
        so ("estimate"), for the interface to call the figure an estimate and for
        the watchdog, which must not take a clock that has reached its cap for a
        machine that stopped. Without an estimate the progress stays `None`, as
        before. `elapsed_seconds` is the same burning time, so elapsed, remaining
        and the bar are one clock; a link that keeps none gives the wall clock
        since the start.
        """
        phase = job.get("phase")
        paused = phase == "paused" or device_paused is True
        ran = job.get("running_seconds")
        ran = float(ran) if _number(ran) and ran >= 0 else None
        estimate = job.get("estimate_seconds")
        estimate = float(estimate) if _number(estimate) and estimate > 0 else None
        if ran is not None:
            elapsed = ran
        else:
            started = job.get("started")
            end = job.get("finished") or time.time()
            elapsed = max(0.0, end - started) if _number(started) else None
        progress = None
        if estimate is not None and ran is not None:
            progress = min(self.ESTIMATE_CAP, ran / estimate)
        return {
            "label": job.get("name") or "",
            "type": "RuidaJob",
            "status": "Paused" if paused else self._LINE_STATUS.get(phase),
            "priority": 0,
            "running": phase in ("sending", "running") and not paused,
            "paused": paused,
            "steps_done": job.get("sent"),
            "steps_total": job.get("total"),
            "progress": progress,
            "progress_basis": "estimate" if progress is not None else None,
            "loops_executed": None,
            "loops": 1,
            "elapsed_seconds": elapsed,
            "estimate_seconds": estimate,
        }

    def job_snapshot(self, job, device_paused=None) -> dict:
        steps_done = _attr(job, "steps_done")
        steps_total = _attr(job, "steps_total")
        if steps_total == 0 and hasattr(job, "calc_steps"):
            # steps_total is only filled in lazily; the web console does the same.
            _safe(job.calc_steps)
            steps_total = _attr(job, "steps_total")

        loops = _attr(job, "loops")
        running = _safe(lambda: bool(job.is_running()))
        return {
            "label": _attr(job, "label") or type(job).__name__,
            "type": type(job).__name__,
            "status": _safe(lambda: job.status),
            "priority": _attr(job, "priority"),
            "running": running,
            # Do not hang it off `running`: a job that has not started yet reports
            # `running is False`, and then a real pause disappeared from view — the bar said
            # "Busy" with a pause button beside it, while the machine stood still and that job
            # was not going to start either. Whoever is at the front is standing still.
            "paused": bool(device_paused),
            "steps_done": steps_done,
            "steps_total": steps_total,
            "progress": self._progress(steps_done, steps_total),
            # The engine counts the steps it executed: a measurement, which the
            # watchdog may read as standing still (see `line_job_snapshot`).
            "progress_basis": "steps",
            "loops_executed": _attr(job, "loops_executed"),
            "loops": None if loops is not None and loops == float("inf") else loops,
            "elapsed_seconds": _safe(lambda: job.elapsed_time()),
            "estimate_seconds": _safe(lambda: job.estimate_time()),
        }

    @staticmethod
    def _progress(done, total):
        if not isinstance(done, (int, float)) or not isinstance(total, (int, float)):
            return None
        if not total:
            return None
        return max(0.0, min(1.0, done / total))


def _number(value) -> bool:
    """A real, finite number — not a bool, not NaN, not infinity."""
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and value == value and value not in (float("inf"), float("-inf")))
