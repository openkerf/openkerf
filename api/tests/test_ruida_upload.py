"""
A job as a file: the bytes, the conversation, and what goes wrong.

Never against a laser. The end-to-end test talks to the engine's own Ruida
emulator, which takes this conversation and reads the file back off it.
"""

import threading
import time

import pytest

from openkerf_api.commands import CommandRunner, _AlwaysConnected
from openkerf_api.edits import DesignError
from openkerf_api.ruida_upload import CHUNK, RuidaUpload


@pytest.fixture
def ruida(kernel):
    """A real Ruida service, the way test_machine_connect also makes one."""
    kernel.console("service device start ruida -i\n")
    return kernel


def a_rectangle(kernel):
    """Something to burn: one rectangle in a cut layer.

    Clears the element tree first, not only the operations: called a second
    time after a different design (see `a_different_design`), the previous
    shape would otherwise still be sitting there and `element* classify`
    would pick it up too, alongside the new rectangle.
    """
    kernel.elements.clear_all()
    kernel.console("rect 20mm 20mm 40mm 30mm\n")
    kernel.console("operation* delete\n")
    kernel.console("op cut\n")
    kernel.console("element* classify\n")


def a_different_design(kernel):
    """
    A different shape with different cut settings — deliberately as unlike
    `a_rectangle` as reasonably possible. A state leak between builds
    (`_reset_upload_driver_state` forgetting a field, or `driver.settings`
    keeping an old key `.update()` never overwrites) is invisible between two
    builds of the *same* design, since there is nothing for the old state to
    disagree with; it only shows up between two different ones.
    """
    kernel.elements.clear_all()
    kernel.console("circle 30mm 30mm 15mm\n")
    kernel.console("operation* delete\n")
    kernel.console("op cut\n")
    kernel.console("element* classify\n")
    layer = next(iter(kernel.elements.ops()))
    layer.speed = 25.0
    layer.power = 700


def a_design_over_one_block(kernel):
    """Something whose job bytes need more than one block: eight circles.

    A rectangle is 433 bytes and fits in a single `CHUNK`, which hides every
    question about where one block ends and the next begins. Measured, these
    eight circles come to 5462 bytes — five full blocks and a tail.
    """
    kernel.elements.clear_all()
    for step in range(8):
        kernel.console(f"circle {10 + step * 5}mm {10 + step * 4}mm {6 + step}mm\n")
    kernel.console("operation* delete\n")
    kernel.console("op cut\n")
    kernel.console("element* classify\n")


def a_parked_driver(device):
    """
    A `RuidaDriver` built for a test to inspect, not to build anything with.

    A bare `RuidaDriver(device)` starts a status thread that tries
    `service.connect()` five times a second for the rest of the run
    (`ruida/controller.py:50,162,189` — the construction `CLAUDE.md`'s own row
    warns against leaving unguarded). Measured against the `ruida` fixture
    (`interface` `usb`, `address` `localhost`, `connected` `False`):
    `RuidaDevice.connect` reaches `active_session.connect()` -> `_open()`,
    which fails locally and reaches no real machine today — but a kernel
    pointed at a real UDP address would send actual packets from that same
    line, and a test has no business depending on today's harmlessness.

    Unlike `_upload_driver_for`, this does *not* call `resume_monitor()` — and
    that omission, not the `_AlwaysConnected` wrap, is what actually parks the
    thread here. `__init__` acquires `_job_lock` and this driver never releases
    it, so once the status thread's first check takes the "connected and idle"
    branch (`_AlwaysConnected` makes sure it does), its own
    `self._job_lock.acquire()` (`ruida/controller.py:173`) blocks forever —
    measured: `Thread-3 (_status_monitor)` still alive 3.6 s later, never
    having reached `connect()` or anything past that first acquire. Adding
    `resume_monitor()` "for parity" with `_upload_driver_for` would let that
    thread through to real work — including, eventually, writing on the real
    `<device>/send` channel — for a driver this helper promises is inert. It
    stays out on purpose.
    """
    from meerk40t.ruida.driver import RuidaDriver

    driver = RuidaDriver(device)
    driver.controller.service = _AlwaysConnected(device)
    driver.recv.unwatch(driver.controller.recv)
    return driver


class _InertSpooler:
    """Takes jobs and runs none.

    Every command the emulator does not treat as realtime ends in
    `self.device.spooler.send(self.job, prevent_duplicate=True)`
    (`ruida/emulator.py:159`) — the spooler of the live Ruida device, whose own
    thread executes what lands in it through the live `RuidaDriver`. Standing in
    for it is what keeps a test that describes a file from starting one.
    """

    def __init__(self):
        self.jobs = []

    def send(self, job, prevent_duplicate=False):
        self.jobs.append(job)


class _RecordingDriver:
    """Answers to anything and does nothing, so a motion command shows up as
    a name in `calls` instead of as a move.

    `status()` is the one exception, because it has to return something the
    caller can unpack: `mem_lookup` (`ruida/emulator.py:1363`) does
    `pos, state, minor = self.device.driver.status()` when the machine is asked
    for its position or its state, which is exactly what a status poll asks.
    A recorder returning `None` there raises `TypeError` instead of answering.
    """

    def __init__(self):
        self.calls = []

    def status(self):
        self.calls.append("status")
        return (0, 0), "idle", "idle"

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append(name)

        return record


class _StandInDevice:
    """The live device for everything the emulator reads, with the two
    attributes it can act through replaced."""

    def __init__(self, device, spooler, driver):
        self._device = device
        self.spooler = spooler
        self.driver = driver

    def __getattr__(self, name):
        return getattr(self._device, name)


