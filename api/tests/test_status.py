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
    Het dummy-apparaat heeft geen enkele verbindingsbron. Dan is "unknown" het
    enige eerlijke antwoord — een gok naar "connected" zou precies de groene
    stip boven een dode poort terugbrengen die deze laag moest wegnemen.
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


# ---------------------------------------------------------------- pauze


class _Job:
    """Een LaserJob zoals de spooler hem teruggeeft: pauze staat er níet in."""

    label = "Vel 1"
    priority = 0
    steps_done = 40
    steps_total = 100
    loops_executed = 0
    loops = 1

    def __init__(self, running=True):
        self._running = running

    @property
    def status(self):
        # Exact de vier waarden uit meerk40t/core/laserjob.py:66 — geen ervan
        # bevat "pause".
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
    De job zegt "Running" of hij nu stilstaat of niet — daar is geen pauze uit
    te lezen. Zonder deze vlag toonde de app een gepauzeerde machine als
    "Bezig", zonder hervatknop.
    """
    reader = StatusReader(None)

    stil = reader.device_snapshot(_Device(True))
    assert stil["paused"] is True
    assert stil["spooler"]["jobs"][0]["paused"] is True
    # De job zelf blijft "Running" melden; dat is precies waarom dit veld moest.
    assert stil["spooler"]["jobs"][0]["status"] == "Running"

    loopt = reader.device_snapshot(_Device(False))
    assert loopt["paused"] is False
    assert loopt["spooler"]["jobs"][0]["paused"] is False


def test_pause_is_unknown_when_the_driver_does_not_say():
    """Niet gokken: geen vlag is `None`, net als bij de verbinding."""

    class Zonder:
        path = "dummy"
        label = "Dummy"
        driver = object()

    assert StatusReader(None).paused(Zonder()) is None
    assert StatusReader(None).paused(object()) is None


def test_a_queued_job_behind_a_paused_one_is_not_itself_paused():
    """Wat achteraan in de rij staat, wacht op zijn beurt — dat is geen pauze."""
    device = _Device(True)
    device.spooler = _Spooler([_Job(running=True), _Job(running=False)])

    jobs = StatusReader(None).device_snapshot(device)["spooler"]["jobs"]
    assert [j["paused"] for j in jobs] == [True, False]


def test_a_job_that_has_not_started_yet_still_shows_the_pause():
    """
    Gemeten met twee vensters open: de driver stond op pauze, de job vooraan
    was nog niet begonnen (`running is False`, `steps_done == 0`), en zowel de
    desktop als de telefoon meldde "Bezig" met een pauzeknop erbij. De pauze
    hing aan `running`, en dat is precies het geval waarin die vlag niets zegt.
    """
    device = _Device(True)
    device.spooler = _Spooler([_Job(running=False)])

    jobs = StatusReader(None).device_snapshot(device)["spooler"]["jobs"]
    assert jobs[0]["running"] is False
    assert jobs[0]["paused"] is True
