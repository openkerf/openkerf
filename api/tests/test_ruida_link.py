"""
`RuidaLink` against the engine's emulator on 127.0.0.1: connecting, status and silence.

Every link here talks to `ruida_peer` on ephemeral ports; the device is a stand-in with
the two settings the engine's Ruida device keeps, `address` and `magic`. Where a value
is decoded, the engine's own `RuidaController.recv` is run on the very nine bytes the
peer sent and the two must agree.

Measured here, with the link's defaults (reply 1.0 s, poll 0.2 s) and the peer
ignoring everything for 5 s (`test_a_five_second_silence_ends_connected_without_asking`):
the read on the line fails after 1.0 s, the session says "connecting" with "The Ruida
did not acknowledge or answer in time.", probes again every 1.5 s — four packets in
the 5 s, the generation moving 0 → 4 — and is "connected" again 1.21–1.23 s (three
runs) after the peer answers again, the rest of one 1.5 s probe cycle, never "disconnected", with nobody calling `connect()`.

Every test ends with no thread of ours alive and no socket left open.
"""

import os
import socket
import stat
import threading
import time
from types import SimpleNamespace

import pytest
from meerk40t.ruida.controller import RuidaController
from meerk40t.ruida.rdjob import (
    ENQ,
    MACHINE_STATUS_MOVING,
    MEM_CARD_ID,
    MEM_CURRENT_X,
    MEM_CURRENT_Y,
    MEM_MACHINE_STATUS,
    RDJob,
)

from openkerf_api.ruida.link import CLOSED, RuidaLink
from openkerf_api.ruida.monitor import card_label

from ruida_peer import ruida_peer

LOCALHOST = "127.0.0.1"
#: Small enough to keep the suite quick, large enough for a loaded laptop.
FAST = dict(listen_port=0, reply_seconds=0.3, poll_seconds=0.02)
#: Tests that run at the link's real timings and may take up to 10 s.
SLOW = {"test_a_five_second_silence_ends_connected_without_asking"}


