"""
Text in an imported SVG comes in as a shape, or is named as not having come in.

Found on a real drawing — side panels for a spray booth, nine red outlines and nine blue
labels (`<text fill="#0000ff" font-size="6" text-anchor="middle">`, Helvetica). Imported,
the canvas showed nine shapes, "Standard-Raster" said 18 elements, and a burn would have
left every label off the plate: the engine reads `<text>` into an `elem text` that only
the wxPython GUI can turn into a shape. See `svgtext`.

The drawing below is two of those panels with their labels, coordinates as in the file.
"""

import numpy as np
import pytest
from fastapi.testclient import TestClient

from openkerf_api import svgtext
from openkerf_api.server import ApiServer

MM = 65535 / 25.4

PANELS = b"""<svg xmlns="http://www.w3.org/2000/svg" width="500mm" height="300mm" viewBox="0 0 500 300">
<path d="M247.667,46.608 L5.000,29.941 L6.713,5.000 L249.380,21.667 Z" fill="none" stroke="#ff0000" stroke-width="0.1"/>
<text x="127.2" y="25.8" font-family="Helvetica, Arial, sans-serif" font-size="6" text-anchor="middle" fill="#0000ff">R2-07</text>
<path d="M283.380,45.355 L253.380,15.355 L278.380,5.000 L308.380,35.000 Z" fill="none" stroke="#ff0000" stroke-width="0.1"/>
<text x="280.9" y="25.2" font-family="Helvetica, Arial, sans-serif" font-size="6" text-anchor="middle" fill="#0000ff">R2-04</text>
</svg>"""


@pytest.fixture
def client(kernel, tmp_path):
    with TestClient(ApiServer(kernel, library_path=tmp_path / "d.db").build_app()) as c:
        yield c


def _import(client, svg: bytes) -> dict:
    response = client.post("/api/job/load", files={"file": ("panels.svg", svg, "image/svg+xml")})
    assert response.status_code == 200, response.text
    return response.json()


def _texts(client) -> list[dict]:
    return [e for e in client.get("/api/design").json()["elements"] if e["text"]]


def test_the_labels_come_in_as_shapes_where_the_file_puts_them(client):
    """
    Before: 2 shapes in the snapshot out of 4. After: all 4, and each label stands on its
    own anchor — the file's x is the middle of the word, its y the baseline.

    Measured: "R2-07" from x 119.50 to 135.10 mm (middle 127.30 against 127.2 in the
    file), bottom at 25.87 against a baseline of 25.8; the few hundredths under the line
    are the round bottoms of the 0, the 2 and the 7.
    """
    result = _import(client, PANELS)

    assert result["count"] == 4
    assert result["unreadable_texts"] == []
    texts = {e["text"]["text"]: e for e in _texts(client)}
    assert set(texts) == {"R2-07", "R2-04"}
    for wording, (x, baseline) in {"R2-07": (127.2, 25.8), "R2-04": (280.9, 25.2)}.items():
        element = texts[wording]
        x0, y0, x1, y1 = (v / MM for v in element["bounds"])
        assert abs((x0 + x1) / 2 - x) < 0.5
        assert abs(y1 - baseline) < 0.2
        # 6 mm type: capitals of about 4.3 mm, measured.
        assert 3.5 < y1 - y0 < 5.0
        assert element["text"]["font_size_mm"] == pytest.approx(6.0)
        assert element["text"]["align"] == "middle"
        assert element["fill"] == "#0000ff"


def test_no_layer_holds_a_shape_nobody_can_see(client):
    """Before: "Standard-Raster" counted 2 elements here and the canvas showed none."""
    _import(client, PANELS)

    visible = {e["id"] for e in client.get("/api/design").json()["elements"]}
    for layer in client.get("/api/design").json()["operations"]:
        assert set(layer["element_ids"]) <= visible
    counted = sum(layer["elements"] for layer in client.get("/api/job/layers").json()["layers"])
    assert counted == len(visible) == 4


