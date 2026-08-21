"""
Filling a shape, so that a raster layer makes an area of it.

Why this exists: a square you draw in OpenKerf has `fill = None`, and our
rasteriser only fills what has a fill. Measured before this action: in a raster
layer such a square came out 8 % black on an image of 100×100 pixels — that is
the outline, not the area. The engine has a command for it (`fill <colour>`,
`core/elements/shapes.py:1905`); we used it nowhere.
"""

import pytest
from fastapi.testclient import TestClient

from openkerf_api.drawing import Drawing, _is_filled
from openkerf_api.edits import DesignError
from openkerf_api.rasterizer import make_raster
from openkerf_api.server import ApiServer


@pytest.fixture
def client(kernel, tmp_path):
    with TestClient(ApiServer(kernel, library_path=tmp_path / "d.db").build_app()) as c:
        yield c


@pytest.fixture
def drawing(kernel):
    return Drawing(kernel)


def black_percentage(kernel, element_id: str) -> float:
    """How much of the area our rasteriser makes black."""
    node = kernel.elements.find_node(element_id)
    image = make_raster([node], node.bounds, 100, 100, None, 1, 1, True).convert("L")
    dark = sum(1 for pixel in image.getdata() if pixel < 128)
    return dark / 100.0


# ------------------------------------------------------------------ the reason


def test_a_drawn_square_is_an_outline_until_you_fill_it(kernel, drawing):
    """The measurement that explains this whole action."""
    shape = drawing.create("rect", x_mm=10, y_mm=10, width_mm=20, height_mm=20)
    node = kernel.elements.find_node(shape["ids"][0])

    assert node.fill is None
    assert _is_filled(node) is False
    assert black_percentage(kernel, shape["ids"][0]) < 20


# ----------------------------------------------------------------- filling


def test_filling_a_square_makes_a_face_of_it(kernel, drawing):
    shape = drawing.create("rect", x_mm=10, y_mm=10, width_mm=20, height_mm=20)

    result = drawing.fill(shape["ids"])

    node = kernel.elements.find_node(shape["ids"][0])
    assert _is_filled(node) is True
    assert result["filled"] == 1
    assert black_percentage(kernel, shape["ids"][0]) > 90


def test_the_fill_takes_the_colour_the_shape_already_has(kernel, drawing):
    """
    The same colour as the stroke, and not simply black.

    In MeerK40t the colour *is* what classification works on; a fill in a different
    colour could land the shape in a different layer from its own stroke at the
    next classification.
    """
    shape = drawing.create("rect", x_mm=10, y_mm=10, width_mm=20, height_mm=20)
    node = kernel.elements.find_node(shape["ids"][0])
    stroke = str(node.stroke)

    drawing.fill(shape["ids"])

    assert str(node.fill).lower() == stroke.lower()


def test_a_colour_can_be_given(kernel, drawing):
    shape = drawing.create("rect", x_mm=10, y_mm=10, width_mm=20, height_mm=20)

    drawing.fill(shape["ids"], color="#ff8800")

    assert str(kernel.elements.find_node(shape["ids"][0]).fill).lower() == "#ff8800"


def test_a_bad_colour_is_refused(drawing):
    shape = drawing.create("rect", x_mm=10, y_mm=10, width_mm=20, height_mm=20)

    with pytest.raises(DesignError):
        drawing.fill(shape["ids"], color="orange-ish")


def test_the_fill_can_be_taken_away_again(kernel, drawing):
    shape = drawing.create("rect", x_mm=10, y_mm=10, width_mm=20, height_mm=20)
    drawing.fill(shape["ids"])

    result = drawing.fill(shape["ids"], filled=False)

    node = kernel.elements.find_node(shape["ids"][0])
    assert _is_filled(node) is False
    assert result["cleared"] == 1
    assert black_percentage(kernel, shape["ids"][0]) < 20


def test_a_line_cannot_be_filled_and_says_so(kernel, drawing):
    """
    A line has no inside.

    The engine would simply set the fill and do nothing with it; then a button is
    on that did nothing. Shapes that were skipped are reported.
    """
    stroke = drawing.create("line", x1_mm=10, y1_mm=10, x2_mm=40, y2_mm=10)

    result = drawing.fill(stroke["ids"])

    assert result["filled"] == 0
    assert result["skipped"] == 1


def test_the_snapshot_shows_the_fill(client, kernel, drawing):
    shape = drawing.create("rect", x_mm=10, y_mm=10, width_mm=20, height_mm=20)
    drawing.fill(shape["ids"])

    element = next(
        e for e in client.get("/api/design").json()["elements"] if e["id"] == shape["ids"][0]
    )

    assert element["fill"] is not None


# ------------------------------------------------------------------- routes


def test_the_route_fills_and_clears(client):
    shape = client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 10, "y_mm": 10, "width_mm": 20, "height_mm": 20},
    ).json()["ids"][0]

    filled = client.post("/api/design/fill", json={"ids": [shape]})
    assert filled.status_code == 200, filled.text
    assert filled.json()["filled"] == 1

    cleared = client.post("/api/design/fill", json={"ids": [shape], "filled": False})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["cleared"] == 1


def test_the_selection_can_go_to_a_raster_layer(client, kernel, drawing):
    """The third button beside cut and engrave."""
    shape = drawing.create("rect", x_mm=10, y_mm=10, width_mm=20, height_mm=20)

    answer = client.post(
        "/api/design/single-layer", json={"ids": shape["ids"], "type": "raster"}
    )

    assert answer.status_code == 200, answer.text
    layer = kernel.elements.find_node(answer.json()["operation_id"])
    assert str(layer.type) == "op raster"
