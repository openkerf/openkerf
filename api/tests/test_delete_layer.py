"""
Removing a layer that still holds shapes, and merging it into another one.

The report (after an import that made too many layers): "I cannot delete layers that
have objects in them — no message, it simply doesn't do it."

Measured before the fix, on this suite's kernel: an SVG with a red and a blue square
loads into two layers (E1 engrave, C1 cut) with one shape each, and
`DELETE /api/design/operations/E1` answers **200** `{"removed": "E1"}`; the layer is
gone and its square is in no layer. So the API never refused. The silence was in the
panel: the row menu's *Remove layer* set the question to open, but the question was
drawn inside the layer's settings fold — closed unless you had unfolded that layer, so
the click changed nothing on screen. (`DesignPanel.svelte`, `confirmDrop`.)

What this file holds down for the API half: removing still works and leaves the shapes
on the bed in no layer, and the new merge moves them into another layer and removes the
emptied one in one step, refusing — before anything moves — what it cannot do.
"""

import pytest
from fastapi.testclient import TestClient

from openkerf_api.server import ApiServer


@pytest.fixture
def client(kernel, tmp_path):
    with TestClient(ApiServer(kernel, library_path=tmp_path / "d.db").build_app()) as c:
        yield c


def _square(client, x):
    response = client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": x, "y_mm": 10, "width_mm": 20, "height_mm": 20},
    )
    assert response.status_code == 201
    return response.json()["ids"][0]


def _layer(client, kind, label):
    response = client.post("/api/design/operations", json={"type": kind, "label": label})
    assert response.status_code == 201
    return response.json()["id"]


def _design(client):
    return client.get("/api/design").json()


def _op(design, layer_id):
    return next((o for o in design["operations"] if o["id"] == layer_id), None)


def _two_cut_layers(client):
    """Two cut layers as an import leaves them: one shape each, plus one in both."""
    a, b, both = _square(client, 10), _square(client, 40), _square(client, 70)
    # A drawn square lands in the colour's layer by itself; start from none.
    assert client.delete("/api/design/operations").status_code == 200
    keep = _layer(client, "cut", "Cut")
    drop = _layer(client, "cut", "Cut 2")
    assert client.post("/api/design/assign", json={"ids": [a, both], "operation_id": keep}).status_code == 200
    assert client.post("/api/design/assign", json={"ids": [b, both], "operation_id": drop}).status_code == 200
    return keep, drop, a, b, both


def test_removing_a_layer_with_shapes_works_and_leaves_them_in_no_layer(client):
    """The API side was never the silent one: 200, and the shape stays on the bed."""
    keep, drop, a, b, both = _two_cut_layers(client)

    response = client.delete(f"/api/design/operations/{drop}")

    assert response.status_code == 200
    design = _design(client)
    assert _op(design, drop) is None
    shapes = {e["id"]: e for e in design["elements"]}
    assert b in shapes, "the shape went with its layer"
    assert shapes[b]["operation_ids"] == []
    assert shapes[both]["operation_ids"] == [keep]


def test_merging_moves_the_shapes_and_removes_the_layer(client):
    keep, drop, a, b, both = _two_cut_layers(client)

    response = client.post(f"/api/design/operations/{drop}/merge-into/{keep}")

    assert response.status_code == 200
    # `both` was in the target already; it is not added a second time.
    assert response.json() == {"removed": drop, "into": keep, "moved": 1, "already_there": 1}
    design = _design(client)
    assert _op(design, drop) is None
    assert sorted(_op(design, keep)["element_ids"]) == sorted([a, b, both])
    for shape in design["elements"]:
        assert shape["operation_ids"] == [keep], f"{shape['id']} sits in {shape['operation_ids']}"


def test_one_undo_brings_both_layers_back(client):
    keep, drop, *_ = _two_cut_layers(client)
    before = sorted(len(o["element_ids"]) for o in _design(client)["operations"])

    client.post(f"/api/design/operations/{drop}/merge-into/{keep}")
    assert client.post("/api/design/undo").status_code == 200

    # Undo renumbers the nodes, so compare by what the layers hold, not by id.
    after = sorted(len(o["element_ids"]) for o in _design(client)["operations"])
    assert after == before == [2, 2]


def test_merging_a_layer_into_itself_is_refused_with_a_code(client):
    keep, *_ = _two_cut_layers(client)

    response = client.post(f"/api/design/operations/{keep}/merge-into/{keep}")

    assert response.status_code == 409
    assert response.headers["X-OpenKerf-Error"] == "layer.mergeSelf"
    assert _op(_design(client), keep) is not None


def test_a_dots_layer_refuses_squares_and_nothing_moves(client):
    """
    A dots layer takes points only. Without the check the engine drops the squares on
    `add_reference` without a word and the source layer would be removed anyway —
    the shapes then in no layer, which is the silent loss this route exists to avoid.
    """
    keep, drop, a, b, both = _two_cut_layers(client)
    dots = _layer(client, "dots", "Dots")

    response = client.post(f"/api/design/operations/{drop}/merge-into/{dots}")

    assert response.status_code == 409
    assert response.headers["X-OpenKerf-Error"] == "layer.mergeWontHold"
    assert '"n": 2' in response.headers["X-OpenKerf-Error-Values"]
    design = _design(client)
    assert sorted(_op(design, drop)["element_ids"]) == sorted([b, both])


def test_merging_into_a_layer_that_is_gone_is_refused(client):
    keep, drop, *_ = _two_cut_layers(client)
    client.delete(f"/api/design/operations/{keep}")

    response = client.post(f"/api/design/operations/{drop}/merge-into/{keep}")

    assert response.status_code == 409
    assert _op(_design(client), drop) is not None
