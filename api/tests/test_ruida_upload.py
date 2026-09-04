"""
A job as a file: the bytes, the conversation, and what goes wrong.

Never against a laser. The end-to-end test talks to the engine's own Ruida
emulator, which takes this conversation and reads the file back off it.
"""

import queue
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
    question about where one block ends and the next begins. These eight circles
    come to 5462 or 5463 bytes — five full blocks and a tail either way, which
    is the whole of what this helper promises.

    Which of the two, and why it is not a warning about `build_job_bytes`:
    building is stable. Measured, ten builds of one drawing gave 5462 ten times,
    both with the runner kept and with a fresh one for every call. It is *this
    function* that moves the answer — ten redraws of the same eight circles gave
    `[5463, 5462, 5463, 5463, 5462, 5462, 5462, 5462, 5463, 5463]`, in no order,
    so "varies" and not "alternates". Measured separately, the difference is not
    a rounded coordinate: the cutcode is pointwise identical (all 192 points) and
    the two encodings are two different, both valid, polygon approximations of
    the same arc, their vertices up to about half a millimetre apart.

    Nothing here asserts a length, only that the design needs more than one
    block; and no test builds a payload twice and compares the two.
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

    The design is eight circles on purpose: at 5462 or 5463 bytes (see
    `a_design_over_one_block`) it is five blocks and a
    tail rather than the single block a rectangle (433 bytes) fits in, so the
    seams between blocks are actually under test here. Measured on this payload:
    cut into six raw 1000-byte slices the emulator reports 5 `Process Failure`s —
    one per interior seam, each a command chopped in half; cut on command
    boundaries, 0, and the job it builds is identical to the one it builds from
    the payload in a single piece.

    What the emulator keeps is the payload minus one command: `SET_FILE_SUM`
    (`E5 05`, seven bytes) it answers itself instead of putting it in the job.
    Measured on one such build: 5462 bytes sent, 5455 in the buffer, and the
    difference is exactly
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
    moment the session is not connected (`:186`).
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
    (`ruida/ruidasession.py:186`) retries a full queue twelve times at 0.25 s and
    then falls out of its own `while _tries:` loop without raising, and
    `_data_sender` (`ruida/controller.py:119`) never looks at whether a write
    landed and says "File Sent." at the end regardless. Its own source carries the
    TODO: "What does the calling method do in the case of timeout? How to inform
    the calling method a timeout occurred?"

    A half upload that says nothing is the worse of the two failures: then there
    is half a file in the machine and everybody thinks it went well. So the
    refusal carries the two numbers that say how bad it is.

    With the line busy from the start, this is the *zero* case: the wait that
    fails is the one in front of the `E8 02` packet, so not a byte has gone out
    and there is nothing on the panel. The sentence has to say that and not the
    other one — an earlier version told the reader to "delete the file on the
    panel" whatever the count, sending them after something that was never
    announced. The partway case is
    `test_a_stall_partway_says_the_file_is_incomplete`, the case where
    everything went out is
    `test_the_last_block_is_not_reported_sent_until_it_is_acknowledged`.
    """
    a_rectangle(ruida)
    upload = RuidaUpload(ruida)
    session = a_fake_session(upload, monkeypatch, busy_forever=True)
    upload.per_chunk_seconds = 0.2

    with pytest.raises(DesignError) as error:
        upload.upload("BORD")

    said = str(error.value)
    assert "of" in said and any(ch.isdigit() for ch in said), said
    assert error.value.code == "upload.stalled"
    assert error.value.values["sent"] == 0, error.value.values
    assert not session.written, "bytes went out while the line was never free"
    assert "delete" not in said.lower(), said
    assert "send it again" in said.lower(), said


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
    block, so two headers and one block are three waits, plus the fourth after
    the last block — four free reads if nothing ever waits. With three busy
    reads to get through first, the count comes out at seven.
    """
    a_rectangle(ruida)
    upload = RuidaUpload(ruida)
    session = a_fake_session(upload, monkeypatch, busy_for=3)
    upload.poll_seconds = 0.001

    result = upload.upload("BORD")

    assert session.busy_reads == 7, session.busy_reads
    assert len(session.written) == result["chunks"] + 2


