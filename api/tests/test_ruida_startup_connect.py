"""
One connect attempt at startup, against the emulator peer: `ApiServer.connect_once`.

Started by `ApiServer.start()` (which the plugin's `openkerf` console command calls), in
a thread of its own, so startup never waits for a controller. One `RuidaLink.connect()`
and nothing after it: when the controller does not answer the link closes its session
and the line stays silent.
"""

import time

import pytest

from openkerf_api import link as link_module
from openkerf_api.ruida import framing
from openkerf_api.ruida.link import RuidaLink
from openkerf_api.server import ApiServer
from ruida_peer import ruida_peer

PROBE = bytes([framing.ENQ])


@pytest.fixture
def peer():
    with ruida_peer() as running:
        yield running


@pytest.fixture
def server(kernel, tmp_path, peer, monkeypatch):
    monkeypatch.setattr(
        link_module.Links,
        "_make",
        lambda self, device: RuidaLink(
            device, send_port=peer.send_port, listen_port=0, reply_seconds=0.3,
            poll_seconds=0.05,
        ),
    )
    made = ApiServer(kernel, library_path=tmp_path / "s.db")
    yield made
    made.links.close()


def _a_ruida(kernel, address):
    kernel.console("service device start ruida -i\n")
    kernel.device.address = address
    return kernel.device


def test_a_ruida_with_an_address_is_connected_once_at_startup(server, kernel, peer):
    device = _a_ruida(kernel, "127.0.0.1")

    thread = server.connect_once()
    thread.join(3)

    assert not thread.is_alive()
    link = server.links.for_device(device)
    assert link.connection()["state"] == "connected"
    assert [entry.payload for entry in peer.received].count(PROBE) == 1


def test_a_failed_attempt_reads_disconnected_and_sends_nothing_after_it(
    server, kernel, peer
):
    """
    The peer loses everything. The attempt ends within the link's bound (0.9 s here),
    the status reads "disconnected" with the link's sentence naming the address, and in
    the 1.5 s after it not one packet reaches the peer.
    """
    device = _a_ruida(kernel, "127.0.0.1")
    peer.ignore_next(10_000)

    started = time.monotonic()
    thread = server.connect_once()
    thread.join(3)
    took = time.monotonic() - started

    assert not thread.is_alive()
    link = server.links.for_device(device)
    reading = link.connection()
    assert reading["state"] == "disconnected"
    assert "127.0.0.1" in reading["detail"] and "did not answer" in reading["detail"]
    assert took < 2.0, took
    heard = len(peer.received)
    assert heard >= 1
    time.sleep(1.5)
    assert len(peer.received) == heard, "the line went on probing after the attempt"


def test_a_ruida_without_an_address_is_not_probed(server, kernel, peer):
    _a_ruida(kernel, "")

    assert server.connect_once() is None
    time.sleep(0.3)
    assert peer.received == []


def test_another_machine_is_not_connected_at_startup(server, kernel, peer):
    # The `kernel` fixture's active device is the dummy.
    assert server.connect_once() is None


def test_start_makes_the_one_attempt(server, kernel, monkeypatch):
    """`start()` is where it happens; recorded, so no port or controller is needed."""
    calls = []
    monkeypatch.setattr(server, "connect_once", lambda: calls.append(True))
    server.port = 0
    server.start()
    try:
        assert calls == [True]
    finally:
        server.stop()
