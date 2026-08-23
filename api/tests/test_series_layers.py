"""
Fifty burns must not mean fifty layers in the file.

This is the standing regression detector under the whole Series design, and the number
it guards is a number the machine gave us: a board of sixteen squares at two passes came
to 33 RD layers and the controller answered "file invalid" with the laser standing still
(CLAUDE.md, the pass-layers row; `api/tests/test_pass_layers.py` has the measurements).
The Ruida writer groups its layers on the *identity* of a cut object's settings dict
(`ruida/rdjob.py:1434`), so anything that quietly gives a piece of work a dict of its own
multiplies the layers in the file.

A series is the obvious way to walk into that. The engine's own answer to "one design,
many pieces" is a placement, and a placement replays the whole plan per piece
(`core/cutplan.py:225-338`) — fifty placements are fifty times every layer. Ours is one
job per row instead, so the layer count comes off the design and the list length never
enters it. That is a claim about material, not about code, and the proxy below is the
same one `test_pass_layers.py:96-103` measures the real RD stream against.

What would make this file go red: turning rows into placements, giving each burn its own
copy of an operation, or losing `_share_pass_settings` on the series route so that a
two-pass layer becomes two layers per plate.
"""

import pytest

from openkerf_api.commands import PLAN_BLOB, PLAN_COPY, CommandRunner
from openkerf_api.drawing import Drawing
from openkerf_api.series import OverrunMutator, Series, read_rows


@pytest.fixture
def drawing(kernel):
    return Drawing(kernel)


@pytest.fixture
def series(kernel, tmp_path):
    return Series(kernel, tmp_path / "openkerf-series.json")


def clean_slate(kernel):
    """
    Without the layers of a previous session.

    The engine puts the previous session's layer list back out of a shared
    `operations.cfg` (see the upstream list in CLAUDE.md), and those layers can carry
    passes of their own. A test that counts layers has to start from an empty list.
    """
    for operation in list(kernel.elements.ops()):
        operation.remove_node()


@pytest.fixture(autouse=True)
def leave_no_layers_behind(kernel):
    """
    And put the list back to empty afterwards, or this file poisons the next one.

    That shared `operations.cfg` is written at shutdown, keyed on the kernel *name* and
    blind to `ignore_settings` — the upstream row CLAUDE.md records. A two-pass layer
    left standing here therefore arrives in the next test's kernel, and `start_job` then
    takes the mutator route instead of the one-line route for a design that asked for
    neither. Measured: with this teardown missing,
    `test_tilerun.py::test_a_plain_job_still_takes_the_single_line_route` fails, and it
    fails on a design of its own that has nothing to do with a series.
    """
    yield
    clean_slate(kernel)


def a_list(rows: int, column: str = "name"):
    """A list of `rows` plainly fictional names, through the real reader."""
    text = column + "\n" + "\n".join(f"N{index:03d}" for index in range(rows)) + "\n"
    return read_rows(text.encode("utf-8"))


class Layers:
    """
    A runner that takes a burn as far as the cutcode and counts its layers.

    It stands in for the spooler and walks the identical road `start_job` walks, minus
    the last word of it: `plan copy`, the mutators the route and the series composed,
    then `preprocess validate blob preopt optimize` — and no `spool`, because nothing
    here may reach a machine. The composition after our own mutators is the runner's
    own (`_plan_and_spool_locked`), asked for rather than copied, so a change in how a
    real burn is put together shows up here instead of being quietly missed.

    It deliberately does not clear the plan afterwards either. `plan copy` *adds* to the
    kernel-global plan (`core/planner.py:593`), and the `clear` at the head of
    `PLAN_COPY` is the only thing that stops the second plate carrying the first one's
    work as well — measured on an ordinary job as 1701 s, 3364 s, 5027 s for the same
    design. A double that tidied up after itself would hide exactly that, and it is a
    failure that doubles the layers per plate.
    """

    def __init__(self, kernel):
        self.kernel = kernel
        self.runner = CommandRunner(kernel)
        self.counts = []

    def start_job(self, name, mutators=()):
        from meerk40t.core.node.util_console import ConsoleOperation

        plan = self.kernel.planner.get_or_make_plan("0")
        after = []
        composed = list(mutators)
        if self.runner._multi_pass_layers():
            composed.append(
                lambda steps: self.runner._with_passes(steps, ConsoleOperation)
            )
            after.append(self.runner._share_pass_settings)
        self.runner.run(PLAN_COPY)
        steps = list(plan.plan)
        for mutator in composed:
            steps = list(mutator(steps))
        plan.plan[:] = steps
        self.runner.run(PLAN_BLOB)
        steps = list(plan.plan)
        for mutator in after:
            steps = list(mutator(steps))
        plan.plan[:] = steps

        objects = [
            item
            for step in plan.plan
            if hasattr(step, "__iter__")
            for item in step
            if isinstance(getattr(item, "settings", None), dict)
        ]
        self.counts.append((len({id(item.settings) for item in objects}), len(objects)))