def test_a_write_that_is_refused_halfway_says_how_far_it_got(ruida, monkeypatch):
    """
    `RuidaSession.write` refuses to queue anything the moment the session is not
    connected, raising `ConnectionError` (`ruida/ruidasession.py:186`).
    Unhandled that is a 500 with a stack trace, which tells the person at the
    laser nothing about the half file now sitting in the machine. It has to be
    the same sentence with the same two numbers as a stall.

    Named for the refused write and not for a lost connection, because the flag
    behind it does not say that much. `connected` is `_responding` and two
    others (`:154`), and `_responding` is cleared by silence as readily as by a
    break — about a second of it, at `normal_timeout()`. See
    `test_a_broken_transfer_says_what_was_seen_and_not_what_caused_it`: the same
    ambiguity, and the same answer, which is that the sentence reports what was
    observed. Three names in this task promised more than their source carried;
    this is the third.
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
    command longer than `CHUNK` goes into a block of its own, oversized.
    Measured: `_blocks(b"\\x88" + b"\\x11" * 1200)` gives **one** block, of 1201
    bytes — the payload is one command and there is nothing to cut it against.
    (The round before this one recorded "1201 and 1"; there is no block of 1.
    Put a second command after it and the answer is `[1201, 2]`.) Building that
    block is right; sending it is not.

    Measured on a pair of loopback UDP sockets: 996, 1000 and 1024 bytes arrive
    whole, and 1201 and 1203 both arrive as **1024**, with no error on either
    side — the tail is simply gone. That settles what happens to anything the
    *engine* receives, because every UDP receiver in it reads with
    `recvfrom(1024)` (`ruida/udp_transport.py:62`, `udp_connection.py:174`,
    `network/udp_server.py:96`), the last of which is the emulator a
    `ruidacontrol` stand-in listens on.

    What a real Ruida's firmware accepts as a datagram is **not** measured here
    and does not follow from those lines — they are our side of the wire. The
    assumption is that it has the same 1024-byte ceiling, leaving 1022 for a
    block once `_package` has put its two checksum bytes in front; the ground
    under it is that the engine cuts its own jobs at 1000 (`controller.py:83`),
    a limit reverse-engineered against real machines. `CHUNK` at 1000 is under
    either reading, and this guard refuses only what is over `CHUNK`, so nothing
    here turns on the assumption being right.

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
    transport open *and* the controller answering (`ruida/ruidasession.py:154`).
    A session that exists while the machine is off is exactly the case where
    `write` raises `ConnectionError` on the first byte, so it is caught here
    instead, before a file is announced.
    """
    a_rectangle(ruida)
    upload = RuidaUpload(ruida)
    session = FakeSession()
    session.connected = False
    monkeypatch.setattr(ruida.device, "active_session", session, raising=False)
    # `_write` too, and not for tidiness: without it this test is safe only
    # because `_session()` happens to refuse before the first write. Move that
    # check one line and the test writes on the live controller of the device
    # this fixture started — a path toward a machine, opened by a test that is
    # about a machine being unreachable.
    monkeypatch.setattr(upload, "_write", session.write)

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

    `RuidaController._status_monitor` (`ruida/controller.py:162`) sends a
    `GET_SETTING` every 0.2 s for as long as the device is connected, over the
    same session our blocks go out on. So while we are sending, its packets land
    between ours. The engine's answer to that is `pause_monitor()`, and the
    measurement below is why we do not use it.

    Measured against the engine's own emulator before deciding: the same eight
    circles in six blocks, once clean and once with a status poll
    (`DA 00 04 00`, `GET_SETTING MEM_MACHINE_STATUS`) written between every pair
    of blocks. Both give the same job, byte for byte, with 0 `Process Failure`s
    — which is what the test asserts, rather than a length, because
    `build_job_bytes` is not byte-deterministic on this design (measured over
    six builds: 5462 or 5463 bytes, differing in the coordinate bytes of the
    circle interpolation from byte 1112 on, when the drawing is made again). The
    comparison is between two runs
    of the same payload, so that variation cannot reach it. (Two builds of the
    same drawing agree anyway — see `a_design_over_one_block` — but the test
    does not need that to be true.) The poll is handled as realtime (`emulator.py:157`,
    `_process_realtime` → `mem_lookup`) and answered; it never reaches the job
    buffer. So interleaved status does not damage the file: there is nothing
    here to protect against.

    Which matters, because the protection costs more than the risk.
    `pause_monitor()` is a bare `acquire()` with no timeout
    (`ruida/controller.py:102`) on a lock four places release — `:98`
    (`resume_monitor`, whose one caller is `ruida/device.py:415`), `:132`
    (`_data_sender`), `:183` (`_status_monitor`, so every poll, every 0.2 s) and
    `:393` (`wait_for_position`). It therefore blocks for as long as
    `_data_sender` holds the lock — which is exactly the stalled case this
    module exists for — and forever if `resume_monitor` never ran.
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


class DeferringSession:
    """A connection where writing and acknowledging come apart, as they really do.

    `FakeSession` cannot catch what this catches, because there writing *is*
    arriving. On a real session `RuidaSession.write` is `send_q.put` and nothing
    else (`ruida/ruidasession.py:188`); a separate handshaker thread pops the
    packet, hands it to the transport, and only then — and only on a `udp`
    interface (`:349`) — sets `_ack_pending`, the half of `is_busy` our own
    blocks ever touch. So there is a window after every write in which the line
    still looks free, and there is no window at all after the last one, because
    nobody looks again.

    This models exactly that: `write` queues, a daemon thread takes from the
    queue, marks the line busy, and clears it `ack_seconds` later. With
    `stops_before=n` the thread takes the nth packet, marks the line busy and
    never clears it — the machine switched off, or the cable out, with a packet
    already handed to the transport. Nothing here reaches a machine: it is a
    queue and a thread in this process.
    """

    def __init__(self, ack_seconds=0.01, stops_before=None, acknowledges=True):
        self.connected = True
        self.acknowledges = acknowledges
        self.send_q = queue.Queue()
        self.written = []
        self.acknowledged = []
        self.ack_seconds = ack_seconds
        self.stops_before = stops_before
        self._ack_pending = False
        self._shutdown = False
        #: The most packets ever out at once — written and not yet acknowledged,
        #: read at the moment of each write. One is the whole point; more than
        #: one means blocks were handed over without waiting for the one before.
        self.deepest = 0
        self.deepest_queue = 0
        self._thread = threading.Thread(target=self._handshake, daemon=True)
        self._thread.start()

    @property
    def is_busy(self):
        return self._ack_pending

    def write(self, data):
        # Raising here is not decoration: `RuidaSession.write` checks `connected`
        # before it queues anything and raises on a session that has dropped
        # (`ruidasession.py:186`). No test in this file reaches it — the drop is
        # arranged on the last packet, so nothing is written after it — but this
        # is what a later test that drops the line halfway would run into, and a
        # stand-in that quietly accepts what the real one refuses measures the
        # wrong thing.
        if not self.connected:
            raise ConnectionError("Not connected to the Ruida controller.")
        self.written.append(data)
        self.send_q.put(data)
        self.deepest = max(self.deepest, len(self.written) - len(self.acknowledged))
        self.deepest_queue = max(self.deepest_queue, self.send_q.qsize())

    def _handshake(self):
        while not self._shutdown:
            try:
                data = self.send_q.get(timeout=0.01)
            except queue.Empty:
                continue
            if (
                self.stops_before is not None
                and len(self.acknowledged) >= self.stops_before
            ):
                # This is where the packet stops, and the two interfaces show it
                # differently. On `udp` it went out and the acknowledgement never
                # comes, so `_ack_pending` stays set. On `usb` the transport
                # write itself fails, which sets `_responding = False`
                # (`ruidasession.py:345-346`) — one of the three things
                # `connected` is made of (`:154`) — and every later `write`
                # raises (`:186`). Both happen at once, with no wait in front of
                # them, which is why this is before the sleep.
                if self.acknowledges:
                    self._ack_pending = True
                else:
                    self.connected = False
                return
            if self.acknowledges:
                self._ack_pending = True
            time.sleep(self.ack_seconds)
            self.acknowledged.append(data)
            self._ack_pending = False

    def stop(self):
        self._shutdown = True
        self._thread.join(timeout=2)


