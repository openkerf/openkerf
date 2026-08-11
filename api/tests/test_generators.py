"""Generatoren: herhalen, veelhoeken, dozen en QR-codes."""

import pytest
from fastapi.testclient import TestClient

from openkerf_api.generators import JOINTS, PHASE, box_panels, teeth_count
from openkerf_api.server import ApiServer


@pytest.fixture
def client(kernel, tmp_path):
    with TestClient(ApiServer(kernel, library_path=tmp_path / "g.db").build_app()) as c:
        yield c


def a_rect(client):
    return client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 10, "y_mm": 10, "width_mm": 20, "height_mm": 10},
    ).json()["ids"][0]


def elements(client):
    return client.get("/api/design").json()["elements"]


# ------------------------------------------------------------------ herhalen


def test_a_grid_multiplies_the_selection(client):
    rect = a_rect(client)

    response = client.post(
        "/api/design/generate/grid",
        json={"ids": [rect], "columns": 3, "rows": 2, "gap_x_mm": 5, "gap_y_mm": 5},
    )

    assert response.status_code == 200
    assert len(elements(client)) == 6


def test_a_grid_of_one_is_refused(client):
    rect = a_rect(client)

    response = client.post(
        "/api/design/generate/grid", json={"ids": [rect], "columns": 1, "rows": 1}
    )

    assert response.status_code == 409


def test_a_grid_without_a_selection_is_refused(client):
    response = client.post(
        "/api/design/generate/grid", json={"ids": [], "columns": 2, "rows": 2}
    )
    assert response.status_code == 409


def test_a_radial_copy_places_the_requested_number(client):
    rect = a_rect(client)

    response = client.post(
        "/api/design/generate/radial",
        json={"ids": [rect], "repeats": 6, "radius_mm": 40},
    )

    assert response.status_code == 200
    assert len(elements(client)) == 6


# -------------------------------------------------------------------- vormen


def test_a_hexagon_is_drawn(client):
    response = client.post(
        "/api/design/generate/polygon",
        json={"corners": 6, "cx_mm": 50, "cy_mm": 50, "radius_mm": 20},
    )

    assert response.status_code == 201
    assert len(elements(client)) == 1


def test_a_star_needs_a_smaller_inner_radius(client):
    response = client.post(
        "/api/design/generate/polygon",
        json={
            "corners": 5,
            "cx_mm": 50,
            "cy_mm": 50,
            "radius_mm": 20,
            "inner_radius_mm": 25,
        },
    )
    assert response.status_code == 409


def test_two_corners_is_not_a_polygon(client):
    response = client.post(
        "/api/design/generate/polygon",
        json={"corners": 2, "cx_mm": 50, "cy_mm": 50, "radius_mm": 20},
    )
    assert response.status_code == 409


# ---------------------------------------------------------------------- doos


def test_every_joint_is_complementary():
    """
    De kern van de doos: waar het ene paneel een tand heeft, hoort het andere
    een gat te hebben. Eén verkeerde en de doos past niet in elkaar — en dat
    merk je pas als het hout al gesneden is.
    """
    for left, right in JOINTS:
        assert PHASE[left] != PHASE[right], f"{left} en {right} hebben allebei dezelfde fase"


def test_mating_edges_get_the_same_number_of_teeth():
    """Anders liggen de tanden niet op dezelfde plek, hoe je ze ook keert."""
    # Een wandhoogte van 50 raakt zowel de voorkant als de zijkant.
    assert teeth_count(50, 10) == teeth_count(50, 10)
    # Altijd oneven: een rand begint en eindigt met materiaal.
    for length in (30, 45, 50, 63.5, 120):
        assert teeth_count(length, 10) % 2 == 1


def test_a_box_panel_is_the_size_you_asked_for(client):
    """
    De `path`-opdracht las eerder een d-string als SVG-gebruikerseenheden en
    schaalde die nog eens: een doos van 100 mm kwam er als 72 meter uit. Alleen
    het aantal panelen tellen zag dat niet.
    """
    client.post(
        "/api/design/generate/box",
        json={
            "width_mm": 60,
            "depth_mm": 40,
            "height_mm": 30,
            "thickness_mm": 3,
            "finger_mm": 10,
        },
    )

    design = client.get("/api/design").json()
    per_mm = design["units_per_mm"]
    bodem = next(e for e in design["elements"] if e["label"].endswith("bodem"))
    x0, y0, x1, y1 = (v / per_mm for v in bodem["bounds"])
    # Breedte plus de tanden die aan weerszijden uitsteken (2 x de dikte).
    assert (x1 - x0) == pytest.approx(60 + 2 * 3, abs=0.2)
    assert (y1 - y0) == pytest.approx(40 + 2 * 3, abs=0.2)


