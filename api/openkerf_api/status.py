"""
Read-only status snapshots of the MeerK40t kernel.

Everything in this module reads; nothing commands the machine. All access to
engine internals is defensive: the driver interface only guarantees `status()`,
`get()`, `set()` and `hold_work()` (see meerk40t/core/drivers.py), so every
other attribute is probed with getattr/try.
"""

from meerk40t.core.units import UNITS_PER_MM, Length


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
            "laser_status": _attr(device, "laser_status"),
            "paused": self.paused(device),
            "connection": self.connection(device),
            "bed": self.bed(device),
            "position": self.position(device),
            "spooler": self.spooler_snapshot(device),
        }

    @staticmethod
    def paused(device):
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
        """
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

        `state` is er één van: "connected", "disconnected", "unknown".
        """
        # Ruida (our target machine) has an explicit property; it is bound to the session
        # layer and therefore the most reliable source there is.
        ruida = _attr(device, "connected")
        if isinstance(ruida, bool):
            return {
                "state": "connected" if ruida else "disconnected",
                "detail": None,
            }

        # Lihuiyu (K40 boards): the controller keeps a connection and a readable state
        # ("connected", "Not Connected", "Unknown"...).
        controller = _attr(device, "controller")
        if controller is not None:
            link = _attr(controller, "connection")
            if link is not None and hasattr(link, "is_connected"):
                open_ = _safe(link.is_connected)
                if isinstance(open_, bool):
                    return {
                        "state": "connected" if open_ else "disconnected",
                        "detail": _attr(controller, "state"),
                    }
            # Geen verbindingsobject = nog nooit geopend.
            if hasattr(controller, "connection"):
                return {
                    "state": "disconnected",
                    "detail": _attr(controller, "state"),
                }

        return {"state": "unknown", "detail": None}

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
        spooler = _attr(device, "spooler")
        if spooler is None:
            return {"present": False, "idle": None, "queue_length": 0, "jobs": []}

        queue = _safe(lambda: list(spooler.queue), []) or []
        # The pause sits on the driver, not on the job (see `paused`). Passing it along here
        # saves the frontend a second source: whoever reads the job also reads whether it is
        # standing still.
        paused = self.paused(device)
        return {
            "present": True,
            "idle": _safe(lambda: bool(spooler.is_idle)),
            "queue_length": len(queue),
            # Only the first in the queue is the job the driver is working on; what is
            # behind it is waiting its turn and is not paused.
            "jobs": [
                self.job_snapshot(job, paused if index == 0 else False)
                for index, job in enumerate(queue)
            ],
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
