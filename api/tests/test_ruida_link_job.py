"""
Phase 5 on `RuidaLink`: a job streamed over our own line, and its phase from the status word.

Offline, `framing.job_blocks` is compared with the engine's own
`RuidaController.divide_data_into_queue` on a stand-in holding the golden files' commands.
On the line, every job goes to `ruida_peer` on 127.0.0.1 — the engine's emulator behind a
UDP socket, which parses the stream and hands the finished job to a spooler that runs
nothing. What the peer reports as its status word is scripted with `peer.state`
("idle" 22, "busy" 21, "hold" 23 in the emulator's mapping) or `peer.memory` (the
KH-5030's and Ruida Bridge's measured words). Nothing here reaches a machine.
"""

import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from meerk40t.ruida.controller import RuidaController
from meerk40t.ruida.rdjob import ENQ, GET_SETTING, MEM_MACHINE_STATUS, RDJob, parse_commands

from openkerf_api.link import LineTaken
from openkerf_api.ruida import encode, framing
from openkerf_api.ruida.link import (
    BURNING,
    EMPTY_JOB,
    FILE_BEFORE_JOB,
    JOB_HOLDS_LINE,
    JOB_ON_LINE,
    LET_GO,
    NEVER_SEEN_RUNNING,
    RuidaLink,
)

from ruida_peer import ruida_peer

FIXTURES = Path(__file__).parent / "fixtures" / "rd"
GOLDEN = sorted(path.stem for path in FIXTURES.glob("*.rd"))
LOCALHOST = "127.0.0.1"
FAST = dict(listen_port=0, reply_seconds=0.3, poll_seconds=0.02)

#: Measured on the KH-5030 (RDC6442S), 11 October: two idle words and a moving one.
KH_IDLE, KH_IDLE_TOO, KH_MOVING = 0, 67072, 16975360
#: Ruida Bridge's (8, 1) running and (8, 3) paused, as this word.
BRIDGE_RUNNING, BRIDGE_PAUSED = 1025, 1027


def golden(name: str) -> bytes:
    return (FIXTURES / f"{name}.rd").read_bytes()


def engine_blocks(rd: bytes) -> list[bytes]:
    """The engine's `divide_data_into_queue`, run on a stand-in with its own `RDJob`."""
    job = RDJob()
    job.buffer.extend(bytes(command) for command in parse_commands(rd))
    stand_in = SimpleNamespace(job=job, _send_queue=[])
    RuidaController.divide_data_into_queue(stand_in)
    return [bytes(block) for block in stand_in._send_queue]