def test_a_qr_code_is_the_size_you_asked_for(client):
    client.post(
        "/api/design/generate/qrcode",
        json={"text": "https://openkerf.nl", "size_mm": 30},
    )

    design = client.get("/api/design").json()
    per_mm = design["units_per_mm"]
    code = design["elements"][0]
    x0, _, x1, _ = (v / per_mm for v in code["bounds"])
    # Zonder de stille rand eromheen: die is leeg en telt niet mee in de bounds.
    assert 20 <= (x1 - x0) <= 30


def test_a_box_yields_six_panels(client):
    response = client.post(
        "/api/design/generate/box",
        json={
            "width_mm": 60,
            "depth_mm": 40,
            "height_mm": 30,
            "thickness_mm": 3,
            "finger_mm": 10,
            "kerf_mm": 0.1,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["panels"] == ["bodem", "voor", "achter", "links", "rechts", "deksel"]
    assert len(elements(client)) == 6


def test_a_box_without_a_lid_yields_five(client):
    response = client.post(
        "/api/design/generate/box",
        json={
            "width_mm": 60,
            "depth_mm": 40,
            "height_mm": 30,
            "thickness_mm": 3,
            "lid": False,
        },
    )

    assert len(response.json()["panels"]) == 5


def test_the_kerf_makes_tabs_bigger_not_smaller():
    """
    De laser haalt aan beide kanten van elke snede materiaal weg. Een tand die
    op papier precies past, is in hout te smal — dus moet hij groeien.
    """
    zonder = dict(box_panels(100, 80, 50, 3, 10, 0.0))
    met = dict(box_panels(100, 80, 50, 3, 10, 0.4))

    def widest(points):
        return max(px for px, _ in points) - min(px for px, _ in points)

    assert widest(met["voor"]) > widest(zonder["voor"])


def test_material_thicker_than_the_box_is_refused(client):
    response = client.post(
        "/api/design/generate/box",
        json={"width_mm": 20, "depth_mm": 20, "height_mm": 20, "thickness_mm": 9},
    )
    assert response.status_code == 409


def test_a_finger_thinner_than_the_material_is_refused(client):
    """Zo'n vinger breekt af zodra je de doos in elkaar zet."""
    response = client.post(
        "/api/design/generate/box",
        json={
            "width_mm": 60,
            "depth_mm": 40,
            "height_mm": 30,
            "thickness_mm": 6,
            "finger_mm": 3,
        },
    )
    assert response.status_code == 409


# ------------------------------------------------------------------- qr-code


def test_a_qr_code_becomes_a_path(client):
    response = client.post(
        "/api/design/generate/qrcode",
        json={"text": "https://openkerf.nl", "size_mm": 30},
    )

    assert response.status_code == 201
    assert response.json()["modules"] > 20
    assert len(elements(client)) == 1


def test_an_empty_qr_code_is_refused(client):
    response = client.post("/api/design/generate/qrcode", json={"text": "  "})
    assert response.status_code == 409


def test_box_panels_stay_on_the_bed(client):
    """
    Zes panelen op één rij zijn zo een meter breed. Wat buiten het bed valt is
    niet meer aan te wijzen, dus dan kun je het ook niet terughalen.
    """
    bed = client.get("/api/devices").json()[0]["bed"]
    client.post(
        "/api/design/generate/box",
        json={
            "width_mm": 60,
            "depth_mm": 40,
            "height_mm": 30,
            "thickness_mm": 3,
            "finger_mm": 10,
        },
    )

    design = client.get("/api/design").json()
    per_mm = design["units_per_mm"]
    right = max(e["bounds"][2] for e in design["elements"]) / per_mm
    low = max(e["bounds"][3] for e in design["elements"]) / per_mm
    assert right <= bed["width_mm"] + 0.5, f"steekt tot {right:.0f} mm uit"
    assert low <= bed["height_mm"] + 0.5, f"loopt tot {low:.0f} mm door"

    rows = {round(e["bounds"][1] / per_mm) for e in design["elements"]}
    assert len(rows) > 1, "alles staat nog op één rij"


def test_a_box_too_tall_for_the_bed_is_refused_before_drawing(client):
    """
    Een halve doos buiten het bed is erger dan geen doos: die kun je niet meer
    aanwijzen om hem weg te halen.
    """
    response = client.post(
        "/api/design/generate/box",
        json={
            "width_mm": 200,
            "depth_mm": 150,
            "height_mm": 120,
            "thickness_mm": 4,
            "finger_mm": 15,
        },
    )

    assert response.status_code == 409
    assert "hoogte nodig" in response.json()["detail"]
    assert client.get("/api/design").json()["elements"] == []


def test_a_box_too_wide_for_the_bed_is_refused(client):
    response = client.post(
        "/api/design/generate/box",
        json={
            "width_mm": 2000,
            "depth_mm": 900,
            "height_mm": 600,
            "thickness_mm": 6,
            "finger_mm": 20,
        },
    )

    assert response.status_code == 409
    assert "past niet" in response.json()["detail"]
