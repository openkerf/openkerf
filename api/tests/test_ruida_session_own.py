"""
Our own Ruida line: framing byte for byte against the engine, the session's
semantics against a fake transport, and one round over real UDP on 127.0.0.1.

The session tests are the thirty of `deploy/patches/ruida-session.patch`
(`test/test_ruida_session.py` in the patched engine), ported to our API; the
name of each patch test is in the docstring of its port. Not ported, and why:

- `test_usb_requires_matching_probe_reply_but_no_data_ack`,
  `test_usb_open_bounds_write_wait_for_shutdown`,
  `test_usb_write_failure_is_not_success` — USB is out of the plan; a Ruida is
  UDP only.
- `test_sender_releases_lock_and_does_not_report_failed_file_sent` — the engine
  controller's `_data_sender`; streaming a file is `link.py`, phase 5. What the
  session owes it, that nothing behind a failed packet goes out, is
  `test_missing_ack_fails_queue_without_resending_file`.

Every test ends with no thread of ours alive and no socket left open; the
autouse fixture checks both.
"""

import os
import queue
import socket
import stat
import struct
import threading
import time
from concurrent.futures import Future
from types import SimpleNamespace

import pytest
from meerk40t.ruida.emulator import RuidaEmulator
from meerk40t.ruida.rdjob import RDJob, encode_bytes
from meerk40t.ruida.ruidasession import RuidaSession as EngineSession
from meerk40t.ruida.udp_connection import UDPConnection

from openkerf_api.ruida import framing
from openkerf_api.ruida.session import RuidaSession
from openkerf_api.ruida.transport import TransportError, TransportTimeout, UdpTransport
from openkerf_api.ruida_upload import _blocks

ACK = bytes([framing.ACK])
NAK = bytes([framing.NAK])
ENQ = bytes([framing.ENQ])
MEM_MACHINE_STATUS = b"\x04\x00"
MEM_CURRENT_X = b"\x04\x21"
MEM_CARD_ID = b"\x05\x7e"
STATUS_READ = framing.GET_SETTING + MEM_MACHINE_STATUS


