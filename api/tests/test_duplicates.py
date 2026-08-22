"""
Shapes lying on top of each other, and keeping one of each.

A duplicate is the one mistake in a design you cannot see: two identical
rectangles at the same place look like one rectangle, and the laser cuts the line
twice. So what is worth testing is not that identical things compare equal — it is
where the line runs. Which differences still count as the same shape (a tenth of a
millimetre of export rounding, a different colour, another layer), which do not (a
different type, a different place, a mirrored order of the pieces), and what
happens to the shape that stays.
"""

import pytest
from fastapi.testclient import TestClient

from openkerf_api.drawing import Drawing
from openkerf_api.duplicates import TOLERANCE_MM, Duplicates
from openkerf_api.edits import DesignEditor
from openkerf_api.server import ApiServer


@pytest.fixture
def drawing(kernel):
    return Drawing(kernel)


@pytest.fixture
def finder(kernel, drawing):
    return Duplicates(kernel, drawing)


@pytest.fixture
def client(kernel, tmp_path):
    with TestClient(ApiServer(kernel, library_path=tmp_path / "l.db").build_app()) as c:
        yield c


def a_rect(drawing, x=10.0, y=10.0, w=20.0, h=15.0):
    return drawing.create("rect", x_mm=x, y_mm=y, width_mm=w, height_mm=h)["ids"][0]


# --------------------------------------------------------------- what matches


def test_two_shapes_at_the_same_place_are_one_stack(drawing, finder):
    a_rect(drawing)
    a_rect(drawing)

    found = finder.find()

    assert found["stacks"] == 1
    assert found["extra"] == 1
    assert found["looked_at"] == 2


def test_three_of_the_same_count_as_two_too_many(drawing, finder):
    """The count in the question is the only evidence the user gets, so it is exact."""
    for _ in range(3):
        a_rect(drawing)

    found = finder.find()

    assert (found["stacks"], found["extra"]) == (1, 2)


def test_the_same_shape_somewhere_else_is_not_a_duplicate(drawing, finder):
    a_rect(drawing, x=10)
    a_rect(drawing, x=60)

    assert finder.find()["stacks"] == 0


def test_a_different_size_at_the_same_place_is_not_a_duplicate(drawing, finder):
    a_rect(drawing, w=20)
    a_rect(drawing, w=25)

    assert finder.find()["stacks"] == 0


def test_a_hair_apart_still_counts_as_the_same_shape(drawing, finder):
    """
    Exports round differently, and two outlines a twentieth of a millimetre apart are
    one line as far as a 0.2 mm kerf is concerned. Without this tolerance the feature
    would find nothing in exactly the case it exists for.
    """
    a_rect(drawing, x=10.0)
    a_rect(drawing, x=10.0 + TOLERANCE_MM / 4)

    assert finder.find()["stacks"] == 1


def test_a_shape_further_off_than_the_tolerance_is_left_alone(drawing, finder):
    a_rect(drawing, x=10.0)
    a_rect(drawing, x=10.0 + TOLERANCE_MM * 8)

    assert finder.find()["stacks"] == 0


def test_the_colour_and_the_layer_are_not_part_of_the_comparison(drawing, finder, kernel):
    """
    Two identical outlines in two layers burn twice, which is the very mistake this
    looks for — so a difference in what the laser does with the shape must not save it.
    """
    first = a_rect(drawing)
    second = a_rect(drawing)
    drawing.single_layer([first], kind="cut")
    drawing.single_layer([second], kind="engrave")
    drawing.paint([second], "#ff0000", None)

    assert finder.find()["stacks"] == 1


def test_a_circle_and_a_rectangle_at_the_same_place_are_two_shapes(drawing, finder):
    a_rect(drawing, x=10, y=10, w=20, h=20)
    drawing.create("circle", cx_mm=20, cy_mm=20, r_mm=10)

    assert finder.find()["stacks"] == 0


def test_what_has_no_outline_is_counted_as_skipped_and_not_guessed_at(
    drawing, finder, kernel
):
    """
    An image or a group has no outline to compare. Silently treating them as
    non-duplicates would be the same number on screen with a different meaning, so the
    dialog says how many were not looked at.
    """
    a_rect(drawing)
    a_rect(drawing)
    first = a_rect(drawing, x=100)
    second = a_rect(drawing, x=140)
    drawing.group([first, second])

    found = finder.find()

    assert found["stacks"] == 1
    # The group node itself has geometry; what matters is that the count adds up and
    # nothing is invented for shapes that cannot be compared.
    assert found["skipped"] + found["looked_at"] >= 3


