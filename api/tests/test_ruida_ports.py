"""
`OPENKERF_RUIDA_SEND_PORT` / `OPENKERF_RUIDA_LISTEN_PORT`: development and tests only.

Unset, a `RuidaLink` made by `Links` keeps the real controller's 50200/40200. Set, the
link goes to the emulator on 127.0.0.1 at that port — end to end through the API's own
routes, with no `_make` patched, which is how the scratch server's `--ruida-emulator`
uses it.
"""

import time

import pytest
from fastapi.testclient import TestClient

from openkerf_api.link import Links, links_for, ruida_ports
from openkerf_api.ruida.transport import LISTEN_PORT, SEND_PORT
from openkerf_api.server import ApiServer
from ruida_peer import ruida_peer


def test_unset_means_the_real_controller_ports():
    assert ruida_ports({}) == {}
    assert ruida_ports({"OPENKERF_RUIDA_SEND_PORT": " "}) == {}


def test_set_ports_are_read_as_numbers():
    assert ruida_ports({"OPENKERF_RUIDA_SEND_PORT": "51234",
                        "OPENKERF_RUIDA_LISTEN_PORT": "0"}) == {"send_port": 51234, "listen_port": 0}


@pytest.mark.parametrize("value", ["fifty", "-1", "65536", "1.5"])
def test_a_value_that_is_not_a_port_is_refused(value):
    with pytest.raises(ValueError, match="OPENKERF_RUIDA_LISTEN_PORT"):
        ruida_ports({"OPENKERF_RUIDA_LISTEN_PORT": value})


def _ruida(client, kernel):
    made = client.post("/api/machines", json={"info": "ruida-beta"})
    assert made.status_code == 201, made.text
    device = next(d for d in kernel.services("device") if d.path == made.json()["path"])
    device.address = "127.0.0.1"
    return device


def test_without_the_variables_a_link_keeps_50200_and_40200(kernel, tmp_path, monkeypatch):
    monkeypatch.delenv("OPENKERF_RUIDA_SEND_PORT", raising=False)
    monkeypatch.delenv("OPENKERF_RUIDA_LISTEN_PORT", raising=False)
    server = ApiServer(kernel, library_path=tmp_path / "d.db")
    with TestClient(server.build_app()) as client:
        device = _ruida(client, kernel)
        link = Links().for_device(device)
        assert (link.send_port, link.listen_port) == (SEND_PORT, LISTEN_PORT) == (50200, 40200)
    server.links.close()


def test_the_variables_take_the_api_to_an_emulator_on_its_own_port(kernel, tmp_path, monkeypatch):
    with ruida_peer() as peer:
        monkeypatch.setenv("OPENKERF_RUIDA_SEND_PORT", str(peer.send_port))
        monkeypatch.setenv("OPENKERF_RUIDA_LISTEN_PORT", "0")
        server = ApiServer(kernel, library_path=tmp_path / "d.db")
        try:
            with TestClient(server.build_app()) as client:
                device = _ruida(client, kernel)
                link = links_for(kernel).for_device(device)
                assert (link.send_port, link.listen_port) == (peer.send_port, 0)
                answer = client.post("/api/machine/connect")
                assert answer.status_code == 200, answer.text
                assert answer.json()["connection"]["state"] == "connected"
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline and not peer.received:
                    time.sleep(0.02)
                assert peer.received, "nothing reached the emulator"
                assert {r.source[0] for r in peer.received} == {"127.0.0.1"}
        finally:
            server.links.close()
