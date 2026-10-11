"""
The emulator as a UDP peer: does it answer the engine the way the engine expects?

Every packet here is framed by the engine itself — `RuidaSession._package` for checksum
and swizzle (`ruida/ruidasession.py:170-172`), `RDJob` for the commands and for reading
the answers back (`ruida/rdjob.py:1332-1366`) — and the round-trip tests go further and
let the engine's own `RuidaSession` and `UDPTransport` do the talking, ports aside. If
the peer and the engine disagreed about a single byte of the wire format, the session
would never report itself connected.

Measured against `ruida_peer()` on 127.0.0.1 (magic 0x88):

- ENQ, a move and a memory read each come back as one ACK datagram (`cc` unswizzled).
- A memory read of `MEM_MACHINE_STATUS` comes back as a second datagram,
  `da 01 04 00 00 00 00 00 16`: 22 in the emulator's mapping for "idle"
  (`ruida/emulator.py:1361-1369`). Note what the engine's controller makes of that:
  22 has bit `0x02` set, `MACHINE_STATUS_PART_END`, so `update_machine_status`
  (`ruida/controller.py:202-223`) labels an idle emulator "Part end", not "Idle".
  Whether a real KH-5030 says 22 when idle is a question for the packet capture.
- The card id read answers `0x65006500`, which the engine's `CID_LUT` calls
  "Unknown card."
"""

import socket
import threading
import time
from types import SimpleNamespace

import pytest
import meerk40t.ruida.udp_transport as udp
from meerk40t.ruida.rdjob import (
    ACK,
    ENQ,
    GET_SETTING,
    MACHINE_STATUS_JOB_RUNNING,
    MACHINE_STATUS_PART_END,
    MEM_CARD_ID,
    MEM_CURRENT_X,
    MEM_CURRENT_Y,
    MEM_MACHINE_STATUS,
    NAK,
    RDJob,
)
from meerk40t.ruida.ruidasession import RuidaSession

from ruida_peer import ruida_peer

LOCALHOST = "127.0.0.1"


@pytest.fixture(autouse=True)
def no_threads_left_behind():
    """Every test here must end with exactly the threads it started with."""
    before = set(threading.enumerate())
    yield
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        extra = [t for t in threading.enumerate() if t not in before and t.is_alive()]
        if not extra:
            return
        time.sleep(0.02)
    pytest.fail(f"threads left behind: {extra}")


@pytest.fixture
def job():
    """The engine's encoder, with the device's default magic (`ruida/device.py`)."""
    return RDJob(magic=0x88)


@pytest.fixture
def client():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((LOCALHOST, 0))
    sock.settimeout(0.3)
    yield sock
    sock.close()


def frame(job, data):
    """The engine's UDP framing — `RuidaSession._package` — without a session thread."""
    return RuidaSession._package(SimpleNamespace(swizzle=job.swizzle, interface="udp"), data)


def answers(sock, job):
    """Everything that comes back until the line has been quiet for 0.3 s, unswizzled."""
    out = []
    while True:
        try:
            data, source = sock.recvfrom(1024)
        except socket.timeout:
            return out
        out.append((job.unswizzle(data), source))


def a_move(job):
    commands = []
    job.move_abs_xy(10_000, 20_000, output=commands.append)
    return commands[0]


def test_a_packet_is_acknowledged_from_the_port_it_was_sent_to(job, client):
    """One ACK, from `(127.0.0.1, send_port)` — the only source the engine's transport
    accepts (`ruida/udp_transport.py:68`) — and the peer has the command, decoded."""
    move = a_move(job)
    with ruida_peer() as peer:
        client.sendto(frame(job, move), (LOCALHOST, peer.send_port))
        got = answers(client, job)
        assert got == [(ACK, (LOCALHOST, peer.send_port))]
        (entry,) = peer.received
        assert entry.action == "ack" and entry.checksum_ok
        assert entry.payload == move
        assert entry.commands == [move]


