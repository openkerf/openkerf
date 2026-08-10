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
    for bad in ("kaas", None, float("inf")):
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
        "/api/design/move", json={"ids": [element_id], "dx_mm": "kaas", "dy_mm": 0}
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
        editor.rotate(first_id(kernel), "scheef")


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
