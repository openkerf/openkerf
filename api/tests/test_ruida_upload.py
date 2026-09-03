"""
Een job als bestand: de bytes, het gesprek en wat er misgaat.

Nooit tegen een laser. De end-to-end-toets praat tegen de Ruida-emulator van de
engine zelf, die dit gesprek aanneemt en het bestand wegschrijft.
"""

import pytest

from openkerf_api.commands import CommandRunner
from openkerf_api.edits import DesignError


@pytest.fixture
def ruida(kernel):
    """Een echte Ruida-service, zoals test_machine_connect die ook maakt."""
    kernel.console("service device start ruida -i\n")
    return kernel


def a_rectangle(kernel):
    """Iets om te branden: één rechthoek in een snijlaag."""
    kernel.console("rect 20mm 20mm 40mm 30mm\n")
    kernel.console("operation* delete\n")
    kernel.console("op cut\n")
    kernel.console("element* classify\n")


def test_the_job_becomes_bytes_that_end_like_a_file(ruida):
    """
    `save_job` in de engine schrijft 4 bytes en laat 623 in de buffer staan
    (gemeten, zie CLAUDE.md). Wij halen ze uit de buffer, en dan hoort er een
    compleet bestand uit te komen: het eindigt op SET_FILE_SUM gevolgd door
    END_OF_FILE.
    """
    a_rectangle(ruida)
    runner = CommandRunner(ruida)

    data = runner.build_job_bytes()

    assert len(data) > 100, f"only {len(data)} bytes — the buffer was not drained"
    # `\xD7` is END_OF_FILE; `\xCC` staat er niet in dit stadium.
    assert data.endswith(b"\xd7"), data[-8:].hex(" ")
    # SET_FILE_SUM staat er vlak voor. Let op: dat is `E5 05`
    # (`meerk40t/ruida/rdjob.py:173`), niet D8 11 — het plan had het mis en de
    # controller heeft dat vóór de uitvoering rechtgezet.
    assert b"\xe5\x05" in data[-16:], data[-16:].hex(" ")


def test_building_the_bytes_does_not_spool_anything(ruida):
    """
    Bouwen is niet branden. Wie deze route aanroept mag geen job in de wachtrij
    krijgen — dat is het hele verschil met `start_job`.
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
