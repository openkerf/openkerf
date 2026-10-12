"""
Phase 4 on `RuidaLink`: moving the head and the realtime verbs, against the engine.

Two kinds of test. Offline, each `encode.py` function is compared with the engine's own
`RuidaDriver` / `RuidaController` method run on a stand-in whose `write` collects the
bytes (no thread, no session), for the same inputs and the same device view. On the
line, each verb goes through `RuidaLink` to `ruida_peer` on 127.0.0.1, and what the
peer received (unswizzled, status reads left out) must be exactly those engine bytes.

The view is a real engine `RuidaDevice`'s, made by `POST /api/machines
{"info": "ruida-beta"}` in the test kernel (24 × 16 in, `home_corner` "auto", no flips,
scale 1, margins 0), then given other origin and flip settings.
"""

import threading
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from meerk40t.core.units import Length
from meerk40t.ruida.controller import RuidaController
from meerk40t.ruida.driver import RuidaDriver
from meerk40t.ruida.rdjob import (
    ENQ,
    GET_SETTING,
    MACHINE_STATUS_MOVING,
    MEM_CARD_ID,
    MEM_MACHINE_STATUS,
    RDJob,
    abscoord,
)

from openkerf_api.link import SendInterrupted
from openkerf_api.ruida import encode
from openkerf_api.ruida.link import (
    FILE_GOING_OUT,
    FILE_STOPPED,
    MOTION_STOPPED,
    NO_POSITION,
    NO_RAIL_LOCK,
    NOT_OPENED,
    CLOSED,
    RuidaLink,
)
from openkerf_api.ruida.monitor import machine_state
from openkerf_api.server import ApiServer

from ruida_peer import ruida_peer

LOCALHOST = "127.0.0.1"
FAST = dict(listen_port=0, reply_seconds=0.3, poll_seconds=0.02)


