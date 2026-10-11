"""
Phase 3 end to end: the upload route, `RuidaUpload`, our `RuidaLink.send_file`, a real
UDP socket, and the engine's emulator taking the file as a controller would.

The fixture is `test_ruida_link_api.py`'s: `Links._make` builds a `RuidaLink` on the
peer's ports, the machine is made through the route and pointed at 127.0.0.1. Only the
ports and the waits differ from production (`reply_seconds` 0.3, polls every 0.05 s).

The peer records every datagram it gets, unswizzled (`ruida_peer.Received.payload`), so
what the controller received can be compared byte for byte with what we built. What is
injected on the wire — a NAK, a lost packet, a reconnect — is aimed at one packet by
wrapping the session's `write`: the monitor is paused during the file, so the packet
after that call is the one on the wire.
"""

import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from openkerf_api import link as link_module
from openkerf_api.busy import the_line_is_in_use
from openkerf_api.ruida import framing
from openkerf_api.ruida.link import RuidaLink
from openkerf_api.server import ApiServer
from ruida_peer import ruida_peer
from test_ruida_upload import a_design_over_one_block

PROBE = bytes([framing.ENQ])


@pytest.fixture
def peer(tmp_path, monkeypatch):
    # The emulator opens `<name>.rd` through `get_safe_path` on our `E7 01`
    # (`ruida/emulator.py:757`); without this it lands where the user lives.
    import meerk40t.ruida.emulator as emulator_module

    monkeypatch.setattr(
        emulator_module, "get_safe_path", lambda name, *a, **kw: str(tmp_path / name)
    )
    with ruida_peer() as running:
        yield running
        stream = running.emulator.filestream
        if stream is not None:
            stream.close()


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
    made = ApiServer(kernel, library_path=tmp_path / "u.db")
    yield made
    made.links.close()


@pytest.fixture
def client(server):
    with TestClient(server.build_app()) as c:
        yield c


def _connected(client, kernel, server):
    """A Ruida made through the route, at 127.0.0.1, connected; its link."""
    made = client.post("/api/machines", json={"info": "ruida-beta"})
    assert made.status_code == 201, made.text
    kernel.device.address = "127.0.0.1"
    answer = client.post("/api/machine/connect")
    assert answer.json()["connection"]["state"] == "connected", answer.text
    return server.links.for_device(kernel.device)


def _pinned(server, kernel):
    """Build the job once and make the upload send exactly those bytes."""
    a_design_over_one_block(kernel)
    upload = server.ruida_upload
    payload = upload.runner.build_job_bytes()
    upload.runner.build_job_bytes = lambda *a, **kw: payload
    frames = upload.frames("BORD", payload)
    assert len(frames) - 2 > 3, "the design left no room for a fault in the middle"
    return payload, frames


def _payload(peer, entry) -> bytes:
    """The unswizzled payload; the peer leaves it empty on a packet it ignored."""
    return entry.payload or peer.emulator.unswizzle(entry.packet[2:])


def _file_packets(peer, since=0):
    """What reached the peer after `since` that is neither a probe nor a memory read."""
    return [
        entry for entry in peer.received[since:]
        if _payload(peer, entry) != PROBE
        and not _payload(peer, entry).startswith(framing.GET_SETTING)
    ]


def _aim(monkeypatch, session, packet, act):
    """Call `act(session)` once, just before `packet` is written."""
    original = session.write
    done = []

    def write(data, **kwargs):
        if data == packet and not done:
            done.append(True)
            act(session)
        return original(data, **kwargs)

    monkeypatch.setattr(session, "write", write)
    return done


def test_a_file_arrives_byte_identical_and_in_order(client, kernel, server, peer):
    """
    Measured on these eight circles: 6 blocks behind the two headers, every one of
    the eight packets acknowledged once, and the payloads the peer unswizzled equal to
    `frames()` byte for byte and in order.
    """
    link = _connected(client, kernel, server)
    payload, frames = _pinned(server, kernel)
    since = len(peer.received)

    answer = client.post("/api/machine/upload", json={"name": "BORD"})

    assert answer.status_code == 200, answer.text
    assert answer.json() == {"name": "BORD", "bytes": len(payload), "chunks": len(frames) - 2}
    arrived = _file_packets(peer, since)
    assert [entry.payload for entry in arrived] == frames
    assert [entry.action for entry in arrived] == ["ack"] * len(frames)
    assert peer.emulator.filename is None, "the emulator never read to END_OF_FILE"
    assert link.connection()["state"] == "connected"


