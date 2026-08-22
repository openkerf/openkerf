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
    A rectangle is parameters, not points. If it becomes a path, the operation has
    to come along — otherwise it stops burning without anybody seeing it.
    """
    operation = client.post(
        "/api/design/operations", json={"type": "cut", "label": "Cut"}
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
    """A path does not have to be replaced, so it keeps its id."""
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


# ------------------------------------------------------------------- curves (P1)


def box_of(client, element_id):
    """The bounding box in millimetres — the cheapest way to ask "did it move?"."""
    design = client.get("/api/design").json()
    per_mm = design["units_per_mm"]
    element = next(e for e in design["elements"] if e["id"] == element_id)
    return [v / per_mm for v in element["bounds"]]


@pytest.fixture
def bend(client):
    """A path of one quadratic curve and one straight piece: 3 anchors, 2 segments."""
    return client.post(
        "/api/design/path",
        json={"points": [[10, 10], [60, 10, 35, 60], [110, 10]]},
    ).json()["ids"][0]


def test_a_segment_says_what_kind_it_is_and_where_its_handle_is(client, bend):
    """
    Without this the node tool could not draw a handle, let alone drag one.

    Measured before: the answer named the three anchors and the control point (35, 60)
    appeared nowhere in it.
    """
    result = client.get(f"/api/design/elements/{bend}/nodes").json()

    kinds = [s["kind"] for s in result["segments"]]
    assert kinds == ["quad", "line"]
    curve = result["segments"][0]
    assert (curve["start"], curve["end"]) == (0, 1)
    handle = curve["controls"][0]
    assert (round(handle["x_mm"]), round(handle["y_mm"])) == (35, 60)
    assert result["segments"][1]["controls"] == []
    assert result["closed"] is False


def test_a_rectangle_is_closed_and_a_line_is_not(client, rect):
    assert client.get(f"/api/design/elements/{rect}/nodes").json()["closed"] is True

    line = client.post(
        "/api/design/elements",
        json={"type": "line", "x1_mm": 0, "y1_mm": 0, "x2_mm": 20, "y2_mm": 0},
    ).json()["ids"][0]
    assert client.get(f"/api/design/elements/{line}/nodes").json()["closed"] is False


def test_a_double_click_puts_a_node_where_it_landed(client, rect):
    """The canvas knows where the click was and nothing else, so it sends millimetres."""
    added = client.post(
        f"/api/design/elements/{rect}/nodes", json={"x_mm": 30, "y_mm": 10}
    )

    assert added.status_code == 200
    result = client.get(f"/api/design/elements/{added.json()['id']}/nodes").json()
    corners = {(round(p["x_mm"]), round(p["y_mm"])) for p in result["points"]}
    assert corners == {(10, 10), (30, 10), (50, 10), (50, 30), (10, 30)}
    # And it is the node it says it is: the caller selects that one afterwards.
    new = next(p for p in result["points"] if p["index"] == added.json()["index"])
    assert (round(new["x_mm"]), round(new["y_mm"])) == (30, 10)


def test_the_menu_asks_for_the_middle_of_a_segment(client, rect):
    added = client.post(
        f"/api/design/elements/{rect}/nodes", json={"segment_index": 0}
    ).json()

    points = client.get(f"/api/design/elements/{added['id']}/nodes").json()["points"]
    new = next(p for p in points if p["index"] == added["index"])
    assert (round(new["x_mm"]), round(new["y_mm"])) == (30, 10)


def test_a_node_on_an_arc_keeps_the_arc(kernel, nodes):
    """
    `Geomstr.split` hands back zero pieces for an arc (upstream #3263), so splitting it
    ourselves is the only way. Without that the quarter the node landed on disappeared.

    Straight from a Geomstr and not through the `circle` command: measured, an
    `elem ellipse` hands back thirteen cubics from `as_geometry()` and no arc at all. Arcs
    reach us through an imported path with an `A` in it, and that is what this is.
    """
    from meerk40t.core.geomstr import Geomstr
    from meerk40t.core.units import UNITS_PER_MM

    circle = Geomstr.circle(20 * UNITS_PER_MM, 50 * UNITS_PER_MM, 50 * UNITS_PER_MM)
    node = kernel.elements.elem_branch.add(
        geometry=circle, type="elem path", stroke="blue"
    )
    kernel.elements.validate_ids()
    before = [v / UNITS_PER_MM for v in circle.bbox()]

    added = nodes.insert_point(node.id, 0, 0.5)

    result = nodes.points(added["id"])
    assert [s["kind"] for s in result["segments"]] == ["arc"] * 5
    geometry = kernel.elements.find_node(added["id"]).as_geometry()
    assert [v / UNITS_PER_MM for v in geometry.bbox()] == pytest.approx(before, abs=0.01)


def test_removing_a_node_joins_what_met_there(client, rect):
    added = client.post(
        f"/api/design/elements/{rect}/nodes", json={"x_mm": 30, "y_mm": 10}
    ).json()

    removed = client.delete(
        f"/api/design/elements/{added['id']}/nodes/{added['index']}"
    )

    assert removed.status_code == 200
    result = client.get(f"/api/design/elements/{removed.json()['id']}/nodes").json()
    corners = {(round(p["x_mm"]), round(p["y_mm"])) for p in result["points"]}
    assert corners == {(10, 10), (50, 10), (50, 30), (10, 30)}
    assert [s["kind"] for s in result["segments"]] == ["line"] * 4


def test_removing_the_end_of_an_open_path_shortens_it(client, bend):
    """An end node has one segment, so taking it away takes that segment away."""
    removed = client.delete(f"/api/design/elements/{bend}/nodes/2").json()

    result = client.get(f"/api/design/elements/{removed['id']}/nodes").json()
    assert [s["kind"] for s in result["segments"]] == ["quad"]
    assert len(result["points"]) == 2


def test_the_last_two_points_of_an_open_path_cannot_be_removed(client):
    line = client.post(
        "/api/design/elements",
        json={"type": "line", "x1_mm": 0, "y1_mm": 0, "x2_mm": 20, "y2_mm": 0},
    ).json()["ids"][0]

    refused = client.delete(f"/api/design/elements/{line}/nodes/0")

    assert refused.status_code == 409
    assert refused.headers["X-OpenKerf-Error"] == "nodes.openNeedsTwo"


def test_a_closed_shape_keeps_three_points(client):
    triangle = client.post(
        "/api/design/path",
        json={"points": [[0, 0], [40, 0], [20, 30]], "closed": True},
    ).json()["ids"][0]

    refused = client.delete(f"/api/design/elements/{triangle}/nodes/0")

    assert refused.status_code == 409
    assert refused.headers["X-OpenKerf-Error"] == "nodes.closedNeedsThree"


def test_a_node_that_is_not_there_cannot_be_removed(client, rect):
    refused = client.delete(f"/api/design/elements/{rect}/nodes/9")

    assert refused.status_code == 409
    assert refused.headers["X-OpenKerf-Error"] == "nodes.noSuchNode"


def test_a_corner_becomes_a_curve_and_back_without_moving(client, rect):
    """
    Turning a corner into a curve must not move a millimetre: the handles land on the
    chord, so the picture is the same and there is now something to drag.
    """
    before = box_of(client, rect)

    curved = client.patch(
        f"/api/design/elements/{rect}/segments/0/kind", json={"kind": "quad"}
    )

    assert curved.status_code == 200
    new_id = curved.json()["id"]
    result = client.get(f"/api/design/elements/{new_id}/nodes").json()
    assert [s["kind"] for s in result["segments"]] == ["quad", "line", "line", "line"]
    assert box_of(client, new_id) == pytest.approx(before, abs=0.01)

    back = client.patch(
        f"/api/design/elements/{new_id}/segments/0/kind", json={"kind": "line"}
    ).json()
    kinds = [
        s["kind"]
        for s in client.get(f"/api/design/elements/{back['id']}/nodes").json()["segments"]
    ]
    assert kinds == ["line"] * 4


def test_a_curve_keeps_its_shape_between_quad_and_cubic(client, bend):
    """
    A quad *is* a cubic with its handles two thirds of the way out from each end, so
    going over must not move the curve. The handles are the measurement here and not the
    bounding box: `Geomstr._bbox_segment` reads a symmetric cubic as flat (the test for a
    vanishing denominator compares an absolute 1e-12 against numbers of the order 1e5, so
    the cancellation at Tat scale does not register). Measured on this very curve: the
    quad said 10→35 mm in y and the identical cubic said 10→10.
    """
    cubic = client.patch(
        f"/api/design/elements/{bend}/segments/0/kind", json={"kind": "cubic"}
    ).json()

    result = client.get(f"/api/design/elements/{cubic['id']}/nodes").json()
    assert [s["kind"] for s in result["segments"]] == ["cubic", "line"]
    first, second = result["segments"][0]["controls"]
    # (10,10) → (60,10) with the quad's control at (35,60): two thirds of the way from
    # each end is (26.67, 43.33) and (43.33, 43.33).
    assert (round(first["x_mm"], 1), round(first["y_mm"], 1)) == (26.7, 43.3)
    assert (round(second["x_mm"], 1), round(second["y_mm"], 1)) == (43.3, 43.3)
    # And the anchors did not budge.
    assert {(round(p["x_mm"]), round(p["y_mm"])) for p in result["points"]} == {
        (10, 10),
        (60, 10),
        (110, 10),
    }


def test_an_unknown_kind_is_refused(client, rect):
    refused = client.patch(
        f"/api/design/elements/{rect}/segments/0/kind", json={"kind": "spiral"}
    )

    assert refused.status_code == 409
    assert refused.headers["X-OpenKerf-Error"] == "nodes.unknownKind"


def test_a_segment_that_is_not_there_is_refused(client, rect):
    refused = client.patch(
        f"/api/design/elements/{rect}/segments/9/kind", json={"kind": "quad"}
    )

    assert refused.status_code == 409
    assert refused.headers["X-OpenKerf-Error"] == "nodes.noSuchSegment"


def test_dragging_a_handle_bends_the_curve(client, bend):
    moved = client.patch(
        f"/api/design/elements/{bend}/segments/0/control",
        json={"which": 1, "x_mm": 35, "y_mm": -40},
    )

    assert moved.status_code == 200
    result = client.get(f"/api/design/elements/{moved.json()['id']}/nodes").json()
    handle = result["segments"][0]["controls"][0]
    assert (round(handle["x_mm"]), round(handle["y_mm"])) == (35, -40)
    # The anchors stayed exactly where they were; a handle moves the curve, not the path.
    assert {(round(p["x_mm"]), round(p["y_mm"])) for p in result["points"]} == {
        (10, 10),
        (60, 10),
        (110, 10),
    }


def test_a_straight_segment_has_no_handle(client, rect):
    refused = client.patch(
        f"/api/design/elements/{rect}/segments/0/control",
        json={"which": 1, "x_mm": 30, "y_mm": 0},
    )

    assert refused.status_code == 409
    assert refused.headers["X-OpenKerf-Error"] == "nodes.noHandle"


def test_a_cubic_has_two_handles_that_move_separately(client, bend):
    cubic = client.patch(
        f"/api/design/elements/{bend}/segments/0/kind", json={"kind": "cubic"}
    ).json()

    client.patch(
        f"/api/design/elements/{cubic['id']}/segments/0/control",
        json={"which": 2, "x_mm": 55, "y_mm": 40},
    )

    controls = client.get(f"/api/design/elements/{cubic['id']}/nodes").json()["segments"][
        0
    ]["controls"]
    first, second = controls
    assert (round(second["x_mm"]), round(second["y_mm"])) == (55, 40)
    assert (round(first["x_mm"]), round(first["y_mm"])) != (55, 40)


def test_dragging_an_anchor_carries_its_handle_along(client, bend):
    """
    Before P1 the handle stayed behind, and then dragging one end of a curve deformed it
    instead of carrying it. Half the movement on a quad's control makes every point of the
    curve move by `shift · (1 − t)`: everything at the anchor, nothing at the far end.
    """
    moved = client.patch(
        f"/api/design/elements/{bend}/nodes", json={"index": 0, "x_mm": 10, "y_mm": 30}
    ).json()

    result = client.get(f"/api/design/elements/{moved['id']}/nodes").json()
    handle = result["segments"][0]["controls"][0]
    assert (round(handle["x_mm"]), round(handle["y_mm"])) == (35, 70)


def test_a_curved_rectangle_keeps_its_layer(client, rect):
    """The rect→path promise holds for the new routes too, or the shape stops burning."""
    operation = client.post(
        "/api/design/operations", json={"type": "cut", "label": "Cut"}
    ).json()
    client.post("/api/design/assign", json={"ids": [rect], "operation_id": operation["id"]})

    curved = client.patch(
        f"/api/design/elements/{rect}/segments/0/kind", json={"kind": "quad"}
    ).json()

    element = next(
        e
        for e in client.get("/api/design").json()["elements"]
        if e["id"] == curved["id"]
    )
    assert element["type"] == "elem path"
    assert operation["id"] in element["operation_ids"]


def test_an_image_has_no_segments_to_bend(kernel, nodes, tmp_path):
    from PIL import Image

    path = tmp_path / "curve.png"
    Image.new("RGB", (10, 10), "white").save(path, "PNG")
    kernel.console(f"load {path}\n")
    node = next(n for n in kernel.elements.elems() if n.type == "elem image")

    with pytest.raises(DesignError):
        nodes.insert_point(node.id, None, None, 1, 1)
    with pytest.raises(DesignError):
        nodes.set_kind(node.id, 0, "quad")


# ── A path of several subpaths ────────────────────────────────────────────────────
#
# The shape the node tool exists for: text turned into outlines, or an import from a CAD
# program. Measured before this fix on the `elem path` that `text "Hi"` leaves behind
# (24 rows, 3 subpaths): the route answered HTTP 500 because eight of the reported anchors
# were `nan`, and `nan` is not JSON.


@pytest.fixture
def letters(client):
    created = client.post(
        "/api/design/elements", json={"type": "text", "x_mm": 10, "y_mm": 30, "text": "Hi"}
    ).json()
    return created["ids"][0]


def test_a_path_of_several_subpaths_reports_only_real_anchors(client, letters):
    """
    The end markers between subpaths hold `nan` in every column. Walking them gave 28
    anchors of which 8 were `nan` and shifted the honest ones to start at index 2, so the
    segments' `start`/`end` pointed at nothing.
    """
    answer = client.get(f"/api/design/elements/{letters}/nodes")

    assert answer.status_code == 200
    result = answer.json()
    assert result["editable"] is True
    assert len(result["points"]) == 20
    assert all(
        p["x_mm"] == p["x_mm"] and p["y_mm"] == p["y_mm"] for p in result["points"]
    )
    # Every segment names two anchors that exist.
    numbering = {p["index"] for p in result["points"]}
    assert all(
        s["start"] in numbering and s["end"] in numbering for s in result["segments"]
    )


def test_a_shape_whose_every_subpath_closes_is_closed(client, letters):
    """
    Read off the first and the last row of the whole shape this said `false`, and on that
    answer a closed loop could be worn down to two points.
    """
    assert client.get(f"/api/design/elements/{letters}/nodes").json()["closed"] is True


def test_a_node_of_a_subpath_can_be_moved_and_removed(client, letters):
    moved = client.patch(
        f"/api/design/elements/{letters}/nodes", json={"index": 0, "x_mm": 20, "y_mm": 40}
    )

    assert moved.status_code == 200
    after = client.get(f"/api/design/elements/{moved.json()['id']}/nodes").json()
    assert (round(after["points"][0]["x_mm"]), round(after["points"][0]["y_mm"])) == (20, 40)
    # And the other subpaths are still there: 20 anchors, not the 12 of the first loop.
    assert len(after["points"]) == 20

    removed = client.delete(f"/api/design/elements/{moved.json()['id']}/nodes/0")
    assert removed.status_code == 200
    assert len(client.get(f"/api/design/elements/{removed.json()['id']}/nodes").json()["points"]) == 19


def test_an_open_subpath_beside_a_closed_one_is_not_closed(nodes):
    """A shape closes only if all of its loops do — otherwise "closed" says too much."""
    from meerk40t.core.geomstr import Geomstr

    # In Tats, because `SAME_POINT` is 30 Tats — roughly a hundredth of a millimetre —
    # and at a scale of tens of units two different corners would count as one point.
    geometry = Geomstr()
    geometry.polyline([0 + 0j, 40000 + 0j, 20000 + 30000j, 0 + 0j])
    geometry.end()
    geometry.polyline([60000 + 0j, 80000 + 0j, 80000 + 20000j])

    assert nodes._closed(geometry) is False
    assert len(nodes._unique(geometry)) == 6
