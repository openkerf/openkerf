"""
Phase 2 of the own Ruida line: which link answers, and where the routes reach it.

A Ruida always goes through our own `RuidaLink`; every other laser through the engine as
before (`EngineLink`). These tests put a `FakeLink` where `RuidaLink` would be, so no
socket opens: they check the wiring, not the line (`test_ruida_link.py` does that).
"""

import socket
import threading
import time
import types

import pytest
from fastapi.testclient import TestClient

import meerk40t.ruida.device as ruida_device_module
from conftest import _bootstrap
from openkerf_api import link as link_module
from openkerf_api.busy import the_line_is_in_use
from openkerf_api.link import EngineLink, Links, is_ruida, links_for
from openkerf_api.machine import MachineControl
from openkerf_api.ruida import closed
from openkerf_api.ruida.closed import ClosedSession
from openkerf_api.ruida_upload import RuidaUpload
from openkerf_api.server import ApiServer
from openkerf_api.edits import DesignError


class FakeLink:
    """A `MachineLink` of kind "ruida" that records what it is asked."""

    kind = "ruida"
    made: list = []

    def __init__(self, device):
        self.device = device
        self.calls: list[str] = []
        self.state = "disconnected"
        self.native = None
        self.use = None
        self.closed = False
        FakeLink.made.append(self)

    def connect(self):
        self.calls.append("connect")
        self.state = "connected"
        return self.connection()

    def disconnect(self):
        self.calls.append("disconnect")
        self.state = "disconnected"
        return self.connection()

    def connection(self):
        return {"state": self.state, "detail": None if self.state == "connected" else "fake"}

    def position(self):
        return self.native

    def machine_state(self):
        return self.machine

    def line_in_use(self):
        return self.use

    def close(self):
        self.calls.append("close")
        self.closed = True

    # -- phase 4: the motion verbs, recorded with their millimetres -------------------

    #: What `motion_capabilities()` answers; a test may take one away.
    caps = dict.fromkeys(
        ("home", "physical_home", "move", "jog", "frame", "focus", "lock", "unlock",
         "pause", "resume", "stop"),
        True,
    )
    #: What `machine_state()` answers.
    machine = "unknown"
    #: An exception every verb raises instead of recording, when set.
    fails: BaseException | None = None

    def motion_capabilities(self):
        return dict(self.caps)

    def _verb(self, *call):
        if self.fails is not None:
            raise self.fails
        self.calls.append(call if len(call) > 1 else call[0])

    def home(self, physical=False):
        self._verb("home", physical)

    def move_to(self, x_mm, y_mm):
        self._verb("move_to", x_mm, y_mm)

    def move_by(self, dx_mm, dy_mm):
        self._verb("move_by", dx_mm, dy_mm)

    def trace(self, corners):
        self._verb("trace", [tuple(c) for c in corners])

    def focus(self, dz_mm):
        self._verb("focus", dz_mm)

    def lock(self):
        self._verb("lock")

    def unlock(self):
        self._verb("unlock")

    def pause(self):
        self._verb("pause")

    def resume(self):
        self._verb("resume")

    def stop(self):
        self._verb("stop")


@pytest.fixture
def fake_links(monkeypatch):
    FakeLink.made = []
    monkeypatch.setattr(link_module.Links, "_make", lambda self, device: FakeLink(device))
    return FakeLink.made


@pytest.fixture
def server(kernel, tmp_path, fake_links):
    return ApiServer(kernel, library_path=tmp_path / "d.db")


@pytest.fixture
def client(server):
    with TestClient(server.build_app()) as c:
        yield c


def a_ruida(client) -> str:
    """A Ruida made through the wizard's route; it is active afterwards."""
    answer = client.post("/api/machines", json={"info": "ruida-beta"})
    assert answer.status_code == 201, answer.text
    return answer.json()["path"]


def link_of(kernel, path) -> FakeLink:
    device = next(d for d in kernel.services("device") if d.path == path)
    return links_for(kernel).for_device(device)


# ------------------------------------------------------------- which link


