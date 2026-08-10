"""Drawing shapes and text, and managing layers."""

import pytest
from fastapi.testclient import TestClient

from meerk40t.core.units import UNITS_PER_MM

from openkerf_api.design import DesignReader
from openkerf_api.drawing import Drawing
from openkerf_api.edits import DesignError
from openkerf_api.server import ApiServer


@pytest.fixture
def client(kernel, tmp_path):
    with TestClient(ApiServer(kernel, library_path=tmp_path / "d.db").build_app()) as c:
        yield c


@pytest.fixture
def drawing(kernel):
    return Drawing(kernel)


def bounds_mm(kernel, element_id):
    node = kernel.elements.find_node(element_id)
    return [round(v / UNITS_PER_MM, 1) for v in node.bounds]


# ---------------------------------------------------------------- shapes

def test_rect_lands_where_it_was_asked_for(kernel, drawing):
    result = drawing.create("rect", x_mm=20, y_mm=15, width_mm=60, height_mm=40)

    assert bounds_mm(kernel, result["ids"][0]) == [20.0, 15.0, 80.0, 55.0]
    assert result["type"] == "elem rect"


def test_circle_and_ellipse(kernel, drawing):
    circle = drawing.create("circle", cx_mm=50, cy_mm=50, r_mm=10)
    ellipse = drawing.create("ellipse", cx_mm=120, cy_mm=50, rx_mm=20, ry_mm=10)

    assert bounds_mm(kernel, circle["ids"][0]) == [40.0, 40.0, 60.0, 60.0]
    assert bounds_mm(kernel, ellipse["ids"][0]) == [100.0, 40.0, 140.0, 60.0]


def test_line(kernel, drawing):
    line = drawing.create("line", x1_mm=10, y1_mm=10, x2_mm=40, y2_mm=30)

    assert bounds_mm(kernel, line["ids"][0]) == [10.0, 10.0, 40.0, 30.0]


def test_text_becomes_vector_geometry(kernel, drawing):
    """Bitmap text has no geometry, so it would be invisible on the canvas."""
    result = drawing.create("text", x_mm=20, y_mm=40, text="OpenKerf")

    node = kernel.elements.find_node(result["ids"][0])
    assert node.bounds is not None
    assert hasattr(node, "as_geometry")
    snapshot = DesignReader(kernel).snapshot()
    assert any(e["id"] == result["ids"][0] and e["path"] for e in snapshot["elements"])


def test_empty_text_is_refused(drawing):
    for bad in ("", "   ", None):
        with pytest.raises(DesignError):
            drawing.create("text", x_mm=10, y_mm=10, text=bad)


def test_unknown_shape_is_refused(drawing):
    with pytest.raises(DesignError):
        drawing.create("driehoek", x_mm=1, y_mm=1, width_mm=1, height_mm=1)


def test_sizes_must_be_positive(drawing):
    with pytest.raises(DesignError):
        drawing.create("rect", x_mm=10, y_mm=10, width_mm=0, height_mm=10)
    with pytest.raises(DesignError):
        drawing.create("circle", cx_mm=10, cy_mm=10, r_mm=-5)


def test_a_new_shape_is_selected(kernel, drawing):
    """So you can drag or resize it straight away."""
    result = drawing.create("rect", x_mm=10, y_mm=10, width_mm=10, height_mm=10)

    emphasized = [n.id for n in kernel.elements.elems(emphasized=True)]
    assert emphasized == result["ids"]


def test_drawing_is_undoable(kernel, drawing, client):
    drawing.create("rect", x_mm=10, y_mm=10, width_mm=10, height_mm=10)
    assert len(list(kernel.elements.elems())) == 1

    client.post("/api/design/undo")

    assert len(list(kernel.elements.elems())) == 0


# --------------------------------------------------------- delete/duplicate

def test_delete_removes_only_the_named_elements(kernel, drawing):
    keep = drawing.create("rect", x_mm=10, y_mm=10, width_mm=10, height_mm=10)
    drop = drawing.create("rect", x_mm=40, y_mm=10, width_mm=10, height_mm=10)

    drawing.delete(drop["ids"])

    remaining = [n.id for n in kernel.elements.elems()]
    assert remaining == keep["ids"]


def test_delete_of_a_stale_id_is_refused(drawing):
    with pytest.raises(DesignError):
        drawing.delete(["meerk40t:bestaatniet"])


def test_duplicate_adds_a_copy(kernel, drawing):
    original = drawing.create("rect", x_mm=10, y_mm=10, width_mm=20, height_mm=20)

    copy = drawing.duplicate(original["ids"])

    assert len(list(kernel.elements.elems())) == 2
    assert copy["ids"] != original["ids"]
    assert bounds_mm(kernel, copy["ids"][0]) == bounds_mm(kernel, original["ids"][0])