def test_the_job_becomes_bytes_that_end_like_a_file(ruida):
    """
    The engine's own `save_job` writes 4 bytes and leaves 623 in the buffer
    (measured, see CLAUDE.md). We take them out of the buffer instead, and then a
    complete file should come out: it ends on SET_FILE_SUM followed by
    END_OF_FILE.
    """
    a_rectangle(ruida)
    runner = CommandRunner(ruida)

    data = runner.build_job_bytes()

    assert len(data) > 100, f"only {len(data)} bytes — the buffer was not drained"
    # `\xD7` is END_OF_FILE; `\xCC` is not there at this stage.
    assert data.endswith(b"\xd7"), data[-8:].hex(" ")
    # SET_FILE_SUM sits right before it. Note: that is `E5 05`
    # (`meerk40t/ruida/rdjob.py:173`), not D8 11 — the plan had that wrong and the
    # controller corrected it before this was built.
    assert b"\xe5\x05" in data[-16:], data[-16:].hex(" ")


def test_building_the_bytes_does_not_spool_anything(ruida):
    """
    Building is not burning. Whoever calls this route must not get a job in the
    queue — that is the whole difference from `start_job`.
    """
    a_rectangle(ruida)
    runner = CommandRunner(ruida)

    runner.build_job_bytes()

    spooler = ruida.device.spooler
    assert not list(spooler.queue), "a job was spooled while only bytes were asked for"


def test_building_the_bytes_never_starts_sending_on_the_live_controller(ruida):
    """
    `RuidaDriver.plot_start` ends on `controller.stop_record()`, which is literally
    `start_sending()` (`ruida/controller.py:325`): on a connected Ruida that ships the
    buffer over the open connection. `build_job_bytes` must build against a *fresh*
    driver and controller of its own — the live one, with the actual connection, must
    never be asked to send anything just because somebody wanted the bytes.

    Spied directly on `start_sending` rather than on the connection itself: the send
    is asynchronous (a background thread drains the queue), so a spy on the write
    would race it. `start_sending` is called synchronously, from the same thread that
    runs `job.execute()`, so there is nothing to race — it either was called or not.

    On the driver from before this fix round (the live driver, handed straight to
    `LaserJob`), this fails: `calls == [True]`, confirmed by hand before writing this
    test (see the fix-2 report).
    """
    a_rectangle(ruida)
    live_controller = ruida.device.driver.controller
    calls = []
    live_controller.start_sending = lambda: calls.append(True)
    runner = CommandRunner(ruida)

    runner.build_job_bytes()

    assert not calls, "the live controller was asked to start sending a file"


def test_an_empty_bed_refuses_with_a_sentence(ruida):
    runner = CommandRunner(ruida)

    with pytest.raises(DesignError) as error:
        runner.build_job_bytes()

    assert "nothing" in str(error.value).lower()


def test_a_non_ruida_machine_refuses_with_a_sentence(kernel):
    """
    The plain `kernel` fixture's active device is the dummy from `conftest.py`
    (`service device start dummy 0`), which keeps no `RDJob` anywhere. This is the
    `upload.notRuida` refusal — `DesignError` was raised in `build_job_bytes` without
    ever being imported into that scope, so this used to be a 500, not a sentence.
    """
    runner = CommandRunner(kernel)

    with pytest.raises(DesignError) as error:
        runner.build_job_bytes()

    assert error.value.code == "upload.notRuida"
    assert "Ruida" in str(error.value)


def test_a_z_step_per_pass_reaches_the_job_unfiltered(ruida, monkeypatch):
    """
    `_plan_without_spooling` turns a layer with a Z step per pass into
    `ConsoleOperation` items among the cutcode (`_with_passes`). An earlier version
    of `build_job_bytes` filtered the plan with
    `[step for step in plan.plan if hasattr(step, "__iter__")]`, which throws away
    every `ConsoleOperation` — precisely the Z-move steps — before the `LaserJob`
    ever sees them; the job would come out with every pass at the same height, the
    kind of mistake you only find on material. `build_job_bytes` must hand the
    unfiltered plan to `LaserJob`.

    A Ruida has no Z axis (`_focus_layers` needs both `supports_z_axis` and a
    registered `z_move` command, neither true here), but `_multi_pass_layers` and
    `_with_passes` do not gate on that — they just read `z_step_mm` off the
    operation, whatever the device. Setting it directly on the node, the way
    `drawing.py`'s guarded route would after its own device check, is enough to
    exercise this path without a GRBL kernel.
    """
    a_rectangle(ruida)
    layer = next(iter(ruida.elements.ops()))
    layer.passes_custom = True
    layer.passes = 2
    layer.z_step_mm = 0.5

    from meerk40t.core.laserjob import LaserJob

    captured = {}
    original_init = LaserJob.__init__

    def spy_init(self, label, items, **kwargs):
        captured["items"] = list(items)
        original_init(self, label, items, **kwargs)

    monkeypatch.setattr(LaserJob, "__init__", spy_init)
    runner = CommandRunner(ruida)

    runner.build_job_bytes()

    from meerk40t.core.node.util_console import ConsoleOperation

    assert any(isinstance(item, ConsoleOperation) for item in captured["items"]), (
        "the Z step's ConsoleOperation never reached the job"
    )


def test_two_passes_share_one_rd_layer(ruida):
    """
    The ⚠️ the reviewer named: measure the layers, don't read the code.

    `_share_pass_settings` gives every pass's copy of the settings dict the same
    identity, so the RD writer's layers-by-identity grouping
    (`ruida/rdjob.py:1434`, `write_header`) does not turn one cut layer into two.
    `LAYER_COLOR_PART` (`\\xCA\\x06`) is written exactly once per RD layer in
    `write_header`, so counting it counts the layers. CLAUDE.md has the measurement
    this guards against: a board of four squares went from 4 layers at one pass to
    8 at two, and a board of sixteen went to 33 and the controller said "file
    invalid".
    """
    a_rectangle(ruida)
    layer = next(iter(ruida.elements.ops()))
    layer.passes_custom = True
    layer.passes = 2
    runner = CommandRunner(ruida)

    data = runner.build_job_bytes()

    layers = data.count(b"\xca\x06")
    assert layers == 1, f"{layers} RD layer(s) for one cut layer with two passes"


