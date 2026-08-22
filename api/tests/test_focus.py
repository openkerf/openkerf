"""
A focus test: the same mark burned at a series of heights.

Two things are worth pinning down here, and neither is the arithmetic of a spread.

The first is the gate. A focus board on a machine whose Z the software cannot move
burns every mark at the same height — ten identical lines that look like an answer.
So it is refused, in words, and the interface does not offer it there.

The second is the seam. The engine cannot carry a height per layer, so the board
puts its offsets in the plan as `z_move` console steps, and those have to be
*relative* differences in the right order, with the head brought back to where it
started at the end. Get that wrong and the mistake is on the workpiece.
"""

from functools import partial

import pytest
from fastapi.testclient import TestClient
from meerk40t.core.node.util_console import ConsoleOperation
from meerk40t.kernel import Kernel

from openkerf_api.commands import CommandRunner
from openkerf_api.edits import DesignError
from openkerf_api.focus import MAX_MARKS, SPAN_LIMIT_MM, plan_focus
from openkerf_api.server import ApiServer


def _grbl_kernel(z_axis: bool):
    """A kernel with a GRBL device: the only driver in the engine with a Z axis."""
    kernel = Kernel("MeerK40t", "0.0.0-testing", "OpenKerf_F", ansi=False, ignore_settings=True)
    from meerk40t.core import core, svg_io
    from meerk40t.device import basedevice, dummydevice
    from meerk40t.extra import coolant, hershey
    from meerk40t.fill import fills
    from meerk40t.grbl import plugin as grbldevice
    from meerk40t.image import imagetools
    from meerk40t.network import kernelserver

    for module in (
        kernelserver,
        basedevice,
        dummydevice,
        core,
        imagetools,
        fills,
        coolant,
        hershey,
        svg_io,
        grbldevice,
    ):
        kernel.add_plugin(module.plugin)
    kernel(partial=True)
    kernel.console("service device start grbl -i\n")
    kernel.device.supports_z_axis = z_axis
    return kernel


@pytest.fixture
def grbl():
    kernel = _grbl_kernel(z_axis=True)
    yield kernel
    kernel()


@pytest.fixture
def flat():
    """A machine without a movable Z — a Ruida, or a diode on a fixed frame."""
    kernel = _grbl_kernel(z_axis=False)
    yield kernel
    kernel()


def client_for(kernel, tmp_path):
    return TestClient(ApiServer(kernel, library_path=tmp_path / "f.db").build_app())


# ----------------------------------------------------------------- the planning


def test_the_marks_run_from_one_end_to_the_other():
    plan = plan_focus(z_from_mm=-2, z_to_mm=2, marks=5)

    assert [mark["z_mm"] for mark in plan["positions"]] == [-2.0, -1.0, 0.0, 1.0, 2.0]
    assert plan["step_mm"] == 1.0


def test_the_ends_may_be_given_the_other_way_round():
    """Nobody should have to think about which of the two numbers is the smaller."""
    plan = plan_focus(z_from_mm=3, z_to_mm=-3, marks=3)

    assert [mark["z_mm"] for mark in plan["positions"]] == [-3.0, 0.0, 3.0]


def test_the_labels_say_which_way_the_head_went():
    """
    A board of ten identical lines is only readable by its numbers, and a bare "2" does
    not say whether that is up or down. The sign does.
    """
    plan = plan_focus(z_from_mm=-1, z_to_mm=1, marks=3)

    assert [mark["label"] for mark in plan["positions"]] == ["-1", "0", "+1"]


def test_the_marks_are_spaced_by_the_gap():
    plan = plan_focus(z_from_mm=-1, z_to_mm=1, marks=3, x_mm=20, gap_mm=6)

    assert [mark["x_mm"] for mark in plan["positions"]] == [20.0, 26.0, 32.0]


def test_one_mark_is_refused():
    with pytest.raises(DesignError) as refusal:
        plan_focus(marks=1)
    assert refusal.value.code == "focus.tooFewMarks"


def test_a_sweep_that_does_not_sweep_is_refused():
    """Both ends the same is the mistake you make by leaving a field at its default."""
    with pytest.raises(DesignError) as refusal:
        plan_focus(z_from_mm=1, z_to_mm=1, marks=5)
    assert refusal.value.code == "focus.noSweep"


def test_a_sweep_further_than_the_head_should_travel_is_refused():
    with pytest.raises(DesignError) as refusal:
        plan_focus(z_from_mm=0, z_to_mm=SPAN_LIMIT_MM + 5, marks=5)
    assert refusal.value.code == "focus.spanTooBig"


