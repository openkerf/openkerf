"""Moving, resizing and undoing elements."""

import pytest
from fastapi.testclient import TestClient

from meerk40t.core.units import UNITS_PER_MM

from openkerf_api.design import DesignReader
from openkerf_api.edits import DesignEditor, DesignError
from openkerf_api.server import ApiServer


@pytest.fixture
def client(kernel):
    with TestClient(ApiServer(kernel).build_app()) as c:
        yield c


@pytest.fixture
def editor(kernel):
    kernel.console("rect 20mm 15mm 60mm 40mm\n")
    return DesignEditor(kernel)


def pose(kernel, element_id):
    from openkerf_api.design import _pose_of

    return _pose_of(kernel.elements.find_node(element_id))


def bounds_mm(kernel, element_id):
    node = kernel.elements.find_node(element_id)
    return [round(v / UNITS_PER_MM, 1) for v in node.bounds]


def first_id(kernel):
    return DesignReader(kernel).snapshot()["elements"][0]["id"]


# ------------------------------------------------------------------ moving

def test_move_shifts_the_element(kernel, editor):
    element_id = first_id(kernel)
    assert bounds_mm(kernel, element_id) == [20.0, 15.0, 80.0, 55.0]

    editor.move(element_id, 10, 5)

    assert bounds_mm(kernel, element_id) == [30.0, 20.0, 90.0, 60.0]


def test_move_accepts_negative_and_fractional_millimetres(kernel, editor):
    element_id = first_id(kernel)

    editor.move(element_id, -0.5, 0.1)

    assert bounds_mm(kernel, element_id) == [19.5, 15.1, 79.5, 55.1]


def test_move_rejects_nonsense(kernel, editor):
    element_id = first_id(kernel)
    for bad in ("cheese", None, float("inf")):
        with pytest.raises(DesignError):
            editor.move(element_id, bad, 0)


def test_move_on_a_stale_id_is_refused(editor):
    with pytest.raises(DesignError):
        editor.move("meerk40t:doesnotexist", 1, 1)


def test_move_only_touches_its_own_element(kernel, editor):
    kernel.console("circle 120mm 50mm 15mm\n")
    ids = [e["id"] for e in DesignReader(kernel).snapshot()["elements"]]
    other_before = bounds_mm(kernel, ids[1])

    editor.move(ids[0], 10, 0)

    assert bounds_mm(kernel, ids[1]) == other_before


# ---------------------------------------------------------------- resizing

def test_resize_sets_exact_bounds(kernel, editor):
    element_id = first_id(kernel)

    editor.resize(element_id, 10, 10, 30, 20)

    assert bounds_mm(kernel, element_id) == [10.0, 10.0, 40.0, 30.0]


def test_resize_rejects_zero_or_negative_size(kernel, editor):
    element_id = first_id(kernel)
    for width, height in ((0, 10), (10, 0), (-5, 10)):
        with pytest.raises(DesignError):
            editor.resize(element_id, 0, 0, width, height)


# -------------------------------------------------------------------- undo

def test_undo_reverts_a_move(kernel, editor):
    element_id = first_id(kernel)
    editor.move(element_id, 10, 5)

    result = editor.undo()

    assert result["applied"] is True
    # The element is back where it was, under whatever id it now carries.
    assert bounds_mm(kernel, first_id(kernel)) == [20.0, 15.0, 80.0, 55.0]


def test_undo_reports_that_ids_are_no_longer_valid(kernel, editor):
    """
    Ids usually survive an undo, but not always: undo restores a whole-tree
    snapshot, which can predate id assignment, and it can step back further
    than the last edit. A client must therefore not reuse a held id after one.
    """
    element_id = first_id(kernel)
    editor.move(element_id, 10, 5)

    result = editor.undo()

    assert result["ids_invalidated"] is True


def test_undo_steps_back_one_edit_and_not_two(kernel, editor):
    """
    Upstream #3258, caught in `_undo_target`.

    The stack keeps, per change, the state *before* that change, but `Undo.undo()`
    restores one below that. Measured on the old code: three shapes drawn, one
    undo, and one was left.
    """
    from openkerf_api.drawing import Drawing

    drawing = Drawing(kernel)
    for i in range(3):
        drawing.create("rect", x_mm=5 + 20 * i, y_mm=90, width_mm=8, height_mm=8)
    before = len(DesignReader(kernel).snapshot()["elements"])

    editor.undo()

    assert len(DesignReader(kernel).snapshot()["elements"]) == before - 1


def test_undo_and_redo_land_on_the_same_states(kernel, editor):
    """What goes back once comes back with one step forward."""
    from openkerf_api.drawing import Drawing

    drawing = Drawing(kernel)
    for i in range(3):
        drawing.create("rect", x_mm=5 + 20 * i, y_mm=90, width_mm=8, height_mm=8)
    full = len(DesignReader(kernel).snapshot()["elements"])

    editor.undo()
    editor.undo()
    assert len(DesignReader(kernel).snapshot()["elements"]) == full - 2

    editor.redo()
    editor.redo()
    assert len(DesignReader(kernel).snapshot()["elements"]) == full


