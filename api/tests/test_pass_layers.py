"""
More passes must not mean extra layers in the file.

Found on the machine: a test board with two passes gave "file invalid" on the
display and the laser did nothing. The cause is not in the passes themselves but
in the shape of the file.

`blob` turns every pass into a piece of cutcode of its own **with a settings dict
of its own** (`core/cutplan.py:_blob_convert` copies the dict as soon as `passes`
and `implicit_passes` differ), and the Ruida driver groups its RD layers on the
identity of that dict (`ruida/rdjob.py:1434`). So every pass became an extra
layer. Measured on the real RD stream of a board with four squares:

    one pass            : 16 cut objects, 4 RD layers  (max_layer_part 3)
    two passes          : 32 cut objects, 8 RD layers  (max_layer_part 7)
    two passes, shared  : 32 cut objects, 4 RD layers

So a board of sixteen squares comes to 33 layers at two passes, and the
controller no longer accepts that. What is tested below is the shape of the plan
that prevents it: the same operation several times in the plan list, so that
`blob` makes fresh cutcode per place and the settings dict stays one object.
"""

import pytest
from fastapi.testclient import TestClient

from openkerf_api.commands import CommandRunner
from openkerf_api.server import ApiServer


@pytest.fixture
def client(kernel, tmp_path):
    with TestClient(ApiServer(kernel, library_path=tmp_path / "d.db").build_app()) as c:
        yield c


def clean_slate(kernel):
    """
    Without the layers of a previous session.

    The engine puts the previous session's layer list back from a shared
    `operations.cfg` (see the upstream list in CLAUDE.md), and those layers can
    carry passes themselves. A test that counts layers has to start with an empty
    list.
    """
    for op in list(kernel.elements.ops()):
        op.remove_node()


def two_layers(client, kernel, passes: int) -> list[str]:
    """Two cut layers, each with a shape of its own, both with this many passes."""
    clean_slate(kernel)
    ids = []
    for x in (10, 60):
        shape = client.post(
            "/api/design/elements",
            json={"type": "rect", "x_mm": x, "y_mm": 10, "width_mm": 20, "height_mm": 20},
        ).json()["ids"][0]
        layer = client.post(
            "/api/design/operations", json={"type": "cut", "speed": 10}
        ).json()
        # Exclusively, not on top: a shape the engine also classifies into a
        # layer of its own burns twice, and then none of this counts any more.
        client.post(
            "/api/design/single-layer",
            json={"ids": [shape], "operation_id": layer["id"]},
        )
        client.patch(f"/api/design/operations/{layer['id']}", json={"passes": passes})
        ids.append(layer["id"])
    return ids


def layers_and_burns(kernel, unfold=True) -> tuple[int, int]:
    """
    (number of RD layers, number of burns), along the same road as a real job.

    The number of RD layers is the number of different settings dicts of the cut
    objects: that is what `ruida/rdjob.py:1434` groups its layers on. We do not
    spool — that would start the job.
    """
    from meerk40t.core.node.util_console import ConsoleOperation

    from openkerf_api.commands import PLAN_BLOB, PLAN_COPY

    runner = CommandRunner(kernel)
    plan = kernel.planner.get_or_make_plan("0")
    runner.run(PLAN_COPY)
    if unfold and runner._multi_pass_layers():
        plan.plan[:] = runner._with_passes(list(plan.plan), ConsoleOperation)
    runner.run(PLAN_BLOB)
    if unfold:
        plan.plan[:] = runner._share_pass_settings(list(plan.plan))

    objects = [
        item
        for step in plan.plan
        if hasattr(step, "__iter__")
        for item in step
        if isinstance(getattr(item, "settings", None), dict)
    ]
    dicts = {id(item.settings) for item in objects}
    return len(dicts), len(objects)


def test_two_passes_keep_one_layer_per_operation(client, kernel):
    two_layers(client, kernel, 2)

    layers, burns = layers_and_burns(kernel)

    assert layers == 2, "two operations should give two RD layers"
    # Eight cut pieces per pass (two rectangles of four sides), so sixteen.
    assert burns == 16, "and yet everything burns twice"


def test_one_pass_is_the_yardstick(client, kernel):
    two_layers(client, kernel, 1)

    assert layers_and_burns(kernel) == (2, 8)


def test_without_the_sharing_the_layers_double(client, kernel):
    """
    The counter-check, because without it the test above proves nothing.

    Without our intervention `blob` gives every pass a settings dict of its own —
    the shape the controller refused.
    """
    two_layers(client, kernel, 2)

    layers, burns = layers_and_burns(kernel, unfold=False)

    assert (layers, burns) == (4, 16)


def test_a_grid_of_sixteen_squares_stays_sixteen_layers(client, kernel):
    """
    The case it broke on: a test board with two passes.

    Sixteen squares plus the label layer is seventeen layers, and that is how it
    should stay. Without the intervention it became thirty-three.
    """
    from openkerf_api.testgrid import TestGridGenerator, plan_grid

    clean_slate(kernel)
    plan, cells = plan_grid(
        operation="snijden",
        speed_min=5, speed_max=20, speed_steps=4,
        power_min=40, power_max=90, power_steps=4,
        cell_mm=8, gap_mm=2, origin_x_mm=20, origin_y_mm=20,
        passes=2,
    )
    TestGridGenerator(kernel).draw(plan, cells)

    layers, burns = layers_and_burns(kernel)

    assert len(cells) == 16
    # Sixteen squares and one label layer, and that last one burns once.
    assert layers == 17
    assert burns > 32


def test_a_layer_that_does_not_burn_is_left_out(client, kernel):
    ids = two_layers(client, kernel, 3)
    client.patch(f"/api/design/operations/{ids[0]}", json={"output": False})

    runner = CommandRunner(kernel)
    assert [op.id for op in runner._multi_pass_layers()] == [ids[1]]


def test_the_z_step_still_gets_its_moves_between_passes(client, kernel):
    """The Z step runs over the same unfolding; it must not die here."""
    from meerk40t.core.node.util_console import ConsoleOperation

    class Fake:
        def __init__(self, passes, z_step_mm=None):
            self.passes = passes
            self.passes_custom = True
            self.implicit_passes = passes
            self.z_step_mm = z_step_mm

    step = Fake(passes=3, z_step_mm=0.5)
    out = CommandRunner._with_passes([step], ConsoleOperation)

    commands = [getattr(s, "command", None) for s in out]
    assert commands.count("z_move 0.500mm") == 2
    assert "z_move -1.000mm" in commands
    assert out.count(step) == 3
    assert step.passes == 1


def test_without_a_z_step_there_are_no_moves(client, kernel):
    from meerk40t.core.node.util_console import ConsoleOperation

    class Fake:
        def __init__(self, passes):
            self.passes = passes
            self.passes_custom = True
            self.implicit_passes = passes
            self.z_step_mm = None

    step = Fake(passes=2)
    out = CommandRunner._with_passes([step], ConsoleOperation)

    assert out == [step, step]
    assert step.passes == 1
