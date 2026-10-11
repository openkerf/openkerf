"""
Phase 5 of the own Ruida line: a burn on a Ruida goes to its link as one RD file.

`CommandRunner.start_job` builds the file with `build_job_bytes` — the same mutators,
rotary and claim on the plan the spooler's road applies — and hands it to
`link.start_job` with the job's name. Every other laser plans and spools as before
(`EngineLink.carries_jobs` is False). What the link says about its job comes back in
the spooler's shape (`StatusReader.spooler_snapshot`), so the interface keeps one
source. A `FakeJobLink` stands where `RuidaLink` would, so no socket opens.
"""

import json

import pytest
from fastapi.testclient import TestClient

from openkerf_api import link as link_module
from openkerf_api.busy import a_job_is_running, sending_a_file, the_line_is_in_use
from openkerf_api.link import EngineLink
from openkerf_api.server import ApiServer

from test_machine_link import FakeLink, a_ruida, link_of
from test_series_routes import a_running_series
from test_tiling_api import _enable_output, _marks_at


class FakeJobLink(FakeLink):
    """A `FakeLink` that carries jobs: records `start_job`, answers `job()` from `the_job`."""

    carries_jobs = True

    def __init__(self, device):
        super().__init__(device)
        self.started: list[tuple[bytes, str | None]] = []
        self.the_job: dict | None = None
        #: Raised by `start_job` instead of starting, when set.
        self.refuses: BaseException | None = None

    def start_job(self, rd, name=None):
        if self.refuses is not None:
            raise self.refuses
        self.started.append((bytes(rd), name))
        self.the_job = a_job("sending", name=name, sent=0, total=4)

    def job(self):
        return None if self.the_job is None else dict(self.the_job)


def a_job(phase, name="Keyrings", sent=4, total=4, detail=None):
    finished = 1_000_010.0 if phase in ("done", "stopped", "failed") else None
    return {"name": name, "phase": phase, "sent": sent, "total": total,
            "detail": detail, "started": 1_000_000.0, "finished": finished}


@pytest.fixture
def job_links(monkeypatch):
    FakeLink.made = []
    monkeypatch.setattr(link_module.Links, "_make", lambda self, device: FakeJobLink(device))
    return FakeLink.made


@pytest.fixture
def server(kernel, tmp_path, job_links):
    return ApiServer(kernel, library_path=tmp_path / "j.db")


@pytest.fixture
def client(server):
    with TestClient(server.build_app()) as c:
        yield c


def a_connected_ruida(client, kernel) -> FakeJobLink:
    path = a_ruida(client)
    link = link_of(kernel, path)
    assert isinstance(link, FakeJobLink)
    link.state = "connected"
    return link


def a_rectangle(kernel):
    """One rectangle in a cut layer; the design `test_ruida_upload.py` builds on."""
    kernel.elements.clear_all()
    kernel.console("rect 20mm 20mm 40mm 30mm\n")
    kernel.console("operation* delete\n")
    kernel.console("op cut\n")
    kernel.console("element* classify\n")


def a_sheet_named(client, name):
    sheet = client.get("/api/sheets").json()["sheets"][0]
    answer = client.patch(f"/api/sheets/{sheet['id']}", json={"name": name})
    assert answer.status_code == 200, answer.text


def recording_builds(server, monkeypatch):
    """Every `build_job_bytes` result, with the mutators it was handed."""
    built = []
    real = server.commands.build_job_bytes

    def build(mutators=()):
        data = real(mutators)
        built.append((data, list(mutators)))
        return data

    monkeypatch.setattr(server.commands, "build_job_bytes", build)
    return built


def active_spooler(client):
    devices = client.get("/api/status").json()["devices"]
    return next(d for d in devices if d["active"])["spooler"]


# ------------------------------------------------------------ the burn itself