def test_a_ruida_gets_our_link_and_the_dummy_the_engines(kernel, fake_links):
    assert not is_ruida(kernel.device)
    assert isinstance(links_for(kernel).for_device(kernel.device), EngineLink)

    kernel.console("service device start ruida -i\n")
    assert is_ruida(kernel.device)
    first = links_for(kernel).for_device(kernel.device)
    assert isinstance(first, FakeLink)
    # Cached per path: the status bar and the connect button ask the same line.
    assert links_for(kernel).for_device(kernel.device) is first


def test_a_recycled_path_closes_the_old_line():
    """The kernel hands a freed path to the next device; that is not the same line."""
    links = Links(factory=FakeLink)

    class Ruida(ruida_device_module.RuidaDevice):
        def __init__(self):  # no service: only the identity matters here
            self._path = "ruida"

    one, two = Ruida(), Ruida()
    old = links.for_device(one)
    new = links.for_device(two)
    assert new is not old
    assert old.closed and not new.closed


# ---------------------------------------------------------------- connecting


def test_connect_and_disconnect_reach_the_link_for_a_ruida(client, kernel):
    path = a_ruida(client)

    answer = client.post("/api/machine/connect")
    assert answer.status_code == 200, answer.text
    assert answer.json()["connection"]["state"] == "connected"

    answer = client.post("/api/machine/disconnect")
    assert answer.status_code == 200, answer.text
    assert answer.json()["connection"]["state"] == "disconnected"
    assert link_of(kernel, path).calls == ["connect", "disconnect"]


def test_a_ruida_link_that_stays_shut_is_a_coded_refusal(client, kernel):
    path = a_ruida(client)
    link = link_of(kernel, path)
    link.connect = lambda: {"state": "disconnected", "detail": "Nobody at 10.0.0.9."}

    answer = client.post("/api/machine/connect")
    assert answer.status_code == 409, answer.text
    assert answer.headers["X-OpenKerf-Error"] == "machine.ruidaConnectFailed"
    assert "Nobody at 10.0.0.9." in answer.json()["detail"]


def test_a_ruida_always_offers_connecting(client):
    a_ruida(client)
    caps = client.get("/api/capabilities").json()
    assert caps["connection"] == {"connect": True, "disconnect": True}


def test_the_dummy_still_goes_to_the_console(client, fake_links):
    """No connect command on the dummy: the engine's refusal, and no line made."""
    answer = client.post("/api/machine/connect")
    assert answer.status_code == 409, answer.text
    assert fake_links == []


def test_another_laser_reaches_the_console_through_engine_link(fake_links):
    class Runner:
        ran: list = []

        def supports(self, name, input_type="None"):
            return name == "usb_connect"

        def run(self, command):
            self.ran.append(command)
            return ["USB Connected."]

    device = types.SimpleNamespace(spooler=None)
    control = MachineControl(types.SimpleNamespace(device=device), Runner())

    result = control.connect()

    assert control.runner.ran == ["usb_connect"]
    assert result["output"] == ["USB Connected."]
    assert fake_links == []


# ------------------------------------------------------------------ status


def test_status_shows_the_links_connection_and_position_for_a_ruida(client, kernel):
    path = a_ruida(client)
    link = link_of(kernel, path)
    link.state = "connected"
    link.native = (10_000, 20_000)  # micrometres, like `driver.native_x/native_y`

    devices = client.get("/api/status").json()["devices"]
    ruida = next(d for d in devices if d["path"] == path)

    assert ruida["connection"]["state"] == "connected"
    assert isinstance(ruida["connection"]["held_ms"], int)
    assert ruida["position"]["native"] == [10_000, 20_000]
    assert ruida["position"]["mm"] == pytest.approx([10.0, 20.0])
    # Nothing open on our side: no counters to show.
    assert ruida["line"] is None

    link.state = "disconnected"
    ruida = next(
        d for d in client.get("/api/status").json()["devices"] if d["path"] == path
    )
    assert ruida["connection"] == {"state": "disconnected", "detail": "fake",
                                   "held_ms": ruida["connection"]["held_ms"]}


def test_the_line_in_use_is_the_links_answer_for_a_ruida(client, kernel):
    path = a_ruida(client)
    assert the_line_is_in_use(kernel) is None
    link_of(kernel, path).use = "uploading"
    assert the_line_is_in_use(kernel) == "uploading"


# ------------------------------------------------- one line to a controller