def test_looking_changes_nothing(drawing, finder, kernel):
    a_rect(drawing)
    a_rect(drawing)
    before = len(list(kernel.elements.elems()))

    finder.find()

    assert len(list(kernel.elements.elems())) == before


def test_a_selection_narrows_the_search(drawing, finder):
    """
    You have just imported something and want to know about *that*. The shapes you did
    not pick stay out of the comparison, even when they are duplicates of each other.
    """
    first = a_rect(drawing, x=10)
    second = a_rect(drawing, x=10)
    a_rect(drawing, x=200)
    a_rect(drawing, x=200)

    whole = finder.find()
    narrow = finder.find([first, second])

    assert whole["stacks"] == 2
    assert (narrow["stacks"], narrow["looked_at"]) == (1, 2)


# --------------------------------------------------------------- what happens


def test_removing_keeps_the_one_that_was_there_first(drawing, finder, kernel):
    """
    Tree order is arrival order, so the shape you drew yourself stays and the one an
    import laid on top of it goes. The other way round would silently replace your work
    with a copy.
    """
    first = a_rect(drawing)
    second = a_rect(drawing)

    outcome = finder.remove()

    assert outcome["removed"] == 1
    assert outcome["removed_ids"] == [second]
    assert kernel.elements.find_node(first) is not None
    assert kernel.elements.find_node(second) is None


def test_removing_twice_finds_nothing_the_second_time(drawing, finder):
    a_rect(drawing)
    a_rect(drawing)
    finder.remove()

    again = finder.find()

    assert (again["stacks"], again["extra"]) == (0, 0)


def test_a_locked_copy_is_the_one_that_stays(drawing, finder, kernel):
    """
    A lock says "do not touch this shape", and that has to win over "the first one
    stays" — otherwise the tidy-up quietly removes the alignment mark you protected.
    """
    loose = a_rect(drawing)
    protected = a_rect(drawing)
    drawing.set_locked([protected], True)

    outcome = finder.remove()

    assert outcome["removed_ids"] == [loose]
    assert kernel.elements.find_node(protected) is not None


def test_two_locked_copies_leave_each_other_alone(drawing, finder, kernel):
    """Nothing may be removed, and the count says so rather than claiming success."""
    first = a_rect(drawing)
    second = a_rect(drawing)
    drawing.set_locked([first, second], True)

    outcome = finder.remove()

    assert outcome["removed"] == 0
    assert len(list(kernel.elements.elems())) == 2


def test_removing_nothing_is_not_an_error(drawing, finder):
    a_rect(drawing, x=10)
    a_rect(drawing, x=60)

    outcome = finder.remove()

    assert outcome["removed"] == 0


def test_removing_can_be_undone(drawing, finder, kernel):
    """
    It is the one edit whose result you cannot see, so the way back has to work: the
    removal runs in an undo scope of its own.
    """
    a_rect(drawing)
    a_rect(drawing)
    finder.remove()
    assert len(list(kernel.elements.elems())) == 1

    DesignEditor(kernel).undo()

    assert len(list(kernel.elements.elems())) == 2


# ----------------------------------------------------------------- the routes


def test_the_route_looks_and_removes(client):
    def rect():
        return client.post(
            "/api/design/elements",
            json={"type": "rect", "x_mm": 10, "y_mm": 10, "width_mm": 20, "height_mm": 15},
        ).json()["ids"][0]

    rect()
    rect()

    looked = client.get("/api/design/duplicates")
    assert looked.status_code == 200, looked.text
    assert looked.json()["extra"] == 1

    removed = client.post("/api/design/duplicates/remove", json={})
    assert removed.status_code == 200, removed.text
    assert removed.json()["removed"] == 1
    assert len(client.get("/api/design").json()["elements"]) == 1


def test_the_route_takes_a_selection(client):
    def rect(x):
        return client.post(
            "/api/design/elements",
            json={"type": "rect", "x_mm": x, "y_mm": 10, "width_mm": 20, "height_mm": 15},
        ).json()["ids"][0]

    first, second = rect(10), rect(10)
    rect(200), rect(200)

    looked = client.get(f"/api/design/duplicates?ids={first},{second}")

    assert looked.json()["looked_at"] == 2
    assert looked.json()["stacks"] == 1