def test_steps_smaller_than_you_can_see_are_refused():
    """
    30 marks over a tenth of a millimetre is a board that cannot answer its own
    question, and you only find that out after burning it.
    """
    with pytest.raises(DesignError) as refusal:
        plan_focus(z_from_mm=0, z_to_mm=0.1, marks=MAX_MARKS)
    assert refusal.value.code == "focus.stepTooSmall"


def test_more_marks_than_fit_on_a_readable_board_are_refused():
    with pytest.raises(DesignError) as refusal:
        plan_focus(marks=MAX_MARKS + 1)
    assert refusal.value.code == "focus.tooManyMarks"


def test_the_labels_shrink_to_fit_their_own_gap():
    """
    Numbers wider than the space between two marks overlap, and overlapping numbers on
    a board whose whole purpose is reading numbers is worse than smaller ones.
    """
    wide = plan_focus(z_from_mm=-2, z_to_mm=2, marks=5, gap_mm=12)
    tight = plan_focus(z_from_mm=-6, z_to_mm=6, marks=5, gap_mm=3)

    assert tight["label_height_mm"] < wide["label_height_mm"]


# --------------------------------------------------------------------- the gate


def test_a_machine_with_a_z_axis_may_burn_a_board(grbl, tmp_path):
    with client_for(grbl, tmp_path) as client:
        made = client.post("/api/design/generate/focus", json={"marks": 4})

        assert made.status_code == 201, made.text
        assert len(made.json()["drawn"]) == 4


def test_a_machine_without_a_z_axis_is_refused_in_words(flat, tmp_path):
    with client_for(flat, tmp_path) as client:
        refused = client.post("/api/design/generate/focus", json={"marks": 4})

        assert refused.status_code == 409
        assert refused.headers.get("X-OpenKerf-Error") == "focus.noZAxis"
        assert "Z axis" in refused.json()["detail"]


def test_the_same_flag_gates_the_board_and_the_step_per_pass(grbl, flat, tmp_path):
    """
    One question, one answer: the interface hides the tab on the same flag that hides
    the drop per pass, so a machine cannot end up offering one and refusing the other.
    """
    with client_for(grbl, tmp_path) as client:
        assert client.get("/api/design/capabilities").json()["z_step"] is True
    with client_for(flat, tmp_path / "second") as client:
        assert client.get("/api/design/capabilities").json()["z_step"] is False


# ------------------------------------------------------------------- the board


def test_every_mark_gets_a_layer_of_its_own_with_its_height_on_it(grbl, tmp_path):
    """
    One layer per mark is not tidiness: it is the only place a height can live. All the
    passes of one layer share a settings dict, so two heights in one layer is not a
    thing the engine can hold.
    """
    with client_for(grbl, tmp_path) as client:
        made = client.post(
            "/api/design/generate/focus",
            json={"z_from_mm": -1, "z_to_mm": 1, "marks": 3},
        ).json()

        # By the ids this board reports, not by everything the tree holds: the engine
        # reads the layer list of the previous session out of `operations.cfg`, keyed on
        # the kernel name and not on the profile (see CLAUDE.md), so `ops()` can hold
        # layers this test never made.
        by_id = {op.id: op for op in grbl.elements.ops()}
        offsets = [by_id[entry["operation_id"]].focus_z_mm for entry in made["drawn"]]
        assert offsets == [-1.0, 0.0, 1.0]


def test_the_board_is_one_thing_you_can_drag(grbl, tmp_path):
    with client_for(grbl, tmp_path) as client:
        made = client.post("/api/design/generate/focus", json={"marks": 3}).json()

        assert made["group_id"], "the marks were left loose on the bed"


def test_the_numbers_are_burned_beside_the_marks(grbl, tmp_path):
    with client_for(grbl, tmp_path) as client:
        client.post("/api/design/generate/focus", json={"marks": 3, "text": True})

        design = client.get("/api/design").json()
        # Three marks plus three labels; the labels are paths, because vector text is
        # the only text a headless engine can burn.
        assert len(design["elements"]) >= 6


def test_a_board_without_numbers_is_only_the_marks(grbl, tmp_path):
    with client_for(grbl, tmp_path) as client:
        client.post("/api/design/generate/focus", json={"marks": 3, "text": False})

        assert len(client.get("/api/design").json()["elements"]) == 3