def test_a_ruida_burn_reaches_the_link_with_the_built_bytes_and_the_sheet_name(
    client, server, kernel, monkeypatch
):
    link = a_connected_ruida(client, kernel)
    a_rectangle(kernel)
    a_sheet_named(client, "Keyrings")
    built = recording_builds(server, monkeypatch)
    queued = len(kernel.device.spooler.queue)

    answer = client.post("/api/job/start")

    assert answer.status_code == 200, answer.text
    assert len(built) == 1
    assert link.started == [(built[0][0], "Keyrings")]
    rd = link.started[0][0]
    assert len(rd) > 100
    # Two builds of the same drawing agree (`test_ruida_upload.a_design_over_one_block`),
    # so the file on the line is the one `build_job_bytes` makes on its own.
    assert rd == server.commands.build_job_bytes()
    # Nothing went to the engine's spooler: the device behind it is kept closed.
    assert len(kernel.device.spooler.queue) == queued


def test_the_mutators_of_the_route_reach_the_build(client, server, kernel, monkeypatch):
    """The route's mutators (zero point, print and cut, the series) go to `build_job_bytes`."""
    link = a_connected_ruida(client, kernel)
    a_rectangle(kernel)
    built = recording_builds(server, monkeypatch)
    seen = []

    def spy(steps):
        seen.append(len(steps))
        return steps

    server.commands.start_job("Spied", mutators=[spy])

    assert built[0][1] == [spy]
    assert seen, "the mutator never saw the plan"
    assert link.started[0][1] == "Spied"


def test_a_nameless_burn_on_a_ruida_is_named_like_a_spooled_one(client, server, kernel):
    link = a_connected_ruida(client, kernel)
    a_rectangle(kernel)
    server.commands.start_job(None)
    assert link.started[0][1] == "1 operation"


def test_the_dummy_device_still_plans_and_spools(client, kernel, job_links):
    """`EngineLink` does not carry jobs: the K40 road is the road it always was."""
    assert EngineLink.carries_jobs is False
    assert EngineLink(kernel.device).job() is None
    with pytest.raises(ConnectionError):
        EngineLink(kernel.device).start_job(b"\x00")
    a_rectangle(kernel)
    a_sheet_named(client, "Plate")
    before = len(kernel.device.spooler.queue)

    answer = client.post("/api/job/start")

    assert answer.status_code == 200, answer.text
    queue = list(kernel.device.spooler.queue)
    assert len(queue) == before + 1
    assert queue[-1].label == "Plate"
    assert job_links == [], "a link was made for the dummy device"


# ---------------------------------------------------------- refusals before the line


def refused(answer, code):
    assert answer.status_code == 409, answer.text
    assert answer.headers["X-OpenKerf-Error"] == code
    return answer


def test_nothing_to_burn_is_refused_before_the_line(client, kernel):
    link = a_connected_ruida(client, kernel)
    refused(client.post("/api/job/start"), "job.nothingToBurn")
    assert link.started == []


def test_a_burn_while_a_file_is_being_sent_is_refused(client, server, kernel, monkeypatch):
    link = a_connected_ruida(client, kernel)
    a_rectangle(kernel)
    built = recording_builds(server, monkeypatch)
    with sending_a_file(kernel) as claimed:
        assert claimed
        refused(client.post("/api/job/start"), "machine.sendingAFile")
    assert link.started == [] and built == []


def test_the_plain_button_under_a_series_is_refused_before_the_line(client, kernel):
    link = a_connected_ruida(client, kernel)
    a_running_series(client)
    refused(client.post("/api/job/start"), "series.runGoing")
    assert link.started == []


def test_a_ruida_without_a_line_is_refused_before_the_build(
    client, server, kernel, monkeypatch
):
    link = a_connected_ruida(client, kernel)
    link.state = "disconnected"
    a_rectangle(kernel)
    built = recording_builds(server, monkeypatch)
    refused(client.post("/api/job/start"), "machine.notConnected")
    assert link.started == [] and built == []