def test_undo_puts_a_shape_back_in_the_layer_it_came_from(kernel, editor):
    """
    Jelle's question: does a layer assignment fall under undo?

    It does — but on the old code the shape did not jump back to the *previous*
    layer but to the one of the action before that, and if that was the same one,
    undo looked as if it did nothing.
    """
    from openkerf_api.drawing import Drawing

    drawing = Drawing(kernel)
    element_id = first_id(kernel)
    red = drawing.paint([element_id], "#ff0000", None)["operation_id"]
    drawing.paint([element_id], "#0000ff", None)

    def in_layer(operation_id):
        return any(
            element_id in op["element_ids"]
            for op in DesignReader(kernel).snapshot()["operations"]
            if op["id"] == operation_id
        )

    assert in_layer(red) is False

    editor.undo()

    assert in_layer(red) is True


def test_undo_at_the_bottom_of_the_stack_is_not_an_error(kernel, editor):
    for _ in range(40):
        result = editor.undo()
        if not result["applied"]:
            break
    else:
        pytest.fail("undo never reported an exhausted stack")

    assert result["ids_invalidated"] is False


# -------------------------------------------------------------------- HTTP

def test_move_over_http(kernel, editor, client):
    element_id = first_id(kernel)

    response = client.post(
        "/api/design/move", json={"ids": [element_id], "dx_mm": 5, "dy_mm": 0}
    )

    assert response.status_code == 200
    assert bounds_mm(kernel, element_id) == [25.0, 15.0, 85.0, 55.0]


def test_bad_payload_is_a_409(kernel, editor, client):
    element_id = first_id(kernel)

    response = client.post(
        "/api/design/move", json={"ids": [element_id], "dx_mm": "cheese", "dy_mm": 0}
    )

    assert response.status_code == 409


def test_undo_over_http(kernel, editor, client):
    element_id = first_id(kernel)
    client.post("/api/design/move", json={"ids": [element_id], "dx_mm": 5, "dy_mm": 0})

    response = client.post("/api/design/undo")

    assert response.status_code == 200
    assert response.json()["ids_invalidated"] is True


# ---------------------------------------------------- multiple selection

def test_move_accepts_several_elements(kernel, editor):
    kernel.console("circle 120mm 50mm 15mm\n")
    ids = [e["id"] for e in DesignReader(kernel).snapshot()["elements"]]
    before = [bounds_mm(kernel, i) for i in ids]

    editor.move(ids, 10, 0)

    for element_id, was in zip(ids, before):
        now = bounds_mm(kernel, element_id)
        assert now[0] == pytest.approx(was[0] + 10, abs=0.05)


def test_move_requires_at_least_one_element(editor):
    for empty in ([], None, ""):
        with pytest.raises(DesignError):
            editor.move(empty, 1, 1)


def test_a_bare_id_still_works(kernel, editor):
    """The single-element form stays valid, so callers need not wrap it."""
    element_id = first_id(kernel)

    editor.move(element_id, 5, 0)

    assert bounds_mm(kernel, element_id)[0] == 25.0


# ---------------------------------------------------------------- rotating

def test_rotate_changes_the_bounding_box(kernel, editor):
    element_id = first_id(kernel)
    before = bounds_mm(kernel, element_id)

    editor.rotate(element_id, 45)

    after = bounds_mm(kernel, element_id)
    assert after != before
    # A rotated rectangle covers a wider box than the axis-aligned original.
    assert (after[2] - after[0]) > (before[2] - before[0])


def test_rotate_rejects_nonsense(kernel, editor):
    with pytest.raises(DesignError):
        editor.rotate(first_id(kernel), "skewed")


def test_pose_reports_the_angle_and_the_mirroring(kernel, editor):
    """
    The pose of a shape is a fact from the engine, not a sum the panel keeps.
    Without these two fields the right-hand bar can rotate but cannot show where
    you are.
    """
    element_id = first_id(kernel)
    assert pose(kernel, element_id) == {"angle_deg": 0.0, "mirrored": False}

    editor.rotate(element_id, 30)
    assert pose(kernel, element_id)["angle_deg"] == pytest.approx(30.0, abs=0.01)
    assert pose(kernel, element_id)["mirrored"] is False


def test_pose_does_not_call_mirroring_a_half_turn(kernel, editor):
    """
    `matrix.rotation` counts a mirroring as 180°. A shape that is only mirrored is
    not upside down, so that half turn has to come off again before the number
    reaches the screen.
    """
    element_id = first_id(kernel)
    DrawingMirror = __import__(
        "openkerf_api.drawing", fromlist=["Drawing"]
    ).Drawing(kernel)
    DrawingMirror.mirror([element_id], "horizontal")

    assert pose(kernel, element_id) == {"angle_deg": 0.0, "mirrored": True}