def test_building_the_bytes_restores_the_merge_settings(ruida):
    """
    `_plan_without_spooling` turns `opt_merge_ops`/`opt_merge_passes` off while it
    works — same reason as `_plan_with_mutators`: on, the optimisation glues pieces
    together and pushes console steps to the back, so a Z would drop after burning
    instead of between passes. A mutator run during the build sees them off; once
    `build_job_bytes` returns, they are back to whatever they were before —
    the user's settings, not ours to leave changed.
    """
    a_rectangle(ruida)
    root = ruida.root
    root.setting(bool, "opt_merge_ops", True)
    root.setting(bool, "opt_merge_passes", True)
    root.opt_merge_ops = True
    root.opt_merge_passes = True
    runner = CommandRunner(ruida)
    seen = {}

    def spy(steps):
        seen["during"] = (root.opt_merge_ops, root.opt_merge_passes)
        return steps

    runner.build_job_bytes(mutators=[spy])

    assert seen["during"] == (False, False), "the flags were not off while building"
    assert (root.opt_merge_ops, root.opt_merge_passes) == (True, True), (
        "the flags were not put back"
    )


def test_building_the_bytes_does_not_pile_up_connect_attempts(ruida):
    """
    `RuidaController.__init__` starts a daemon thread unconditionally
    (`ruida/controller.py:50`); its loop sleeps 3 s and then, every 0.2 s forever,
    calls `service.connect()` on a service that reports itself not connected and
    not busy (`:172`, `:189`) — five times a second, for as long as it does.
    Before `_AlwaysConnected` existed, a `build_job_bytes` driver on this same
    test kernel took that branch: measured, 5 calls in the 4 s this test waits
    (the first ~3 s of that wait is the startup sleep; the calls land in the ~1 s
    left, at the 0.2 s cadence), isolated from the live driver's own identical
    thread, which does the same thing independently of this feature — see
    CLAUDE.md's row on the Ruida's connection lifecycle. With `_AlwaysConnected`:
    0 in the same 4 s.

    The live driver's own thread is neutralised the same way here, on purpose:
    without that, this test would still see calls from a thread this feature does
    not control, and "assert none" would be false regardless of what
    `build_job_bytes` does.

    Slow on purpose (a bit over 4 s) — that is the price of proving a thread
    never dials, rather than assuming it from the code.
    """
    a_rectangle(ruida)
    ruida.device.driver.controller.service = _AlwaysConnected(ruida.device)
    calls = []
    ruida.device.connect = lambda *a, **kw: calls.append(True)
    runner = CommandRunner(ruida)

    runner.build_job_bytes()
    time.sleep(4)

    assert not calls, f"{len(calls)} connect() call(s) in the 4s after building"


def test_ten_builds_do_not_leave_ten_threads(ruida):
    """
    A fresh `RuidaDriver` per call — the state before `_upload_driver_for` reused
    one — left two threads behind per build: a status monitor
    (`ruida/controller.py:50`) and, once `_AlwaysConnected` closed the connect
    storm, a `_data_sender` (`ruida/driver.py:301` → `controller.py:76`) blocked
    forever on `_job_lock`, never released. Measured on that code: `before=5`,
    `after one build=7`, `after ten builds=25` — climbing by two every call, still
    all alive 3 s later.

    With the driver reused and `_job_lock` released once (`resume_monitor`, see
    `_upload_driver_for`): measured `before=5`, `after one build=6`,
    `after ten builds=6` — the one thread the reused driver's own status monitor
    adds, and nothing more.
    """
    a_rectangle(ruida)
    runner = CommandRunner(ruida)

    # Named threads, not `active_count()`: this suite runs many kernels in one
    # process, and their own daemon threads dying at the wrong instant makes a raw
    # count flaky — a thread that was already in `before` vanishing from a later
    # `enumerate()` cannot register as "new", so this is immune to that noise.
    before = set(threading.enumerate())
    runner.build_job_bytes()
    new_after_one = set(threading.enumerate()) - before
    for _ in range(9):
        runner.build_job_bytes()
    new_after_ten = set(threading.enumerate()) - before

    assert len(new_after_one) == 1, (
        f"{len(new_after_one)} new thread(s) for one build: "
        f"{[t.name for t in new_after_one]}"
    )
    assert new_after_ten == new_after_one, (
        f"threads differ after nine more builds: "
        f"+{[t.name for t in new_after_ten - new_after_one]} "
        f"-{[t.name for t in new_after_one - new_after_ten]}"
    )