@pytest.mark.parametrize("phase", ["sending", "running", "paused"])
def test_a_second_burn_while_a_job_is_on_the_line_is_refused(
    client, server, kernel, monkeypatch, phase
):
    link = a_connected_ruida(client, kernel)
    link.the_job = a_job(phase)
    a_rectangle(kernel)
    built = recording_builds(server, monkeypatch)
    answer = refused(client.post("/api/job/start"), "job.alreadyOnTheMachine")
    assert "nothing has been sent" in answer.json()["detail"]
    assert link.started == [] and built == []


@pytest.mark.parametrize("phase", ["done", "stopped", "failed"])
def test_a_job_that_ended_leaves_the_line_free(client, kernel, phase):
    link = a_connected_ruida(client, kernel)
    link.the_job = a_job(phase)
    a_rectangle(kernel)
    assert client.post("/api/job/start").status_code == 200
    assert len(link.started) == 1


def test_the_links_refusal_becomes_a_sentence_with_a_code(client, kernel):
    link = a_connected_ruida(client, kernel)
    link.refuses = ConnectionError("A file is going to the controller.")
    a_rectangle(kernel)

    answer = refused(client.post("/api/job/start"), "job.notStarted")

    assert answer.json()["detail"] == (
        "The machine did not take the job: A file is going to the controller."
    )
    assert json.loads(answer.headers["X-OpenKerf-Error-Values"]) == {
        "detail": "A file is going to the controller."
    }


# ------------------------------------------------------- what the screen reads


def test_status_reads_each_phase_in_the_spoolers_shape(client, kernel):
    link = a_connected_ruida(client, kernel)

    empty = active_spooler(client)
    assert empty == {"present": True, "idle": True, "queue_length": 0, "jobs": [],
                     "ended": None}

    for phase, running, paused, status in (
        ("sending", True, False, "Running"),
        ("running", True, False, "Running"),
        ("paused", False, True, "Paused"),
    ):
        link.the_job = a_job(phase, sent=3, total=9)
        spooler = active_spooler(client)
        assert spooler["idle"] is False and spooler["queue_length"] == 1, phase
        assert spooler["ended"] is None
        (job,) = spooler["jobs"]
        assert job["label"] == "Keyrings"
        assert job["running"] is running, phase
        assert job["paused"] is paused, phase
        assert job["status"] == status, phase
        assert (job["steps_done"], job["steps_total"]) == (3, 9)
        # Packets on the line are not work on the material; see `line_job_snapshot`.
        assert job["progress"] is None
        assert job["elapsed_seconds"] > 0
        assert a_job_is_running(kernel) is True
        assert the_line_is_in_use(kernel) == "burning"

    link.the_job = a_job("done")
    assert active_spooler(client) == {"present": True, "idle": True, "queue_length": 0,
                                      "jobs": [], "ended": None}
    assert a_job_is_running(kernel) is False
    assert the_line_is_in_use(kernel) is None

    for phase in ("stopped", "failed"):
        link.the_job = a_job(phase, detail=f"The job was {phase} at block 2 of 4.")
        spooler = active_spooler(client)
        assert spooler["jobs"] == [] and spooler["idle"] is True
        assert spooler["ended"] == {
            "name": "Keyrings",
            "phase": phase,
            "detail": f"The job was {phase} at block 2 of 4.",
            "finished": 1_000_010.0,
        }


def test_the_engine_spooler_says_nothing_ended(client):
    assert active_spooler(client)["ended"] is None


def test_moving_is_refused_while_a_ruida_burns(client, kernel):
    """`MachineControl._idle()` reads the link's job through `a_job_is_running`."""
    link = a_connected_ruida(client, kernel)
    link.the_job = a_job("running")
    refused(client.post("/api/machine/jog", json={"dx_mm": 1, "dy_mm": 0}),
            "machine.movingWhileBurning")
    assert not [c for c in link.calls if isinstance(c, tuple)]