def test_absolute_rotation_is_a_destination_not_a_step(kernel, editor):
    """
    The same number twice has to give the same picture. That is the whole reason
    the angle field may be typed into.

    The engine has `rotate -a` for this itself, but that computes `start - target`
    where `target - start` is meant and so doubles the angle on every call; hence
    the difference is worked out in our layer. This test falls over as soon as
    upstream repairs that *and* we start using it again.
    """
    element_id = first_id(kernel)
    before = bounds_mm(kernel, element_id)

    editor.rotate(element_id, 40, absolute=True)
    once = bounds_mm(kernel, element_id)
    assert pose(kernel, element_id)["angle_deg"] == pytest.approx(40.0, abs=0.01)

    editor.rotate(element_id, 40, absolute=True)
    assert bounds_mm(kernel, element_id) == once

    # And back to zero is really back: no drift over a series of rotations.
    editor.rotate(element_id, 0, absolute=True)
    assert bounds_mm(kernel, element_id) == before


def test_absolute_rotation_refuses_a_selection_at_mixed_angles(kernel, editor):
    kernel.console("rect 100mm 10mm 20mm 20mm\n")
    ids = [e["id"] for e in DesignReader(kernel).snapshot()["elements"]]
    editor.rotate(ids[0], 25)

    with pytest.raises(DesignError, match="different angles"):
        editor.rotate(ids, 90, absolute=True)


def test_rotate_over_http(kernel, editor, client):
    element_id = first_id(kernel)
    before = bounds_mm(kernel, element_id)

    response = client.post(
        "/api/design/rotate", json={"ids": [element_id], "angle_deg": 90}
    )

    assert response.status_code == 200
    assert bounds_mm(kernel, element_id) != before


# ------------------------------------------------------ layer assignment

def operations(kernel):
    return DesignReader(kernel).snapshot()["operations"]


def test_assign_puts_an_element_back_in_an_operation(kernel, editor):
    """
    The engine auto-classifies new elements into every operation whose colour
    matches, so an unassigned element has to be made first.
    """
    kernel.console("element* cut -s 12 -p 65\n")
    snapshot = DesignReader(kernel).snapshot()
    element_id = snapshot["elements"][0]["id"]
    operation_id = snapshot["operations"][0]["id"]
    editor.unassign([element_id], operation_id)
    assert operation_id not in _membership(kernel)[element_id]

    result = editor.assign([element_id], operation_id)

    assert result["added"] == 1
    assert operation_id in _membership(kernel)[element_id]


def _membership(kernel):
    return {e["id"]: e["operation_ids"] for e in DesignReader(kernel).snapshot()["elements"]}


def test_assign_is_idempotent(kernel, editor):
    kernel.console("element* cut -s 12 -p 65\n")
    snapshot = DesignReader(kernel).snapshot()
    element_id = snapshot["elements"][0]["id"]
    operation_id = snapshot["operations"][0]["id"]

    editor.assign([element_id], operation_id)
    result = editor.assign([element_id], operation_id)

    assert result["added"] == 0


def test_unassign_removes_the_reference(kernel, editor):
    kernel.console("element* cut -s 12 -p 65\n")
    snapshot = DesignReader(kernel).snapshot()
    element_id = snapshot["elements"][0]["id"]
    operation_id = snapshot["operations"][0]["id"]

    result = editor.unassign([element_id], operation_id)

    assert result["removed"] >= 1
    after = {e["id"]: e["operation_ids"] for e in DesignReader(kernel).snapshot()["elements"]}
    assert operation_id not in after.get(element_id, [])


def test_assign_refuses_a_non_operation(kernel, editor):
    element_id = first_id(kernel)
    with pytest.raises(DesignError):
        editor.assign([element_id], element_id)


def test_assign_over_http(kernel, editor, client):
    kernel.console("element* cut -s 12 -p 65\n")
    snapshot = DesignReader(kernel).snapshot()
    element_id = snapshot["elements"][0]["id"]
    operation_id = snapshot["operations"][0]["id"]
    client.post("/api/design/unassign", json={"ids": [element_id], "operation_id": operation_id})

    response = client.post(
        "/api/design/assign", json={"ids": [element_id], "operation_id": operation_id}
    )

    assert response.status_code == 200
    assert response.json()["added"] == 1


def _count(c):
    return len(c.get("/api/design").json()["elements"])


@pytest.mark.parametrize("beforehand", [0, 25])
def test_undo_after_delete_regardless_of_history_length(kernel, beforehand):
    """
    The engine's stack holds 20 states (`Undo.levels`). Once it is full,
    `validate()` throws the oldest out and every index shifts — while `undo()` has
    already worked out its target index before that validate.
    """
    with TestClient(ApiServer(kernel).build_app()) as c:
        for i in range(beforehand):
            c.post(
                "/api/design/elements",
                json={"type": "rect", "x_mm": 1 + i, "y_mm": 200, "width_mm": 2, "height_mm": 2},
            )
        base = _count(c)
        for i in range(3):
            c.post(
                "/api/design/elements",
                json={"type": "rect", "x_mm": 10 + i * 30, "y_mm": 10, "width_mm": 20, "height_mm": 20},
            )
        assert _count(c) == base + 3
        ids = [e["id"] for e in c.get("/api/design").json()["elements"]]
        c.post("/api/design/elements/delete", json={"ids": [ids[-1]]})
        assert _count(c) == base + 2

        c.post("/api/design/undo", json={})

        assert _count(c) == base + 3
