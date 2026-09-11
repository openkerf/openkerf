"""Snapshot shape and defensiveness of the read-only status layer."""

import time

import pytest

from openkerf_api.status import StatusReader, forget_connection_history


@pytest.fixture(autouse=True)
def _a_clean_connection_history():
    """
    The how-long-has-it-held memory is per process, so one test must not be able
    to read another one's stopwatch.
    """
    forget_connection_history()
    yield
    forget_connection_history()


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
        "line",
        "bed",
        "position",
        "spooler",
    }
    assert snap["active"] is True
    assert set(snap["connection"]) == {"state", "detail", "held_ms"}
    assert snap["line"] is None, "a dummy device has no Ruida session"
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
        "held_ms": 0,
    }


def test_connection_reads_a_ruida_style_property():
    class Device:
        connected = True

    assert StatusReader(None).connection(Device())["state"] == "connected"


def test_how_long_the_connection_has_read_the_same_starts_at_nothing():
    """
    A Ruida falls silent for seconds at a time and comes back with nothing having
    changed — measured on a KH-5030, four gaps of up to 4.6 s in three minutes.
    The bar must be able to tell that apart from a machine that is off, and the
    only thing that separates them is how long it has lasted. So the reading
    carries its own age.
    """
    class Device:
        connected = True

    device = Device()

    assert StatusReader(None).connection(device)["held_ms"] == 0


def test_a_reading_that_stays_the_same_gets_older():
    class Device:
        connected = True

    device = Device()
    reader = StatusReader(None)
    reader.connection(device)
    time.sleep(0.05)

    assert reader.connection(device)["held_ms"] >= 50


def test_a_reading_that_changes_starts_counting_again():
    class Device:
        connected = True

    device = Device()
    reader = StatusReader(None)
    reader.connection(device)
    time.sleep(0.05)
    device.connected = False

    second = reader.connection(device)

    assert second["state"] == "disconnected"
    assert second["held_ms"] < 50, second


def test_two_machines_keep_their_own_stopwatch(kernel):
    """
    Keyed on the device, not on the reader: `StatusReader` is built fresh for
    every request, and there is more than one machine in the list.
    """
    class Device:
        def __init__(self, path, connected):
            self.path = path
            self.connected = connected

    one, two = Device("ruida", True), Device("lhystudios", False)
    StatusReader(None).connection(one)
    time.sleep(0.05)
    StatusReader(None).connection(two)

    assert StatusReader(None).connection(one)["held_ms"] >= 50
    assert StatusReader(None).connection(two)["held_ms"] < 50


def test_the_line_reports_what_the_flow_control_reads():
    """
    Why this exists. An upload refuses with "the machine stopped taking the file"
    when `_line_is_busy` has been true for ten seconds — and that is two different
    faults wearing one sentence: packets of somebody else's still in the queue, or
    a flag left standing. Twice today a diagnosis was reasoned out from the
    outside and twice it was wrong, because from the outside those two look
    identical.

    The engine keeps the numbers already and calls them "Stats for test and debug"
    (`ruida/ruidasession.py:64`); nothing exposed them. These are the same fields
    `RuidaUpload._line_is_busy` decides on, so what is read here is what it sees.
    """
    class Session:
        is_busy = True
        _ack_pending = False
        _reply_pending = True
        sends = 12
        acks = 11
        naks = 0
        replies = 0
        enqs = 7
        dropped_packets = 0

        class send_q:
            @staticmethod
            def qsize():
                return 3

            @staticmethod
            def empty():
                return False

    class Device:
        path = "ruida"
        active_session = Session()

    line = StatusReader(None).line(Device())

    assert line == {
        "busy": True,
        "queued": 3,
        "ack_pending": False,
        "reply_pending": True,
        "sends": 12,
        "acks": 11,
        "naks": 0,
        "replies": 0,
        "enqs": 7,
        "dropped": 0,
    }


def test_a_machine_without_a_session_has_no_line():
    class Device:
        path = "lhystudios"

    assert StatusReader(None).line(Device()) is None


def test_the_line_survives_a_session_that_answers_nothing():
    """
    Status must never raise: every field here is probed on an engine object that a
    version change can empty out.
    """
    class Session:
        pass

    class Device:
        path = "ruida"
        active_session = Session()

    line = StatusReader(None).line(Device())

    assert line["queued"] is None
    assert line["sends"] is None


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
