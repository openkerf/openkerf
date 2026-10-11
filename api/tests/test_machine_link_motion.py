"""
Phase 4 of the own Ruida line: the motion routes and the realtime verbs reach the link.

A Ruida's move, jog, home, frame, focus, lock, unlock, pause, resume and stop go to its
`MachineLink` with the design's millimetres; the dummy device's go to the console with
exactly the lines they always did (`EngineLink`). The guards about the request itself
stay in `machine.py` and fire before either link is asked. A `FakeLink` stands where
`RuidaLink` would, so no socket opens.
"""

import pytest
from fastapi.testclient import TestClient

from openkerf_api import machine as machine_module
from openkerf_api.busy import sending_a_file
from openkerf_api.server import ApiServer

from test_machine_link import FakeLink, a_ruida, fake_links, link_of  # noqa: F401


@pytest.fixture
def server(kernel, tmp_path, fake_links):  # noqa: F811
    return ApiServer(kernel, library_path=tmp_path / "m.db")


@pytest.fixture
def client(server):
    with TestClient(server.build_app()) as c:
        yield c


class Console(list):
    """What the console was asked once `arm()`ed, recorded rather than run."""

    def __init__(self, server, monkeypatch):
        super().__init__()
        self.server, self.monkeypatch = server, monkeypatch

    def arm(self):
        def run(command):
            self.append(command)
            return [f"ran {command}"]

        self.monkeypatch.setattr(self.server.commands, "run", run)
        return self


@pytest.fixture
def console(server, monkeypatch):
    # Armed after a Ruida is made: making one runs console lines of its own.
    return Console(server, monkeypatch)


def moves(link):
    return [c for c in link.calls if c not in ("close", "connect", "disconnect")]


ROUTES = [
    ("/api/machine/home", {}, ("home", False)),
    ("/api/machine/home", {"physical": True}, ("home", True)),
    ("/api/machine/move", {"x_mm": 10, "y_mm": 20.5}, ("move_to", 10.0, 20.5)),
    ("/api/machine/jog", {"dx_mm": -1.5, "dy_mm": 0}, ("move_by", -1.5, 0.0)),
    ("/api/machine/focus", {"distance_mm": 2}, ("focus", 2.0)),
    ("/api/machine/lock", None, "lock"),
    ("/api/machine/unlock", None, "unlock"),
    ("/api/job/pause", None, "pause"),
    ("/api/job/resume", None, "resume"),
    ("/api/job/stop", None, "stop"),
]


def post(client, route, body):
    return client.post(route, json=body) if body is not None else client.post(route)


# ---------------------------------------------------------- a Ruida: the link


@pytest.mark.parametrize("route, body, call", ROUTES)
def test_each_route_reaches_a_ruidas_link(client, kernel, console, route, body, call):
    path = a_ruida(client)
    console.arm()
    answer = post(client, route, body)
    assert answer.status_code == 200, answer.text
    assert moves(link_of(kernel, path)) == [call]
    assert console == [], "a Ruida's verb went to the engine's console"


def test_a_frame_reaches_a_ruidas_link_as_five_corners(client, kernel, console):
    path = a_ruida(client)
    console.arm()
    answer = client.post(
        "/api/machine/frame", json={"x_mm": 10, "y_mm": 20, "width_mm": 30, "height_mm": 40}
    )
    assert answer.status_code == 200, answer.text
    assert answer.json()["corners"] == 5
    assert answer.json()["notice"] is None
    assert moves(link_of(kernel, path)) == [
        ("trace", [(10, 20), (40, 20), (40, 60), (10, 60), (10, 20)])
    ]
    assert console == []