def test_switching_machines_closes_the_old_line(client, kernel):
    first = a_ruida(client)
    client.post("/api/machine/connect")
    old = link_of(kernel, first)
    second = a_ruida(client)  # `device add` activates it
    assert second != first
    assert old.closed

    client.post("/api/machine/connect")
    new = link_of(kernel, second)
    answer = client.post(f"/api/machines/{first}/activate")
    assert answer.status_code == 200, answer.text
    assert new.closed


def test_deleting_a_ruida_closes_its_line(client, kernel):
    first = a_ruida(client)
    a_ruida(client)  # active now; the first one's line was closed by the switch
    client.get("/api/status")  # the status bar reads every machine, the first included
    held = links_for(kernel)._ruida[first][1]
    assert not held.closed

    answer = client.delete(f"/api/machines/{first}")
    assert answer.status_code == 200, answer.text
    assert held.closed
    assert first not in links_for(kernel)._ruida


def test_shutdown_closes_every_line(server, client, kernel):
    path = a_ruida(client)
    client.post("/api/machine/connect")
    link = link_of(kernel, path)

    server.stop()

    assert link.closed
    assert links_for(kernel)._ruida == {}


# ---------------------------------------------------------------- settings


def test_the_ruida_settings_sheet_has_no_interface(client):
    path = a_ruida(client)
    for essential in ("true", "false"):
        sheets = client.get(f"/api/machines/{path}/settings?essential={essential}").json()
        attrs = {field["attr"] for sheet in sheets for field in sheet["fields"]}
        assert "interface" not in attrs
        assert "address" in attrs
    every = client.get(f"/api/machines/{path}/settings").json()
    assert "magic" in {field["attr"] for sheet in every for field in sheet["fields"]}

    refused = client.patch(f"/api/machines/{path}/settings", json={"interface": "usb"})
    assert refused.status_code == 409, refused.text


# ------------------------------------------- what the line does not carry yet


def test_burning_a_ruida_is_refused_until_the_line_carries_it(client, kernel):
    """Phase 5 is the burn; until then a start is refused and nothing reaches the line."""
    path = a_ruida(client)
    answer = client.post("/api/job/start")
    assert answer.status_code == 409, answer.text
    assert answer.headers["X-OpenKerf-Error"] == "machine.notOnTheLineYet"
    assert [c for c in link_of(kernel, path).calls if c != "close"] == []


def test_an_upload_to_a_ruida_is_refused_at_once(kernel):
    kernel.console("service device start ruida -i\n")
    upload = RuidaUpload(kernel)
    started = time.monotonic()
    with pytest.raises(DesignError) as error:
        upload._link()
    assert error.value.code == "upload.notConnected"
    # Not the eight-second wait for an engine session that will never connect.
    assert time.monotonic() - started < 0.5


# ------------------------------------------------- the engine's device, closed


def test_the_plugin_keeps_the_engines_ruida_closed(monkeypatch):
    """Installed once at `register`, idempotent, and nothing opens on activation."""
    binds = []
    real_bind = socket.socket.bind

    def bind(sock, address):
        binds.append(address)
        return real_bind(sock, address)

    monkeypatch.setattr(socket.socket, "bind", bind)
    before = set(threading.enumerate())
    kernel = _bootstrap()
    try:
        assert closed.installed()
        assert ruida_device_module.RuidaSession is ClosedSession
        assert closed.install() is False  # a second registration changes nothing

        kernel.console("service device start ruida -i\n")
        assert type(kernel.device.active_session) is ClosedSession
        kernel.console(".interface_update\n")
        kernel.console(".ruida_connect\n")
        time.sleep(0.6)  # past one retry of the engine's worker, had one started

        assert binds == []
        assert [t for t in threading.enumerate()
                if t not in before and "_ruida_handshaker" in t.name] == []
    finally:
        kernel()


def test_install_puts_it_back_once(monkeypatch):
    monkeypatch.setattr(ruida_device_module, "RuidaSession", object)
    assert closed.install() is True
    assert ruida_device_module.RuidaSession is ClosedSession
    assert closed.install() is False


def test_install_refuses_an_engine_without_the_attribute(monkeypatch):
    monkeypatch.delattr(ruida_device_module, "RuidaSession")
    with pytest.raises(RuntimeError):
        closed.install()
