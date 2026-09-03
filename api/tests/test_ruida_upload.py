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
    (`ruida/emulator.py:160`) — the spooler of the live Ruida device this fixture
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

    class _InertSpooler:
        """Takes jobs and runs none. See the docstring."""

        def __init__(self):
            self.jobs = []

        def send(self, job, prevent_duplicate=False):
            self.jobs.append(job)

    class _RecordingDriver:
        """Answers to anything and does nothing, so a motion command shows up as
        a name in `calls` instead of as a move."""

        def __init__(self):
            self.calls = []

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
    emulator = RuidaEmulator(ruida.device, ruida.device.view.matrix)
    emulator.channel = said.append
    monkeypatch.setattr(
        emulator, "device", _StandInDevice(ruida.device, spooler, driver)
    )
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