# ---------------------------------------------------------------- layers

def test_create_a_layer_with_settings(kernel, drawing):
    result = drawing.create_operation("cut", label="Buitenrand", speed=12, power_percent=65)

    node = kernel.elements.find_node(result["id"])
    assert node.type == "op cut"
    assert node.label == "Buitenrand"
    assert node.speed == 12
    # 0-1000 in the engine, percent on the wire.
    assert node.power == 650


def test_layer_types(kernel, drawing):
    for kind, expected in (
        ("cut", "op cut"),
        ("engrave", "op engrave"),
        ("raster", "op raster"),
        ("dots", "op dots"),
    ):
        result = drawing.create_operation(kind)
        assert kernel.elements.find_node(result["id"]).type == expected


def test_unknown_layer_type_is_refused(drawing):
    with pytest.raises(DesignError):
        drawing.create_operation("laser-beam")


def test_update_a_layer(kernel, drawing):
    created = drawing.create_operation("cut", speed=10, power_percent=50)

    drawing.update_operation(
        created["id"], label="Snijden fijn", speed=8, power_percent=70, passes=2, output=False
    )

    node = kernel.elements.find_node(created["id"])
    assert node.label == "Snijden fijn"
    assert node.speed == 8
    assert node.power == 700
    assert node.passes == 2
    assert node.output is False


def test_power_outside_the_range_is_refused(drawing):
    created = drawing.create_operation("cut")
    for bad in (0, -10, 150):
        with pytest.raises(DesignError):
            drawing.update_operation(created["id"], power_percent=bad)


def test_delete_a_layer_keeps_the_elements(kernel, drawing):
    element = drawing.create("rect", x_mm=10, y_mm=10, width_mm=10, height_mm=10)
    layer = drawing.create_operation("cut", speed=10, power_percent=50)
    kernel.elements.find_node(layer["id"]).add_reference(
        kernel.elements.find_node(element["ids"][0])
    )

    drawing.delete_operation(layer["id"])

    assert kernel.elements.find_node(layer["id"]) is None
    assert kernel.elements.find_node(element["ids"][0]) is not None


def test_an_element_is_not_a_layer(kernel, drawing):
    element = drawing.create("rect", x_mm=10, y_mm=10, width_mm=10, height_mm=10)
    with pytest.raises(DesignError):
        drawing.delete_operation(element["ids"][0])


# ------------------------------------------------------------------- HTTP

def test_draw_over_http(kernel, client):
    response = client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 20, "y_mm": 15, "width_mm": 60, "height_mm": 40},
    )

    assert response.status_code == 201
    assert bounds_mm(kernel, response.json()["ids"][0]) == [20.0, 15.0, 80.0, 55.0]


def test_layer_lifecycle_over_http(kernel, client):
    created = client.post(
        "/api/design/operations", json={"type": "engrave", "label": "Tekst", "speed": 200}
    )
    assert created.status_code == 201
    layer_id = created.json()["id"]

    patched = client.patch(f"/api/design/operations/{layer_id}", json={"power_percent": 25})
    assert patched.status_code == 200
    assert kernel.elements.find_node(layer_id).power == 250

    removed = client.delete(f"/api/design/operations/{layer_id}")
    assert removed.status_code == 200
    assert kernel.elements.find_node(layer_id) is None


def test_bad_shape_over_http_is_a_409(client):
    response = client.post("/api/design/elements", json={"type": "rect", "x_mm": "kaas"})
    assert response.status_code == 409


def test_a_new_empty_layer_stays_visible(kernel, client):
    """
    A fresh element tree carries 201 empty default operations, so empty layers
    are normally hidden. A layer you just created yourself must not vanish
    before you have put anything in it.
    """
    before = len(client.get("/api/design").json()["operations"])

    created = client.post("/api/design/operations", json={"type": "cut", "label": "Nieuw"})

    operations = client.get("/api/design").json()["operations"]
    assert len(operations) == before + 1
    assert any(o["id"] == created.json()["id"] for o in operations)


def test_the_default_stack_stays_hidden(kernel, client):
    """Showing every empty operation would flood the list with 201 entries."""
    operations = client.get("/api/design").json()["operations"]
    assert len(operations) < 10


def test_a_removed_layer_disappears_again(kernel, client):
    created = client.post("/api/design/operations", json={"type": "cut"}).json()
    assert any(o["id"] == created["id"] for o in client.get("/api/design").json()["operations"])

    client.delete(f"/api/design/operations/{created['id']}")

    assert not any(
        o["id"] == created["id"] for o in client.get("/api/design").json()["operations"]
    )