@pytest.fixture
def deferring():
    """`DeferringSession`s, all of them stopped again when the test ends."""
    made = []

    def make(upload, monkeypatch, **kwargs):
        session = DeferringSession(**kwargs)
        made.append(session)
        monkeypatch.setattr(upload, "_session", lambda: session)
        monkeypatch.setattr(upload, "_write", session.write)
        return session

    yield make
    for session in made:
        session.stop()


def test_the_last_block_is_not_reported_sent_until_it_is_acknowledged(
    ruida, monkeypatch, deferring
):
    """
    The last block is the one that closes the file: `SET_FILE_SUM` and
    `END_OF_FILE` are in it. Waiting before each block means every block but that
    one is confirmed by the wait in front of the next; after the last one there
    is no next, so without a final wait `upload()` returns `{"chunks": 6}` on a
    file whose closing block the machine never took. That is the failure this
    whole module exists to prevent, with reassurance attached — the worst of the
    two.

    Measured on this setup before the final wait existed: the connection dies on
    the eighth packet (the sixth and last block), and `upload("BORD")` *returned*
    `{'chunks': 6}` — six of six, as a success — with
    `session.acknowledged` seven packets long, the last block among the missing.
    It now refuses instead, and this is also the case that fixes what the two
    numbers count.

    They count blocks handed to the line, so here they read six of six: every
    block has been written, including the one holding `SET_FILE_SUM` and
    `END_OF_FILE`. They used to read five of six at this point, on the reasoning
    that the sixth was not yet acknowledged — defensible, except that the
    sentence says "blocks" and not "acknowledged blocks", so it reported a
    number nothing had measured. The thing that *is* unknown here has a sentence
    of its own instead: the last block went out and nothing came back to say the
    machine took it, so the file may be whole and may be missing its end. Which
    is a different errand for whoever walks to the panel than "this file is
    incomplete, delete it".
    """
    a_design_over_one_block(ruida)
    upload = RuidaUpload(ruida)
    # Both the packet the line dies on and the numbers expected back are derived
    # from the frames, not counted out: how many blocks a drawing makes is a
    # property of the drawing (see `a_design_over_one_block`). The job is built
    # once and pinned, so the bytes measured here and the bytes `upload()` sends
    # are the same object. Two builds of one drawing do agree today — but a test
    # that leans on that fails, when it stops being true, by aiming
    # `stops_before` at the wrong packet and reading numbers it did not expect:
    # a red result pointing at the flow control for something that happened in
    # the building. There is nothing left here to compare.
    payload = upload.runner.build_job_bytes()
    monkeypatch.setattr(upload.runner, "build_job_bytes", lambda *a, **kw: payload)
    total = len(upload.frames("BORD", payload))
    blocks = total - 2
    assert blocks > 1, "the design fitted in one block after all"
    # The last packet is the last block: it goes out and is never acknowledged.
    session = deferring(upload, monkeypatch, stops_before=total - 1)
    upload.per_chunk_seconds = 0.5

    with pytest.raises(DesignError) as error:
        upload.upload("BORD")

    assert error.value.code == "upload.stalled"
    assert error.value.values == {"sent": blocks, "chunks": blocks}
    said = str(error.value)
    assert f"{blocks} of {blocks}" in said, said
    assert "not acknowledged" in said, said
    assert len(session.written) == total, "not every packet was handed over"
    assert len(session.acknowledged) == total - 1, (
        "the count of acknowledgements moved"
    )