def wait_for(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("Timed out waiting")


def phase(link):
    return (link.job() or {}).get("phase")


def commands(peer, start=0):
    """What reached the peer from `start` on, without probes and status reads."""
    return [r.payload for r in list(peer.received)[start:]
            if r.payload != ENQ and r.payload[:2] != GET_SETTING]


def slow(peer, seconds):
    """Hold every packet `seconds` before the emulator sees it: a slower line."""
    handle = peer._handle

    def held(packet, source):
        time.sleep(seconds)
        handle(packet, source)

    peer._handle = held


def on_block(peer, number, action):
    """Call `action()` just before the `number`-th non-read, non-probe packet (1-based)."""
    handle = peer._handle
    seen = [0]
    swizzler = framing.Swizzler(0x88)

    def counted(packet, source):
        payload = swizzler.unswizzle(packet[2:])
        if payload != ENQ and payload[:2] != GET_SETTING:
            seen[0] += 1
            if seen[0] == number:
                action()
        handle(packet, source)

    peer._handle = counted


#: A long job of 7-byte speed commands: `count` of them; the engine cuts 994 bytes, then 1001s.
def long_job(count=20000) -> bytes:
    return encode.jog_speed(321) * count


@pytest.fixture
def peer(tmp_path, monkeypatch):
    import meerk40t.ruida.emulator as emulator_module

    monkeypatch.setattr(
        emulator_module, "get_safe_path", lambda name, *a, **kw: str(tmp_path / name))
    with ruida_peer() as running:
        yield running
        stream = running.emulator.filestream
        if stream is not None:
            stream.close()


@pytest.fixture
def line(peer):
    link = RuidaLink(SimpleNamespace(address=LOCALHOST, magic=0x88),
                     send_port=peer.send_port, **FAST)
    yield link
    link.close()
    assert not [t for t in threading.enumerate() if t.name == "ruida-job"]


def connected(link, peer):
    assert link.connect()["state"] == "connected"
    wait_for(lambda: link.monitor.status_word is not None)
    return len(peer.received)


def sent_in_full(link):
    wait_for(lambda: (link.job() or {}).get("sent") == (link.job() or {}).get("total"))


# ------------------------------------------------------------------ the engine's blocks


@pytest.mark.parametrize("name", GOLDEN)
def test_a_job_is_cut_into_the_engines_blocks(name):
    rd = golden(name)
    assert framing.job_blocks(rd) == engine_blocks(rd)
    assert b"".join(framing.job_blocks(rd)) == rd


def test_the_engines_blocks_run_over_1000_and_uploads_do_not():
    """
    The golden raster file (3625 bytes, 850 commands): the engine's rule gives 1000,
    1003, 1003 and 619 bytes, `split` (the upload's rule) 1000, 1000, 995 and 630.
    """
    rd = golden("raster_filled_rect")
    assert [len(b) for b in framing.job_blocks(rd)] == [1000, 1003, 1003, 619]
    assert [len(b) for b in framing.split(rd)] == [1000, 1000, 995, 630]


def test_the_long_test_job_is_cut_as_the_engine_cuts_it():
    rd = long_job()
    blocks = framing.job_blocks(rd)
    assert blocks == engine_blocks(rd)
    assert len(blocks) == 140 and {len(b) for b in blocks[1:-1]} == {1001}


# ------------------------------------------------------------------ on the line


@pytest.mark.parametrize("name", GOLDEN)
def test_a_golden_job_reaches_the_peer_as_the_engines_packets(line, peer, name):
    start = connected(line, peer)
    rd = golden(name)
    line.start_job(rd, name=name)
    sent_in_full(line)
    assert commands(peer, start) == engine_blocks(rd)
    received = [r for r in list(peer.received)[start:] if r.payload in engine_blocks(rd)]
    assert all(r.action == "ack" for r in received)
    job = line.job()
    assert job["name"] == name and job["total"] == len(engine_blocks(rd))
    assert job["phase"] == "running"


def test_the_phase_follows_the_emulators_words(line, peer):
    """sending → running (all confirmed) → paused (23) → running (21) → done (22, twice)."""
    connected(line, peer)
    slow(peer, 0.01)
    line.start_job(golden("raster_filled_rect"))
    assert phase(line) == "sending"
    assert line.line_in_use() == "burning"
    sent_in_full(line)
    wait_for(lambda: phase(line) == "running")
    peer.state = "busy"
    time.sleep(0.15)
    assert phase(line) == "running"
    peer.state = "hold"
    wait_for(lambda: phase(line) == "paused")
    assert line.line_in_use() == "burning"
    peer.state = "busy"
    wait_for(lambda: phase(line) == "running")
    peer.state = "idle"
    wait_for(lambda: phase(line) == "done")
    job = line.job()
    assert job["detail"] is None and job["finished"] >= job["started"]
    assert line.line_in_use() is None


@pytest.mark.parametrize("busy_word, idle_word", [
    (KH_MOVING, KH_IDLE), (KH_MOVING, KH_IDLE_TOO), (BRIDGE_RUNNING, KH_IDLE_TOO),
])
def test_the_phase_follows_measured_words(line, peer, busy_word, idle_word):
    peer.memory[MEM_MACHINE_STATUS] = idle_word
    connected(line, peer)
    line.start_job(golden("cut_rect_circle"))
    sent_in_full(line)
    peer.memory[MEM_MACHINE_STATUS] = busy_word
    wait_for(lambda: line.monitor.status_word == busy_word)
    peer.memory[MEM_MACHINE_STATUS] = BRIDGE_PAUSED
    wait_for(lambda: phase(line) == "paused")
    peer.memory[MEM_MACHINE_STATUS] = busy_word
    wait_for(lambda: phase(line) == "running")
    peer.memory[MEM_MACHINE_STATUS] = idle_word
    wait_for(lambda: phase(line) == "done")


def test_idle_before_the_controller_begins_is_not_done(line, peer):
    """Idle words after the last ACK, never a busy one: still running within START_SECONDS."""
    connected(line, peer)
    line.START_SECONDS = 10.0
    line.start_job(golden("cut_3_passes"))
    sent_in_full(line)
    answers = line.monitor.answers
    wait_for(lambda: line.monitor.answers >= answers + 12)  # four or more status words
    assert phase(line) == "running"
    peer.state = "busy"
    time.sleep(0.15)
    peer.state = "idle"
    wait_for(lambda: phase(line) == "done")
    assert line.job()["detail"] is None


def test_a_job_never_seen_running_is_done_with_that_said(line, peer):
    connected(line, peer)
    line.START_SECONDS = 0.3
    line.start_job(golden("cut_3_passes"))
    wait_for(lambda: phase(line) == "done")
    job = line.job()
    assert job["detail"] == NEVER_SEEN_RUNNING
    assert job["finished"] - job["started"] >= 0.3


def test_a_silent_status_gives_no_verdict(line, peer):
    """Busy, then no status word at all: the job stays running, it does not end."""
    connected(line, peer)
    line.start_job(golden("cut_3_passes"))
    sent_in_full(line)
    peer.state = "busy"
    wait_for(lambda: line.monitor.status_word == 21)
    line.monitor.pause()
    peer.state = "idle"
    time.sleep(0.3)
    assert phase(line) == "running"
    line.monitor.resume()
    wait_for(lambda: phase(line) == "done")


# ------------------------------------------------------------------ pause, resume, stop


def test_pause_and_resume_during_a_job(line, peer):
    """
    Both go out during the stream, ahead of the remaining blocks; the phase follows
    the word, not the command.
    """
    start = connected(line, peer)
    slow(peer, 0.01)
    rd = long_job(3000)
    line.start_job(rd)
    wait_for(lambda: line.job()["sent"] >= 3)
    line.pause()
    line.resume()
    assert phase(line) == "sending"
    sent = commands(peer, start)
    blocks = framing.job_blocks(rd)
    assert sent.index(b"\xd8\x02") < len(blocks) and b"\xd8\x03" in sent
    sent_in_full(line)
    wait_for(lambda: phase(line) == "running")
    line.pause()
    peer.state = "hold"
    wait_for(lambda: phase(line) == "paused")
    line.resume()
    peer.state = "busy"
    wait_for(lambda: phase(line) == "running")
    without = [p for p in commands(peer, start) if p not in (b"\xd8\x02", b"\xd8\x03")]
    assert without == blocks


def test_stop_during_the_stream(line, peer):
    start = connected(line, peer)
    slow(peer, 0.005)
    rd = long_job()
    blocks = framing.job_blocks(rd)
    line.start_job(rd)
    wait_for(lambda: line.job()["sent"] >= 5)
    called = time.monotonic()
    line.stop()
    took = time.monotonic() - called
    job = line.job()
    assert job["phase"] == "stopped" and job["finished"] is not None
    assert f"after {job['sent']} of 140 packets" in job["detail"]
    assert "machine's own stop is the sure stop" in job["detail"]
    assert line.line_in_use() is None
    sent = commands(peer, start)
    at = sent.index(b"\xd8\x01")
    assert sent[:at] + sent[at + 1:] == blocks[:job["sent"]]
    assert not [p for p in sent[at + 1:] if p in blocks]
    assert took < 0.5, took
    wait_for(lambda: line._job_thread is None)
    line.start_job(golden("cut_3_passes"))  # the line is free again


def test_stop_while_it_burns(line, peer):
    start = connected(line, peer)
    line.start_job(golden("cut_rect_circle"))
    sent_in_full(line)
    peer.state = "busy"
    wait_for(lambda: line.monitor.status_word == 21)
    line.stop()
    job = line.job()
    assert job["phase"] == "stopped"
    assert "has not been measured yet" in job["detail"]
    assert "machine's own stop is the sure stop" in job["detail"]
    assert commands(peer, start)[-1] == b"\xd8\x01"
    assert line.line_in_use() is None
    peer.state = "idle"
    time.sleep(0.2)
    assert phase(line) == "stopped"  # the final phase stays


def test_a_stop_that_cannot_be_sent_says_so(line, peer):
    connected(line, peer)
    line.start_job(golden("cut_3_passes"))
    sent_in_full(line)
    line.disconnect()
    with pytest.raises(ConnectionError):
        line.stop()
    job = line.job()
    assert job["phase"] == "stopped"
    assert "did not reach the Ruida" in job["detail"] and "own stop" in job["detail"]


# ------------------------------------------------------------------ a broken stream


def test_a_missing_ack_fails_the_job_and_nothing_is_resent(line, peer):
    start = connected(line, peer)
    slow(peer, 0.002)
    rd = long_job(3000)
    blocks = framing.job_blocks(rd)
    on_block(peer, 4, peer.drop_ack_next)
    line.start_job(rd)
    wait_for(lambda: phase(line) == "failed")
    job = line.job()
    assert job["sent"] == 3
    assert "after 3 of 21 packets" in job["detail"]
    assert "nothing was sent twice" in job["detail"]
    time.sleep(0.5)  # the session reconnects meanwhile
    assert commands(peer, start) == blocks[:4]
    dropped = [r for r in peer.received if r.action == "ack-dropped"]
    assert len(dropped) == 1 and dropped[0].payload == blocks[3]
    assert line.line_in_use() is None


def test_a_reconnect_mid_stream_fails_the_job(line, peer):
    """
    The session reconnected between block 5 and 6 (closed and opened again, a new
    generation): the sixth block is refused by its generation, the job fails, and
    nothing of it goes out on the new connection.
    """
    start = connected(line, peer)
    rd = long_job(3000)
    blocks = framing.job_blocks(rd)
    until_clear = line._until_clear

    def reconnect_at_six(session, index, seconds, stopped):
        if index == 5:
            session.close()
            session.open()
            wait_for(lambda: session.connected)
        until_clear(session, index, seconds, stopped)

    line._until_clear = reconnect_at_six
    line.start_job(rd)
    wait_for(lambda: phase(line) == "failed")
    job = line.job()
    assert job["sent"] == 5 and "after 5 of 21 packets" in job["detail"]
    assert "changed during the transfer" in job["detail"]
    time.sleep(0.2)
    assert commands(peer, start) == blocks[:5]
    assert line.connection()["state"] == "connected"


def test_close_during_a_job(line, peer):
    connected(line, peer)
    line.start_job(golden("cut_3_passes"))
    sent_in_full(line)
    line.close()
    job = line.job()
    assert job["phase"] == "failed" and job["detail"] == LET_GO


# ------------------------------------------------------------------ who holds the line


def test_refusals_before_anything_is_sent(line, peer):
    with pytest.raises(ConnectionError, match="not open"):
        line.start_job(golden("cut_3_passes"))
    assert line.job() is None
    start = connected(line, peer)
    with pytest.raises(ConnectionError, match=EMPTY_JOB):
        line.start_job(b"")
    assert commands(peer, start) == [] and line.job() is None


def test_one_job_at_a_time_and_nothing_else_beside_it(line, peer):
    connected(line, peer)
    slow(peer, 0.005)
    line.start_job(long_job(3000), name="first")
    assert line.line_in_use() == "burning"
    with pytest.raises(ConnectionError, match=JOB_ON_LINE):
        line.start_job(golden("cut_3_passes"), name="second")
    called = time.monotonic()
    with pytest.raises(LineTaken, match=JOB_HOLDS_LINE):
        line.send_file([b"\xc9\x02\x00\x00\x00\x00\x01"])
    assert time.monotonic() - called < 0.1
    with pytest.raises(ConnectionError, match=BURNING):
        line.move_by(1, 0)
    sent_in_full(line)
    assert phase(line) == "running"
    with pytest.raises(ConnectionError, match=BURNING):
        line.move_to(10, 10)
    with pytest.raises(ConnectionError, match=JOB_ON_LINE):
        line.start_job(golden("cut_3_passes"))
    assert line.job()["name"] == "first"
    peer.state = "busy"
    time.sleep(0.1)
    peer.state = "idle"
    wait_for(lambda: phase(line) == "done")
    assert line.line_in_use() is None
    wait_for(lambda: line._job_thread is None)
    line.start_job(golden("cut_3_passes"), name="second")
    assert line.job()["name"] == "second" and line.job()["phase"] in ("sending", "running")


def test_no_job_while_a_file_goes_out(line, peer):
    connected(line, peer)
    slow(peer, 0.005)
    done = threading.Event()

    def upload():
        line.send_file([encode.jog_speed(123)] * 60)
        done.set()

    sender = threading.Thread(target=upload)
    sender.start()
    wait_for(lambda: line.line_in_use() == "uploading")
    with pytest.raises(ConnectionError, match=FILE_BEFORE_JOB):
        line.start_job(golden("cut_3_passes"))
    sender.join(5)
    assert done.is_set() and line.job() is None


def test_the_last_job_is_kept_until_the_next(line, peer):
    connected(line, peer)
    line.START_SECONDS = 0.1
    line.start_job(golden("cut_3_passes"), name="kept")
    wait_for(lambda: phase(line) == "done")
    time.sleep(0.2)
    assert line.job()["name"] == "kept" and line.job()["phase"] == "done"


def test_job_never_raises():
    link = RuidaLink(SimpleNamespace(address=LOCALHOST, magic=0x88), **FAST)
    assert link.job() is None and link.carries_jobs is True
    link._job = object()  # broken on purpose
    assert link.job() is None


def test_no_thread_or_socket_is_left_behind(peer):
    before = {t.ident for t in threading.enumerate()}
    for _ in range(3):
        link = RuidaLink(SimpleNamespace(address=LOCALHOST, magic=0x88),
                         send_port=peer.send_port, **FAST)
        connected(link, peer)
        link.START_SECONDS = 0.1
        link.start_job(golden("cut_3_passes"))
        wait_for(lambda: phase(link) == "done")
        session = link.session
        link.close()
        assert session._transport is None
    time.sleep(0.1)
    left = [t for t in threading.enumerate()
            if t.ident not in before and t.name.startswith("ruida-") and t.is_alive()]
    assert left == []