def test_a_design_built_before_and_after_a_different_one_is_byte_identical(ruida):
    """
    Reusing the driver reuses its state as well as its controller.
    `RuidaDriver.__init__` sets `power_dirty`/`speed_dirty` true
    (`ruida/driver.py:51,55`); `_move` (`:555-559`) writes `speed_laser_1` and the
    min/max power once and then sets both false. On a driver kept around across
    calls, only the first build ever wrote them again — measured, on the same
    rectangle built three times in a row, before `_reset_upload_driver_state`
    existed: `433, 418, 418` bytes, the second and third missing exactly
    `SPEED_LASER_1` (`c9 02 00 00 00 4e 10`) and the min/max power pair
    (`c6 02 7f 7f`/`c6 01 7f 7f`). `CommandRunner` lives for the life of an
    `ApiServer` (`server.py:273`), so only the first upload of a session would
    have been right.

    Three builds of the *same* design cannot catch every version of this bug,
    though: `driver.settings` (`Parameters`'s own dict) is *updated*, not
    replaced, from each plot's own settings (`self.settings.update(p_set
    .settings)`, `ruida/driver.py:285`), so a forgotten `.clear()` leaves an old
    key sitting underneath — invisible unless a later build's design actually
    reads that key differently. So: build A, then a deliberately different
    design B (a circle, its own speed and power), then A again, and require
    the two A builds to match byte for byte, not just in length — a leftover
    key does not change how long the file is.

    Measured (this rectangle and this circle, this runner): A is 433 bytes, B
    is 1349, and with `driver.settings.clear()` in place the second A is 433
    bytes too, identical to the first. With that line removed from
    `_reset_upload_driver_state`: the second A is *also* 433 bytes — same
    length, different content. First difference at byte 351:
    `c9 02 00 00 00 4e 10` (first A: `SPEED_LASER_1`, 10 mm/s, the rectangle's
    own default speed) against `c9 02 00 00 01 43 28` (second A: still B's
    `25.0`) — B's speed, left over in `driver.settings`, outliving the design
    that set it.
    """
    a_rectangle(ruida)
    runner = CommandRunner(ruida)
    first_a = runner.build_job_bytes()

    a_different_design(ruida)
    runner.build_job_bytes()

    a_rectangle(ruida)
    second_a = runner.build_job_bytes()

    assert first_a == second_a, (
        f"the first and second build of A differ ({len(first_a)} vs "
        f"{len(second_a)} bytes) after building a different design (B) in between"
    )


def test_the_reset_covers_every_field_ruidadriver_init_sets(ruida):
    """
    `_reset_upload_driver_state` is a line-by-line mirror of `RuidaDriver.__init__`
    as it reads today — nothing enforces that it stays one. A field the engine
    adds there tomorrow, that this test does not also add to
    `_reset_upload_driver_state` (or to the deliberately-kept construction half,
    `service`/`events`/`controller`/`recv`/`name`), would silently start leaking
    state between builds again exactly the way `power_dirty`/`speed_dirty` did:
    measured, `433, 418, 418` bytes across three otherwise identical builds, the
    second and third missing `SPEED_LASER_1` and the min/max power pair entirely
    (see `test_three_builds_of_the_same_design_are_byte_identical`). A forgotten
    field is not a style nitpick; it is a job that goes out wrong the second time
    somebody uses the button.

    So: build a real fresh `RuidaDriver`, read the names in its `__dict__`, and
    require every one of them to be either kept across builds on purpose or
    reset. `_reset_upload_driver_state` itself decides the second list — run
    against a stand-in object and read back what it touched — so this test
    breaks the moment the two lists drift apart, not a version behind.

    Built through `a_parked_driver`, not `RuidaDriver(...)` directly — see its
    own docstring for why a bare one has no business existing even in a test.
    """
    fresh = a_parked_driver(ruida.device)
    fresh_fields = set(vars(fresh).keys())

    # The expensive, stateful half `_upload_driver_for` deliberately keeps across
    # builds instead of resetting — see its docstring.
    kept_on_construction = {"service", "events", "controller", "recv", "name"}

    class _BlankDriver:
        """Enough of a driver for the reset to run against: just `settings`,
        the one field it mutates in place (`.clear()`) rather than reassigns."""

        def __init__(self):
            self.settings = {}

    stand_in = _BlankDriver()
    CommandRunner._reset_upload_driver_state(stand_in)
    reset_touches = set(vars(stand_in).keys())

    accounted_for = kept_on_construction | reset_touches
    forgotten = fresh_fields - accounted_for
    assert not forgotten, (
        f"RuidaDriver.__init__ now sets {sorted(forgotten)}, which "
        "_reset_upload_driver_state does not reset and _upload_driver_for does "
        "not list among the fields it deliberately keeps — add it to one or the "
        "other."
    )


def test_the_build_driver_is_off_the_shared_recv_channel(ruida):
    """
    `RuidaDriver.__init__` puts `controller.recv` on the shared `<device>/recv`
    channel (`ruida/driver.py:47,48`) — the same channel the live driver's own
    controller watches. `_upload_driver_for` takes it straight back off
    (`driver.recv.unwatch(driver.controller.recv)`): a build driver never needs
    an answer, so there is nothing this watcher is for, only a real reply it
    would needlessly react to.
    """
    a_rectangle(ruida)
    runner = CommandRunner(ruida)

    runner.build_job_bytes()

    build_driver = runner._upload_driver
    assert build_driver.controller.recv not in build_driver.recv.watchers, (
        "the build driver's controller is still watching the shared recv channel"
    )


def test_a_reply_on_the_shared_channel_writes_the_live_driver_only_once(ruida, monkeypatch):
    """
    Measured what staying on the channel would cost: `update_x`
    (`ruida/controller.py:259-268`) writes `self.service.driver.native_x` — and
    `self.service` for a build controller is `_AlwaysConnected`, whose
    `__getattr__` still resolves `.driver` to `device.driver`, the *live* driver.
    So a build controller left on the shared channel writes the live driver's
    position a second time for every reply that arrives while it exists — not a
    path toward the machine, but a needless second write to state the app reads
    to show where the head is.

    No real machine is involved: a reply is exactly five bytes of 7-bit-encoded
    value after a header (`RDJob.decode_reply`), so one is built by hand here and
    played onto the channel both drivers watch. `native_x` is turned into a
    counting property for the one instance under test (`monkeypatch`, reverted
    automatically) so "written twice" and "written once" are told apart by count,
    not by two writes of the same number looking like one.
    """
    from meerk40t.ruida.driver import RuidaDriver
    from meerk40t.ruida.rdjob import MEM_CURRENT_X

    def encode35(value):
        return bytes(
            [
                (value >> 28) & 0x7F,
                (value >> 21) & 0x7F,
                (value >> 14) & 0x7F,
                (value >> 7) & 0x7F,
                value & 0x7F,
            ]
        )

    a_rectangle(ruida)
    runner = CommandRunner(ruida)
    runner.build_job_bytes()

    writes = []

    def _set_native_x(self, value):
        writes.append(value)
        self.__dict__["native_x"] = value

    monkeypatch.setattr(
        RuidaDriver,
        "native_x",
        property(lambda self: self.__dict__.get("native_x", 0), _set_native_x),
        raising=False,  # `native_x` is only ever an instance attribute, set in
        # `__init__`, so the class itself has none yet to check against.
    )

    reply = bytes([0xDA, 0x01]) + MEM_CURRENT_X + encode35(12345)
    name = ruida.device.safe_label
    recv_channel = ruida.device.channel(f"{name}/recv", pure=True)

    recv_channel(reply)

    assert writes == [12345], f"native_x written {len(writes)} time(s): {writes}"