def test_a_block_is_not_written_before_the_one_before_it_has_gone_out(
    ruida, monkeypatch, deferring
):
    """
    The flow control is per block, and only a count of packets in flight can
    say so.

    The wall clock cannot. The wait after the last block already forces the
    whole file to be acknowledged before `upload()` returns, so "wait before
    every block" and "wait once at the end" finish in the same time with the
    same number of acknowledgements. Measured, eight packets acknowledged at
    0.05 s each: **0.625 s and 8 of 8** with the wait in the loop, **0.481 s and
    8 of 8** with only the final wait. An earlier version of this test asserted
    on those two numbers and passed with the loop's wait removed — it was
    guarding half of what it is named after. (The 0.019 s in the round before
    that was measured on code with *neither* mechanism, which is why it looked
    like evidence.)

    What does separate them is how many packets are out at once — written and
    not yet acknowledged, read at the moment of each write. One block at a time
    means never more than one. Measured on the same two runs: **1** with the
    wait in the loop, **8** without it, and the send queue never deeper than
    those same numbers.

    So this runs both. The B half neutralises exactly the line under test — the
    first eight calls to `_wait_for_the_line` are the ones inside the loop, the
    ninth is the one after it — and requires the depth to blow out, because a
    test that cannot fail on the broken code is not evidence about the working
    code.
    """
    def upload_once(only_at_the_end):
        a_design_over_one_block(ruida)
        upload = RuidaUpload(ruida)
        session = deferring(upload, monkeypatch, ack_seconds=0.05)
        if only_at_the_end:
            real = upload._wait_for_the_line

            def only_after_the_last_write(session_arg, sent, chunks):
                # The wait after the loop is the one that runs when every packet
                # has already been written — two headers and `chunks` blocks.
                # Derived from the code under test rather than counted out to a
                # literal, because the number of blocks is a property of a
                # drawing (see `a_design_over_one_block`), not a constant.
                if len(session.written) == chunks + 2:
                    real(session_arg, sent, chunks)

            monkeypatch.setattr(
                upload, "_wait_for_the_line", only_after_the_last_write
            )
        result = upload.upload("BORD")
        return result, session

    result, session = upload_once(only_at_the_end=False)
    packets = result["chunks"] + 2
    assert result["chunks"] > 1, "the design fitted in one block after all"
    assert session.deepest == 1, (
        f"{session.deepest} packets were out at once; one block at a time means one"
    )
    assert session.deepest_queue == 1, session.deepest_queue
    assert len(session.acknowledged) == packets

    # And the same run with the loop's wait taken out, to show the assertion
    # above is about that wait and not about the one after the loop.
    _, without = upload_once(only_at_the_end=True)
    assert without.deepest == packets, (
        f"removing the wait inside the loop left the depth at {without.deepest}, "
        f"so the assertion above would not have caught its removal"
    )


def test_a_nameless_upload_says_so_before_it_says_anything_about_the_job(
    ruida, monkeypatch
):
    """
    Two things can be wrong at once, and the order of the sentences matters.

    A name of nothing but spaces on a design that builds no bytes used to answer
    `upload.emptyFile`, because the payload was built before `frames()` ever
    looked at the name. Both are refusals, but the name is the one the user can
    fix on the spot — the empty job is a design problem somewhere else. So the
    name is checked first, and the sentence the user gets back is the one they
    can act on.
    """
    a_rectangle(ruida)
    upload = RuidaUpload(ruida)
    session = a_fake_session(upload, monkeypatch)
    monkeypatch.setattr(upload.runner, "build_job_bytes", lambda *a, **kw: b"")

    with pytest.raises(DesignError) as error:
        upload.upload("  \t ")

    assert error.value.code == "upload.needsName"
    assert not session.written


def test_a_nameless_upload_never_asks_the_design_for_bytes(ruida, monkeypatch):
    """
    And it refuses before building, not after: `build_job_bytes` plans the whole
    job and runs it through a driver, which is seconds of work on a real design
    for an answer that was known from the argument.
    """
    a_rectangle(ruida)
    upload = RuidaUpload(ruida)
    a_fake_session(upload, monkeypatch)
    builds = []
    monkeypatch.setattr(
        upload.runner, "build_job_bytes", lambda *a, **kw: builds.append(True) or b"x"
    )

    with pytest.raises(DesignError):
        upload.upload("")

    assert not builds, "the job was built for an upload that could never be sent"


def test_on_usb_the_queue_alone_still_bounds_what_is_in_flight(
    ruida, monkeypatch, deferring
):
    """
    The `usb` branch, which is the one every run of this suite actually uses.

    `_ack_pending` is set only on `udp` (`ruidasession.py:349`), so on `usb`
    `is_busy` never says anything about our blocks and the send queue is all
    that is left. It still bounds what is out at once, but at two rather than
    one: the queue goes empty the moment the handshaker takes a packet, while
    that packet is still being written to the transport, so the next block can
    be queued behind one still in the engine's hands. Measured over six runs at
    two different write speeds, deepest **2** every time, with the queue itself
    never deeper than 1 — against **8** with the wait inside the loop removed.

    Two is the floor here, not a defect to fix: nothing in the engine marks the
    moment a `usb` write completes, so nobody outside it can wait for one.
    """
    def upload_once(only_at_the_end):
        a_design_over_one_block(ruida)
        upload = RuidaUpload(ruida)
        session = deferring(
            upload, monkeypatch, ack_seconds=0.02, acknowledges=False
        )
        if only_at_the_end:
            real = upload._wait_for_the_line

            def only_after_the_last_write(session_arg, sent, chunks):
                if len(session.written) == chunks + 2:
                    real(session_arg, sent, chunks)

            monkeypatch.setattr(
                upload, "_wait_for_the_line", only_after_the_last_write
            )
        return upload.upload("BORD"), session

    result, session = upload_once(only_at_the_end=False)
    packets = result["chunks"] + 2
    assert result["chunks"] > 1, "the design fitted in one block after all"
    assert session._ack_pending is False, "this was supposed to model usb"
    assert session.deepest == 2, session.deepest
    assert session.deepest_queue == 1, session.deepest_queue
    # Seven or eight, run to run: the last block can still be at the transport
    # when `upload()` returns, and on `usb` there is nothing to wait for that
    # would say otherwise. See the note at the final wait in `upload()`.
    assert len(session.acknowledged) >= packets - 1, len(session.acknowledged)

    _, without = upload_once(only_at_the_end=True)
    assert without.deepest == packets, (
        f"removing the wait inside the loop left the depth at {without.deepest}, "
        f"so the assertion above would not have caught its removal"
    )