def a_design(kernel, drawing, passes: int = 1):
    """
    Two layers that burn: a frame to cut and a name to engrave.

    Both hold work, and neither is marked "burn only once" — the flag would take the
    frame off every plate after the first and the layer count would drop, which is a
    different thing being tested (`test_series.py`, the jig).
    """
    clean_slate(kernel)
    drawing.create("rect", x_mm=5.0, y_mm=5.0, width_mm=60.0, height_mm=30.0)
    drawing.create("text", x_mm=10.0, y_mm=20.0, text="{name}", font_size_mm=8.0)
    for operation in kernel.elements.ops():
        if list(operation.children):
            # What the operator does in the Layers panel. Without it the plan is empty
            # and every count below would be nought.
            operation.output = True
            operation.passes = passes
            operation.passes_custom = passes > 1
    return len([op for op in kernel.elements.ops() if list(op.children)])


def burn_them(series, count: int) -> None:
    """`count` plates, the way the operator makes them: burn, move on, burn."""
    for _ in range(count):
        series.burn()
        series.advance()


@pytest.mark.parametrize("burns", (1, 10, 50))
def test_a_series_does_not_multiply_rd_layers(kernel, drawing, series, burns):
    """
    Every plate of a fifty-plate series is the same handful of layers as one plate.

    The proxy is the number of distinct settings dicts among the cut objects, which is
    what the Ruida writer groups its RD layers on (`ruida/rdjob.py:1434`). Measured
    here: two layers and eight cut objects on every one of fifty plates — the four sides
    of the frame plus the strokes of a four-letter name, which move with the name and are
    therefore not asserted on.

    Fails the moment rows become placements or a burn gets its own copy of an operation:
    at fifty rows that is a hundred layers where the controller stopped accepting a file
    at thirty-three.
    """
    expected = a_design(kernel, drawing)
    series.attach(a_list(burns))
    series.runner = Layers(kernel)
    series.start()

    burn_them(series, burns)

    layers = [count for count, _ in series.runner.counts]
    assert len(layers) == burns, "every row should have made a plate"
    assert layers == [expected] * burns


def test_the_list_is_not_in_the_layer_count(kernel, drawing, series):
    """
    A three-row list and a fifty-row list give a plate of the same shape.

    Said separately from the test above because that one could pass while the count grew
    with the *list* rather than with the burn — a design that builds the whole list into
    every plan would still be constant per plate and still hand the controller a file it
    refuses.
    """
    expected = a_design(kernel, drawing)
    counts = {}
    for rows in (3, 50):
        series.attach(a_list(rows))
        series.runner = Layers(kernel)
        series.start()
        series.burn()
        counts[rows] = series.runner.counts[0][0]
        series.stop()

    assert counts == {3: expected, 50: expected}


def test_two_passes_stay_one_layer_on_every_plate_of_a_series(
    kernel, drawing, series
):
    """
    The two multipliers must not meet.

    `blob` gives every pass its own settings dict as soon as the plan holds an operation
    more than once (`core/cutplan.py:_blob_convert`), and `_share_pass_settings` is what
    puts them back into one. A series burn goes through the same runner, so it has to get
    the same treatment: without it a two-layer design at two passes is four layers per
    plate, and a test board of sixteen squares is the 33 the controller refused.

    The second assertion is the one that keeps the first honest. "One layer" is also what
    you get by losing a pass, and that would be a job that burns half as deep as it says
    — so the same plate is measured at one pass and at two, and the work has to double
    while the layers do not. Measured on this design: 2 layers and 8 cut objects at one
    pass, 2 layers and 16 at two.
    """
    counts = {}
    for passes in (1, 2):
        expected = a_design(kernel, drawing, passes=passes)
        series.attach(a_list(10))
        series.runner = Layers(kernel)
        series.start()

        burn_them(series, 10)

        layers = [count for count, _ in series.runner.counts]
        assert layers == [expected] * 10, f"at {passes} pass(es)"
        # The first plate of each run engraves the same name, so the two runs are
        # comparable piece for piece.
        counts[passes] = series.runner.counts[0][1]
        series.detach()

    assert counts[2] == counts[1] * 2
