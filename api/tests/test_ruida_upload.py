"""
A job as a file: the bytes, the conversation, and what goes wrong.

Never against a laser. The end-to-end test talks to the engine's own Ruida
emulator, which accepts this conversation and writes the file out.
"""

import threading
import time

import pytest

from openkerf_api.commands import CommandRunner, _AlwaysConnected
from openkerf_api.edits import DesignError


@pytest.fixture
def ruida(kernel):
    """A real Ruida service, the way test_machine_connect also makes one."""
    kernel.console("service device start ruida -i\n")
    return kernel


def a_rectangle(kernel):
    """Something to burn: one rectangle in a cut layer."""
    kernel.console("rect 20mm 20mm 40mm 30mm\n")
    kernel.console("operation* delete\n")
    kernel.console("op cut\n")
    kernel.console("element* classify\n")


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
    not busy (`:172`, `:189`). Before `_AlwaysConnected` existed, a
    `build_job_bytes` driver on this same test kernel took that branch: measured,
    10 calls in the four seconds after the sleep ended (isolated from the live
    driver's own identical thread, which does the same thing independently of
    this feature — see CLAUDE.md's row on the Ruida's connection lifecycle).
    With `_AlwaysConnected`: 0.

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


def test_three_builds_of_the_same_design_are_byte_identical(ruida):
    """
    Reusing the driver reuses its state as well as its controller.
    `RuidaDriver.__init__` sets `power_dirty`/`speed_dirty` true
    (`ruida/driver.py:51,55`); `_move` (`:555-559`) writes `speed_laser_1` and the
    min/max power once and then sets both false. On a driver kept around across
    calls, only the first build ever wrote them again — measured, on this same
    rectangle, this same runner, before `_reset_upload_driver_state` existed:
    `433, 418, 418` bytes, the second and third missing exactly `SPEED_LASER_1`
    (`c9 02 00 00 00 4e 10`) and the min/max power pair (`c6 02 7f 7f`/
    `c6 01 7f 7f`). `CommandRunner` lives for the life of an `ApiServer`
    (`server.py:273`), so only the first upload of a session would have been
    right. With the reset: `433, 433, 433` — verified by hand against the code
    before this fix by disabling the reset call (see the fix-4 report).

    The thread tests (above) count threads; this is the gap they left — a thread
    count says nothing about what ended up in the file.
    """
    a_rectangle(ruida)
    runner = CommandRunner(ruida)

    first = runner.build_job_bytes()
    second = runner.build_job_bytes()
    third = runner.build_job_bytes()

    lengths = (len(first), len(second), len(third))
    assert first == second == third, f"lengths {lengths}, not identical"
