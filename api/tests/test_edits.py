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
        f"/api/design/elements/{element_id}/move", json={"dx_mm": 5, "dy_mm": 0}
    )

    assert response.status_code == 200
    assert bounds_mm(kernel, element_id) == [25.0, 15.0, 85.0, 55.0]


def test_bad_payload_is_a_409(kernel, editor, client):
    element_id = first_id(kernel)

    response = client.post(
        f"/api/design/elements/{element_id}/move", json={"dx_mm": "kaas", "dy_mm": 0}
    )

    assert response.status_code == 409


def test_undo_over_http(kernel, editor, client):
    element_id = first_id(kernel)
    client.post(f"/api/design/elements/{element_id}/move", json={"dx_mm": 5, "dy_mm": 0})

    response = client.post("/api/design/undo")

    assert response.status_code == 200
    assert response.json()["ids_invalidated"] is True