def wait_for(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("Timed out waiting")


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
def leaves_nothing_behind(request):
    threads = set(threading.enumerate())
    sockets = _socket_fds()
    started = time.monotonic()
    yield
    left = [t for t in threading.enumerate() if t not in threads and t.is_alive()]
    assert not left, f"threads left running: {left}"
    assert _socket_fds() <= sockets, "a socket was left open"
    limit = 10 if request.node.name in SLOW else 5
    assert time.monotonic() - started < limit, f"a test took longer than {limit} s"


@pytest.fixture
def peer():
    with ruida_peer() as p:
        yield p


def device(address=LOCALHOST, magic=0x88):
    return SimpleNamespace(address=address, magic=magic)


@pytest.fixture
def link(peer):
    made = RuidaLink(device(), send_port=peer.send_port, **FAST)
    yield made
    made.close()


def _silence(peer):
    """Lose everything until `_speak`; `ignore_next` with a count nothing reaches."""
    peer.ignore_next(10 ** 9)


def _speak(peer):
    with peer._changed:
        peer._ignore = 0


def _engine(reply: bytes):
    """The engine controller's own reading of `reply`, on a stand-in with no thread."""
    driver = SimpleNamespace(native_x=None, native_y=None)
    events = []
    stand_in = SimpleNamespace(
        job=RDJob(), _dispatch_lut=RuidaController._dispatch_lut,
        machine_status=None, card_id=b"", events=events.append,
        bed_x=-1.0, bed_y=-1.0, x=-1.0, y=-1.0, _x_read=False, _y_read=False,
        _update_position=lambda: None, _idle=None, _waiting=True, _connected=False,
        service=SimpleNamespace(driver=driver, signal=lambda *a: None,
                                bedwidth="", bedheight=""))
    RuidaController.recv(stand_in, reply)
    return stand_in, driver, events


def _last_reply(peer, address):
    for reply in reversed(list(peer.replies)):
        if len(reply.data) == 9 and reply.data[2:4] == address:
            return reply.data
    raise AssertionError(f"no reply for {address.hex()}")


# -- nothing before connect --------------------------------------------------------


def test_the_constructor_opens_nothing(peer):
    threads, sockets = set(threading.enumerate()), _socket_fds()
    link = RuidaLink(device(), send_port=peer.send_port, **FAST)
    assert set(threading.enumerate()) == threads
    assert _socket_fds() == sockets
    assert link.kind == "ruida"
    assert link.connection() == {"state": "disconnected",
                                 "detail": "The line to the Ruida is not open."}
    assert link.position() is None
    assert link.machine_state() == "unknown"
    assert link.line_in_use() is None
    time.sleep(0.1)
    assert peer.received == []
    link.close()
    link.close()


def test_the_constructor_signature_and_defaults():
    link = RuidaLink(device())
    assert (link.send_port, link.listen_port) == (50200, 40200)
    assert (link.reply_seconds, link.poll_seconds) == (1.0, 0.2)
    link.close()


def test_a_host_name_is_refused_and_nothing_is_tried():
    link = RuidaLink(device("laser.local"), send_port=9, **FAST)
    sentence = "The Ruida's address must be a numeric IPv4 address, not 'laser.local'."
    assert link.connection() == {"state": "disconnected", "detail": sentence}
    threads = set(threading.enumerate())
    assert link.connect() == {"state": "disconnected", "detail": sentence}
    assert set(threading.enumerate()) == threads
    assert link.session is None
    link.close()


def test_the_engines_default_address_is_refused_in_a_sentence():
    """The engine's device setting defaults to "localhost" (`ruida/device.py:355`)."""
    link = RuidaLink(device("localhost"), send_port=9, **FAST)
    detail = link.connect()["detail"]
    assert detail.endswith("not 'localhost'.") and detail[0].isupper()
    link.close()


# -- connecting and reading -------------------------------------------------------


def test_connect_is_connected_and_starts_with_a_probe(link, peer):
    assert link.connect() == {"state": "connected", "detail": None}
    wait_for(lambda: link.position() is not None)
    assert peer.received[0].payload == ENQ
    reads = [r.payload[2:4] for r in peer.received[1:8]]
    assert reads[:4] == [MEM_CARD_ID, MEM_MACHINE_STATUS, MEM_CURRENT_X, MEM_CURRENT_Y]
    assert link.machine_state() == "idle"


def test_status_position_and_card_id_decode_as_the_engine_does(link, peer):
    peer.position_um = (123000, 45600)
    link.connect()
    wait_for(lambda: link.position() == (123000, 45600))
    monitor = link.monitor

    _, driver, _ = _engine(_last_reply(peer, MEM_CURRENT_X))
    _, driver_y, _ = _engine(_last_reply(peer, MEM_CURRENT_Y))
    assert link.position() == (driver.native_x, driver_y.native_y) == (123000, 45600)

    engine, _, events = _engine(_last_reply(peer, MEM_MACHINE_STATUS))
    assert monitor.status_word == engine.machine_status == 22
    assert events == ["Part end"]

    engine, _, _ = _engine(_last_reply(peer, MEM_CARD_ID))
    assert card_label(monitor.card_id) == engine.card_id == "Unknown card.: (0x65006500)"
    assert time.monotonic() - monitor.last_answer < 1


@pytest.mark.parametrize("state, word, ours, engines", [
    ("idle", 22, "idle", "Part end"),
    ("busy", 21, "running", "Job running"),
    ("hold", 23, "running", "Part end"),
    ("moving", MACHINE_STATUS_MOVING, "moving", "Moving"),
])
def test_machine_state_of_each_word(link, peer, state, word, ours, engines):
    """Where we differ from the engine's label, `monitor.machine_state` says why."""
    if state == "moving":
        peer.memory[MEM_MACHINE_STATUS] = word
    else:
        peer.state = state
    link.connect()
    wait_for(lambda: link.monitor.status_word == word)
    assert link.machine_state() == ours
    _, _, events = _engine(_last_reply(peer, MEM_MACHINE_STATUS))
    assert events == [engines]


# -- disconnecting ----------------------------------------------------------------


def test_disconnect_stays_disconnected_and_sends_nothing(link, peer):
    link.connect()
    wait_for(lambda: link.position() is not None)
    assert link.disconnect() == {"state": "disconnected", "detail": CLOSED}
    count = len(peer.received)
    time.sleep(link.poll_seconds * 5 + link.reply_seconds)
    assert len(peer.received) == count
    assert link.connection() == {"state": "disconnected", "detail": CLOSED}
    assert link.machine_state() == "unknown"
    assert not link.monitor.running


def test_reconnect_is_a_new_generation_and_reads_again(link, peer):
    link.connect()
    first = link.generation
    link.disconnect()
    answers = link.monitor.answers
    assert link.connect()["state"] == "connected"
    assert link.generation > first
    wait_for(lambda: link.monitor.answers > answers + 3)
    assert link.machine_state() == "idle"


def test_close_is_bounded_and_idempotent(link, peer):
    link.connect()
    wait_for(lambda: link.position() is not None)
    started = time.monotonic()
    link.close()
    link.close()
    assert time.monotonic() - started < 1.5
    assert link.session is None
    assert link.connection()["state"] == "disconnected"


# -- silence ----------------------------------------------------------------------


def test_a_five_second_silence_ends_connected_without_asking(peer):
    """
    The KH-5030 gaps were 3.9, 4.5 and 4.6 s; this is 5 s, at the link's defaults.
    Measured: four packets lost in the 5 s (one read, three probes), generation 0 → 4,
    connected again 1.21–1.23 s after the peer answers again (three runs; one probe
    cycle is 1.5 s), never "disconnected".
    """
    link = RuidaLink(device(), send_port=peer.send_port, listen_port=0)
    try:
        assert link.connect()["state"] == "connected"
        wait_for(lambda: link.position() is not None)
        generation = link.generation
        seen = []
        stop = threading.Event()

        def watch():
            while not stop.is_set():
                seen.append(link.connection()["state"])
                time.sleep(0.01)

        watcher = threading.Thread(target=watch)
        watcher.start()
        before = len(peer.received)
        _silence(peer)
        time.sleep(5.0)
        lost = len(peer.received) - before
        _speak(peer)
        spoke = time.monotonic()
        answers = link.monitor.answers
        wait_for(lambda: link.connection()["state"] == "connected", timeout=2.0)
        back = time.monotonic() - spoke
        wait_for(lambda: link.monitor.answers > answers)
        stop.set()
        watcher.join()

        assert "connecting" in seen and "disconnected" not in seen
        assert 3 <= lost <= 5
        assert link.generation >= generation + 3
        assert back < 1.6
    finally:
        link.close()


def test_a_disconnect_during_a_silence_is_not_undone_by_answers(link, peer):
    link.connect()
    wait_for(lambda: link.position() is not None)
    _silence(peer)
    wait_for(lambda: link.connection()["state"] == "connecting")
    assert link.connection()["detail"] == "The Ruida did not acknowledge or answer in time."
    link.disconnect()
    _speak(peer)
    count = len(peer.received)
    time.sleep(1.0)
    assert link.connection() == {"state": "disconnected", "detail": CLOSED}
    assert len(peer.received) == count


def test_an_address_that_never_answers_gives_up_within_the_bound():
    mute = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    mute.bind((LOCALHOST, 0))
    try:
        link = RuidaLink(device(), send_port=mute.getsockname()[1], **FAST)
        started = time.monotonic()
        answer = link.connect()
        took = time.monotonic() - started
        assert answer == {"state": "disconnected",
                          "detail": "The Ruida at 127.0.0.1 did not answer within 0.9 seconds."}
        assert 0.85 <= took < 1.4
        assert link.machine_state() == "unknown"
        # It let go: nothing more is sent.
        mute.settimeout(0.05)
        while True:
            try:
                mute.recvfrom(64)
            except TimeoutError:
                break
        mute.settimeout(0.6)
        with pytest.raises(TimeoutError):
            mute.recvfrom(64)
        link.close()
    finally:
        mute.close()