def test_an_upload_is_refused_while_a_ruida_burns(client, kernel):
    link = a_connected_ruida(client, kernel)
    link.the_job = a_job("running")
    a_rectangle(kernel)
    refused(client.post("/api/machine/upload", json={"name": "BORD"}),
            "upload.whileBurning")


# ------------------------------------------------------ a series and a tile run


def test_a_series_burns_plate_by_plate_over_the_line(client, kernel):
    """
    One plate per burn, each refused while the last is still on the line.

    A series marks a plate when its burn starts, on every laser — the spooler's road
    does the same — so "done" is what frees the line for the next plate, and a plate
    that ended "failed" or "stopped" says so on the status (`ended`) for the operator,
    who burns it again with the series' own confirmation.
    """
    link = a_connected_ruida(client, kernel)
    a_running_series(client)

    first = client.post("/api/series/burn", json={})
    assert first.status_code == 200, first.text
    assert first.json()["burned_rows"] == [0]
    assert [name for _, name in link.started] == ["Series 1 of 5"]

    link.the_job = a_job("running", name="Series 1 of 5")
    assert client.post("/api/series/advance", json={}).status_code == 200
    second = refused(client.post("/api/series/burn", json={}), "job.alreadyOnTheMachine")
    assert second.json()["detail"].endswith("nothing has been sent.")
    assert client.get("/api/series").json()["run"]["done"] == [[0, 0]]

    link.the_job = a_job("done", name="Series 1 of 5")
    second = client.post("/api/series/burn", json={})
    assert second.status_code == 200, second.text
    assert second.json()["burned_rows"] == [1]
    assert [name for _, name in link.started] == ["Series 1 of 5", "Series 2 of 5"]

    for phase in ("failed", "stopped"):
        link.the_job = a_job(phase, name="Series 2 of 5", detail="The line went away.")
        ended = active_spooler(client)["ended"]
        assert (ended["phase"], ended["detail"]) == (phase, "The line went away.")
    third = client.post("/api/series/advance", json={})
    assert third.status_code == 200
    assert client.post("/api/series/burn", json={}).status_code == 200
    assert link.started[-1][1] == "Series 3 of 5"


def test_a_tile_run_burns_tile_by_tile_over_the_line(client, kernel):
    link = a_connected_ruida(client, kernel)
    bed = next(d for d in client.get("/api/status").json()["devices"] if d["active"])["bed"]
    sheet = client.get("/api/sheets").json()["sheets"][0]
    client.patch(f"/api/sheets/{sheet['id']}",
                 json={"width_mm": bed["width_mm"] * 2.5, "height_mm": 150.0})
    client.patch(f"/api/sheets/{sheet['id']}", json={"tiling": {"enabled": True}})
    client.post("/api/design/elements", json={
        "type": "rect", "x_mm": 10, "y_mm": 40, "width_mm": 40, "height_mm": 40})
    client.post("/api/design/elements", json={
        "type": "rect", "x_mm": bed["width_mm"] * 1.2, "y_mm": 40,
        "width_mm": 40, "height_mm": 40})
    _enable_output(client)
    assert client.post("/api/tiling/start").status_code == 200

    client.post("/api/tiling/align", json={
        "reference": "plate_corner", "points": [{"x_mm": 0.0, "y_mm": 0.0}]})
    first = client.post("/api/tiling/burn")
    assert first.status_code == 200, first.text
    assert [name for _, name in link.started] == ["Tile 1"]

    link.the_job = a_job("running", name="Tile 1")
    client.post("/api/tiling/advance")
    client.post("/api/tiling/align", json={
        "reference": "markers", "points": _marks_at(client, 0)})
    refused(client.post("/api/tiling/burn"), "job.alreadyOnTheMachine")
    assert len(link.started) == 1

    link.the_job = a_job("done", name="Tile 1")
    second = client.post("/api/tiling/burn")
    assert second.status_code == 200, second.text
    assert [name for _, name in link.started] == ["Tile 1", "Tile 2"]
