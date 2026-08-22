"""
Print and cut: laying a job over marks that are already on the material.

The maths is the tile run's (`tiling.alignment`) and is tested there. What is worth
testing here is the join: that two shapes you point out give the right pair of
points, that a half-finished alignment is not half-applied, that the pose lands on
the plan and not on the drawing, and that a job without an alignment takes exactly
the route it always took.
"""

import math

import pytest
from fastapi.testclient import TestClient

from openkerf_api.drawing import Drawing
from openkerf_api.edits import DesignError
from openkerf_api.printcut import MAX_ANGLE_DEG, TOLERANCE_MM, PoseMutator, PrintCut
from openkerf_api.server import ApiServer
from openkerf_api.tiling import Alignment


@pytest.fixture
def client(kernel, tmp_path):
    with TestClient(ApiServer(kernel, library_path=tmp_path / "p.db").build_app()) as c:
        yield c


@pytest.fixture
def drawing(kernel):
    return Drawing(kernel)


class Head:
    """A machine that says where its head is, or refuses to."""

    def __init__(self, where=(0.0, 0.0)):
        self.where = where

    def _current_mm(self):
        return self.where


@pytest.fixture
def printcut(kernel, drawing):
    return PrintCut(kernel, drawing, Head())


def a_mark(drawing, x, y, r=2.0):
    """A registration mark in the drawing: a small circle at a known middle."""
    return drawing.create("circle", cx_mm=x, cy_mm=y, r_mm=r)["ids"][0]


# ------------------------------------------------------------- pointing them out


def test_the_marks_are_taken_by_their_middle(printcut, drawing):
    """
    A cross or a circle is aimed at by its middle, and the middle does not depend on
    which way round the shape was drawn.
    """
    first = a_mark(drawing, 20, 20)
    second = a_mark(drawing, 120, 30)

    state = printcut.set_marks([first, second])

    assert [m["drawn"] for m in state["marks"]] == [
        {"x_mm": 20.0, "y_mm": 20.0},
        {"x_mm": 120.0, "y_mm": 30.0},
    ]


def test_one_mark_is_refused(printcut, drawing):
    """One point is a shift, and a shift is what the zero point already does."""
    with pytest.raises(DesignError) as refusal:
        printcut.set_marks([a_mark(drawing, 20, 20)])
    assert refusal.value.code == "printcut.needsTwoMarks"


def test_three_marks_are_refused(printcut, drawing):
    with pytest.raises(DesignError) as refusal:
        printcut.set_marks(
            [a_mark(drawing, 20, 20), a_mark(drawing, 120, 20), a_mark(drawing, 60, 90)]
        )
    assert refusal.value.code == "printcut.needsTwoMarks"


def test_the_same_shape_twice_is_refused(printcut, drawing):
    mark = a_mark(drawing, 20, 20)
    with pytest.raises(DesignError) as refusal:
        printcut.set_marks([mark, mark])
    assert refusal.value.code == "printcut.sameMark"


def test_two_marks_too_close_together_are_refused(printcut, drawing):
    """
    A millimetre of aiming error over 5 mm is more than ten degrees of angle. Accepting
    that would turn the whole job on a slip you cannot see.
    """
    with pytest.raises(DesignError) as refusal:
        printcut.set_marks([a_mark(drawing, 20, 20, r=1), a_mark(drawing, 25, 20, r=1)])
    assert refusal.value.code == "printcut.marksTooClose"


# ------------------------------------------------------------------- driving to


def test_one_point_is_not_an_alignment(printcut, drawing):
    """Half an alignment must not be half applied — that is a job on the wrong place."""
    printcut.set_marks([a_mark(drawing, 20, 20), a_mark(drawing, 120, 20)])

    state = printcut.measure(0, 22, 21)

    assert state["aligned"] is False
    assert printcut.mutators() == []


def test_two_points_give_the_shift(printcut, drawing):
    printcut.set_marks([a_mark(drawing, 20, 20), a_mark(drawing, 120, 20)])

    printcut.measure(0, 25, 23)
    state = printcut.measure(1, 125, 23)

    assert state["aligned"] is True
    assert (state["dx_mm"], state["dy_mm"]) == (5.0, 3.0)
    assert state["angle_deg"] == 0.0


def test_two_points_give_the_angle(printcut, drawing):
    """The sheet lies a degree out; that degree is the whole point of doing this."""
    printcut.set_marks([a_mark(drawing, 0, 0), a_mark(drawing, 100, 0)])

    printcut.measure(0, 0, 0)
    state = printcut.measure(1, 100 * math.cos(math.radians(1)), 100 * math.sin(math.radians(1)))

    assert state["angle_deg"] == pytest.approx(1.0, abs=0.01)


