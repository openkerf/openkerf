"""
A second program on the same Ruida: said in `connection()["warning"]`, not suffered.

Measured on a KH-5030 (RDC6442S, UDP) on 11 October: with an older OpenKerf on another
host polling the controller every 0.2 s, ~40 % of our reads were acknowledged and never
answered, ACKs 30–440 ms; alone, 96 of 96 answered in 3–5 ms. A physical home made the
controller silent — ACKs missing too — and the session reconnected twice; that is a
silence, not a second client.

Here the peer plays the other program with `swallow_replies`: the ACK goes, the answer
does not. The rule (`monitor.SecondClient`): raised at 5 or more unanswered of the last
20 acknowledged reads, cleared at 1 or fewer; reads with no ACK do not count.
"""

import threading
import time
from types import SimpleNamespace

import pytest

from openkerf_api.ruida.link import RuidaLink
from openkerf_api.ruida.monitor import SECOND_CLIENT, SecondClient
from openkerf_api import status
from openkerf_api.status import StatusReader, forget_connection_history

from ruida_peer import ruida_peer

FAST = dict(listen_port=0, reply_seconds=0.3, poll_seconds=0.02)
#: Two of five reads lose their answer: the ~40 % measured with a second client.
SHARED = (True, False, True, False, False)


def wait_for(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("Timed out waiting")


@pytest.fixture(autouse=True)
def leaves_no_thread(request):
    threads = set(threading.enumerate())
    started = time.monotonic()
    yield
    left = [t for t in threading.enumerate() if t not in threads and t.is_alive()]
    assert not left, f"threads left running: {left}"
    assert time.monotonic() - started < 8


@pytest.fixture
def peer():
    with ruida_peer() as p:
        yield p


@pytest.fixture
def link(peer):
    made = RuidaLink(SimpleNamespace(address="127.0.0.1", magic=0x88),
                     send_port=peer.send_port, **FAST)
    yield made
    made.close()


def _answered_reads(link, count):
    start = link.monitor.answers
    wait_for(lambda: link.monitor.answers >= start + count)


# -- the rule on its own --------------------------------------------------------


def test_the_measured_cases_fall_either_side_of_the_rule():
    alone = SecondClient()
    for _ in range(96):  # 96 of 96 answered, 3-5 ms
        alone.note(True, 0.004)
        assert alone.warning() is None

    shared = SecondClient()
    for i in range(20):  # ~40 % unanswered, 30-440 ms
        shared.note(not SHARED[i % 5], 0.2)
    warning = shared.warning()
    assert warning["code"] == SECOND_CLIENT
    assert (warning["unanswered"], warning["asked"], warning["ack_ms"]) == (8, 20, 200)
    assert warning["message"].startswith(
        "Another program seems to be talking to this Ruida: 8 of the last 20 status "
        "questions were acknowledged but not answered.")


def test_stray_losses_never_raise_it():
    rule = SecondClient()
    for i in range(200):  # one in ten lost: twice the 1-in-20 of a dropped datagram
        rule.note(i % 10 != 0, 0.004)
        assert rule.warning() is None


def test_it_clears_only_when_the_window_is_nearly_clean():
    rule = SecondClient()
    for _ in range(5):
        rule.note(False, 0.1)
    assert rule.warning() is not None
    for _ in range(15):
        rule.note(True, 0.004)
    assert rule.warning() is not None  # still 5 of 20
    for _ in range(3):
        rule.note(True, 0.004)
    assert rule.warning() is not None  # 2 of 20: hysteresis, no flicker
    rule.note(True, 0.004)
    assert rule.warning() is None  # 1 of 20


# -- against the peer -----------------------------------------------------------


def test_a_peer_that_answers_everything_gives_no_warning(link, peer):
    assert link.connect() == {"state": "connected", "detail": None}
    _answered_reads(link, 60)
    assert link.monitor.unanswered == 0
    assert "warning" not in link.connection()


def test_a_second_client_is_warned_about_and_the_warning_clears(link, peer, monkeypatch):
    link.connect()
    _answered_reads(link, 5)
    peer.swallow_replies(SHARED)
    wait_for(lambda: "warning" in link.connection())
    reading = link.connection()
    # The line still works; only the answers go astray.
    assert reading["state"] == "connected" and reading["detail"] is None
    warning = reading["warning"]
    assert warning["code"] == SECOND_CLIENT
    assert 5 <= warning["unanswered"] <= warning["asked"] <= 20
    assert isinstance(warning["ack_ms"], int)
    # No reconnects: an acknowledged read that goes unanswered is not a dead line.
    generation = link.generation
    assert generation == 0

    # Through the status reader, in the shape the interface reads.
    forget_connection_history()
    monkeypatch.setattr(status, "link_for", lambda kernel, device: link)
    snap = StatusReader(SimpleNamespace()).connection(SimpleNamespace(path="ruida"))
    assert set(snap) == {"state", "detail", "held_ms", "warning"}
    assert snap["warning"]["code"] == SECOND_CLIENT

    peer.swallow_replies(())
    wait_for(lambda: "warning" not in link.connection())
    assert link.connection() == {"state": "connected", "detail": None}
    assert link.generation == generation


def test_a_silent_controller_is_not_a_second_client(link, peer):
    """No ACKs at all, as during the physical home: the session rides it out."""
    link.connect()
    _answered_reads(link, 5)
    seen = []
    stop = threading.Event()

    def watch():
        while not stop.is_set():
            seen.append("warning" in link.connection())
            time.sleep(0.01)

    watcher = threading.Thread(target=watch)
    watcher.start()
    try:
        peer.ignore_next(10 ** 9)
        wait_for(lambda: link.connection()["state"] == "connecting")
        time.sleep(2.0)
        with peer._changed:
            peer._ignore = 0
        wait_for(lambda: link.connection()["state"] == "connected")
        _answered_reads(link, 20)
    finally:
        stop.set()
        watcher.join()
    assert link.generation >= 2
    assert not any(seen)
    assert link.monitor.unanswered == 0


def test_a_fresh_connection_starts_with_a_clean_window(link, peer):
    link.connect()
    peer.swallow_replies((True,))
    wait_for(lambda: "warning" in link.connection())
    peer.swallow_replies(())
    link.disconnect()
    assert "warning" not in link.connection()
    link.connect()
    assert "warning" not in link.connection()