def test_the_name_goes_over_the_line_in_eight_capitals(ruida):
    """
    The machine keeps eight characters, in capitals — the engine's own emulator
    truncates to eight and upper-cases them itself (`ruida/emulator.py:749-753`
    reads until the NUL; the panel shows what a Ruida keeps). So we send what
    arrives, and the screen says the same thing the panel does.
    """
    upload = RuidaUpload(ruida)

    frames = upload.frames("kastje-groot", b"\x00")

    name = frames[1]
    assert name.startswith(b"\xe7\x01")
    assert name[2:-1] == b"KASTJE-G"
    assert name.endswith(b"\x00")


def test_a_space_never_reaches_the_panel(ruida):
    """
    Eight characters is little enough without spending them on gaps, and the
    refusal below promises "letters or digits". So `my box` goes out as `MYBOX`,
    not as `MY BOX` — one thing to say about the name, not two.
    """
    upload = RuidaUpload(ruida)

    frames = upload.frames("my box", b"\x00")

    assert frames[1][2:-1] == b"MYBOX"


def test_the_conversation_opens_with_a_file_transfer(ruida):
    """
    The header, and then the payload in blocks that never cut a command in two.

    The payload here is not a real job but five hundred six-byte commands: a
    Ruida command starts at a byte >= 0x80 and runs until the next one
    (`ruida/rdjob.py:419`, `parse_commands`), so this is the smallest thing that
    has boundaries to respect. Six bytes on purpose: 166 of them make 996, so a
    full block stops four bytes short of `CHUNK` and a block boundary can only
    land where a command ends. At five bytes it would divide 1000 exactly and
    slicing the payload blindly would give the same answer as respecting the
    commands.
    """
    upload = RuidaUpload(ruida)
    command = b"\x88" + b"\x11" * 5
    payload = command * 500

    frames = upload.frames("BORD", payload)

    assert frames[0] == b"\xe8\x02"
    blocks = frames[2:]
    assert b"".join(blocks) == payload
    assert all(len(block) <= CHUNK for block in blocks)
    assert [len(block) for block in blocks] == [996, 996, 996, 12]
    # Every block begins at a command, so the receiving side can parse each one
    # on its own.
    assert all(block[0] >= 0x80 for block in blocks)


def test_a_nameless_file_refuses_with_a_sentence(ruida):
    """
    A name of nothing but spaces and control characters leaves nothing for the
    panel to show, and `E7 01 00` is a file the user cannot find back. That is a
    refusal with a sentence, not an empty name sent anyway.
    """
    upload = RuidaUpload(ruida)

    with pytest.raises(DesignError) as error:
        upload.frames("  \t ", b"\x00")

    assert error.value.code == "upload.needsName"


