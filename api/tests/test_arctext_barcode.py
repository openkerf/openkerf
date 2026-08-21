"""Tekst langs een boog, en streepjescodes."""

import math

import pytest
from fastapi.testclient import TestClient

from openkerf_api.server import ApiServer


@pytest.fixture
def client(kernel, tmp_path):
    with TestClient(ApiServer(kernel, library_path=tmp_path / "b.db").build_app()) as c:
        yield c


def only_element(client):
    design = client.get("/api/design").json()
    per_mm = design["units_per_mm"]
    element = design["elements"][0]
    return element, [v / per_mm for v in element["bounds"]]


# ----------------------------------------------------------------- boogtekst


def test_arc_text_lands_around_the_centre(client):
    response = client.post(
        "/api/design/generate/arctext",
        json={"text": "OPENKERF", "cx_mm": 100, "cy_mm": 100, "radius_mm": 40},
    )

    assert response.status_code == 201
    _, (x0, y0, x1, y1) = only_element(client)
    # On the outside: above the centre, within the radius plus the letter height.
    assert y1 < 100, "the text should sit above the centre"
    assert 100 - 60 < (x0 + x1) / 2 < 100 + 60
    for corner in (x0, x1):
        assert abs(corner - 100) <= 60


def test_arc_text_actually_bends(client):
    """
    Straight text is a strip one letter height tall. Curved text is taller than
    that, or nothing happened.
    """
    client.post(
        "/api/design/generate/arctext",
        json={
            "text": "OPENKERF LASER",
            "cx_mm": 100,
            "cy_mm": 100,
            "radius_mm": 30,
            "font_size_mm": 8,
        },
    )

    _, (_, y0, _, y1) = only_element(client)
    assert y1 - y0 > 8 * 1.5


def test_arc_text_takes_the_font_you_pick(client):
    """
    The arc text generator let you pick no font: the dialog did not ask for one,
    so every arc came out in the default font. The route could already do it —
    this pins down that the chosen font really reaches the generator, and that a
    different font gives a different shape.
    """
    fonts = client.get("/api/design/fonts").json()
    choice = next(
        (f for f in fonts if f["file"].lower().endswith((".ttf", ".jhf", ".shx"))),
        None,
    )
    if choice is None:
        pytest.skip("no font on this machine")

    request = {"text": "OPENKERF", "cx_mm": 100, "cy_mm": 100, "radius_mm": 40}
    default = client.post("/api/design/generate/arctext", json=request)
    assert default.status_code == 201
    _, box_default = only_element(client)

    client.post("/api/design/clear")
    picked = client.post(
        "/api/design/generate/arctext", json={**request, "font": choice["file"]}
    )

    assert picked.status_code == 201, picked.json()
    _, box_picked = only_element(client)
    # A different font draws different outlines; identical measures would mean
    # the choice evaporated on the way.
    assert box_picked != box_default or choice["file"] == ""


def test_inside_text_sits_below_the_centre(client):
    client.post(
        "/api/design/generate/arctext",
        json={
            "text": "ONDERKANT",
            "cx_mm": 100,
            "cy_mm": 100,
            "radius_mm": 40,
            "inside": True,
        },
    )

    _, (_, y0, _, _) = only_element(client)
    assert y0 > 100, "on the inside the text should sit below the centre"


def test_arc_text_is_no_longer_editable_text(kernel, client):
    """
    The engine re-renders text as soon as you change it, and would then quietly
    straighten the arc out. That is why we let the source go.
    """
    made = client.post(
        "/api/design/generate/arctext",
        json={"text": "ROND", "cx_mm": 100, "cy_mm": 100, "radius_mm": 40},
    ).json()

    node = kernel.elements.find_node(made["ids"][0])
    assert getattr(node, "mktext", None) is None

    element = next(
        e for e in client.get("/api/design").json()["elements"] if e["id"] == made["ids"][0]
    )
    assert element["text"] is None


def test_text_longer_than_the_circle_is_refused(client):
    """Anders loopt de tekst over zichzelf heen en is hij onleesbaar."""
    response = client.post(
        "/api/design/generate/arctext",
        json={
            "text": "DIT IS VEEL TE LANG VOOR ZO EEN KLEINE CIRKEL ECHT WAAR",
            "cx_mm": 100,
            "cy_mm": 100,
            "radius_mm": 5,
            "font_size_mm": 10,
        },
    )

    assert response.status_code == 409


def test_empty_arc_text_is_refused(client):
    response = client.post(
        "/api/design/generate/arctext",
        json={"text": "   ", "cx_mm": 100, "cy_mm": 100, "radius_mm": 40},
    )
    assert response.status_code == 409


# --------------------------------------------------------------- streepjescode


def test_a_code128_barcode_is_drawn_at_the_size_asked_for(client):
    response = client.post(
        "/api/design/generate/barcode",
        json={"text": "OPENKERF-1", "x_mm": 10, "y_mm": 10, "width_mm": 60, "height_mm": 20},
    )

    assert response.status_code == 201
    assert response.json()["bars"] > 10
    _, (x0, y0, x1, y1) = only_element(client)
    assert (x1 - x0) == pytest.approx(60, abs=1.5)
    assert (y1 - y0) == pytest.approx(20, abs=0.2)


def test_an_ean13_needs_a_valid_number(client):
    """
    EAN puts demands on the length and the check digit. That message is more use
    to the user than an empty code that does not scan.
    """
    good = client.post(
        "/api/design/generate/barcode",
        json={"text": "590123412345", "kind": "ean13"},
    )
    fout = client.post(
        "/api/design/generate/barcode", json={"text": "hallo", "kind": "ean13"}
    )

    assert good.status_code == 201
    assert fout.status_code == 409


def test_an_unknown_barcode_type_is_refused(client):
    response = client.post(
        "/api/design/generate/barcode", json={"text": "1234", "kind": "morse"}
    )
    assert response.status_code == 409


def test_an_empty_barcode_is_refused(client):
    response = client.post("/api/design/generate/barcode", json={"text": ""})
    assert response.status_code == 409