def test_the_board_is_refused_when_it_falls_off_the_bed(grbl, tmp_path):
    with client_for(grbl, tmp_path) as client:
        refused = client.post(
            "/api/design/generate/focus",
            json={"marks": 20, "gap_mm": 60, "x_mm": 10},
        )

        assert refused.status_code == 409
        assert refused.headers.get("X-OpenKerf-Error") == "focus.offBed"


def test_the_preview_makes_nothing(grbl, tmp_path):
    """The same preview route as every other generator, so the form needs no special case."""
    with client_for(grbl, tmp_path) as client:
        looked = client.post(
            "/api/design/generate/preview", json={"what": "focus", "marks": 5}
        )

        assert looked.status_code == 200, looked.text
        assert len(looked.json()["parts"]) == 5
        assert client.get("/api/design").json()["elements"] == []


def test_the_preview_puts_the_marks_where_the_board_puts_them(grbl, tmp_path):
    """
    One sum for the picture and for the wood. Kept apart, the preview could show a
    spacing the board does not use, and you would only see it on material.
    """
    with client_for(grbl, tmp_path) as client:
        looked = client.post(
            "/api/design/generate/preview",
            json={"what": "focus", "marks": 3, "gap_mm": 7, "x_mm": 20},
        ).json()

        assert [part["x"] for part in looked["parts"]] == [20.0, 27.0, 34.0]


# ------------------------------------------------------- the heights in the plan


class Layer:
    """A plan step with just enough on it to test the build-up."""

    def __init__(self, focus_z_mm=None, passes=1):
        self.focus_z_mm = focus_z_mm
        self.passes = passes
        self.passes_custom = False


def commands_of(steps):
    return [step.command for step in steps if isinstance(step, ConsoleOperation)]


def test_an_ordinary_job_is_left_untouched():
    """Every job goes through this, so a job without a focus board must not change."""
    step = Layer()

    assert CommandRunner._with_focus_moves([step], ConsoleOperation) == [step]


def test_the_moves_are_the_differences_and_not_the_offsets():
    """
    `z_move` is a relative move. Sending the offsets themselves would take the head
    -1, then -0.5 further, then 0.5 further: a sweep that walks away from the work
    instead of through it.
    """
    steps = [Layer(-1.0), Layer(-0.5), Layer(0.0), Layer(0.5)]

    out = CommandRunner._with_focus_moves(steps, ConsoleOperation)

    assert commands_of(out) == [
        "z_move -1.000mm",
        "z_move 0.500mm",
        "z_move 0.500mm",
        "z_move 0.500mm",
        "z_move -0.500mm",
    ]


def test_the_head_comes_back_to_the_height_it_started_at():
    """
    Otherwise the next job on the same sheet burns at the height of the last mark, and
    nothing on the screen says so.
    """
    steps = [Layer(0.0), Layer(2.0)]

    out = CommandRunner._with_focus_moves(steps, ConsoleOperation)

    assert commands_of(out)[-1] == "z_move -2.000mm"


def test_a_move_comes_before_the_layer_it_belongs_to():
    steps = [Layer(1.0)]

    out = CommandRunner._with_focus_moves(steps, ConsoleOperation)

    assert isinstance(out[0], ConsoleOperation)
    assert out[1] is steps[0]


def test_a_layer_that_repeats_does_not_get_a_move_of_nothing():
    """
    A layer unfolded into passes stands in the list several times. A `z_move 0mm`
    between the copies is a command for nothing, and on a Ruida-sized job list every
    such command is a line in the file.
    """
    layer = Layer(1.0)
    steps = [layer, layer, layer]

    out = CommandRunner._with_focus_moves(steps, ConsoleOperation)

    assert commands_of(out) == ["z_move 1.000mm", "z_move -1.000mm"]


def test_the_plan_of_a_real_board_carries_its_heights(grbl, tmp_path):
    """
    The whole seam in one go: draw a board, build the plan, and read the console steps
    out of it. This is the test that would have caught the moves being absolute.
    """
    with client_for(grbl, tmp_path) as client:
        client.post(
            "/api/design/generate/focus",
            json={"z_from_mm": -1, "z_to_mm": 1, "marks": 3, "text": False},
        )
        runner = CommandRunner(grbl)

        steps = runner.build_plan(
            [lambda plan: runner._with_focus_moves(plan, ConsoleOperation)]
        )

        assert commands_of(steps) == [
            "z_move -1.000mm",
            "z_move 1.000mm",
            "z_move 1.000mm",
            "z_move -1.000mm",
        ]