def test_a_ruidas_capabilities_come_from_its_link(client, kernel):
    path = a_ruida(client)
    link = link_of(kernel, path)
    link.caps = {**FakeLink.caps, "focus": False, "pause": False}

    caps = client.get("/api/capabilities").json()
    assert caps["motion"] == {
        "home": True, "physical_home": True, "unlock": True, "lock": True,
        "move": True, "jog": True, "focus": False,
    }
    assert caps["actions"]["pause"] is False
    assert caps["actions"]["resume"] is True
    assert caps["actions"]["stop"] is True

    # And what the link says it cannot do is refused before it is asked.
    answer = client.post("/api/machine/focus", json={"distance_mm": 2})
    assert answer.status_code == 409
    assert moves(link) == []


def test_a_ruidas_pause_and_activity_are_read_from_its_link(client, kernel):
    path = a_ruida(client)
    link = link_of(kernel, path)

    def read():
        devices = client.get("/api/devices").json()
        device = next(d for d in devices if d["path"] == path)
        return device["paused"], device["laser_status"]

    assert read() == (None, None), "unknown is not 'not paused'"
    link.machine = "paused"
    assert read() == (True, "paused")
    link.machine = "running"
    assert read() == (False, "active")
    link.machine = "idle"
    assert read() == (False, "idle")


def test_a_second_pause_on_a_paused_ruida_is_not_sent(client, kernel):
    path = a_ruida(client)
    link = link_of(kernel, path)
    link.machine = "paused"
    answer = client.post("/api/job/pause")
    assert answer.status_code == 200, answer.text
    assert answer.json()["output"] == ["already paused"]
    assert moves(link) == []


# ------------------------------------------------- a line that does not carry it


@pytest.mark.parametrize("route, body, call", ROUTES[:-1])
def test_a_lost_line_is_a_coded_refusal(client, kernel, route, body, call):
    path = a_ruida(client)
    link_of(kernel, path).fails = ConnectionError("the line is shut")
    answer = post(client, route, body)
    assert answer.status_code == 409, answer.text
    assert answer.headers["X-OpenKerf-Error"] == "machine.notConnected"
    assert "Connect first" in answer.json()["detail"]


def test_an_unconfirmed_move_says_so(client, kernel):
    path = a_ruida(client)
    link_of(kernel, path).fails = TimeoutError("no ACK")
    answer = client.post("/api/machine/jog", json={"dx_mm": 1, "dy_mm": 0})
    assert answer.status_code == 409, answer.text
    assert answer.headers["X-OpenKerf-Error"] == "machine.unconfirmed"


@pytest.mark.parametrize("why", [ConnectionError("shut"), TimeoutError("no ACK")])
def test_a_stop_that_did_not_arrive_points_at_the_machines_button(client, kernel, why):
    path = a_ruida(client)
    link_of(kernel, path).fails = why
    answer = client.post("/api/job/stop")
    assert answer.status_code == 409, answer.text
    assert answer.headers["X-OpenKerf-Error"] == "machine.stopUnconfirmed"
    assert "stop button on the machine" in answer.json()["detail"]


# ------------------------------------------- the request's guards, before the link


@pytest.mark.parametrize(
    "route, body",
    [
        ("/api/machine/jog", {"dx_mm": 0, "dy_mm": 0}),
        ("/api/machine/jog", {"dx_mm": "nan", "dy_mm": 0}),
        ("/api/machine/move", {"x_mm": None, "y_mm": 3}),
        ("/api/machine/focus", {"distance_mm": 101}),
        ("/api/machine/focus", {"distance_mm": 0}),
        ("/api/machine/frame",
         {"x_mm": 0, "y_mm": 0, "width_mm": 99999, "height_mm": 10}),
    ],
)
def test_the_requests_own_guards_fire_before_the_link(client, kernel, route, body):
    path = a_ruida(client)
    answer = client.post(route, json=body)
    assert answer.status_code in (409, 422), answer.text
    assert moves(link_of(kernel, path)) == []