def test_on_usb_a_connection_that_drops_on_the_last_block_still_refuses(
    ruida, monkeypatch, deferring
):
    """
    And the hole that branch had until this test was written.

    On `udp` a machine that goes away leaves `_ack_pending` set for ever, and
    the wait after the last block catches it. On `usb` there is no
    acknowledgement to be missing: the handshaker takes our last block, the
    transport write fails, and the queue is empty — so a wait that asks only
    "is anything still out?" sees a clear line and `upload()` *returns* on the
    block that closes the file. Measured before the `connected` check below
    existed: `{'chunks': 6}`, handed back as a success, with the last block never
    written through and the session already dropped. What it does now is refuse
    with those same two numbers — six blocks were handed to the line, which is
    what they count — and a sentence saying the last one was never acknowledged.

    What the engine does have is `_responding`: a failed transport write clears
    it (`ruidasession.py:346`), it is one of the three things `connected` is made
    of (`:154`), and every `write` after it raises (`:186`). So the wait asks
    that too, and asks it first, because a session that is not answering is a
    more specific answer than "it is taking too long". What the flag does *not*
    say is why — see
    `test_a_broken_transfer_says_what_was_seen_and_not_what_caused_it`, and the
    sentence it produces reports only what was seen.
    """
    a_design_over_one_block(ruida)
    upload = RuidaUpload(ruida)
    # Both the packet the line dies on and the numbers expected back are derived
    # from the frames, not counted out: how many blocks a drawing makes is a
    # property of the drawing (see `a_design_over_one_block`). The job is built
    # once and pinned, so the bytes measured here and the bytes `upload()` sends
    # are the same object. Two builds of one drawing do agree today — but a test
    # that leans on that fails, when it stops being true, by aiming
    # `stops_before` at the wrong packet and reading numbers it did not expect:
    # a red result pointing at the flow control for something that happened in
    # the building. There is nothing left here to compare.
    payload = upload.runner.build_job_bytes()
    monkeypatch.setattr(upload.runner, "build_job_bytes", lambda *a, **kw: payload)
    total = len(upload.frames("BORD", payload))
    blocks = total - 2
    session = deferring(
        upload,
        monkeypatch,
        ack_seconds=0.02,
        acknowledges=False,
        stops_before=total - 1,
    )
    upload.per_chunk_seconds = 0.5

    with pytest.raises(DesignError) as error:
        upload.upload("BORD")

    assert error.value.code == "upload.interrupted"
    assert error.value.values == {"sent": blocks, "chunks": blocks}
    assert f"{blocks} of {blocks}" in str(error.value), str(error.value)
    assert not session.connected


def test_a_broken_transfer_says_what_was_seen_and_not_what_caused_it(
    ruida, monkeypatch, deferring
):
    """
    `upload.interrupted` is raised off `session.connected`, and the flag under
    it does not carry a cause.

    `_responding` — one of the three things `connected` is made of
    (`ruidasession.py:154`) — is cleared in seven places, and only three of them
    are a broken link. `:366` is the ACK read running out of tries, which at
    `normal_timeout()` is four reads of 0.25 s: **about one second of silence**.
    The engine's own comment right above it (`:359-360`) says when that happens:
    "This will occur while the controller is executing a physical home." The
    handshaker then goes back to `connect()` and can set the flag to `True`
    again (`:258`), so the machine was never gone.

    A refusal that names a cause the flag cannot carry is worse than one that
    only reports what was seen: it sends somebody to check a cable while their
    machine was homing. So the sentence says the machine stopped answering,
    which is exactly what was observed on either story, and the advice — look at
    the panel, delete the file — is right on both.
    """
    a_design_over_one_block(ruida)
    upload = RuidaUpload(ruida)
    # Both the packet the line dies on and the numbers expected back are derived
    # from the frames, not counted out: how many blocks a drawing makes is a
    # property of the drawing (see `a_design_over_one_block`). The job is built
    # once and pinned, so the bytes measured here and the bytes `upload()` sends
    # are the same object. Two builds of one drawing do agree today — but a test
    # that leans on that fails, when it stops being true, by aiming
    # `stops_before` at the wrong packet and reading numbers it did not expect:
    # a red result pointing at the flow control for something that happened in
    # the building. There is nothing left here to compare.
    payload = upload.runner.build_job_bytes()
    monkeypatch.setattr(upload.runner, "build_job_bytes", lambda *a, **kw: payload)
    total = len(upload.frames("BORD", payload))
    blocks = total - 2
    session = deferring(
        upload,
        monkeypatch,
        ack_seconds=0.02,
        acknowledges=False,
        stops_before=total - 1,
    )
    upload.per_chunk_seconds = 0.5

    with pytest.raises(DesignError) as error:
        upload.upload("BORD")

    said = str(error.value)
    assert "stopped answering" in said, said
    assert "connection" not in said.lower(), said
    assert f"{blocks} of {blocks}" in said and "panel" in said, said


def a_server_with_a_fake_line(kernel, tmp_path, monkeypatch, **kwargs):
    """An `ApiServer` whose upload writes into a `FakeSession`, not onto a line.

    The same two patches `a_fake_session` makes, on the server's own
    `RuidaUpload` — which is the object the route reaches, and which was built
    with the live kernel. Patching one of the two would leave `_write` pointed
    at `device.driver.controller.write`, the live controller of the device the
    fixture started: a path toward a machine, opened by a test about a route.
    """
    from openkerf_api.server import ApiServer

    server = ApiServer(kernel, library_path=tmp_path / "u.db")
    session = a_fake_session(server.ruida_upload, monkeypatch, **kwargs)
    return server, session


def test_the_route_refuses_without_a_connection(kernel, tmp_path):
    """A route that says nothing about a missing connection sends you to a dead panel.

    (The brief's own test, with its sentence in the source language: every other
    docstring in this file is English, and CLAUDE.md says that is where it
    starts. Nothing about what the test asserts has changed.)
    """
    from fastapi.testclient import TestClient

    from openkerf_api.server import ApiServer

    kernel.console("service device start ruida -i\n")
    server = ApiServer(kernel, library_path=tmp_path / "u.db")
    with TestClient(server.build_app()) as client:
        client.post("/api/design/elements", json={
            "type": "rect", "x_mm": 20, "y_mm": 20, "width_mm": 40, "height_mm": 30,
        })

        response = client.post("/api/machine/upload", json={"name": "BORD"})

        assert response.status_code == 409
        assert "connection" in response.json()["detail"].lower()
        assert response.headers["X-OpenKerf-Error"] == "upload.notConnected"


