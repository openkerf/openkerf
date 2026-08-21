"""Snapshot shape and defensiveness of the read-only status layer."""

from openkerf_api.status import StatusReader


def test_snapshot_has_kernel_and_devices(kernel):
    snap = StatusReader(kernel).snapshot()

    assert snap["kernel"]["name"] == "MeerK40t"
    assert isinstance(snap["devices"], list)
    assert snap["devices"], "bootstrap starts a dummy device"


def test_device_snapshot_shape(kernel):
    device = next(iter(kernel.services("device")))
    snap = StatusReader(kernel).device_snapshot(device, getattr(kernel.device, "path", None))

    assert set(snap) == {
        "label",
        "path",
        "active",
        "laser_status",
        "paused",
        "connection",
        "bed",
        "position",
        "spooler",
    }
    assert snap["active"] is True
    assert set(snap["connection"]) == {"state", "detail"}
    assert set(snap["position"]) == {"native", "mm", "state"}
    assert snap["spooler"]["present"] is True
    assert snap["spooler"]["queue_length"] == 0
    assert snap["spooler"]["jobs"] == []


def test_connection_never_guesses_connected(kernel):
    """
    The dummy device has no connection source at all. Then "unknown" is the only
    honest answer — a guess at "connected" would bring back exactly the green dot
    over a dead port that this layer was meant to take away.
    """
    device = next(iter(kernel.services("device")))
    link = StatusReader(kernel).connection(device)

    assert link["state"] in {"connected", "disconnected", "unknown"}
    assert link["state"] != "connected"


def test_connection_reads_a_lihuiyu_style_controller():
    class Link:
        @staticmethod
        def is_connected():
            return False

    class Device:
        controller = type("C", (), {"connection": Link(), "state": "unknown"})()

    assert StatusReader(None).connection(Device()) == {
        "state": "disconnected",
        "detail": "unknown",
    }


def test_connection_reads_a_ruida_style_property():
    class Device:
        connected = True

    assert StatusReader(None).connection(Device())["state"] == "connected"


def test_bed_size_is_reported_in_mm(kernel):
    device = next(iter(kernel.services("device")))
    bed = StatusReader(kernel).bed(device)

    assert bed["width_mm"] > 0
    assert bed["height_mm"] > 0


def test_position_is_reported_in_native_units_and_mm(kernel):
    device = next(iter(kernel.services("device")))
    position = StatusReader(kernel).position(device)

    assert position["native"] is not None
    assert len(position["native"]) == 2
    assert position["mm"] is not None
    assert all(isinstance(v, float) for v in position["mm"])


def test_snapshot_is_json_serialisable(kernel):
    import json

    json.dumps(StatusReader(kernel).snapshot(), default=str)


def test_reader_survives_a_broken_device(kernel):
    class Broken:
        path = "broken"
        label = "Broken"

        @property
        def driver(self):
            raise RuntimeError("device fell over")

        @property
        def spooler(self):
            raise RuntimeError("device fell over")

    # A device that raises on every access must degrade, not take the API down.
    snap = StatusReader(kernel).device_snapshot(Broken())
    assert snap["label"] == "Broken"
    assert snap["position"]["native"] is None
    assert snap["spooler"]["present"] is False


def test_progress_fraction():
    assert StatusReader._progress(5, 10) == 0.5
    assert StatusReader._progress(0, 0) is None
    assert StatusReader._progress(None, 10) is None
    assert StatusReader._progress(20, 10) == 1.0


# ---------------------------------------------------------------- pause


class _Job:
    """A LaserJob as the spooler hands it back: the pause is *not* in it."""

    label = "Sheet 1"
    priority = 0
    steps_done = 40
    steps_total = 100
    loops_executed = 0
    loops = 1

    def __init__(self, running=True):
        self._running = running

    @property
    def status(self):
        # Exactly the four values from meerk40t/core/laserjob.py:66 — not one of
        # them holds "pause".
        return "Running" if self._running else "Waiting"

    def is_running(self):
        return self._running

    def elapsed_time(self):
        return 12.0

    def estimate_time(self):
        return 30.0


class _Spooler:
    def __init__(self, jobs):
        self.queue = jobs
        self.is_idle = not jobs


class _Device:
    """Lihuiyu, Ruida en grbl zetten alle drie `driver.paused`."""

    path = "lhystudios"
    label = "Berk 5030"
    laser_status = "idle"

    def __init__(self, paused):
        self.driver = type("D", (), {"paused": paused})()
        self.spooler = _Spooler([_Job()])


def test_pause_is_read_from_the_driver_not_from_the_job_status():
    """
    The job says "Running" whether it is standing still or not — there is no pause
    to be read from it. Without this flag the app showed a paused machine as "Busy",
    with no resume button.
    """
    reader = StatusReader(None)

    still = reader.device_snapshot(_Device(True))
    assert still["paused"] is True
    assert still["spooler"]["jobs"][0]["paused"] is True
    # The job itself keeps reporting "Running"; that is exactly why this field was needed.
    assert still["spooler"]["jobs"][0]["status"] == "Running"

    running_now = reader.device_snapshot(_Device(False))
    assert running_now["paused"] is False
    assert running_now["spooler"]["jobs"][0]["paused"] is False


def test_pause_is_unknown_when_the_driver_does_not_say():
    """No guessing: no flag is `None`, just as with the connection."""

    class Without:
        path = "dummy"
        label = "Dummy"
        driver = object()

    assert StatusReader(None).paused(Without()) is None
    assert StatusReader(None).paused(object()) is None


def test_a_queued_job_behind_a_paused_one_is_not_itself_paused():
    """What is at the back of the queue is waiting its turn — that is not a pause."""
    device = _Device(True)
    device.spooler = _Spooler([_Job(running=True), _Job(running=False)])

    jobs = StatusReader(None).device_snapshot(device)["spooler"]["jobs"]
    assert [j["paused"] for j in jobs] == [True, False]


def test_a_job_that_has_not_started_yet_still_shows_the_pause():
    """
    Measured with two windows open: the driver was paused, the job at the front had
    not started yet (`running is False`, `steps_done == 0`), and both the desktop
    and the phone reported "Busy" with a pause button beside it. The pause hung off
    `running`, and that is exactly the case in which that flag says nothing.
    """
    device = _Device(True)
    device.spooler = _Spooler([_Job(running=False)])

    jobs = StatusReader(None).device_snapshot(device)["spooler"]["jobs"]
    assert jobs[0]["running"] is False
    assert jobs[0]["paused"] is True