def test_the_emulator_receives_the_file_we_built(ruida, monkeypatch, tmp_path):
    """
    End to end without a laser and without a socket: the engine's own Ruida
    emulator takes this conversation, and what arrives in its job is byte for
    byte what `build_job_bytes` built.

    Deliberately not what the spec asked for ("a second engine with
    `ruidacontrol`"): that opens UDP ports in a test suite, and a test that needs
    a port fails the day something else has it. The emulator is an ordinary class
    with `write(data, unswizzle=False)`; feeding it directly exercises the same
    conversation and depends on no network. Talking to a real `ruidacontrol`
    belongs to task 7, with the user present.

    The design is eight circles on purpose: at 5462 bytes it is five blocks and a
    tail rather than the single block a rectangle (433 bytes) fits in, so the
    seams between blocks are actually under test here. Measured on this payload:
    cut into six raw 1000-byte slices the emulator reports 5 `Process Failure`s —
    one per interior seam, each a command chopped in half; cut on command
    boundaries, 0, and the job it builds is identical to the one it builds from
    the payload in a single piece.

    What the emulator keeps is the payload minus one command: `SET_FILE_SUM`
    (`E5 05`, seven bytes) it answers itself instead of putting it in the job.
    Measured: 5462 bytes sent, 5455 in the buffer, and the difference is exactly
    that one command — so the comparison below is against everything else, and
    it is against the payload we built, not against what we sent, which is what
    makes it notice bytes going missing on the way.

    `get_safe_path` is redirected to `tmp_path` rather than switching `saving`
    off, because switching it off would take a branch of the conversation away:
    our `E8 02` is what sets `emulator.saving` (`ruida/emulator.py:797`) and the
    `E7 01` that follows opens `<name>.rd` because of it (`:757`). Measured
    without the redirect: `~/Library/Application Support/BORD.rd`, created by
    this test alone and left open — the house rule in CLAUDE.md says a test does
    not write where the user lives. The engine never writes a byte to that
    stream (`filestream` is opened at `:757` and appears nowhere else), so the
    file that lands in `tmp_path` is empty; the test closes the handle itself.

    Redirecting the module's `get_safe_path` rather than that one call covers
    every other path the emulator has to the disk as well — it imports the name
    once (`:11`) and every file it touches goes through it, including the branch
    that `os.remove`s *every* `.rd` in that directory on an `E8 00` (`:769-777`).
    Our payload does not contain that command, but a test does not get to hold
    the user's files hostage to that.

    The emulator gets a stand-in device, and that is not tidiness either. Every
    command it does not treat as realtime ends in
    `self.device.spooler.send(self.job, prevent_duplicate=True)`
    (`ruida/emulator.py:159`) — the spooler of the live Ruida device this fixture
    started, whose own thread executes what lands in it through the live
    `RuidaDriver`. And a few commands it does treat as realtime reach
    `self.device.driver` directly (`_home_device`, `:164-170`; `move_abs`,
    `:341`). Measured with the stand-ins counting what the real ones would have
    been asked for: this payload reaches `spooler.send` 1072 times, always with
    the same `RDJob` — so `prevent_duplicate` leaves one job in the queue, and
    the spooler's own thread executes it. The driver is asked for nothing by this
    particular payload (0 calls), but it stays a stand-in all the same: whether
    the live one is touched must not depend on which design somebody built. On
    this fixture the interface is `usb` and nothing is connected, so nothing left
    the process today — a kernel pointed at a real machine would have moved a
    head from that thread, and this project does not start jobs to test
    something.
    """
    import meerk40t.ruida.emulator as emulator_module
    from meerk40t.ruida.emulator import RuidaEmulator
    from meerk40t.ruida.rdjob import parse_commands

    monkeypatch.setattr(
        emulator_module,
        "get_safe_path",
        lambda name, *args, **kwargs: str(tmp_path / name),
    )
    a_design_over_one_block(ruida)
    upload = RuidaUpload(ruida)
    payload = upload.runner.build_job_bytes()
    assert len(payload) > CHUNK, f"{len(payload)} bytes is a single block"

    spooler = _InertSpooler()
    driver = _RecordingDriver()
    said = []
    stand_in = _StandInDevice(ruida.device, spooler, driver)
    # Built *with* the stand-in, not patched onto it afterwards: `__init__` hands
    # `device.driver` to its own `RDJob` (`ruida/emulator.py:57-58`), and
    # `RDJob.process` calls `self._driver.plot(...)` (`rdjob.py:741`). Patched
    # after construction, that job holds the live driver, and whether it is ever
    # asked to plot then depends on who runs the job — exactly the "it depends on
    # who calls what" this test refuses everywhere else.
    emulator = RuidaEmulator(stand_in, ruida.device.view.matrix)
    assert emulator.job._driver is driver
    emulator.channel = said.append
    packets = upload.frames("BORD", payload)
    assert len(packets) - 2 >= 2, "the payload went out in one block after all"

    emulator.write(packets[0], unswizzle=False)
    emulator.write(packets[1], unswizzle=False)
    named = emulator.filename
    for frame in packets[2:]:
        emulator.write(frame, unswizzle=False)
    if emulator.filestream is not None:
        emulator.filestream.close()

    assert named == "BORD"
    received = b"".join(emulator.job.buffer)
    expected = b"".join(
        command
        for command in parse_commands(payload)
        if not bytes(command).startswith(b"\xe5\x05")
    )
    assert received == expected, (
        f"{len(received)} bytes arrived of the {len(expected)} we built"
    )
    failures = [line for line in said if "Process Failure" in line]
    assert not failures, (
        f"the emulator could not parse {len(failures)} command(s): {failures[:3]}"
    )
    # And it read the file all the way to its end: END_OF_FILE (`\xD7`, the last
    # byte `build_job_bytes` writes) is what puts the name back to `None` and
    # closes program mode (`ruida/emulator.py:354-358`).
    assert emulator.filename is None and emulator.program_mode is False, (
        "the emulator never reached END_OF_FILE, so it did not read the whole file"
    )
    assert not list(ruida.device.spooler.queue), (
        "a job reached the live device's spooler while a file was being described"
    )
    assert not driver.calls, f"the live driver would have been asked for {driver.calls}"
    # The redirect worked, and the engine wrote nothing to the stream it opened.
    written = tmp_path / "BORD.rd"
    assert written.exists() and written.read_bytes() == b""


class FakeSession:
    """A connection that records what it is handed, and can misbehave on cue.

    Stands in for `RuidaSession` in the three ways the flow control cares about:
    `is_busy` (`ruida/ruidasession.py:161`, `_reply_pending or _ack_pending`),
    `connected`, and `write`, which on the real one raises `ConnectionError` the
    moment the session is not connected (`:167`).
    """

    connected = True

    def __init__(self, busy_forever=False, busy_for=0, fail_after=None):
        self.written = []
        self.busy_forever = busy_forever
        self.busy_for = busy_for
        self.fail_after = fail_after
        self.busy_reads = 0

    @property
    def is_busy(self):
        self.busy_reads += 1
        if self.busy_forever:
            return True
        return self.busy_reads <= self.busy_for

    def write(self, data):
        if self.fail_after is not None and len(self.written) >= self.fail_after:
            raise ConnectionError("Not connected to the Ruida controller.")
        self.written.append(data)


def a_fake_session(upload, monkeypatch, **kwargs):
    """Put a `FakeSession` in the place of both ways out of `RuidaUpload`.

    Both, not one: `_session` is what the flow control reads `is_busy` off and
    `_write` is what puts bytes on the line, and on a real device they are two
    faces of the same session (`ruida/device.py:410` binds `controller.write` to
    `active_session.write`). Patching only one would leave the other pointed at
    the live controller of the device this fixture started — which is a path
    toward a machine, and this suite has none.
    """
    session = FakeSession(**kwargs)
    monkeypatch.setattr(upload, "_session", lambda: session)
    monkeypatch.setattr(upload, "_write", session.write)
    return session