def test_the_route_answers_with_the_name_the_panel_will_show(
    ruida, tmp_path, monkeypatch
):
    """
    What comes back is what stands on the machine, not what was typed.

    `machine_name` cuts to eight capitals and drops the space, so a client that
    echoed its own input would tell the user to look for a file that is not
    there. The route hands `upload()`'s answer through unchanged; this is the
    test that says so from outside.
    """
    from fastapi.testclient import TestClient

    a_rectangle(ruida)
    server, session = a_server_with_a_fake_line(ruida, tmp_path, monkeypatch)
    with TestClient(server.build_app()) as client:
        response = client.post("/api/machine/upload", json={"name": "my box 12345"})

    assert response.status_code == 200, response.text
    answer = response.json()
    assert answer["name"] == "MYBOX123"
    assert answer["chunks"] == len(session.written) - 2
    assert answer["bytes"] == sum(len(block) for block in session.written[2:])


def test_the_route_puts_the_file_there_and_starts_nothing(
    ruida, tmp_path, monkeypatch
):
    """
    The one difference between this button and the one that burns.

    Starting is done on the machine's own panel; nothing this route does may
    reach the queue the live device's thread executes. Measured from outside the
    module, because the route is where a second path to the spooler would be
    added — `manage(self.ruida_upload.upload, ...)` and nothing else beside it.
    """
    from fastapi.testclient import TestClient

    a_rectangle(ruida)
    server, _ = a_server_with_a_fake_line(ruida, tmp_path, monkeypatch)
    with TestClient(server.build_app()) as client:
        response = client.post("/api/machine/upload", json={"name": "BORD"})

    assert response.status_code == 200, response.text
    assert not list(ruida.device.spooler.queue), "a job was spooled by the route"


def test_the_route_refuses_a_nameless_upload(ruida, tmp_path, monkeypatch):
    """
    A body with no name is a refusal the caller can act on, not a 500.

    `str(body.get("name") or "")` makes `{}`, `{"name": null}` and `{"name": "
    "}` one case, and `_checked_name` answers it before the job is built.
    """
    from fastapi.testclient import TestClient

    a_rectangle(ruida)
    server, session = a_server_with_a_fake_line(ruida, tmp_path, monkeypatch)
    with TestClient(server.build_app()) as client:
        response = client.post("/api/machine/upload", json={})

    assert response.status_code == 409, response.text
    assert response.headers["X-OpenKerf-Error"] == "upload.needsName"
    assert not session.written, "a nameless upload announced a file anyway"


def test_the_numbers_of_a_half_upload_reach_the_client(
    ruida, tmp_path, monkeypatch
):
    """
    Half a file on the machine has to say how far it got, in the reader's own
    language — so the two numbers travel beside the code, in
    `X-OpenKerf-Error-Values`, and not only inside the English sentence.

    Measured on this rectangle, whose job is one block: with the line busy for
    ever, the stall is at the first packet and the answer is
    `{"sent": 0, "chunks": 1}`. `sent` is 0 and not 1 because the wait that fails
    is the one *in front of* the first block — nothing has gone out, which is
    what the sentence says. The block count is read off the frames rather than
    written down here; how many blocks a drawing makes is a property of the
    drawing.
    """
    import json

    from fastapi.testclient import TestClient

    a_rectangle(ruida)
    server, _ = a_server_with_a_fake_line(
        ruida, tmp_path, monkeypatch, busy_forever=True
    )
    upload = server.ruida_upload
    upload.per_chunk_seconds = 0.2
    blocks = len(upload.frames("BORD", upload.runner.build_job_bytes())) - 2
    with TestClient(server.build_app()) as client:
        response = client.post("/api/machine/upload", json={"name": "BORD"})

    assert response.status_code == 409, response.text
    assert response.headers["X-OpenKerf-Error"] == "upload.stalled"
    values = json.loads(response.headers["X-OpenKerf-Error-Values"])
    assert values == {"sent": 0, "chunks": blocks}


class _BurningSpooler:
    """A spooler with a job that says it is running.

    `is_running()` and a `queue` is the whole of what `a_job_is_running` reads —
    the same two things `MachineControl._idle()` read before it was the one
    reader. Nothing here burns, spools or reaches a device: it is a list with an
    object in it, put where the kernel's device keeps its spooler.
    """

    class _Job:
        def is_running(self):
            return True

    def __init__(self):
        self.queue = [self._Job()]


def test_an_upload_while_a_job_is_burning_is_refused(ruida, monkeypatch):
    """
    The same rule as moving the head, for the same reason, one module along.

    `MachineControl._idle()` refuses to move while a job runs because "the UI is
    advice: a second tab, a phone or a curl command can go straight through it".
    Our blocks go down `controller.write` -> `active_session.write` -> the very
    `send_q` the burning job is streaming through, so the argument is not
    weaker here; it is the same connection.

    `_line_is_busy` does not cover it and cannot: `_data_sender`
    (`ruida/controller.py:119`) empties that queue in one go, and the machine
    goes on burning for minutes afterwards. An empty queue is not a quiet
    machine.

    What the two streams do to each other was measured against the engine's own
    emulator — a burn of 5463 bytes with the whole upload conversation dropped in
    halfway lands in **one** `RDJob`, with `program_mode` already `False` in the
    middle of the burn and **0** parse failures to show for it. The numbers, and
    the part of it that stays an assumption, are at the check itself in
    `ruida_upload.py`.

    Checked before `_session()` and therefore before the job is built, so a
    refusal costs a sentence and not a plan.
    """
    a_rectangle(ruida)
    upload = RuidaUpload(ruida)
    session = a_fake_session(upload, monkeypatch)
    monkeypatch.setattr(ruida.device, "spooler", _BurningSpooler(), raising=False)

    with pytest.raises(DesignError) as error:
        upload.upload("BORD")

    assert error.value.code == "upload.whileBurning"
    assert "nothing has been sent" in str(error.value).lower()
    assert not session.written, "blocks went out while the machine was burning"