def test_a_memory_read_of_the_machine_status_is_answered_after_the_ack(job, client):
    """ACK, then nine bytes `da 01 04 00 <value:5>` — the shape the session waits for
    (`ruida/ruidasession.py:262-263`) — and `RDJob.decode_reply`, which the controller's
    `recv` uses (`ruida/controller.py:308`), reads it as the status word."""
    with ruida_peer() as peer:
        client.sendto(frame(job, GET_SETTING + MEM_MACHINE_STATUS), (LOCALHOST, peer.send_port))
        (ack, _), (reply, _) = answers(client, job)
        assert ack == ACK
        assert len(reply) == 9 and reply[:4] == b"\xda\x01" + MEM_MACHINE_STATUS
        mem, value, _ = job.decode_reply(reply)
        assert (mem, value) == (MEM_MACHINE_STATUS, 22)
        # The emulator's idle word carries the part-end bit; see the module docstring.
        assert value & MACHINE_STATUS_PART_END

        peer.state = "busy"
        client.sendto(frame(job, GET_SETTING + MEM_MACHINE_STATUS), (LOCALHOST, peer.send_port))
        _, (reply, _) = answers(client, job)
        assert job.decode_reply(reply)[1] == 21
        assert job.decode_reply(reply)[1] & MACHINE_STATUS_JOB_RUNNING

        peer.memory[MEM_MACHINE_STATUS] = 0
        client.sendto(frame(job, GET_SETTING + MEM_MACHINE_STATUS), (LOCALHOST, peer.send_port))
        _, (reply, _) = answers(client, job)
        assert job.decode_reply(reply)[1] == 0


def test_position_and_card_id_reads_come_from_the_emulator(job, client):
    """Position in micrometres from the stand-in driver's `status()`; the card id the
    emulator hard-codes (`ruida/emulator.py:1467-1468`)."""
    with ruida_peer() as peer:
        peer.position_um = (123_000, 45_000)
        values = {}
        for mem in (MEM_CURRENT_X, MEM_CURRENT_Y, MEM_CARD_ID):
            client.sendto(frame(job, GET_SETTING + mem), (LOCALHOST, peer.send_port))
            _, (reply, _) = answers(client, job)
            values[mem] = job.decode_reply(reply)[1]
        assert values[MEM_CURRENT_X] == 123_000
        assert values[MEM_CURRENT_Y] == 45_000
        assert values[MEM_CARD_ID] == "Unknown card.: (0x65006500)"


def test_a_bad_checksum_and_an_oversized_packet_are_refused(job, client):
    """The emulator's own refusal, not an injected one: a wrong checksum, and a packet
    longer than the 1470 payload bytes it reads (`ruida/emulator.py:112`)."""
    with ruida_peer() as peer:
        good = frame(job, a_move(job))
        bad = bytes([good[0] ^ 0xFF]) + good[1:]
        client.sendto(bad, (LOCALHOST, peer.send_port))
        assert [a for a, _ in answers(client, job)] == [NAK]

        client.sendto(frame(job, b"\xe7" * 1471), (LOCALHOST, peer.send_port))
        assert [a for a, _ in answers(client, job)] == [NAK]
        client.sendto(frame(job, b"\xe7" * 1470), (LOCALHOST, peer.send_port))
        assert [a for a, _ in answers(client, job)] == [ACK]
        assert [e.action for e in peer.received] == ["nak", "nak", "ack"]


def test_injected_nak_dropped_ack_and_lost_packet(job, client):
    """Each misbehaviour applies to exactly one packet, and the next one is normal."""
    move = frame(job, a_move(job))
    status = frame(job, GET_SETTING + MEM_MACHINE_STATUS)
    with ruida_peer() as peer:
        peer.nak_next()
        client.sendto(move, (LOCALHOST, peer.send_port))
        assert [a for a, _ in answers(client, job)] == [NAK]

        peer.drop_ack_next()
        client.sendto(status, (LOCALHOST, peer.send_port))
        # The ACK is lost; the reply data is not.
        (reply, _), = answers(client, job)
        assert reply[:4] == b"\xda\x01" + MEM_MACHINE_STATUS

        peer.ignore_next()
        client.sendto(move, (LOCALHOST, peer.send_port))
        assert answers(client, job) == []

        client.sendto(move, (LOCALHOST, peer.send_port))
        assert [a for a, _ in answers(client, job)] == [ACK]

        assert [e.action for e in peer.received] == [
            "nak-injected", "ack-dropped", "ignored", "ack"]
        assert [(r.data[:1], r.sent) for r in peer.replies] == [
            (NAK, True), (ACK, False), (b"\xda", True), (ACK, True)]