def test_a_transfer_that_stalls_says_how_far_it_got(ruida, monkeypatch):
    """
    The engine gives up after about four seconds in silence — `RuidaSession.write`
    (`ruida/ruidasession.py:167`) retries a full queue twelve times at 0.25 s and
    then falls out of its own `while _tries:` loop without raising, and
    `_data_sender` (`ruida/controller.py:118`) never looks at whether a write
    landed and says "File Sent." at the end regardless. Its own source carries the
    TODO: "What does the calling method do in the case of timeout? How to inform
    the calling method a timeout occurred?"

    A half upload that says nothing is the worse of the two failures: then there
    is half a file in the machine and everybody thinks it went well. So the
    refusal carries the two numbers that say how bad it is.
    """
    a_rectangle(ruida)
    upload = RuidaUpload(ruida)
    session = a_fake_session(upload, monkeypatch, busy_forever=True)
    upload.per_chunk_seconds = 0.2

    with pytest.raises(DesignError) as error:
        upload.upload("BORD")

    said = str(error.value)
    assert "of" in said and any(ch.isdigit() for ch in said), said
    assert "incomplete" in said.lower()
    assert error.value.code == "upload.stalled"
    assert not session.written, "bytes went out while the line was never free"


def test_a_transfer_that_flows_reports_what_went(ruida, monkeypatch):
    a_rectangle(ruida)
    upload = RuidaUpload(ruida)
    session = a_fake_session(upload, monkeypatch)

    result = upload.upload("bord-1")

    assert result["name"] == "BORD-1"
    assert result["chunks"] == len(session.written) - 2  # without the two headers
    assert result["bytes"] > 100
    assert session.written[0] == b"\xe8\x02"
    assert session.written[1].startswith(b"\xe7\x01")
    assert sum(len(block) for block in session.written[2:]) == result["bytes"]


def test_the_upload_waits_for_a_busy_line_instead_of_writing_over_it(
    ruida, monkeypatch
):
    """
    Waiting is the whole point of the flow control, so it has to be visible that
    it happens — a loop that never waits passes every test above this one.

    `is_busy` here reports busy for the first three reads and free after that,
    and the poll interval is turned down so the wait costs a few milliseconds
    rather than the 0.02 s the real one uses. Measured on this rectangle: one
    block, so four reads of `is_busy` for two headers and one block would mean
    no waiting at all; with three busy reads to get through, the count comes out
    at six.
    """
    a_rectangle(ruida)
    upload = RuidaUpload(ruida)
    session = a_fake_session(upload, monkeypatch, busy_for=3)
    upload.poll_seconds = 0.001

    result = upload.upload("BORD")

    assert session.busy_reads == 6, session.busy_reads
    assert len(session.written) == result["chunks"] + 2


def test_a_connection_lost_halfway_says_how_far_it_got(ruida, monkeypatch):
    """
    `RuidaSession.write` raises `ConnectionError` as soon as the session is not
    connected (`ruida/ruidasession.py:167`) — the machine switched off, the cable
    out, the Ruida's own habit of dropping and silently reopening (CLAUDE.md's
    row on the connection lifecycle). Unhandled that is a 500 with a stack trace,
    which tells the person at the laser nothing about the half file now sitting
    in the machine. It has to be the same sentence with the same two numbers as a
    stall.
    """
    a_design_over_one_block(ruida)
    upload = RuidaUpload(ruida)
    # Two headers and three blocks land; the fourth block is where it breaks.
    session = a_fake_session(upload, monkeypatch, fail_after=5)

    with pytest.raises(DesignError) as error:
        upload.upload("BORD")

    said = str(error.value)
    assert error.value.code == "upload.interrupted"
    assert "3 of" in said, said
    assert "incomplete" in said.lower()
    assert len(session.written) == 5


def test_a_command_longer_than_a_block_refuses_before_anything_goes_out(
    ruida, monkeypatch
):
    """
    `_blocks` cuts on command boundaries and never inside one, so a single
    command longer than `CHUNK` goes into a block of its own, oversized —
    measured in the round before this one: `\\x88` followed by 1200 bytes gives
    blocks of 1201 and 1. Building that is right; sending it is not.

    Measured on a pair of loopback UDP sockets, which is what the line to the
    machine is: a datagram of 1201 bytes read by a receiver that calls
    `recvfrom(1024)` arrives as 1024 bytes, with no error on either side — the
    tail is simply gone. And `recvfrom(1024)` is what *every* receiver in the
    engine uses (`ruida/udp_transport.py:62`, `udp_connection.py:174`,
    `network/udp_server.py:96`, `ruida/tcp_connection.py:156`). Add the two
    checksum bytes UDP packaging puts in front (`ruidasession.py:_package`) and
    the real ceiling on a block is 1022 bytes; `CHUNK` at 1000 sits under it with
    room to spare.

    So an oversized block would be truncated silently — the same damage
    `_blocks` exists to avoid, one layer further down and past the point where
    anyone can see it. It is refused before the first byte goes out, so nothing
    half-written is left on the panel. Measured on this project's designs the
    longest command is 16 bytes, so this is a guard against a payload nobody has
    made yet, not a case anybody meets.
    """
    a_rectangle(ruida)
    upload = RuidaUpload(ruida)
    session = a_fake_session(upload, monkeypatch)
    monkeypatch.setattr(
        upload.runner, "build_job_bytes", lambda *a, **kw: b"\x88" + b"\x11" * 1200
    )

    with pytest.raises(DesignError) as error:
        upload.upload("BORD")

    assert error.value.code == "upload.commandTooLong"
    said = str(error.value)
    assert "1201" in said and "1000" in said, said
    assert not session.written, "an oversized block went out anyway"