def wait_for(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("Timed out waiting")


# ------------------------------------------------------------------ the engine's side


@pytest.fixture
def ruida(kernel, tmp_path):
    """The engine's Ruida device as `POST /api/machines {"info": "ruida-beta"}` makes it."""
    server = ApiServer(kernel, library_path=tmp_path / "u.db")
    with TestClient(server.build_app()) as client:
        made = client.post("/api/machines", json={"info": "ruida-beta", "label": "M"})
        assert made.status_code == 201, made.text
        yield kernel.device


def configure(device, **settings):
    for name, value in settings.items():
        setattr(device, name, value)
    device.realize()
    return device


SETTINGS = {
    "defaults": {},
    "flip_x": {"flip_x": True},
    "flip_y": {"flip_y": True},
    "swap_xy": {"swap_xy": True},
    "top-right": {"home_corner": "top-right"},
    "bottom-left+flip_x": {"home_corner": "bottom-left", "flip_x": True},
    "bottom-right": {"home_corner": "bottom-right"},
    "center": {"home_corner": "center"},
    "scaled": {"scale_x": 1.01, "scale_y": 0.99},
}


class Engine:
    """The engine's driver and controller methods on a stand-in that only collects."""

    def __init__(self, view, native=(0, 0)):
        self.sent: list[bytes] = []
        noop = lambda *a, **k: None  # noqa: E731
        controller = SimpleNamespace(
            job=RDJob(), write=self.sent.append, wait_for_move=noop,
            gross_timeout=noop, normal_timeout=noop, update_machine_status=noop,
            sync=noop, mode="rapid", paused=False)
        controller.pause = lambda: RuidaController.pause(controller)
        controller.resume = lambda: RuidaController.resume(controller)
        controller.abort = lambda: RuidaController.abort(controller)
        self.driver = SimpleNamespace(
            controller=controller, native_x=native[0], native_y=native[1],
            _jog_speed=600.0, paused=False, events=noop,
            service=SimpleNamespace(view=view, signal=noop))

    def __call__(self, name, *args):
        method = getattr(RuidaDriver, name)
        if name == "home":
            # `RuidaDriver.home` is `self.move_abs(0, 0)` on the instance.
            self.driver.move_abs = lambda x, y: RuidaDriver.move_abs(self.driver, x, y)
        method(self.driver, *args)
        return [bytes(b) for b in self.sent]


NATIVES = [(0, 0), (100000, 50000), (10000, 37000), (600000, 400000)]
TARGETS = [(0.0, 0.0), (10.0, 20.0), (10.0, 37.0), (123.456, 7.89), (-5.0, 3.0)]
JOGS = [(10.0, 0.0), (0.0, -5.0), (10.0, 5.0), (-10.0, -5.0), (0.1, 0.1)]


@pytest.mark.parametrize("label", SETTINGS)
def test_moves_are_the_engine_drivers_bytes(ruida, label):
    """
    `move_absolute`, `move_relative` (with and without the clamp) and `home`, for 4
    head positions × 5 targets/jogs, under 9 device settings: 360 comparisons.
    """
    configure(ruida, **SETTINGS[label])
    view = ruida.view
    for native in NATIVES:
        for x, y in TARGETS:
            ours, _ = encode.move_to(view, encode.millimetres(x), encode.millimetres(y),
                                     *native)
            theirs = Engine(view, native)(
                "move_abs", Length(f"{x:.4f}mm"), Length(f"{y:.4f}mm"))
            assert ours == theirs, (native, x, y)
        for dx, dy in JOGS:
            for confined in (True, False):
                sx, sy = encode.millimetres(dx), encode.millimetres(dy)
                ours, _ = encode.move_by(view, sx, sy, *native, confined=confined)
                if confined:
                    # The clamp is ours (the engine's has X's sign wrong, see
                    # `encode.confine`); the bytes for what it leaves must be the
                    # engine's own for that same, unclamped, vector.
                    sx, sy = encode.confine(view, sx, sy, *native)
                theirs = Engine(view, native)("move_rel", sx, sy, False)
                assert ours == theirs, (native, dx, dy, confined)
        ours, _ = encode.move_to(view, 0, 0, *native)
        assert ours == Engine(view, native)("home")


def test_a_jog_away_from_zero_goes_and_a_jog_off_the_bed_is_cut(ruida):
    """
    Measured on the KH-5030 (RDC6442S): at (0, 0) a +10 mm X jog through the engine's
    clamp put only `C9 02` on the line and the head stood still; +10 mm X from (50, 30)
    took the panel from 49.9 to 59.9. So at (0, 0): +10 mm X goes, −5 mm Y stays at the
    edge, and a jog past the far edge stops at it.
    """
    view = ruida.view
    mm = encode.millimetres
    assert encode.confine(view, mm(10.0), mm(0.0), 0, 0) == (mm(10.0), mm(0.0))
    assert encode.confine(view, mm(0.0), mm(-5.0), 0, 0) == (mm(0.0), 0)
    far = view.width
    dx, _ = encode.confine(view, far * 2, mm(0.0), 0, 0)
    assert dx == far
    packets, target = encode.move_by(view, mm(10.0), mm(0.0), 0, 0)
    assert len(packets) == 2
    assert target[0] == pytest.approx(10_000, abs=1)


def test_the_one_command_verbs_are_the_engines_bytes(ruida):
    view = ruida.view
    assert encode.home_xy() == Engine(view)("physical_home") == [b"\xd8\x2a"]
    assert encode.focus_z() == Engine(view)("focusz") == [b"\xd8\x2e"]
    assert encode.pause() == Engine(view)("pause") == [b"\xd8\x02"]
    engine = Engine(view)
    engine.driver.paused = True
    assert encode.resume() == engine("resume") == [b"\xd8\x03"]
    assert encode.stop() == Engine(view)("reset") == [b"\xd8\x01"]
    assert encode.jog_speed() == bytes.fromhex("c9020000244f40")


def test_the_engines_ruida_driver_has_no_rail_lock():
    """What made `lock`/`unlock` write 0 bytes through the engine (see `encode.py`)."""
    assert not hasattr(RuidaDriver, "lock_rail")
    assert not hasattr(RuidaDriver, "unlock_rail")


def test_design_millimetres_to_controller_micrometres(ruida):
    """
    Measured through the device's view, 24 × 16 in bed (609.6 × 406.4 mm):
    (10, 20) mm is (10000, 20000) µm with the defaults, (599600, 20000) with
    flip_x, (10000, 386400) with flip_y, (20000, 10000) with swap_xy.
    """
    def native(**settings):
        configure(ruida, **{"flip_x": False, "flip_y": False, "swap_xy": False,
                            "home_corner": "auto", **settings})
        x, y = encode.to_native(ruida.view, encode.millimetres(10), encode.millimetres(20))
        return round(x, 3), round(y, 3)

    assert native() == (10000, 20000)
    assert native(flip_x=True) == (599600, 20000)
    assert native(flip_y=True) == (10000, 386400)
    assert native(swap_xy=True) == (20000, 10000)


# ------------------------------------------------------------------ the line


@pytest.fixture
def peer():
    with ruida_peer() as p:
        yield p


def follow(peer):
    """Make the peer's head go where every move sends it, as a controller would."""
    record = peer._record

    def moved(entry):
        p = entry.payload
        x, y = peer.position_um
        if p[:2] == b"\xd9\x10":
            peer.position_um = (abscoord(p[3:8]), abscoord(p[8:13]))
        elif p[:2] == b"\xd9\x00":
            peer.position_um = (x + abscoord(p[3:8]), y)
        elif p[:2] == b"\xd9\x01":
            peer.position_um = (x, y + abscoord(p[3:8]))
        record(entry)

    peer._record = moved


def commands(peer, start=0):
    """What reached the peer from `start` on, without probes and status reads."""
    return [r.payload for r in list(peer.received)[start:]
            if r.payload != ENQ and r.payload[:2] != GET_SETTING]


@pytest.fixture
def line(peer, ruida):
    """A connected link on the peer, with the engine device's view."""
    stand_in = SimpleNamespace(address=LOCALHOST, magic=0x88, view=ruida.view)
    link = RuidaLink(stand_in, send_port=peer.send_port, **FAST)
    yield link
    link.close()


def connected(link, peer, position=(0, 0)):
    peer.position_um = position
    assert link.connect()["state"] == "connected"
    wait_for(lambda: link.position() == position)
    return len(peer.received)


def test_each_verb_puts_the_engines_bytes_on_the_line(line, peer, ruida):
    view = ruida.view
    native = (100000, 50000)
    start = connected(line, peer, native)
    expected = []

    line.move_to(10, 20)
    expected += Engine(view, native)("move_abs", Length("10.0000mm"), Length("20.0000mm"))
    line.ARRIVE_SECONDS = 0.05  # the peer's head stays put here
    line.move_by(-10, 5)
    expected += Engine(view, native)("move_rel", Length("-10.0000mm"), Length("5.0000mm"),
                                     True)
    line.home()
    expected += Engine(view, native)("home")
    line.home(physical=True)
    expected += Engine(view)("physical_home")
    line.focus(5)
    expected += Engine(view)("focusz")
    line.pause()
    expected += Engine(view)("pause")
    line.resume()
    paused = Engine(view)
    paused.driver.paused = True
    expected += paused("resume")
    line.stop()
    expected += Engine(view)("reset")

    wait_for(lambda: len(commands(peer, start)) >= len(expected))
    assert commands(peer, start) == expected
    assert all(r.action == "ack" for r in peer.received[start:])


def test_a_frame_is_worked_out_from_each_corner_reached(line, peer, ruida):
    """
    Five corners with the peer's head following: each move after the first is the
    engine's `move_abs` from the corner before, as `wait_for_move` left `native_x`.
    Measured: three absolute `D9 10` moves and two relative Y-only `D9 01` (+30 and
    -30 mm), each after a `C9 02` jog speed.
    """
    follow(peer)
    start = connected(line, peer, (0, 0))
    corners = [(20, 30), (70, 30), (70, 60), (20, 60), (20, 30)]
    line.trace(corners)
    expected, native = [], (0, 0)
    for x, y in corners:
        engine = Engine(ruida.view, native)
        expected += engine("move_abs", Length(f"{x}.0000mm"), Length(f"{y}.0000mm"))
        native = (x * 1000, y * 1000)
    wait_for(lambda: len(commands(peer, start)) >= len(expected))
    assert commands(peer, start) == expected
    # Which form each corner takes rides on float noise, as in the engine: through the
    # default view X comes out exact (20 mm is 20000.0) and Y does not (30 mm is
    # 30000.000000000007), so a corner that changes only Y finds dx == 0 and goes
    # relative, while one that changes only X finds dy != 0 and goes absolute.
    assert [p[:2].hex() for p in expected[1::2]] == ["d910", "d910", "d901", "d910", "d901"]


@pytest.mark.parametrize("label", ["defaults", "flip_x", "bottom-right", "swap_xy"])
def test_millimetres_reach_the_controller_as_the_engine_converts_them(line, peer, ruida,
                                                                      label):
    configure(ruida, **SETTINGS[label])
    native = (1000, 2000)
    start = connected(line, peer, native)
    line.move_to(10, 20)
    expected = Engine(ruida.view, native)("move_abs", Length("10.0000mm"),
                                          Length("20.0000mm"))
    wait_for(lambda: len(commands(peer, start)) >= 2)
    sent = commands(peer, start)
    assert sent == expected
    tx, ty = encode.to_native(ruida.view, encode.millimetres(10), encode.millimetres(20))
    assert (abscoord(sent[1][3:8]), abscoord(sent[1][8:13])) == (int(tx), int(ty))


def test_a_move_waits_for_the_last_one_to_arrive(line, peer, ruida):
    """The second jog is worked out from the first one's target, seen reached."""
    follow(peer)
    start = connected(line, peer, (100000, 100000))
    line.CONFINED = False
    line.move_by(10, 10)
    line.move_by(5, 5)
    sent = commands(peer, start)
    assert (abscoord(sent[3][3:8]), abscoord(sent[3][8:13])) == (115000, 115000)


def test_pause_and_stop_overtake_queued_packets(line, peer):
    """
    40 speed packets queued in the normal lane, then pause and stop: each went out
    as the next packet after the one already on the line (index 1 and 2 or earlier
    among the 42), never behind the queue.
    """
    start = connected(line, peer)
    line.monitor.pause()
    wait_for(lambda: not line.session.busy)
    filler = encode.jog_speed(123)
    receipts = [line.session.write(filler) for _ in range(40)]
    line.pause()
    line.stop()
    for receipt in receipts:
        receipt.result(5)
    sent = commands(peer, start)
    assert len(sent) == 42
    assert sent.index(b"\xd8\x02") <= 2
    assert sent.index(b"\xd8\x01") <= 3
    assert sent.index(b"\xd8\x02") < sent.index(b"\xd8\x01")


def test_stop_ends_a_file_going_out(line, peer):
    """
    A 400-packet file; stop after the 10th has arrived. Measured in five runs
    (`reply_seconds` 0.3, on 127.0.0.1): `stop()` returned in 0.2-0.3 ms, 0 or 1 file
    packet reached the peer between the call and the stop (the one already on the
    line), none after it, and the file ended at that packet with `on_line` False.
    """
    start = connected(line, peer)
    filler = encode.jog_speed(321)
    outcome = {}

    def send():
        try:
            line.send_file([filler] * 400)
        except SendInterrupted as error:
            outcome["error"] = error

    sender = threading.Thread(target=send)
    sender.start()
    wait_for(lambda: commands(peer, start).count(filler) >= 10)
    with pytest.raises(ConnectionError, match=FILE_GOING_OUT):
        line.move_by(1, 0)
    arrived = commands(peer, start).count(filler)
    called = time.monotonic()
    line.stop()
    took = time.monotonic() - called
    sender.join(5)
    assert not sender.is_alive()
    error = outcome["error"]
    assert str(error) == FILE_STOPPED and not error.stalled
    sent = commands(peer, start)
    at = sent.index(b"\xd8\x01")
    assert filler not in sent[at + 1:]
    assert sent[:at].count(filler) - arrived <= 1
    assert error.index == sent[:at].count(filler)
    assert took < 0.5, took
    assert line.line_in_use() is None
    # The line is free again afterwards.
    line.pause()


def test_verbs_refuse_on_a_closed_line(line, peer):
    verbs = [
        lambda: line.move_to(1, 2), lambda: line.move_by(1, 0), lambda: line.home(),
        lambda: line.home(physical=True), lambda: line.trace([(0, 0), (1, 1)]),
        lambda: line.focus(1), line.pause, line.resume, line.stop,
    ]
    for verb in verbs:
        with pytest.raises(ConnectionError, match=NOT_OPENED):
            verb()
    connected(line, peer)
    line.disconnect()
    count = len(peer.received)
    for verb in verbs:
        with pytest.raises(ConnectionError, match=CLOSED):
            verb()
    time.sleep(0.1)
    assert len(peer.received) == count


def test_lock_and_unlock_are_refused_and_send_nothing(line, peer):
    start = connected(line, peer)
    caps = line.motion_capabilities()
    assert caps["lock"] is False and caps["unlock"] is False
    assert all(caps[k] for k in ("home", "physical_home", "move", "jog", "frame",
                                 "focus", "pause", "resume", "stop"))
    for verb in (line.lock, line.unlock):
        with pytest.raises(ConnectionError, match=NO_RAIL_LOCK):
            verb()
    assert commands(peer, start) == []


def test_no_move_before_the_position_is_read(peer, ruida):
    stand_in = SimpleNamespace(address=LOCALHOST, magic=0x88, view=ruida.view)
    link = RuidaLink(stand_in, send_port=peer.send_port, listen_port=0,
                     reply_seconds=0.3, poll_seconds=5)
    try:
        assert link.connect()["state"] == "connected"
        assert link.position() is None
        start = len(peer.received)
        with pytest.raises(ConnectionError, match=NO_POSITION):
            link.move_to(1, 2)
        link.home(physical=True)  # needs no position
        assert commands(peer, start) == [b"\xd8\x2a"]
    finally:
        link.close()


def test_stop_cuts_a_wait_for_the_head_short(line, peer):
    start = connected(line, peer)  # the peer's head never moves here
    line.move_to(50, 50)
    outcome = {}

    def second():
        try:
            line.move_to(60, 60)
        except ConnectionError as error:
            outcome["error"] = error

    waiting = threading.Thread(target=second)
    waiting.start()
    time.sleep(0.1)
    line.stop()
    waiting.join(2)
    assert str(outcome["error"]) == MOTION_STOPPED
    assert commands(peer, start)[-1] == b"\xd8\x01"


# ------------------------------------------------------------------ status word


@pytest.mark.parametrize("word, state", [
    (0, "idle"),                      # KH-5030, measured idle
    (12 << 7, "idle"),                # Ruida Bridge (12, 0)
    ((8 << 7) | 1, "running"),        # Ruida Bridge (8, 1)
    ((8 << 7) | 3, "paused"),         # Ruida Bridge (8, 3)
    (22, "idle"), (21, "running"), (23, "paused"),  # the emulator
    (MACHINE_STATUS_MOVING, "moving"),
    (MACHINE_STATUS_MOVING | 1, "running"),
    (None, "unknown"),
])
def test_machine_state_of_a_word(word, state):
    assert machine_state(word) == state


@pytest.mark.parametrize("word, state", [
    ((8 << 7) | 3, "paused"), ((8 << 7) | 1, "running"), (12 << 7, "idle"), (0, "idle"),
])
def test_machine_state_read_from_the_peer(peer, word, state):
    peer.memory[MEM_MACHINE_STATUS] = word
    link = RuidaLink(SimpleNamespace(address=LOCALHOST, magic=0x88),
                     send_port=peer.send_port, **FAST)
    try:
        link.connect()
        wait_for(lambda: link.monitor.status_word == word)
        assert link.machine_state() == state
    finally:
        link.close()


def test_the_card_id_read_stays_out_of_commands(peer):
    """`commands()` leaves reads out: the card id is the first thing the monitor asks."""
    link = RuidaLink(SimpleNamespace(address=LOCALHOST, magic=0x88),
                     send_port=peer.send_port, **FAST)
    try:
        link.connect()
        wait_for(lambda: link.monitor.card_id is not None)
        assert any(r.payload == GET_SETTING + MEM_CARD_ID for r in peer.received)
        assert commands(peer) == []
    finally:
        link.close()


def test_a_head_put_somewhere_else_does_not_hold_the_next_move(line, peer, ruida):
    """
    The delay the user saw before a frame on a new sheet: the last move's target
    outlived whatever moved the head next (a job ends at (0, 0) on the KH-5030), so the
    next move waited the full `ARRIVE_SECONDS` (10 s) for a corner the head would never
    reach again. Now a head read standing still elsewhere counts as arrived.
    """
    follow(peer)
    connected(line, peer, (0, 0))
    line.move_to(20, 30)
    peer.position_um = (0, 0)  # the controller took the head home, as after a job
    assert line.ARRIVE_SECONDS == 10.0

    started = time.monotonic()
    line.move_to(50, 50)
    took = time.monotonic() - started

    assert took < 2.0, took


def test_a_target_on_a_half_millimetre_is_reached_by_a_reading_beside_it(line, peer, ruida):
    """
    The engine compared whole millimetres: a target of 20.5 mm (20500 µm) and a
    reading of 20503 µm round to 20 and 21 and never matched. Within half a millimetre
    is there.
    """
    connected(line, peer, (0, 0))
    line.move_to(20.5, 30.5)
    peer.position_um = (20503, 30497)
    line.STILL_SECONDS = 60.0  # only the tolerance may end this wait

    started = time.monotonic()
    line.move_to(40, 40)
    took = time.monotonic() - started

    assert took < 2.0, took