def test_a_nak_on_one_block_is_resent_once_and_the_upload_still_succeeds(
    client, kernel, server, peer, monkeypatch
):
    link = _connected(client, kernel, server)
    payload, frames = _pinned(server, kernel)
    since = len(peer.received)
    _aim(monkeypatch, link.session, frames[3], lambda session: peer.nak_next())

    answer = client.post("/api/machine/upload", json={"name": "BORD"})

    assert answer.status_code == 200, answer.text
    arrived = _file_packets(peer, since)
    assert [e.action for e in arrived if e.payload == frames[3]] == ["nak-injected", "ack"]
    assert [e.payload for e in arrived if e.action == "ack"] == frames
    assert link.session.naks == 1


def test_an_ignored_block_mid_file_is_interrupted_and_nothing_follows_it(
    client, kernel, server, peer, monkeypatch
):
    """
    The peer loses packet 4 (the third block) altogether: no ACK. The session fails it
    after `reply_seconds` and never sends it again, and the route says three of six —
    the two blocks before it and the one that went out unacknowledged — announced.
    """
    link = _connected(client, kernel, server)
    payload, frames = _pinned(server, kernel)
    chunks = len(frames) - 2
    since = len(peer.received)
    _aim(monkeypatch, link.session, frames[4], lambda session: peer.ignore_next())

    answer = client.post("/api/machine/upload", json={"name": "BORD"})

    assert answer.status_code == 409, answer.text
    assert answer.headers["X-OpenKerf-Error"] == "upload.interrupted"
    values = json.loads(answer.headers["X-OpenKerf-Error-Values"])
    assert values == {"sent": 3, "chunks": chunks, "announced": True}
    assert f"3 of {chunks}" in answer.json()["detail"]
    time.sleep(1.0)  # the session reconnects meanwhile; no block may follow
    arrived = [_payload(peer, e) for e in _file_packets(peer, since)]
    assert arrived == frames[:5], [p[:4].hex() for p in arrived]
    assert [e.action for e in _file_packets(peer, since)][-1] == "ignored"


def test_a_reconnect_mid_file_fails_the_upload(client, kernel, server, peer, monkeypatch):
    """
    The line drops and comes back between two confirmed blocks: the generation moves
    on, and the next block is refused before it is sent — never resumed on the new
    connection. One block was out (frames 2), the second (frames 3) never left.
    """
    link = _connected(client, kernel, server)
    payload, frames = _pinned(server, kernel)
    chunks = len(frames) - 2
    since = len(peer.received)
    before = link.session.generation

    def reconnect(session):
        session.close()
        session.open()
        deadline = time.monotonic() + 2
        while not session.connected and time.monotonic() < deadline:
            time.sleep(0.01)
        assert session.connected, "the session did not come back"

    _aim(monkeypatch, link.session, frames[3], reconnect)

    answer = client.post("/api/machine/upload", json={"name": "BORD"})

    assert answer.status_code == 409, answer.text
    assert answer.headers["X-OpenKerf-Error"] == "upload.interrupted"
    values = json.loads(answer.headers["X-OpenKerf-Error-Values"])
    assert values == {"sent": 1, "chunks": chunks, "announced": True}
    assert link.session.generation > before
    assert link.connection()["state"] == "connected"
    assert [e.payload for e in _file_packets(peer, since)] == frames[:3]


