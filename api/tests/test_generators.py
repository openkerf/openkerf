"""Generatoren: herhalen, veelhoeken, dozen en QR-codes."""

import re

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


def path_box(element):
    """The path's bounding box as the canvas draws it, in units."""
    getallen = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?(?:E-?\d+)?", element["path"])]
    xs, ys = getallen[0::2], getallen[1::2]
    return [min(xs), min(ys), max(xs), max(ys)]


def assert_bounds_follow_the_shape(client):
    """
    The handles are around the shape you click.

    `bounds` feeds the selection frame, `path` the drawing. If they drift apart, the copy you
    clicked does get a thick border but the frame is around another shape — exactly what
    happened when the engine copied the original's bounding box along without recomputing it.
    """
    for element in elements(client):
        box = path_box(element)
        for gemeten, getekend in zip(element["bounds"], box):
            assert gemeten == pytest.approx(getekend, abs=1.0), element["id"]


def test_a_grid_copy_carries_its_own_bounds(client):
    client.post(
        "/api/design/generate/grid",
        json={"ids": [a_rect(client)], "columns": 3, "rows": 2, "gap_x_mm": 5, "gap_y_mm": 5},
    )

    assert_bounds_follow_the_shape(client)


def test_a_radial_copy_carries_its_own_bounds(client):
    client.post(
        "/api/design/generate/radial",
        json={"ids": [a_rect(client)], "repeats": 6, "radius_mm": 40},
    )

    assert_bounds_follow_the_shape(client)


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
    The core of the box: where one panel has a tooth, the other should have a gap. One wrong
    and the box does not fit together — and you only notice that once the wood has been cut.
    """
    for left, right in JOINTS:
        assert PHASE[left] != PHASE[right], f"{left} en {right} hebben allebei dezelfde fase"


def test_mating_edges_get_the_same_number_of_teeth():
    """Otherwise the teeth are not in the same place, however you turn them."""
    # A wall height of 50 touches both the front and the side.
    assert teeth_count(50, 10) == teeth_count(50, 10)
    # Always odd: an edge begins and ends with material.
    for length in (30, 45, 50, 63.5, 120):
        assert teeth_count(length, 10) % 2 == 1


def test_a_box_panel_is_the_size_you_asked_for(client):
    """
    The `path` command used to read a d-string as SVG user units and scale it again: a box of
    100 mm came out as 72 metres. Counting only the number of panels did not see that.
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
    bodem = next(e for e in design["elements"] if e["label"].endswith("bottom"))
    x0, y0, x1, y1 = (v / per_mm for v in bodem["bounds"])
    # The width plus the teeth sticking out on both sides (2 × the thickness).
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
    # Without the quiet zone around it: that is empty and does not count in the bounds.
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
    assert body["panels"] == ["bottom", "front", "back", "left", "right", "lid"]
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
    The laser takes material off both sides of every cut. A tooth that fits exactly on paper
    is too narrow in wood — so it has to grow.
    """
    zonder = dict(box_panels(100, 80, 50, 3, 10, 0.0))
    met = dict(box_panels(100, 80, 50, 3, 10, 0.4))

    def widest(points):
        return max(px for px, _ in points) - min(px for px, _ in points)

    assert widest(met["front"]) > widest(zonder["front"])


def test_material_thicker_than_the_box_is_refused(client):
    response = client.post(
        "/api/design/generate/box",
        json={"width_mm": 20, "depth_mm": 20, "height_mm": 20, "thickness_mm": 9},
    )
    assert response.status_code == 409


def test_a_finger_thinner_than_the_material_is_refused(client):
    """Such a finger snaps off as soon as you assemble the box."""
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
    Six panels in one row are a metre wide in no time. What falls off the bed can no longer
    be pointed at, so you cannot bring it back either.
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
    assert len(rows) > 1, "everything is still in one row"


BIG_BOX = {
    "width_mm": 200,
    "depth_mm": 150,
    "height_mm": 120,
    "thickness_mm": 4,
    "finger_mm": 15,
}


def test_a_box_that_does_not_fit_is_spread_over_sheets(client):
    """
    Such a box used to be refused with the advice "cut it in two goes", without you being
    able to do that. Now it lays itself out on several sheets.
    """
    response = client.post("/api/design/generate/box", json=BIG_BOX)

    assert response.status_code == 201
    assert response.json()["sheets"] > 1

    sheets = client.get("/api/sheets").json()["sheets"]
    assert len(sheets) > 1
    # We are back on the sheet we started on; the canvas should not slide out from under
    # you.
    assert sheets[0]["active"] is True

    on_each = []
    for sheet in sheets:
        client.post(f"/api/sheets/{sheet['id']}/activate")
        on_each.append(len(client.get("/api/design").json()["elements"]))
    assert sum(on_each) == 6, f"not all the panels have been drawn: {on_each}"
    assert all(count > 0 for count in on_each)


def test_spreading_can_be_switched_off(client):
    """Anybody who does not want extra sheets should be told instead of getting them."""
    response = client.post(
        "/api/design/generate/box", json={**BIG_BOX, "spread": False}
    )

    assert response.status_code == 409
    assert "does not fit on one sheet" in response.json()["detail"]
    assert client.get("/api/design").json()["elements"] == []


def test_a_panel_wider_than_the_sheet_stays_refused(client):
    """Spreading does not help when one panel is already too wide."""
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
    assert "widest panel" in response.json()["detail"]





def test_generated_parts_land_in_exactly_one_layer(client):
    """
    Colour classification put a box panel in an *engrave* layer *and* in a second layer
    claiming the same colour — the same panel burned twice, and you only notice that on
    material. Hence one explicit layer.
    """
    client.post(
        "/api/design/generate/box",
        json={"width_mm": 60, "depth_mm": 40, "height_mm": 30, "thickness_mm": 3},
    )

    design = client.get("/api/design").json()
    layers = [o for o in design["operations"] if o["element_ids"]]
    assert [o["label"] for o in layers] == ["Cut"]
    assert all(len(e["operation_ids"]) == 1 for e in design["elements"])


def test_a_qr_code_is_engraved_not_cut(client):
    """Een QR-code uitsnijden levert een hoopje vierkantjes op."""
    client.post("/api/design/generate/qrcode", json={"text": "openkerf", "size_mm": 30})

    layers = [
        o for o in client.get("/api/design").json()["operations"] if o["element_ids"]
    ]
    assert [o["label"] for o in layers] == ["Engrave"]


# ------------------------------------------------------- the lid that binds


def test_a_lid_used_to_be_a_bottom_with_nowhere_to_go():
    """
    The fault found on the wood, as a test.

    The lid was an exact copy of the bottom — 48 points, so cut-outs all round — and the walls
    had a dead straight top edge. So those bites fitted nowhere. Now *every* edge of the lid
    has a counterpart.
    """
    from openkerf_api.generators import JOINTS

    naden = {links for links, _ in JOINTS} | {rechts for _, rechts in JOINTS}

    for rand in ("front", "back", "left", "right"):
        assert ("lid", rand) in naden, f"the lid is loose on its {rand} edge"
        assert (rand, "over") in naden, f"the {rand} wall has no tooth for the lid"


def test_the_walls_grow_teeth_on_top_only_when_there_is_a_lid():
    """
    Zonder deksel blijft de bovenrand recht.

    Anders staan er tanden op een doos die open blijft: dan snijd je een rand
    vol uitsteeksels waar niets op komt.
    """
    met = dict(box_panels(80, 60, 40, thickness=3, finger=10, kerf=0.1, lid=True))
    zonder = dict(box_panels(80, 60, 40, thickness=3, finger=10, kerf=0.1, lid=False))

    assert "lid" not in zonder
    assert len(met["front"]) > len(zonder["front"]), "met deksel horen er tanden bij"
    assert len(zonder["front"]) == 28  # zoals het altijd was: recht van boven


def test_the_lid_seam_is_the_same_construction_as_the_bottom_seam():
    """
    De sterkste proef die er zonder hout is.

    De bodemnaad past — dat is op materiaal vastgesteld. Als de dekselnaad
    punt voor punt dezelfde vorm heeft (zelfde aantal tanden, zelfde
    x-posities, zelfde kerfcompensatie, tegengestelde fase), dan past die dus
    ook. Een test op `teeth_count(80, 10) == teeth_count(80, 10)` bewijst
    daarentegen niets: dat is dezelfde aanroep twee keer.
    """
    from openkerf_api.generators import edge_points

    breedte, dikte, vinger, kerf = 80.0, 3.0, 10.0, 0.1
    heen = ((0.0, 0.0), (breedte, 0.0))

    wand_onder = edge_points(*heen, dikte, vinger, kerf, PHASE[("front", "under")])
    bodem_rand = edge_points(*heen, dikte, vinger, kerf, PHASE[("bottom", "front")])
    wand_boven = edge_points(*heen, dikte, vinger, kerf, PHASE[("front", "over")])
    deksel_rand = edge_points(*heen, dikte, vinger, kerf, PHASE[("lid", "front")])

    assert wand_boven == wand_onder
    assert deksel_rand == bodem_rand
    # En de naad zelf: tegengestelde fase, en de tanden vallen op dezelfde
    # plekken op ±kerf na — precies zoals bij de bodem.
    assert PHASE[("front", "over")] != PHASE[("lid", "front")]
    boven = sorted({round(a[0] - b[0], 4) for a, b in zip(wand_boven, deksel_rand)})
    onder = sorted({round(a[0] - b[0], 4) for a, b in zip(wand_onder, bodem_rand)})
    assert boven == onder == [-kerf, kerf]


def test_a_box_with_a_lid_still_fits_on_the_sheet(client):
    """De wanden worden hoger van hun tanden; dat mag het vel niet breken."""
    antwoord = client.post(
        "/api/design/generate/box",
        json={
            "width_mm": 80,
            "depth_mm": 60,
            "height_mm": 40,
            "thickness_mm": 3,
            "finger_mm": 10,
            "lid": True,
        },
    )

    assert antwoord.status_code == 201, antwoord.text
    assert antwoord.json()["panels"] == [
        "bottom",
        "front",
        "back",
        "left",
        "right",
        "lid",
    ]