@pytest.mark.parametrize(
    "route, body, code",
    [
        ("/api/machine/jog", {"dx_mm": 1, "dy_mm": 0}, "machine.movingWhileBurning"),
        ("/api/machine/home", {}, "machine.movingWhileBurning"),
        ("/api/machine/frame",
         {"x_mm": 1, "y_mm": 1, "width_mm": 5, "height_mm": 5},
         "machine.movingWhileBurning"),
        ("/api/machine/unlock", None, "machine.motorsWhileBurning"),
    ],
)
def test_nothing_moves_a_ruida_while_a_job_burns(
    client, kernel, monkeypatch, route, body, code
):
    path = a_ruida(client)
    monkeypatch.setattr(machine_module, "a_job_is_running", lambda _kernel: True)
    answer = post(client, route, body)
    assert answer.status_code == 409, answer.text
    assert answer.headers["X-OpenKerf-Error"] == code
    assert moves(link_of(kernel, path)) == []


def test_the_rotary_refusal_comes_before_a_ruidas_link(client, kernel):
    path = a_ruida(client)
    client.post("/api/machine/rotary", json={"active": True, "kind": "chuck", "diameter_mm": 80})
    refused = client.post("/api/machine/home", json={})
    assert refused.headers["X-OpenKerf-Error"] == "rotary.homeWhileActive"
    assert moves(link_of(kernel, path)) == []


def test_while_a_file_is_being_sent_only_stop_reaches_a_ruida(client, kernel):
    """
    Every verb but stop is refused during an upload; stop goes through, in one call.
    See `test_stopping_stays_reachable_while_a_file_is_being_sent` for why.
    """
    path = a_ruida(client)
    link = link_of(kernel, path)
    with sending_a_file(kernel) as claimed:
        assert claimed
        for route, body, _call in ROUTES[:-1]:
            answer = post(client, route, body)
            assert answer.status_code == 409, (route, answer.text)
            assert answer.headers["X-OpenKerf-Error"] == "machine.sendingAFile", route
        assert moves(link) == []

        answer = client.post("/api/job/stop")
        assert answer.status_code == 200, answer.text
    assert moves(link) == ["stop"]


# ------------------------------------------------- the dummy: the console, as before


@pytest.mark.parametrize(
    "route, body, lines",
    [
        ("/api/machine/home", {}, ["home"]),
        ("/api/machine/home", {"physical": True}, ["physical_home"]),
        ("/api/machine/move", {"x_mm": 10, "y_mm": 20.5},
         ["move_absolute 10.0000mm 20.5000mm"]),
        ("/api/machine/jog", {"dx_mm": -1.5, "dy_mm": 0},
         ["move_relative -1.5000mm 0.0000mm"]),
        ("/api/machine/frame", {"x_mm": 10, "y_mm": 20, "width_mm": 30, "height_mm": 40},
         [
             "move_absolute -f 10.0000mm 20.0000mm",
             "move_absolute -f 40.0000mm 20.0000mm",
             "move_absolute -f 40.0000mm 60.0000mm",
             "move_absolute -f 10.0000mm 60.0000mm",
             "move_absolute -f 10.0000mm 20.0000mm",
         ]),
        ("/api/machine/lock", None, ["lock"]),
        ("/api/machine/unlock", None, ["unlock"]),
        ("/api/job/pause", None, ["pause"]),
        ("/api/job/stop", None, ["abort"]),
    ],
)
def test_the_dummy_reaches_the_console_as_before(
    client, console, fake_links, route, body, lines  # noqa: F811
):
    console.arm()
    answer = post(client, route, body)
    assert answer.status_code == 200, answer.text
    assert console == lines
    assert answer.json()["output"] == [f"ran {line}" for line in lines]
    assert fake_links == [], "the dummy got a Ruida's line"


def test_a_busy_console_still_gives_the_frame_its_notice(server, client, monkeypatch):
    monkeypatch.setattr(server.commands, "run", lambda command: ["Busy Error"])
    answer = client.post(
        "/api/machine/frame", json={"x_mm": 10, "y_mm": 20, "width_mm": 30, "height_mm": 40}
    )
    assert answer.status_code == 200, answer.text
    assert "busy" in answer.json()["notice"]