def test_no_status_poll_goes_out_during_the_upload(
    client, kernel, server, peer, monkeypatch
):
    """
    The monitor polls every 0.05 s here, and before and after the file it does; between
    the first packet of the file and the last not one memory read reaches the peer.

    The line is held idle for 0.2 s before the second block — four poll periods — so the
    monitor has room to slip a read in. Without the pause it does: measured with
    `Monitor.pause` made a no-op, a read went out in that window. Without the idle window
    it did not, even unpaused, in 6 of 6 runs (eight circles, 6 blocks, with and without
    a 30 ms ACK delay in the peer): the monitor skips while the session is busy, and the
    gap between one receipt and the next write is shorter than its period. The pause makes
    that a rule instead of a timing.
    """
    link = _connected(client, kernel, server)
    payload, frames = _pinned(server, kernel)
    _aim(monkeypatch, link.session, frames[3], lambda session: time.sleep(0.2))
    deadline = time.monotonic() + 2
    while link.monitor.polls < 3 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert link.monitor.polls >= 3, "the monitor was not polling before the upload"

    answer = client.post("/api/machine/upload", json={"name": "BORD"})
    assert answer.status_code == 200, answer.text

    payloads = [entry.payload for entry in peer.received]
    first = payloads.index(frames[0])
    last = first + payloads[first:].index(frames[-1])
    between = [p for p in payloads[first:last + 1] if p.startswith(framing.GET_SETTING)]
    assert between == [], f"{len(between)} status reads went out during the file"
    polls = link.monitor.polls
    deadline = time.monotonic() + 2
    while link.monitor.polls == polls and time.monotonic() < deadline:
        time.sleep(0.01)
    assert link.monitor.polls > polls, "the monitor did not poll again after the file"


def test_the_line_says_uploading_during_the_file_and_nothing_after(
    client, kernel, server, peer, monkeypatch
):
    link = _connected(client, kernel, server)
    payload, frames = _pinned(server, kernel)
    assert link.line_in_use() is None
    seen = []
    original = link.session.write

    def write(data, **kwargs):
        seen.append((link.line_in_use(), the_line_is_in_use(kernel)))
        return original(data, **kwargs)

    monkeypatch.setattr(link.session, "write", write)

    answer = client.post("/api/machine/upload", json={"name": "BORD"})

    assert answer.status_code == 200, answer.text
    assert len(seen) == len(frames)
    assert set(seen) == {("uploading", "uploading")}, seen
    assert link.line_in_use() is None
    assert the_line_is_in_use(kernel) is None


def test_a_jog_during_the_file_is_refused_by_what_the_link_says(
    client, kernel, server, peer, monkeypatch
):
    """
    `busy.py` reads the link first: with the claim of `sending_a_file` out of the
    picture, the link alone saying "uploading" still refuses a second writer.
    """
    from openkerf_api import busy
    from openkerf_api.edits import DesignError

    link = _connected(client, kernel, server)
    payload, frames = _pinned(server, kernel)
    monkeypatch.setattr(busy, "a_file_is_being_sent", lambda kernel: False)
    answers = []

    def jog(session):
        # Straight to the control the route calls, from inside the upload's own
        # request: a second request through the same TestClient would wait on it.
        try:
            server.motion.jog(5, 0)
            answers.append("moved")
        except DesignError as error:
            answers.append(error.code)

    _aim(monkeypatch, link.session, frames[2], jog)

    answer = client.post("/api/machine/upload", json={"name": "BORD"})

    assert answer.status_code == 200, answer.text
    assert answers == ["machine.sendingAFile"], answers


def test_a_second_file_on_the_same_line_is_refused_while_the_first_holds_it(
    client, kernel, server, peer, monkeypatch
):
    link = _connected(client, kernel, server)
    payload, frames = _pinned(server, kernel)
    server.ruida_upload.line_claim_seconds = 0.05
    outcome = {}

    def second(session):
        thread = threading.Thread(
            target=lambda: outcome.setdefault("second", _try(link, [b"\xe8\x02"])))
        thread.start()
        thread.join(2)

    _aim(monkeypatch, link.session, frames[2], second)
    answer = client.post("/api/machine/upload", json={"name": "BORD"})

    assert answer.status_code == 200, answer.text
    assert outcome["second"] == "LineTaken"


def _try(link, packets):
    try:
        link.send_file(packets, claim_seconds=0.05)
    except link_module.LineTaken:
        return "LineTaken"
    except Exception as error:  # pragma: no cover - reported through the value
        return repr(error)
    return "sent"