def test_a_sheet_that_lies_impossibly_askew_is_refused(printcut, drawing):
    printcut.set_marks([a_mark(drawing, 0, 0), a_mark(drawing, 100, 0)])
    printcut.measure(0, 0, 0)

    with pytest.raises(DesignError) as refusal:
        printcut.measure(1, 100 * math.cos(math.radians(20)), 100 * math.sin(math.radians(20)))

    assert refusal.value.code == "printcut.askew"
    assert printcut.mutators() == []


def test_a_distance_that_does_not_match_is_refused(printcut, drawing):
    """
    Scale is checked and never adopted. Adopt it and one slip of the aim stretches the
    whole job; check it, and the same slip is a sentence on the screen.
    """
    printcut.set_marks([a_mark(drawing, 0, 0), a_mark(drawing, 100, 0)])
    printcut.measure(0, 0, 0)

    with pytest.raises(DesignError) as refusal:
        printcut.measure(1, 100 + TOLERANCE_MM * 3, 0)

    assert refusal.value.code == "printcut.distance"


def test_a_hair_of_stretch_is_allowed(printcut, drawing):
    """A printed sheet does move a little with the weather; that is not a wrong mark."""
    printcut.set_marks([a_mark(drawing, 0, 0), a_mark(drawing, 100, 0)])
    printcut.measure(0, 0, 0)

    state = printcut.measure(1, 100 + TOLERANCE_MM / 2, 0)

    assert state["aligned"] is True


def test_driving_to_a_point_again_recomputes_from_both(printcut, drawing):
    """
    Doing one of the two over is the normal correction — you were not quite on the mark.
    The answer is then computed again from both points and it is the *new* answer; the
    old one is not kept beside it.
    """
    printcut.set_marks([a_mark(drawing, 0, 0), a_mark(drawing, 100, 0)])
    printcut.measure(0, 0, 0)
    printcut.measure(1, 100, 0)
    assert printcut.state()["dx_mm"] == 0.0

    state = printcut.measure(0, 1, 0)

    assert state["aligned"] is True
    assert state["dx_mm"] == 1.0


def test_a_correction_that_no_longer_agrees_refuses_and_keeps_nothing(printcut, drawing):
    """
    Move one point far enough and the pair no longer describes one sheet. Then there is
    no pose at all — not the old one, which was about where the head *used* to be
    pointed, and not a new one from a pair that does not fit.
    """
    printcut.set_marks([a_mark(drawing, 0, 0), a_mark(drawing, 100, 0)])
    printcut.measure(0, 0, 0)
    printcut.measure(1, 100, 0)

    with pytest.raises(DesignError) as refusal:
        printcut.measure(0, 10, 0)

    assert refusal.value.code == "printcut.distance"
    assert printcut.state()["aligned"] is False
    assert printcut.mutators() == []


def test_new_marks_throw_the_measurements_away(printcut, drawing):
    printcut.set_marks([a_mark(drawing, 0, 0), a_mark(drawing, 100, 0)])
    printcut.measure(0, 0, 0)
    printcut.measure(1, 100, 0)

    state = printcut.set_marks([a_mark(drawing, 10, 10), a_mark(drawing, 110, 10)])

    assert state["aligned"] is False
    assert [m["measured"] for m in state["marks"]] == [None, None]


def test_driving_to_a_mark_before_pointing_them_out_is_refused(printcut):
    with pytest.raises(DesignError) as refusal:
        printcut.measure(0)
    assert refusal.value.code == "printcut.noMarks"


def test_a_machine_that_does_not_say_where_it_is(kernel, drawing):
    """
    Then it says so. Silently taking 0,0 would align the job to the corner of the bed —
    a whole sheet's worth of error, from a machine that was simply not connected.
    """
    class Mute(Head):
        def _current_mm(self):
            return None

    cut = PrintCut(kernel, drawing, Mute())
    cut.set_marks([a_mark(drawing, 0, 0), a_mark(drawing, 100, 0)])

    with pytest.raises(DesignError) as refusal:
        cut.measure(0)
    assert refusal.value.code == "printcut.noPosition"


def test_without_coordinates_it_reads_the_machine(kernel, drawing):
    head = Head((42.0, 17.0))
    cut = PrintCut(kernel, drawing, head)
    cut.set_marks([a_mark(drawing, 0, 0), a_mark(drawing, 100, 0)])

    state = cut.measure(0)

    assert state["marks"][0]["measured"] == {"x_mm": 42.0, "y_mm": 17.0}


def test_clearing_gives_the_ordinary_job_back(printcut, drawing):
    printcut.set_marks([a_mark(drawing, 0, 0), a_mark(drawing, 100, 0)])
    printcut.measure(0, 1, 1)
    printcut.measure(1, 101, 1)
    assert printcut.mutators()

    state = printcut.clear()

    assert state["aligned"] is False
    assert printcut.mutators() == []


# ---------------------------------------------------------------- on the plan