def test_the_route_refuses_an_upload_while_a_job_is_burning(
    ruida, tmp_path, monkeypatch
):
    """
    And from outside, because that is where the second tab is.

    A greyed-out button is not the guard; this is.
    """
    from fastapi.testclient import TestClient

    a_rectangle(ruida)
    server, session = a_server_with_a_fake_line(ruida, tmp_path, monkeypatch)
    monkeypatch.setattr(ruida.device, "spooler", _BurningSpooler(), raising=False)
    with TestClient(server.build_app()) as client:
        response = client.post("/api/machine/upload", json={"name": "BORD"})

    assert response.status_code == 409, response.text
    assert response.headers["X-OpenKerf-Error"] == "upload.whileBurning"
    assert not session.written


def test_a_second_upload_at_the_same_time_is_refused(ruida, monkeypatch):
    """
    Two POSTs at once — a double-click, a second tab — over one session.

    `machine_upload` is a plain `def`, so FastAPI runs it in the threadpool and
    two calls really do overlap. Building is serialised by `claim_plan()`'s
    RLock, but the *sending* was not: the blocks of two files would go out
    interleaved down one session and both calls would answer 200, leaving one
    file in the machine's memory made of two jobs.

    Held here at the first packet rather than by timing: the first upload's
    `_write` blocks until this test lets it go, which is the window a second
    call would otherwise walk into.

    Measured with no lock, two `upload()` calls over one session on this
    rectangle: both returned a result — `{'name': 'EEN', 'bytes': 433,
    'chunks': 1}` and the same for `TWEE` — and the line saw six packets in the
    order `E8 02, E8 02, E7 01, E7 01, D8 10, D8 10`. Two transfers begun, two
    names, and then both files' blocks: not two files but one, made of two jobs,
    with two 200s telling the user both went fine.
    """
    a_rectangle(ruida)
    upload = RuidaUpload(ruida)
    session = a_fake_session(upload, monkeypatch)
    at_the_first_packet = threading.Event()
    let_it_go = threading.Event()
    straight_to_the_session = upload._write

    def held(data):
        at_the_first_packet.set()
        let_it_go.wait(5)
        straight_to_the_session(data)

    monkeypatch.setattr(upload, "_write", held)
    first = {}

    def send_the_first():
        try:
            first["result"] = upload.upload("EEN")
        except Exception as e:  # pragma: no cover - reported through `first`
            first["error"] = e

    sender = threading.Thread(target=send_the_first, daemon=True)
    sender.start()
    assert at_the_first_packet.wait(10), "the first upload never reached the line"

    try:
        with pytest.raises(DesignError) as error:
            upload.upload("TWEE")
    finally:
        let_it_go.set()
        sender.join(timeout=10)

    assert error.value.code == "upload.busy"
    assert "nothing has been sent" in str(error.value).lower()
    assert first.get("result"), first
    assert len(session.written) == first["result"]["chunks"] + 2, (
        "packets of a second file went out over the same session"
    )


def test_a_stall_partway_says_the_file_is_incomplete(ruida, monkeypatch, deferring):
    """
    The middle case, and the only one where "delete it on the panel" is right.

    Zero blocks out is
    `test_a_transfer_that_stalls_says_how_far_it_got` (nothing announced,
    nothing to delete); every block out is
    `test_the_last_block_is_not_reported_sent_until_it_is_acknowledged` (whole
    file out, no word back). In between the machine holds a file that stops in
    the middle of the job, and that is the one somebody has to go and remove
    before pressing start on it.

    Stopped after three acknowledgements rather than by timing, so which wait
    fails is fixed: the fourth packet is taken and never acknowledged, and
    `_line_is_busy` reads the queue first, so it says busy from the moment the
    block is handed over whether or not the handshaker has got to it yet.
    Measured on these eight circles: `{"sent": 2, "chunks": 6}` — the two blocks
    behind the two headers.
    """
    a_design_over_one_block(ruida)
    upload = RuidaUpload(ruida)
    payload = upload.runner.build_job_bytes()
    monkeypatch.setattr(upload.runner, "build_job_bytes", lambda *a, **kw: payload)
    blocks = len(upload.frames("BORD", payload)) - 2
    assert blocks > 2, "the design left no room for a stall in the middle"
    deferring(upload, monkeypatch, stops_before=3)
    upload.per_chunk_seconds = 0.5

    with pytest.raises(DesignError) as error:
        upload.upload("BORD")

    said = str(error.value)
    sent = error.value.values["sent"]
    assert error.value.code == "upload.stalled"
    assert 0 < sent < blocks, error.value.values
    assert f"{sent} of {blocks}" in said, said
    assert "incomplete" in said.lower() and "delete" in said.lower(), said


def test_a_nameless_body_still_gets_no_further_than_the_connection(
    ruida, tmp_path, monkeypatch
):
    """
    Which guard a body with no name actually meets, measured rather than assumed.

    `test_write_actions.py` calls this route with `{}` to prove the token gate
    holds, and its comment has to say what would happen if the gate were gone.
    The answer is not the name: `_upload()` asks for a live session before it
    looks at the name at all, so on a machine that has never been connected the
    code is `upload.notConnected`, and with no device `upload.noMachine`. Either
    way nothing is built and nothing goes out, which is what that comment is
    really claiming — but a comment that names the wrong guard is one somebody
    reads a safety argument out of later.

    Deliberately not `a_server_with_a_fake_line`: the point is the *real*
    `_session()`, on the `-i` service that has no session.
    """
    from fastapi.testclient import TestClient

    a_rectangle(ruida)
    from openkerf_api.server import ApiServer

    server = ApiServer(ruida, library_path=tmp_path / "u.db")
    with TestClient(server.build_app()) as client:
        response = client.post("/api/machine/upload", json={})

    assert response.status_code == 409, response.text
    assert response.headers["X-OpenKerf-Error"] == "upload.notConnected"