def test_a_fixed_reply_port_answers_there_and_not_to_the_source(job, client):
    """`reply_port` set: the answer goes to that port on the sender's host, the way an
    engine bound to 40200 would hear it even when it sent from elsewhere."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
        sender.bind((LOCALHOST, 0))
        sender.settimeout(0.3)
        with ruida_peer(reply_port=client.getsockname()[1]) as peer:
            sender.sendto(frame(job, ENQ), (LOCALHOST, peer.send_port))
            assert [a for a, _ in answers(client, job)] == [ACK]
            assert answers(sender, job) == []


# ---------------------------------------------------------------------------
# The engine's own session and transport, against the peer.


class _LoopbackTransport(udp.UDPTransport):
    """`UDPTransport` with the two things a test must change: the peer's port instead of
    50200, and a socket bound to 127.0.0.1 on a free port instead of `("", 40200)`
    (`ruida/udp_transport.py:18-19,40`). Everything else is the engine's."""

    peer_port = None

    def __init__(self, service):
        super().__init__(service)
        self.send_port = self.peer_port
        self.listen_port = 0

    def open(self):
        if self.is_open:
            return
        self._peer = socket.gethostbyname(self.send_address)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.settimeout(self._s_to)
        self.socket.bind((LOCALHOST, self.listen_port))


@pytest.fixture
def engine_session(monkeypatch, job):
    """A `RuidaSession` whose transport talks to a fresh peer; yields both."""
    with ruida_peer() as peer:
        transport = type("T", (_LoopbackTransport,), {"peer_port": peer.send_port})
        monkeypatch.setattr("meerk40t.ruida.ruidasession.udp.UDPTransport", transport)
        replies = []

        def channel(name, **kwargs):
            return replies.append if name.endswith("/recv") else (lambda *a: None)

        service = SimpleNamespace(
            interface="udp", safe_label="peer", name="peer", address=LOCALHOST,
            channel=channel, signal=lambda *a: None)
        session = RuidaSession(service)
        session.set_swizzles(job.swizzle, job.unswizzle)
        session.open()
        try:
            deadline = time.monotonic() + 2
            while not session.connected:
                assert time.monotonic() < deadline, "the session never connected"
                time.sleep(0.005)
            yield session, peer, replies
        finally:
            session.shutdown()


def test_the_engine_session_connects_and_reads_the_status(engine_session):
    """ENQ, ACK, connected; a status read resolves its Future and the reply reaches the
    recv channel, nine bytes the controller can decode."""
    session, peer, replies = engine_session
    assert peer.received[0].payload == ENQ
    session.write(GET_SETTING + MEM_MACHINE_STATUS).result(2)
    assert session.replies == 1 and len(replies) == 1
    assert RDJob().decode_reply(replies[0])[:2] == (MEM_MACHINE_STATUS, 22)


def test_the_engine_session_resends_after_an_injected_nak(engine_session, job):
    """NAK: the session sends the same packet once more (`ruida/ruidasession.py:253-261`)
    and the second copy is acknowledged."""
    session, peer, _ = engine_session
    move = a_move(job)
    peer.nak_next()
    session.write(move).result(2)
    copies = [e for e in peer.received if e.payload == move]
    assert [e.action for e in copies] == ["nak-injected", "ack"]
    assert copies[0].packet == copies[1].packet == frame(job, move)
    assert session.naks == 1


def test_the_engine_session_does_not_resend_after_a_dropped_ack(engine_session, job):
    """Lost ACK: the Future fails after the timeout and the block is *not* sent again
    (`ruida/ruidasession.py:237-240`) — the controller may well have taken it."""
    session, peer, _ = engine_session
    session._tries = 2  # 0.5 s instead of 1 s before the session gives up.
    move = a_move(job)
    peer.drop_ack_next()
    with pytest.raises(ConnectionError):
        session.write(move).result(3)
    time.sleep(0.3)
    assert [e.action for e in peer.received if e.payload == move] == ["ack-dropped"]


def test_shutdown_leaves_no_thread_and_frees_the_port():
    """After the context manager: the thread has ended, the socket is closed and the
    port can be bound again. (The autouse fixture checks the thread count as well.)"""
    with ruida_peer() as peer:
        port = peer.send_port
        thread = peer.thread
        assert thread.is_alive()
    assert not thread.is_alive()
    assert peer._socket.fileno() == -1
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as again:
        again.bind((LOCALHOST, port))