def test_the_pose_moves_the_plan_and_not_the_drawing(client, kernel, drawing):
    """
    The sheet moved, your design did not. If the drawing itself shifted, the next job
    would be aligned twice — and the canvas would jump under a job you did not change.
    """
    from openkerf_api.commands import CommandRunner

    shape = drawing.create("rect", x_mm=10, y_mm=10, width_mm=20, height_mm=20)["ids"][0]
    drawing.single_layer([shape], kind="cut")
    before = [round(v, 1) for v in kernel.elements.find_node(shape).bounds]
    mutator = PoseMutator(
        Alignment(angle_deg=0.0, dx_mm=30.0, dy_mm=0.0, distance_error_mm=0.0),
        drawing._units_per_mm(),
    )
    runner = CommandRunner(kernel)

    steps = runner.build_plan([mutator])

    per_mm = drawing._units_per_mm()
    moved = [
        child.bounds
        for step in steps
        for child in (getattr(step, "children", None) or [])
        if getattr(child, "bounds", None)
    ]
    assert moved, "the plan holds no geometry"
    assert round(min(b[0] for b in moved) / per_mm, 1) == pytest.approx(40.0, abs=0.5)
    assert [round(v, 1) for v in kernel.elements.find_node(shape).bounds] == before


def test_a_job_without_an_alignment_is_left_exactly_as_it_was(printcut):
    """Every job passes this, so "no alignment" has to mean "no change at all"."""
    assert printcut.mutators() == []


# ------------------------------------------------------------------- the routes


def test_the_routes_walk_the_whole_way(client):
    def mark(x, y):
        return client.post(
            "/api/design/elements", json={"type": "circle", "cx_mm": x, "cy_mm": y, "r_mm": 2}
        ).json()["ids"][0]

    first, second = mark(20, 20), mark(120, 20)

    marks = client.post("/api/printcut/marks", json={"ids": [first, second]})
    assert marks.status_code == 200, marks.text
    assert marks.json()["aligned"] is False

    client.post("/api/printcut/measure", json={"index": 0, "x_mm": 22, "y_mm": 21})
    both = client.post("/api/printcut/measure", json={"index": 1, "x_mm": 122, "y_mm": 21})
    assert both.status_code == 200, both.text
    assert both.json()["aligned"] is True
    assert client.get("/api/printcut").json()["dx_mm"] == 2.0

    assert client.post("/api/printcut/clear").json()["aligned"] is False


def test_a_refusal_carries_its_code(client):
    def mark(x, y):
        return client.post(
            "/api/design/elements", json={"type": "circle", "cx_mm": x, "cy_mm": y, "r_mm": 2}
        ).json()["ids"][0]

    refused = client.post("/api/printcut/marks", json={"ids": [mark(20, 20)]})

    assert refused.status_code == 409
    assert refused.headers.get("X-OpenKerf-Error") == "printcut.needsTwoMarks"


def test_the_state_says_what_it_would_refuse(client):
    """
    The panel says the two bounds before you point at anything, because they are the two
    reasons the answer can come back a refusal.
    """
    state = client.get("/api/printcut").json()

    assert state["tolerance_mm"] == TOLERANCE_MM
    assert state["max_angle_deg"] == MAX_ANGLE_DEG


def test_the_alignment_lapses_when_a_mark_is_deleted(printcut, drawing, kernel):
    """
    Otherwise the numbers stay on the screen looking valid while the shape they were
    measured against is gone — and the job burns to a pose about nothing.
    """
    first = a_mark(drawing, 0, 0)
    second = a_mark(drawing, 100, 0)
    printcut.set_marks([first, second])
    printcut.measure(0, 0, 0)
    printcut.measure(1, 100, 0)
    assert printcut.state()["aligned"] is True

    drawing.delete([second])

    assert printcut.state()["aligned"] is False
    assert printcut.state()["lapsed"] == "gone"
    assert printcut.mutators() == []


def test_the_alignment_lapses_on_another_machine(kernel, drawing):
    """
    A pose is a pair of machine coordinates. On another bed — another size, another
    home corner — it is a shift into nowhere.
    """
    cut = PrintCut(kernel, drawing, Head())
    cut.set_marks([a_mark(drawing, 0, 0), a_mark(drawing, 100, 0)])
    cut.measure(0, 0, 0)
    cut.measure(1, 100, 0)
    assert cut.state()["aligned"] is True

    cut._machine = "some other laser"

    assert cut.state()["aligned"] is False
    assert cut.state()["lapsed"] == "machine"


def test_the_state_reports_the_offset_you_can_check_with_a_ruler(printcut, drawing):
    """
    Not the pose's own dx/dy: that is the translation after turning about the origin,
    and at any real angle it is a number far bigger than the bed. True and unreadable.
    """
    printcut.set_marks([a_mark(drawing, 20, 20), a_mark(drawing, 120, 20)])
    printcut.measure(0, 23, 22)
    state = printcut.measure(1, 123, 22)

    assert state["offset_mm"] == {"x_mm": 3.0, "y_mm": 2.0}