def test_a_filled_label_rasters_and_an_outlined_one_engraves(client, kernel):
    """
    The text classifies the way its outline as a `<path>` would, because that is what it
    now is. Measured with a path of each paint: `fill="#0000ff"` lands in the raster
    layer, `fill="none" stroke="#0000ff"` in an engrave layer.
    """
    svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" viewBox="0 0 100 100">'
        b'<text x="10" y="20" font-size="6" fill="#0000ff">FILLED</text>'
        b'<text x="10" y="40" font-size="6" fill="none" stroke="#0000ff">OUTLINED</text>'
        b"</svg>"
    )
    _import(client, svg)

    layers = {op["id"]: op["type"] for op in client.get("/api/design").json()["operations"]}
    kinds = {e["text"]["text"]: {layers[o] for o in e["operation_ids"]} for e in _texts(client)}
    assert kinds == {"FILLED": {"op raster"}, "OUTLINED": {"op engrave"}}


def test_the_raster_layer_burns_the_letters(client, kernel):
    """
    The point of all this. The rasteriser skips `elem text` on purpose; an outlined label
    is a path, and its letters come out black. Measured at 10 px/mm over the label's own
    box: 2198 of 6864 pixels black for "R2-07", none before (there was no shape).
    """
    _import(client, PANELS)
    element = next(e for e in _texts(client) if e["text"]["text"] == "R2-07")
    node = kernel.elements.find_node(element["id"])
    make_raster = kernel.root.lookup("render-op/make_raster")

    x0, y0, x1, y1 = node.bounds
    step = MM / 10
    image = make_raster([node], bounds=(x0, y0, x1, y1), step_x=step, step_y=step)
    black = int((np.asarray(image.convert("L")) < 128).sum())

    assert black > 1000


def test_a_rotated_label_stays_rotated(client):
    """
    A text standing on its side keeps standing: the rotation stays in the matrix and only
    the scale moves into the font size. Measured: 4.39 mm wide and 15.6 mm tall, centred
    at 50.1 mm.
    """
    svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" viewBox="0 0 100 100">'
        b'<text x="50" y="50" font-size="6" text-anchor="middle" fill="#0000ff"'
        b' transform="rotate(90 50 50)">R2-07</text></svg>'
    )
    _import(client, svg)

    (element,) = _texts(client)
    x0, y0, x1, y1 = (v / MM for v in element["bounds"])
    assert y1 - y0 > 3 * (x1 - x0)
    assert abs((y0 + y1) / 2 - 50) < 0.5
    assert element["text"]["font_size_mm"] == pytest.approx(6.0)


def test_a_font_nobody_has_falls_back_instead_of_disappearing(client):
    _import(
        client,
        b'<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" viewBox="0 0 100 100">'
        b'<text x="10" y="20" font-size="6" font-family="No Such Typeface, fantasy">A1</text></svg>',
    )

    (element,) = _texts(client)
    assert element["text"]["font"]


def test_importing_a_label_does_not_choose_the_next_texts_font(client, kernel):
    """Same trap as `Drawing._keep_last_font`: the engine writes every font it uses there."""
    kernel.root.setting(str, "last_font", "")
    kernel.root.last_font = "meerk40t.jhf"

    _import(client, PANELS)

    assert kernel.root.last_font == "meerk40t.jhf"


def test_a_label_that_cannot_be_made_is_named_and_not_left_in_a_layer(
    client, kernel, monkeypatch
):
    """
    When no shape comes out of a text — no usable font on the machine at all — the import
    says which wording did not come in, and no layer is left counting an invisible member.
    """
    monkeypatch.setattr(svgtext, "_vector_text", lambda *args: None)

    result = _import(client, PANELS)

    assert result["unreadable_texts"] == ["R2-07", "R2-04"]
    assert result["count"] == 2
    assert not any(n.type == "elem text" for n in kernel.elements.elems())
    counted = sum(layer["elements"] for layer in client.get("/api/job/layers").json()["layers"])
    assert counted == 2


def test_an_empty_text_is_dropped_without_a_word(client, kernel):
    """Spaces draw nothing in any program, so there is no label to report missing."""
    result = _import(
        client,
        b'<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" viewBox="0 0 100 100">'
        b'<rect x="1" y="1" width="20" height="10" fill="none" stroke="#ff0000"/>'
        b'<text x="10" y="20" font-size="6">   </text></svg>',
    )

    assert result["unreadable_texts"] == []
    assert not any(n.type == "elem text" for n in kernel.elements.elems())