def test_an_empty_file_is_never_announced(ruida, monkeypatch):
    """
    `frames(name, b"")` is two headers and no blocks: a file announced with
    nothing in it. `build_job_bytes` refuses an empty bed itself
    (`job.nothingToBurn`) so nothing reaches this today, but "the payload is
    never empty" is a promise about another function, and the cost of it being
    wrong is a name on the machine's panel that burns nothing. Announcing costs
    the user a file to find and delete; refusing costs a sentence.
    """
    a_rectangle(ruida)
    upload = RuidaUpload(ruida)
    session = a_fake_session(upload, monkeypatch)
    monkeypatch.setattr(upload.runner, "build_job_bytes", lambda *a, **kw: b"")

    with pytest.raises(DesignError) as error:
        upload.upload("BORD")

    assert error.value.code == "upload.emptyFile"
    assert not session.written, "the file was announced before it was found empty"


def test_a_machine_that_is_not_connected_refuses_with_a_sentence(ruida):
    """
    The `ruida` fixture starts the service with `-i`, so no session was ever
    opened and `device.active_session` is `None` — the state a user is in before
    they press connect. That is a sentence saying nothing has been sent, not an
    `AttributeError` on `None`.
    """
    a_rectangle(ruida)
    upload = RuidaUpload(ruida)

    with pytest.raises(DesignError) as error:
        upload.upload("BORD")

    assert error.value.code == "upload.notConnected"
    assert "nothing has been sent" in str(error.value).lower()


def test_a_session_that_is_open_but_not_connected_refuses_too(ruida, monkeypatch):
    """
    `RuidaSession.connected` is more than "an object exists": it wants the
    transport open *and* the controller answering (`ruida/ruidasession.py:150`).
    A session that exists while the machine is off is exactly the case where
    `write` raises `ConnectionError` on the first byte, so it is caught here
    instead, before a file is announced.
    """
    a_rectangle(ruida)
    upload = RuidaUpload(ruida)
    session = FakeSession()
    session.connected = False
    monkeypatch.setattr(ruida.device, "active_session", session, raising=False)

    with pytest.raises(DesignError) as error:
        upload.upload("BORD")

    assert error.value.code == "upload.notConnected"
    assert not session.written


def test_uploading_leaves_the_live_spooler_empty(ruida, monkeypatch):
    """
    Sending a file is not starting one. Whatever else an upload does, nothing may
    reach the queue that the live device's own thread executes — that is the one
    difference between this button and the one that burns, and there is
    deliberately no route in this module that begins a job.
    """
    a_rectangle(ruida)
    upload = RuidaUpload(ruida)
    a_fake_session(upload, monkeypatch)

    upload.upload("BORD")

    assert not list(ruida.device.spooler.queue), "a job was spooled by an upload"


def test_a_status_poll_between_blocks_does_not_damage_the_file(
    ruida, monkeypatch, tmp_path
):
    """
    Why the upload does *not* pause the engine's status monitor while it sends.

    `RuidaController._status_monitor` (`ruida/controller.py:160`) sends a
    `GET_SETTING` every 0.2 s for as long as the device is connected, over the
    same session our blocks go out on, and it holds `_job_lock` only against the
    engine's own `_data_sender`. So while we are sending, its packets land
    between ours. The engine's answer to that is `pause_monitor()`, which
    acquires a lock that is released in exactly one place
    (`ruida/device.py:415`) — taking it and failing to give it back stops the
    machine's status for the rest of the session, and taking it when it was
    never released deadlocks the request thread.

    Measured against the engine's own emulator before deciding: the same eight
    circles sent as six blocks, once clean and once with a status poll
    (`DA 00 04 00`, `GET_SETTING MEM_MACHINE_STATUS`) written between every pair
    of blocks. Both give a job of 5455 bytes, byte for byte identical, with 0
    `Process Failure`s. The poll is handled as realtime (`emulator.py:157`,
    `_process_realtime` → `mem_lookup`) and answered; it never reaches the job
    buffer. So interleaved status does not damage the file, and the lock — with
    its two ways to hang the app — stays untouched.
    """
    import meerk40t.ruida.emulator as emulator_module
    from meerk40t.ruida.emulator import RuidaEmulator
    from meerk40t.ruida.rdjob import GET_SETTING, MEM_MACHINE_STATUS

    monkeypatch.setattr(
        emulator_module,
        "get_safe_path",
        lambda name, *args, **kwargs: str(tmp_path / name),
    )
    a_design_over_one_block(ruida)
    upload = RuidaUpload(ruida)
    packets = upload.frames("BORD", upload.runner.build_job_bytes())
    assert len(packets) - 2 >= 2, "the payload went out in one block after all"
    poll = bytes(GET_SETTING) + bytes(MEM_MACHINE_STATUS)

    def received(interleaved):
        said = []
        driver = _RecordingDriver()
        emulator = RuidaEmulator(
            _StandInDevice(ruida.device, _InertSpooler(), driver),
            ruida.device.view.matrix,
        )
        emulator.channel = said.append
        emulator.write(packets[0], unswizzle=False)
        emulator.write(packets[1], unswizzle=False)
        for index, frame in enumerate(packets[2:]):
            if interleaved and index:
                emulator.write(poll, unswizzle=False)
            emulator.write(frame, unswizzle=False)
        if emulator.filestream is not None:
            emulator.filestream.close()
        failures = [line for line in said if "Process Failure" in line]
        assert not failures, failures[:3]
        return b"".join(emulator.job.buffer), driver.calls

    clean, _ = received(False)
    polled, calls = received(True)

    assert calls.count("status") == len(packets) - 3, calls
    assert polled == clean, (
        f"{len(polled)} bytes arrived with the status poll interleaved against "
        f"{len(clean)} without it"
    )