class _NoMachine:
    """A kernel with no active device, and nothing else about it changed.

    `_device()` reads `kernel.device` and this has none, which is the whole of
    what `upload.noMachine` is about. Standing a bare object in front of the
    upload rather than blanking the live kernel's `device`: that attribute is
    read by the status reader, the event bridge and the engine's own threads, and
    setting it to `None` under a running service hangs the test run — measured,
    the case never finished and had to be killed. A test about a missing machine
    has no business stopping the machinery around it.
    """


def _no_machine(server, session, monkeypatch):
    upload = server.ruida_upload
    # The real `_session()` back first, because `_device()` is what raises this
    # and the fake line replaces the whole path to it — with `_session` patched,
    # this case would have passed through to a *connected* line and proved
    # nothing. `_write` stays on the fake, so there is still no way out to a
    # machine; there is simply nothing here to write to.
    monkeypatch.setattr(upload, "_session", type(upload)._session.__get__(upload))
    monkeypatch.setattr(upload, "kernel", _NoMachine())


def _an_empty_job(server, session, monkeypatch):
    monkeypatch.setattr(
        server.ruida_upload.runner, "build_job_bytes", lambda *a, **kw: b""
    )


def _one_command_over_a_block(server, session, monkeypatch):
    # A single command of 1201 bytes: one byte >= 0x80 and 1200 that are not, so
    # `parse_commands` gives one command and `_blocks` cannot cut it. Measured in
    # `test_a_command_longer_than_a_block_refuses_before_anything_goes_out`.
    monkeypatch.setattr(
        server.ruida_upload.runner,
        "build_job_bytes",
        lambda *a, **kw: b"\x88" + b"\x11" * 1200,
    )


def _a_line_that_breaks_on_the_first_write(server, session, monkeypatch):
    session.fail_after = 0


def _an_upload_already_running(server, session, monkeypatch):
    """Hold the lock the way a first upload holds it, and hand back the release.

    Returned rather than released here, so it happens in the test's `finally`: a
    lock left held would refuse every upload after it for the life of that
    server.
    """
    server.ruida_upload._sending.acquire()
    return server.ruida_upload._sending.release


def _nothing_on_the_bed(server, session, monkeypatch):
    server.kernel.elements.clear_all()


@pytest.mark.parametrize(
    "arrange, code, values",
    [
        (_no_machine, "upload.noMachine", None),
        (_an_empty_job, "upload.emptyFile", None),
        (
            _one_command_over_a_block,
            "upload.commandTooLong",
            {"block": 1201, "limit": CHUNK},
        ),
        (
            _a_line_that_breaks_on_the_first_write,
            "upload.interrupted",
            {"sent": 0, "chunks": 1},
        ),
        (_an_upload_already_running, "upload.busy", None),
        (_nothing_on_the_bed, "job.nothingToBurn", None),
    ],
)
def test_every_refusal_travels_out_through_the_route(
    ruida, tmp_path, monkeypatch, arrange, code, values
):
    """
    Every code this route can answer with, seen coming out of the route.

    Four of them already had a test of their own from outside
    (`notConnected`, `needsName`, `stalled`, `whileBurning`); these are the rest
    of what `ruida_upload.py` and `build_job_bytes` raise, and each is arranged
    for real rather than by making `upload()` throw. That matters most for
    `commandTooLong`, the second code that carries numbers: a refusal whose
    `values` never leave the module is a sentence the panel cannot say in the
    reader's language, and nothing until now proved they leave.

    `upload.notRuida` is the one code missing here, because this fixture's
    machine *is* a Ruida — it has a test beside this one.
    """
    import json

    from fastapi.testclient import TestClient

    a_rectangle(ruida)
    server, session = a_server_with_a_fake_line(ruida, tmp_path, monkeypatch)
    undo = arrange(server, session, monkeypatch)
    try:
        with TestClient(server.build_app()) as client:
            response = client.post("/api/machine/upload", json={"name": "BORD"})
    finally:
        if undo is not None:
            undo()

    assert response.status_code == 409, response.text
    assert response.headers["X-OpenKerf-Error"] == code
    assert response.json()["detail"].endswith("."), response.json()["detail"]
    if values is None:
        assert "X-OpenKerf-Error-Values" not in response.headers
    else:
        assert json.loads(response.headers["X-OpenKerf-Error-Values"]) == values
    assert not session.written, "bytes went out on a refusal"


def test_a_non_ruida_machine_refuses_through_the_route(kernel, tmp_path, monkeypatch):
    """
    The last of the codes, on the only machine that can raise it.

    The plain `kernel` fixture's device is the dummy from `conftest.py`, which
    keeps no `RDJob`. The fake line gets `upload()` past `_session()` so the
    refusal comes from `build_job_bytes`, where it belongs, rather than from the
    connection check in front of it.
    """
    from fastapi.testclient import TestClient

    a_rectangle(kernel)
    server, session = a_server_with_a_fake_line(kernel, tmp_path, monkeypatch)
    with TestClient(server.build_app()) as client:
        response = client.post("/api/machine/upload", json={"name": "BORD"})

    assert response.status_code == 409, response.text
    assert response.headers["X-OpenKerf-Error"] == "upload.notRuida"
    assert not session.written