def wait_for(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("Timed out waiting for session state")


def _socket_fds() -> set[int]:
    out = set()
    for name in os.listdir("/dev/fd"):
        try:
            if stat.S_ISSOCK(os.fstat(int(name)).st_mode):
                out.add(int(name))
        except OSError:
            pass
    return out


@pytest.fixture(autouse=True)
def leaves_nothing_behind():
    threads = set(threading.enumerate())
    sockets = _socket_fds()
    started = time.monotonic()
    yield
    left = [t for t in threading.enumerate() if t not in threads and t.is_alive()]
    assert not left, f"threads left running: {left}"
    assert _socket_fds() <= sockets, "a socket was left open"
    assert time.monotonic() - started < 5, "a test took longer than 5 s"


# -- framing, byte for byte against the engine -------------------------------


def _commands() -> bytes:
    """A payload of real commands, from the engine's own encoders."""
    job = RDJob(magic=framing.DEFAULT_MAGIC)
    out: list[bytes] = []
    for i in range(400):
        job.move_abs_xy(1000 + 37 * i, 2000 + 11 * i, output=out.append)
        job.cut_abs_xy(3000 + 13 * i, 4000 + 7 * i, output=out.append)
    job.get_setting(MEM_CARD_ID, output=out.append)
    return b"".join(out)


def _engine_package(packer, payload: bytes, magic: int) -> bytes:
    """An engine `_package`, called on a stand-in so no session or thread exists."""
    stand_in = SimpleNamespace(interface="udp", swizzle=RDJob(magic=magic).swizzle)
    return packer(stand_in, payload)


@pytest.mark.parametrize("magic", [0x88, 0x11, 0x38, -1])
def test_swizzle_is_the_engine_table_for_every_byte(magic):
    every = bytes(range(256))
    swizzler = framing.Swizzler(magic)
    assert swizzler.swizzle(every) == encode_bytes(every, magic=magic)
    assert swizzler.swizzle(every) == RDJob(magic=magic).swizzle(every)
    assert swizzler.unswizzle(swizzler.swizzle(every)) == every


@pytest.mark.parametrize("magic", [0x88, 0x11])
@pytest.mark.parametrize("payload", [ENQ, STATUS_READ, b"\xd8\x00", _commands()[:997]],
                         ids=["enq", "status-read", "stop", "997-bytes"])
def test_frame_is_the_engine_package(magic, payload):
    """Both engine packers: the patched session's and the older UDPConnection's."""
    swizzler = framing.Swizzler(magic)
    ours = framing.frame(payload, swizzler)
    assert ours == _engine_package(EngineSession._package, payload, magic)
    assert ours == _engine_package(UDPConnection._package, payload, magic)
    assert framing.unframe(ours, swizzler) == payload


def test_wire_bytes_of_the_answers_at_the_default_magic():
    """Measured: with magic 0x88 ACK is C6 on the wire, NAK 48, ENQ C8."""
    swizzler = framing.Swizzler()
    assert swizzler.swizzle(ACK + NAK + ENQ) == b"\xc6\x48\xc8"
    assert framing.frame(ENQ, swizzler) == b"\x00\xc8\xc8"


def _emulator():
    driver = SimpleNamespace(status=lambda: ((0, 0), "idle", "idle"))
    device = SimpleNamespace(driver=driver, current=(0, 0),
                             spooler=SimpleNamespace(send=lambda *a, **kw: None))
    return RuidaEmulator(device, None)


def test_engine_emulator_accepts_our_frames_and_rejects_a_broken_sum():
    """The emulator answers our frame with an ACK and parses all of it; one
    flipped checksum bit gets a NAK and nothing parsed."""
    swizzler = framing.Swizzler()
    emulator = _emulator()
    answers: list[bytes] = []
    emulator.reply = answers.append
    block = framing.split(_commands())[0]
    packet = framing.frame(block, swizzler)
    emulator.checksum_write(packet)
    assert [swizzler.unswizzle(a) for a in answers] == [ACK]
    assert emulator.job.get_contents() == block
    emulator.job.clear()
    answers.clear()
    emulator.checksum_write(packet[:1] + bytes([packet[1] ^ 1]) + packet[2:])
    assert [swizzler.unswizzle(a) for a in answers] == [NAK]
    assert emulator.job.buffer == []


def test_emulator_answers_a_memory_read_with_ack_then_nine_bytes():
    swizzler = framing.Swizzler()
    emulator = _emulator()
    answers: list[bytes] = []
    emulator.reply = answers.append
    emulator.checksum_write(framing.frame(STATUS_READ, swizzler))
    ack, reply = (swizzler.unswizzle(a) for a in answers)
    assert ack == ACK
    assert framing.is_reply_to(reply, MEM_MACHINE_STATUS)
    assert not framing.is_reply_to(reply, MEM_CURRENT_X)
    assert framing.memory_address(STATUS_READ) == MEM_MACHINE_STATUS
    assert framing.memory_address(STATUS_READ + b"\x00") is None


def test_split_cuts_between_commands_as_the_uploader_does():
    payload = _commands()
    blocks = framing.split(payload)
    assert blocks == _blocks(payload)
    assert b"".join(blocks) == payload
    assert len(blocks) > 3
    assert all(len(b) <= framing.MAX_PAYLOAD for b in blocks)
    assert all(b[0] >= 0x80 for b in blocks)


def test_split_against_the_engines_own_job_chopper():
    """Same bytes, cut at command starts; the engine's blocks run past 1000."""
    from meerk40t.ruida.controller import RuidaController
    from meerk40t.ruida.rdjob import parse_commands

    payload = _commands()
    controller = RuidaController.__new__(RuidaController)
    controller.job = RDJob()
    controller.job.buffer = [bytes(c) for c in parse_commands(payload)]
    controller._send_queue = []
    controller.divide_data_into_queue()
    theirs = controller._send_queue
    assert b"".join(theirs) == b"".join(framing.split(payload)) == payload
    assert all(b[0] >= 0x80 for b in theirs)
    assert max(len(b) for b in theirs) > framing.MAX_PAYLOAD
    assert max(len(b) for b in framing.split(payload)) <= framing.MAX_PAYLOAD


# -- the session, against a fake transport ------------------------------------


class FakeTransport:
    """The patch's fake, with our transport's method names."""

    def __init__(self):
        self.is_open = False
        self.writes: list[bytes] = []
        self.owners: set[int] = set()
        self.incoming: queue.Queue = queue.Queue()
        self.fail_opens = 0
        self.opens = 0
        self.respond = lambda data: [ACK]

    def touch(self):
        self.owners.add(threading.get_ident())

    def open(self):
        self.touch()
        self.opens += 1
        if self.fail_opens:
            self.fail_opens -= 1
            raise TransportError("bind failed")
        self.is_open = True

    def close(self):
        self.touch()
        self.is_open = False
        while not self.incoming.empty():
            self.incoming.get_nowait()

    def send(self, data):
        self.touch()
        if not self.is_open:
            raise TransportError("closed")
        self.writes.append(data)
        for reply in self.respond(data):
            self.incoming.put(reply)

    def receive(self, seconds=None):
        self.touch()
        try:
            return self.incoming.get(timeout=min(seconds or 0.02, 0.02))
        except queue.Empty:
            raise TransportTimeout() from None

    def drain(self):
        self.touch()
        count = 0
        while not self.incoming.empty():
            self.incoming.get_nowait()
            count += 1
        return count


def framed(payload: bytes) -> bytes:
    # magic -1 is the identity table, as `set_swizzles(bytes, bytes)` in the patch.
    return framing.frame(payload, framing.Swizzler(-1))


def make_session(transport, **kwargs) -> RuidaSession:
    options = dict(magic=-1, reply_seconds=0.2, receive_seconds=0.02,
                   nak_resends=1, retry_seconds=0.05)
    options.update(kwargs)
    return RuidaSession(lambda: transport, **options)


@pytest.fixture
def transport():
    return FakeTransport()


@pytest.fixture
def session(transport):
    session = make_session(transport)
    session.open()
    wait_for(lambda: session.connected)
    yield session
    session.shutdown()


def test_write_returns_acknowledgement_future(session, transport):
    """Patch: test_write_returns_acknowledgement_future."""
    future = session.write(b"file block")
    assert isinstance(future, Future)
    assert future.result(2) is None
    assert not session.busy
    assert transport.writes[-1] == framed(b"file block")


def test_no_double_packaged_probe(session, transport):
    """Patch: test_no_double_packaged_probe."""
    time.sleep(0.08)
    assert transport.writes == [framed(ENQ)]


def test_close_stays_closed_until_open(session, transport):
    """Patch: test_close_stays_closed_until_open."""
    session.close()
    assert not transport.is_open
    count = len(transport.writes)
    time.sleep(0.1)
    assert not session.connected
    assert not session.connecting
    assert session.state == "closed"
    assert len(transport.writes) == count
    session.open()
    wait_for(lambda: session.connected)
    assert len(transport.owners) == 1


def test_reply_before_ack_and_wrong_address(session, transport):
    """Patch: test_reply_before_ack_and_wrong_address. The answer is the result."""
    right = framing.SETTING_REPLY + MEM_MACHINE_STATUS + b"\x00" * 5
    wrong = framing.SETTING_REPLY + MEM_CURRENT_X + b"\x00" * 5
    transport.respond = lambda data: [wrong, right, ACK]
    future = session.write(STATUS_READ)
    assert future.result(2) == right
    assert session.replies == 1
    assert session.dropped == 1
    assert not session.busy


def test_missing_ack_fails_queue_without_resending_file(session, transport):
    """Patch: test_missing_ack_fails_queue_without_resending_file."""
    transport.respond = lambda data: []
    first = session.write(b"first block")
    second = session.write(b"second block")
    with pytest.raises(ConnectionError):
        first.result(2)
    with pytest.raises(ConnectionError):
        second.result(2)
    assert transport.writes.count(framed(b"first block")) == 1
    assert framed(b"second block") not in transport.writes
    assert not session.busy


def test_reply_timeout_clears_busy_and_recovers(session, transport):
    """Patch: test_reply_timeout_clears_busy_and_recovers."""
    future = session.write(STATUS_READ)
    with pytest.raises(ConnectionError):
        future.result(2)
    assert not session.busy
    wait_for(lambda: session.connected)
    session.write(b"later block").result(2)


def test_nak_is_bounded(transport):
    """Patch: test_nak_is_bounded. Exact: two resends allowed, three sends."""
    session = make_session(transport, nak_resends=2)
    try:
        session.open()
        wait_for(lambda: session.connected)
        transport.respond = lambda data: [NAK]
        future = session.write(b"bad block")
        with pytest.raises(ConnectionError, match="rejected"):
            future.result(2)
        assert transport.writes.count(framed(b"bad block")) == 3
    finally:
        session.shutdown()


def test_retry_failed_bind(session, transport):
    """Patch: test_retry_failed_bind."""
    session.close()
    transport.fail_opens = 1
    session.open()
    wait_for(lambda: session.connected)
    assert transport.opens >= 3


def test_shutdown_of_a_session_that_never_connects_terminates(transport):
    """Patch: test_shutdown_without_swizzles_terminates. We have no swizzles to
    wait for; the nearest case is a worker stuck failing to open."""
    never = make_session(transport)
    never.shutdown()  # never opened: no worker was ever started
    transport.fail_opens = 10 ** 6
    other = make_session(transport)
    other.open()
    worker = other._worker
    wait_for(lambda: transport.opens >= 2)
    other.shutdown()
    assert not worker.is_alive()
    with pytest.raises(ConnectionError):
        other.open()


def test_external_open_never_touches_transport(session, transport):
    """Patch: test_external_connect_never_reads_transport."""
    threads = [threading.Thread(target=session.open) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(1)
        assert not thread.is_alive()
    assert len(transport.owners) == 1
    assert transport.owners == {session._worker.ident}


def test_failed_queue_tolerates_concurrent_future_cancellation(session, transport):
    """Patch: test_failed_queue_tolerates_concurrent_future_cancellation."""
    transport.respond = lambda data: []
    first = session.write(b"active")
    wait_for(lambda: framed(b"active") in transport.writes)
    queued = session.write(b"queued")
    original_done = queued.done

    def cancel_during_check():
        done = original_done()
        queued.cancel()
        return done

    queued.done = cancel_during_check
    session.close()
    assert queued.cancelled()
    assert isinstance(first.exception(), ConnectionError)
    assert not session.busy
    assert session._worker.is_alive()


def test_old_generation_cannot_continue_upload_after_reconnect(session, transport):
    """Patch: test_old_generation_cannot_continue_upload_after_reconnect."""
    generation = session.generation
    session.write(b"first", generation=generation).result(2)
    session.close()
    session.open()
    wait_for(lambda: session.connected)
    with pytest.raises(ConnectionError):
        session.write(b"remainder", generation=generation)
    assert framed(b"remainder") not in transport.writes
    session.write(b"new transfer", generation=session.generation).result(2)


def test_close_reports_closed(transport):
    """Patch: test_close_emits_disconnected_status."""
    seen = []
    session = make_session(transport, on_state=lambda state, detail: seen.append(state))
    try:
        session.open()
        wait_for(lambda: session.connected)
        session.close()
        assert seen == ["connecting", "connected", "closed"]
    finally:
        session.shutdown()


def test_closed_session_reports_closed(session):
    """Patch: test_closed_session_reports_disconnected."""
    session.close()
    assert session.state == "closed"


def test_full_queue_fails_caller_without_blocking_worker(transport):
    """Patch: test_full_queue_fails_caller_without_blocking_worker."""
    session = make_session(transport, queue_size=1)
    try:
        session.open()
        wait_for(lambda: session.connected)
        transport.respond = lambda data: []
        first = session.write(b"active")
        wait_for(lambda: framed(b"active") in transport.writes)
        second = session.write(b"queued")
        started = time.monotonic()
        with pytest.raises(ConnectionError, match="full"):
            session.write(b"overflow")
        assert time.monotonic() - started < 0.05
        session.close()
        assert isinstance(first.exception(), ConnectionError)
        assert isinstance(second.exception(), ConnectionError)
    finally:
        session.shutdown()


def test_queued_cancellation_never_sends_later(session, transport):
    """Patch: test_queued_cancellation_never_sends_later."""
    session.reply_seconds = 2
    transport.respond = lambda data: []
    first = session.write(b"active")
    wait_for(lambda: framed(b"active") in transport.writes)
    assert session.busy
    assert not first.cancel()
    second = session.write(b"cancelled")
    assert second.cancel()
    transport.incoming.put(ACK)
    first.result(2)
    wait_for(lambda: not session.busy)
    assert framed(b"cancelled") not in transport.writes


def test_delayed_reply_after_ack_keeps_transaction_busy(session, transport):
    """Patch: test_delayed_reply_after_ack_keeps_transaction_busy."""
    session.reply_seconds = 2
    future = session.write(STATUS_READ)
    wait_for(lambda: session.acks >= 2)
    assert session.busy
    assert not future.done()
    reply = framing.SETTING_REPLY + MEM_MACHINE_STATUS + b"\x00" * 5
    transport.incoming.put(reply)
    assert future.result(2) == reply
    assert not session.busy


def test_nak_then_ack_retries_only_rejected_packet(session, transport):
    """Patch: test_nak_then_ack_retries_only_rejected_packet."""
    replies = iter([[NAK], [ACK]])
    transport.respond = lambda data: next(replies)
    session.write(b"block").result(2)
    assert transport.writes.count(framed(b"block")) == 2
    assert transport.writes == [framed(ENQ), framed(b"block"), framed(b"block")]


def test_close_interrupts_long_reply_wait_and_fails_future(session, transport):
    """Patch: test_close_interrupts_long_reply_wait_and_fails_future."""
    session.reply_seconds = 40
    future = session.write(STATUS_READ)
    wait_for(lambda: session._reply_pending)
    started = time.monotonic()
    session.close()
    assert time.monotonic() - started < 0.5
    with pytest.raises(ConnectionError):
        future.result(1)
    assert not session.busy
    assert not session._reply_pending
    assert not session._ack_pending


def test_many_status_reads_do_not_accumulate_queue(session, transport):
    """Patch: test_many_status_reads_do_not_accumulate_queue."""
    def respond(data):
        command = data[2:]
        if command.startswith(framing.GET_SETTING):
            return [ACK, framing.SETTING_REPLY + command[2:4] + b"\x00" * 5]
        return [ACK]

    transport.respond = respond
    for _ in range(50):
        session.read_memory(MEM_MACHINE_STATUS).result(2)
        assert not session.busy
        assert session.queued == 0
    assert session.replies == 50


def test_write_on_a_closed_session_does_not_reopen_it(session, transport):
    """Patch: test_monitor_does_not_reconnect_disconnected_session — the
    session's half: asking a closed line for something refuses and leaves it shut."""
    session.close()
    opens = transport.opens
    with pytest.raises(ConnectionError, match="Not connected"):
        session.read_memory(MEM_MACHINE_STATUS)
    time.sleep(0.1)
    assert transport.opens == opens
    assert session.state == "closed"


def test_close_then_open_is_a_fresh_connection(session, transport):
    """Patch: test_sync_explicitly_reopens_session — close and open, in that
    order, give a new generation, a new socket open and a new probe."""
    generation = session.generation
    opens = transport.opens
    session.close()
    session.open()
    wait_for(lambda: session.connected)
    assert session.generation > generation
    assert transport.opens == opens + 1
    assert transport.writes.count(framed(ENQ)) == 2


def test_close_while_still_connecting_cancels_the_retry(transport):
    """Patch: test_disconnect_cancels_retry_without_a_connected_device. A
    controller that never answers the probe; close stops the retrying."""
    transport.respond = lambda data: []
    session = make_session(transport)
    try:
        session.open()
        wait_for(lambda: transport.opens >= 2)
        assert session.state == "connecting"
        session.close()
        opens, writes = transport.opens, len(transport.writes)
        time.sleep(0.3)
        assert (transport.opens, len(transport.writes)) == (opens, writes)
        assert not transport.is_open
    finally:
        session.shutdown()


# -- what the patch did not have -----------------------------------------------


def test_priority_write_goes_before_queued_normal_packets(session, transport):
    """The packet on the line finishes first; then the priority lane, then the rest."""
    session.reply_seconds = 2
    transport.respond = lambda data: []
    active = session.write(b"active")
    wait_for(lambda: framed(b"active") in transport.writes)
    normal = [session.write(b"block %d" % i) for i in range(3)]
    stop = session.write(b"\xd8\x01", priority=True)
    assert session.queued == 4
    transport.respond = lambda data: [ACK]
    transport.incoming.put(ACK)
    for future in [active, stop, *normal]:
        future.result(2)
    sent = transport.writes[transport.writes.index(framed(b"active")):]
    assert sent == [framed(b"active"), framed(b"\xd8\x01"),
                    framed(b"block 0"), framed(b"block 1"), framed(b"block 2")]


def test_priority_lane_has_room_when_the_file_queue_is_full(transport):
    session = make_session(transport, queue_size=1)
    try:
        session.open()
        wait_for(lambda: session.connected)
        session.reply_seconds = 2
        transport.respond = lambda data: []
        session.write(b"active")
        wait_for(lambda: framed(b"active") in transport.writes)
        session.write(b"queued")
        with pytest.raises(ConnectionError, match="full"):
            session.write(b"overflow")
        stop = session.write(b"\xd8\x01", priority=True)
        transport.respond = lambda data: [ACK]
        transport.incoming.put(ACK)
        stop.result(2)
    finally:
        session.shutdown()


def test_a_stale_answer_waiting_before_a_send_does_not_count(session, transport):
    """An ACK already in the inbox when a packet goes out belongs to nothing."""
    transport.respond = lambda data: []
    transport.incoming.put(ACK)
    future = session.write(b"block")
    with pytest.raises(ConnectionError):
        future.result(2)
    assert session.drained == 1


def test_a_failure_moves_the_generation_and_says_why(session, transport):
    generation = session.generation
    transport.respond = lambda data: []
    with pytest.raises(ConnectionError):
        session.write(b"block").result(2)
    assert session.generation > generation
    assert "in time" in session.detail
    transport.respond = lambda data: [ACK]
    wait_for(lambda: session.connected)
    assert session.detail == ""


# -- the transport, on real sockets --------------------------------------------


def _bound_udp() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    return sock


def test_failed_udp_bind_closes_socket():
    """Patch: test_failed_udp_bind_closes_socket — with a real port in use."""
    taken = _bound_udp()
    try:
        transport = UdpTransport("127.0.0.1", listen_port=taken.getsockname()[1],
                                 bind_host="127.0.0.1")
        with pytest.raises(TransportError):
            transport.open()
        assert transport.socket is None
    finally:
        taken.close()


def test_udp_refuses_a_host_name_and_writes_to_the_numeric_peer():
    """Patch: test_udp_writes_to_resolved_peer. We do not resolve: a name is
    refused when the transport is made, and the IP gets the datagram."""
    with pytest.raises(ValueError, match="numeric"):
        UdpTransport("laser.invalid")
    peer = _bound_udp()
    transport = UdpTransport("127.0.0.1", send_port=peer.getsockname()[1],
                             listen_port=0, bind_host="127.0.0.1")
    try:
        transport.open()
        transport.send(b"block")
        peer.settimeout(1)
        data, sender = peer.recvfrom(64)
        assert data == b"block"
        assert sender == transport.local_address
    finally:
        transport.close()
        peer.close()


def test_udp_ignores_foreign_sender():
    """Patch: test_udp_ignores_foreign_sender — another port on the same host
    is foreign too."""
    peer, stranger = _bound_udp(), _bound_udp()
    transport = UdpTransport("127.0.0.1", send_port=peer.getsockname()[1],
                             listen_port=0, bind_host="127.0.0.1")
    try:
        transport.open()
        stranger.sendto(b"wrong", transport.local_address)
        peer.sendto(b"right", transport.local_address)
        assert transport.receive(1) == b"right"
        assert transport.dropped == 1
        with pytest.raises(TransportTimeout):
            transport.receive(0.02)
    finally:
        transport.close()
        peer.close()
        stranger.close()
    assert not transport.is_open


def test_drain_empties_what_is_waiting():
    peer = _bound_udp()
    transport = UdpTransport("127.0.0.1", send_port=peer.getsockname()[1],
                             listen_port=0, bind_host="127.0.0.1")
    try:
        transport.open()
        for _ in range(3):
            peer.sendto(ACK, transport.local_address)
        wait_for(lambda: _readable(transport.socket))
        time.sleep(0.02)
        assert transport.drain() == 3
        with pytest.raises(TransportTimeout):
            transport.receive(0.02)
    finally:
        transport.close()
        peer.close()


def _readable(sock) -> bool:
    import select
    return bool(select.select([sock], [], [], 0)[0])


# -- end to end over 127.0.0.1, with the engine's emulator answering -----------


class EmulatorPeer:
    """A UDP socket on 127.0.0.1 that hands every datagram to the emulator."""

    def __init__(self, silent: tuple[bytes, ...] = ()):
        self.sock = _bound_udp()
        self.sock.settimeout(0.02)
        self.emulator = _emulator()
        self.silent = silent
        self.received: list[bytes] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, name="emulator-peer")

    @property
    def port(self) -> int:
        return self.sock.getsockname()[1]

    def _serve(self):
        while not self._stop.is_set():
            try:
                data, sender = self.sock.recvfrom(2048)
            except TimeoutError:
                continue
            self.received.append(data)
            if framing.unframe(data, framing.Swizzler()) in self.silent:
                continue
            self.emulator.reply = lambda answer: self.sock.sendto(answer, sender)
            self.emulator.checksum_write(data)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join(1)
        self.sock.close()


def _udp_session(peer: EmulatorPeer) -> RuidaSession:
    return RuidaSession(
        lambda: UdpTransport("127.0.0.1", send_port=peer.port, listen_port=0,
                             bind_host="127.0.0.1"),
        reply_seconds=0.3, receive_seconds=0.02, retry_seconds=0.05)


def test_loopback_send_ack_and_memory_read_over_real_udp():
    """Every block of an 801-command payload ACKed by the emulator over UDP; the
    bytes it received are our frames, and it parsed the payload whole."""
    payload = _commands()
    blocks = framing.split(payload)
    with EmulatorPeer() as peer, _udp_session(peer) as session:
        session.open()
        wait_for(lambda: session.connected)
        generation = session.generation
        futures = [session.write(b, generation=generation) for b in blocks]
        for future in futures:
            assert future.result(2) is None
        status = session.read_memory(MEM_MACHINE_STATUS).result(2)
        assert framing.is_reply_to(status, MEM_MACHINE_STATUS)
        swizzler = framing.Swizzler()
        assert peer.received[0] == framing.frame(ENQ, swizzler)
        assert peer.received[1:1 + len(blocks)] == [framing.frame(b, swizzler) for b in blocks]
        # The card-ID read at the end is answered, not kept as job data.
        assert b"".join(peer.emulator.job.buffer) == payload[:-4]
        assert session.acks == len(blocks) + 2
        assert session.naks == 0
        session.close()
        assert session.state == "closed"


def test_loopback_missing_ack_is_not_replayed():
    """The emulator stays silent on one block: that block went out once, the
    block behind it never, and the session reconnects on its own."""
    blocks = framing.split(_commands())
    with EmulatorPeer(silent=(blocks[1],)) as peer, _udp_session(peer) as session:
        session.open()
        wait_for(lambda: session.connected)
        futures = [session.write(b) for b in blocks[:3]]
        futures[0].result(2)
        for future in futures[1:]:
            with pytest.raises(ConnectionError):
                future.result(2)
        swizzler = framing.Swizzler()
        assert peer.received.count(framing.frame(blocks[1], swizzler)) == 1
        assert framing.frame(blocks[2], swizzler) not in peer.received
        wait_for(lambda: session.connected)
        session.write(blocks[2]).result(2)
