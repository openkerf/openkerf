"""
The whole of phase 2, end to end: the API's own routes, our `RuidaLink`, a real UDP socket,
and the engine's emulator answering as a controller.

`test_machine_link.py` checks the wiring with a stand-in link and `test_ruida_link.py`
the line without the API; this is the one place both are real at once. Only the ports
differ from production, so the test does not need 50200/40200 free.
"""

import time

import pytest
from fastapi.testclient import TestClient

from openkerf_api import link as link_module
from openkerf_api.ruida.closed import ClosedSession
from openkerf_api.ruida.link import RuidaLink
from openkerf_api.server import ApiServer
from ruida_peer import ruida_peer


@pytest.fixture
def peer():
    with ruida_peer() as running:
        yield running


@pytest.fixture
def client(kernel, tmp_path, peer, monkeypatch):
    monkeypatch.setattr(
        link_module.Links,
        "_make",
        lambda self, device: RuidaLink(
            device, send_port=peer.send_port, listen_port=0, reply_seconds=0.3, poll_seconds=0.05
        ),
    )
    server = ApiServer(kernel, library_path=tmp_path / "d.db")
    with TestClient(server.build_app()) as c:
        yield c
    server.links.close()


def _ruida(client, kernel) -> str:
    made = client.post("/api/machines", json={"info": "ruida-beta"})
    assert made.status_code == 201, made.text
    path = made.json()["path"]
    device = next(d for d in kernel.services("device") if d.path == path)
    device.address = "127.0.0.1"
    return path


def _reading(client, path) -> dict:
    return next(d for d in client.get("/api/status").json()["devices"] if d["path"] == path)


def _until(predicate, seconds=2.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.02)
    return predicate()


def test_connect_status_position_and_disconnect_through_the_routes(client, kernel, peer):
    path = _ruida(client, kernel)
    device = kernel.device
    assert type(device.active_session) is ClosedSession
    peer.position_um = (123_000, 45_600)

    answer = client.post("/api/machine/connect")
    assert answer.status_code == 200, answer.text
    assert answer.json()["connection"]["state"] == "connected"

    reading = _until(lambda: (r := _reading(client, path))["position"]["native"] and r)
    assert reading["connection"]["state"] == "connected"
    assert reading["position"]["native"] == [123_000, 45_600]
    assert reading["line"]["acks"] > 0

    answer = client.post("/api/machine/disconnect")
    assert answer.status_code == 200, answer.text
    assert answer.json()["connection"]["state"] == "disconnected"
    heard = len(peer.received)
    time.sleep(0.3)
    assert len(peer.received) == heard
    assert _reading(client, path)["connection"]["state"] == "disconnected"


def test_a_controller_that_never_answers_is_a_refusal_with_its_address(client, kernel, peer):
    _ruida(client, kernel)
    peer.ignore_next(10_000)

    answer = client.post("/api/machine/connect")

    assert answer.status_code == 409, answer.text
    assert answer.headers.get("X-OpenKerf-Error") == "machine.ruidaConnectFailed"
    assert "127.0.0.1" in answer.text
