"""Knooppunten bewerken: één hoek verleggen zonder de rest te verliezen."""

import pytest
from fastapi.testclient import TestClient

from openkerf_api.edits import DesignError
from openkerf_api.nodes import Nodes
from openkerf_api.server import ApiServer


@pytest.fixture
def client(kernel, tmp_path):
    with TestClient(ApiServer(kernel, library_path=tmp_path / "n.db").build_app()) as c:
        yield c


@pytest.fixture
def nodes(kernel):
    return Nodes(kernel)


@pytest.fixture
def rect(client):
    created = client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 10, "y_mm": 10, "width_mm": 40, "height_mm": 20},
    ).json()
    return created["ids"][0]


def test_a_rectangle_has_four_corners(client, rect):
    result = client.get(f"/api/design/elements/{rect}/nodes").json()

    assert result["editable"] is True
    corners = {(round(p["x_mm"]), round(p["y_mm"])) for p in result["points"]}
    assert corners == {(10, 10), (50, 10), (50, 30), (10, 30)}


def test_moving_a_corner_moves_only_that_corner(client, rect):
    before = client.get(f"/api/design/elements/{rect}/nodes").json()["points"]
    corner = next(p for p in before if round(p["x_mm"]) == 10 and round(p["y_mm"]) == 10)

    response = client.patch(
        f"/api/design/elements/{rect}/nodes",
        json={"index": corner["index"], "x_mm": 0, "y_mm": 0},
    )

    assert response.status_code == 200
    new_id = response.json()["id"]
    after = {
        (round(p["x_mm"]), round(p["y_mm"]))
        for p in client.get(f"/api/design/elements/{new_id}/nodes").json()["points"]
    }
    assert after == {(0, 0), (50, 10), (50, 30), (10, 30)}


def test_a_moved_rectangle_becomes_a_path_but_keeps_its_layer(client, rect):
    """
    Een rechthoek is parameters, geen punten. Wordt hij een pad, dan moet de
    bewerking mee — anders brandt hij niet meer mee zonder dat iemand dat ziet.
    """
    operation = client.post(
        "/api/design/operations", json={"type": "cut", "label": "Snijden"}
    ).json()
    client.post("/api/design/assign", json={"ids": [rect], "operation_id": operation["id"]})

    moved = client.patch(
        f"/api/design/elements/{rect}/nodes", json={"index": 0, "x_mm": 5, "y_mm": 5}
    ).json()

    design = client.get("/api/design").json()
    element = next(e for e in design["elements"] if e["id"] == moved["id"])
    assert element["type"] == "elem path"
    assert operation["id"] in element["operation_ids"]


def test_a_path_keeps_its_identity(client):
    """Een pad hoeft niet vervangen te worden, dus houdt het zijn id."""
    line = client.post(
        "/api/design/elements",
        json={"type": "line", "x1_mm": 0, "y1_mm": 0, "x2_mm": 20, "y2_mm": 0},
    ).json()["ids"][0]

    first = client.patch(
        f"/api/design/elements/{line}/nodes", json={"index": 1, "x_mm": 20, "y_mm": 10}
    ).json()
    second = client.patch(
        f"/api/design/elements/{first['id']}/nodes",
        json={"index": 1, "x_mm": 25, "y_mm": 10},
    ).json()

    assert second["id"] == first["id"]
    points = client.get(f"/api/design/elements/{second['id']}/nodes").json()["points"]
    assert (round(points[1]["x_mm"]), round(points[1]["y_mm"])) == (25, 10)


def test_a_nonexistent_corner_is_refused(client, rect):
    response = client.patch(
        f"/api/design/elements/{rect}/nodes", json={"index": 9, "x_mm": 0, "y_mm": 0}
    )
    assert response.status_code == 409


def test_an_image_has_no_corners_to_drag(kernel, nodes, tmp_path):
    from PIL import Image

    path = tmp_path / "knoop.png"
    Image.new("RGB", (10, 10), "white").save(path, "PNG")
    kernel.console(f"load {path}\n")
    node = next(n for n in kernel.elements.elems() if n.type == "elem image")

    with pytest.raises(DesignError):
        nodes.move_point(node.id, 0, 1, 1)
