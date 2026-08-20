"""
Een vorm vullen, zodat een rasterlaag er een vlak van maakt.

Waarom dit bestaat: een vierkant dat je in OpenKerf tekent heeft `fill = None`,
en onze rasteraar vult alleen wat een vulling heeft. Gemeten vóór deze
handeling: in een rasterlaag werd zo'n vierkant op een beeld van 100×100 pixels
voor 8 % zwart — dat is de rand, niet het vlak. De engine heeft er een commando
voor (`fill <kleur>`, `core/elements/shapes.py:1905`); wij gebruikten het nergens.
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


def zwart_percentage(kernel, element_id: str) -> float:
    """Hoeveel van het vlak onze rasteraar zwart maakt."""
    node = kernel.elements.find_node(element_id)
    beeld = make_raster([node], node.bounds, 100, 100, None, 1, 1, True).convert("L")
    donker = sum(1 for pixel in beeld.getdata() if pixel < 128)
    return donker / 100.0


# ------------------------------------------------------------------ de reden


def test_a_drawn_square_is_an_outline_until_you_fill_it(kernel, drawing):
    """De meting die deze hele handeling verklaart."""
    vorm = drawing.create("rect", x_mm=10, y_mm=10, width_mm=20, height_mm=20)
    node = kernel.elements.find_node(vorm["ids"][0])

    assert node.fill is None
    assert _is_filled(node) is False
    assert zwart_percentage(kernel, vorm["ids"][0]) < 20


# ----------------------------------------------------------------- vullen


def test_filling_a_square_makes_a_face_of_it(kernel, drawing):
    vorm = drawing.create("rect", x_mm=10, y_mm=10, width_mm=20, height_mm=20)

    result = drawing.fill(vorm["ids"])

    node = kernel.elements.find_node(vorm["ids"][0])
    assert _is_filled(node) is True
    assert result["filled"] == 1
    assert zwart_percentage(kernel, vorm["ids"][0]) > 90


def test_the_fill_takes_the_colour_the_shape_already_has(kernel, drawing):
    """
    Dezelfde kleur als de lijn, en niet zomaar zwart.

    In MeerK40t ís de kleur waar de classificatie op werkt; een vulling in een
    andere kleur zou de vorm bij een volgende classificatie in een andere laag
    kunnen laten belanden dan zijn eigen lijn.
    """
    vorm = drawing.create("rect", x_mm=10, y_mm=10, width_mm=20, height_mm=20)
    node = kernel.elements.find_node(vorm["ids"][0])
    lijn = str(node.stroke)

    drawing.fill(vorm["ids"])

    assert str(node.fill).lower() == lijn.lower()


def test_a_colour_can_be_given(kernel, drawing):
    vorm = drawing.create("rect", x_mm=10, y_mm=10, width_mm=20, height_mm=20)

    drawing.fill(vorm["ids"], color="#ff8800")

    assert str(kernel.elements.find_node(vorm["ids"][0]).fill).lower() == "#ff8800"


def test_a_bad_colour_is_refused(drawing):
    vorm = drawing.create("rect", x_mm=10, y_mm=10, width_mm=20, height_mm=20)

    with pytest.raises(DesignError):
        drawing.fill(vorm["ids"], color="oranje-ish")


def test_the_fill_can_be_taken_away_again(kernel, drawing):
    vorm = drawing.create("rect", x_mm=10, y_mm=10, width_mm=20, height_mm=20)
    drawing.fill(vorm["ids"])

    result = drawing.fill(vorm["ids"], filled=False)

    node = kernel.elements.find_node(vorm["ids"][0])
    assert _is_filled(node) is False
    assert result["cleared"] == 1
    assert zwart_percentage(kernel, vorm["ids"][0]) < 20


def test_a_line_cannot_be_filled_and_says_so(kernel, drawing):
    """
    Een lijn heeft geen binnenkant.

    De engine zou de vulling gewoon zetten en er niets mee doen; dan staat er
    een knop aan die niets deed. Overgeslagen vormen worden gemeld.
    """
    lijn = drawing.create("line", x1_mm=10, y1_mm=10, x2_mm=40, y2_mm=10)

    result = drawing.fill(lijn["ids"])

    assert result["filled"] == 0
    assert result["skipped"] == 1


def test_the_snapshot_shows_the_fill(client, kernel, drawing):
    vorm = drawing.create("rect", x_mm=10, y_mm=10, width_mm=20, height_mm=20)
    drawing.fill(vorm["ids"])

    element = next(
        e for e in client.get("/api/design").json()["elements"] if e["id"] == vorm["ids"][0]
    )

    assert element["fill"] is not None


# ------------------------------------------------------------------- routes


def test_the_route_fills_and_clears(client):
    vorm = client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 10, "y_mm": 10, "width_mm": 20, "height_mm": 20},
    ).json()["ids"][0]

    gevuld = client.post("/api/design/fill", json={"ids": [vorm]})
    assert gevuld.status_code == 200, gevuld.text
    assert gevuld.json()["filled"] == 1

    leeg = client.post("/api/design/fill", json={"ids": [vorm], "filled": False})
    assert leeg.status_code == 200, leeg.text
    assert leeg.json()["cleared"] == 1


def test_the_selection_can_go_to_a_raster_layer(client, kernel, drawing):
    """De derde knop naast snijden en graveren."""
    vorm = drawing.create("rect", x_mm=10, y_mm=10, width_mm=20, height_mm=20)

    antwoord = client.post(
        "/api/design/single-layer", json={"ids": vorm["ids"], "type": "raster"}
    )

    assert antwoord.status_code == 200, antwoord.text
    laag = kernel.elements.find_node(antwoord.json()["operation_id"])
    assert str(laag.type) == "op raster"
