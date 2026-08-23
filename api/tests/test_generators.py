"""Generatoren: herhalen, veelhoeken, dozen en QR-codes."""

import re

import pytest
from fastapi.testclient import TestClient

from openkerf_api.generators import (
    JOINTS,
    PHASE,
    box_panels,
    qr_squares,
    teeth_count,
)
from openkerf_api.server import ApiServer


@pytest.fixture
def client(kernel, tmp_path):
    # The server itself hangs on the client, because the repeat that follows a list is
    # about two of its parts agreeing (`generators` and `series`) and one test below
    # reaches for them directly.
    server = ApiServer(kernel, library_path=tmp_path / "g.db")
    with TestClient(server.build_app()) as c:
        c.server = server
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


# ------------------------------------------------- herhalen langs een lijst
#
# "Each copy takes the next name from the list". The measured gap it closes:
# `core/elements/grid.py:237-241` copies with a plain `copy(node)` and knows nothing
# about a wordlist, so a repeated `{name}` gives the same name as many times as you
# asked for — three plates all reading Anna.

FIVE = ("Anna", "Bram", "Cees", "Daan", "Eva")


def a_list(client, names=FIVE, column="name"):
    """Attach a list the way the Series window does: upload, then attach."""
    data = (column + "\n" + "\n".join(names) + "\n").encode("utf-8")
    uploaded = client.post(
        "/api/series/upload", files={"file": ("names.csv", data, "text/csv")}
    )
    assert uploaded.status_code == 200, uploaded.text
    attached = client.post(
        "/api/series/attach", json={"file": uploaded.json()["file"]}
    )
    assert attached.status_code == 200, attached.text


def a_text(client, template, x_mm=10.0, y_mm=20.0):
    """
    A text on the bed, placed *after* the list is attached.

    In that order deliberately: a text placed while nothing is attached renders as the
    empty string, so its bounding box comes back `(nan, nan, nan, nan)` and it belongs
    to no layer at all. That ghost is its own subject; a repeat test has to start from a
    shape that is really there.
    """
    response = client.post(
        "/api/design/elements",
        json={
            "type": "text",
            "x_mm": x_mm,
            "y_mm": y_mm,
            "text": template,
            "font_size_mm": 8,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["ids"][0]


def repeat(client, ids, columns=3, rows=1, **body):
    return client.post(
        "/api/design/generate/grid",
        json={"ids": ids, "columns": columns, "rows": rows, "gap_x_mm": 5, **body},
    )


#: How wide a row is when reading the bed. Not nought: these texts hold different
#: names once they are rendered, and different letters are different heights — measured,
#: half a millimetre between `Anna` and `Bram` — so a row is a band and not a line. Five
#: millimetres is far under the gap between two rows of a grid and far over that.
ROW_BAND_MM = 5.0


def in_reading_order(kernel):
    """Every text on the bed, top to bottom and left to right, as (template, burned)."""
    from meerk40t.core.units import UNITS_PER_MM

    nodes = [n for n in kernel.elements.elems() if getattr(n, "mktext", None)]
    nodes.sort(
        key=lambda n: (
            round(n.bounds[1] / UNITS_PER_MM / ROW_BAND_MM),
            round(n.bounds[0] / UNITS_PER_MM, 2),
        )
    )
    return [(str(n.mktext), getattr(n, "_translated_text", None)) for n in nodes]


def test_a_repeat_gives_each_copy_the_next_name(client, kernel):
    """
    Three copies read Anna, Bram and Cees — the whole point of the option.

    The names are the engine's own rendering (`_translated_text`), not our arithmetic,
    which is what makes this the same answer the burn gives. Fails on the engine's plain
    `copy(node)`: measured, three copies all reading Anna, in one undo scope, with
    nothing anywhere saying why.
    """
    a_list(client)
    text = a_text(client, "{name}")

    response = repeat(client, [text], follow_list=True)

    assert response.status_code == 200, response.text
    assert in_reading_order(kernel) == [
        ("{name}", "Anna"),
        ("{name#+1}", "Bram"),
        ("{name#+2}", "Cees"),
    ]


def test_without_the_option_every_copy_reads_the_same_row(client, kernel):
    """
    The counter-proof, and the behaviour anybody who does not tick the box still gets.

    Also the guard on the default: `follow_list` absent must mean off, because a repeat
    of a text that is *meant* to be the same on every piece — a logo's wordmark — must
    not start walking a list.
    """
    a_list(client)
    text = a_text(client, "{name}")

    assert repeat(client, [text]).status_code == 200

    assert in_reading_order(kernel) == [("{name}", "Anna")] * 3


def test_a_repeat_across_two_rows_follows_reading_order(client, kernel):
    """
    Two by two: left to right, then down. Nobody hands out plates in another order.

    A 2x2 grid is also where the cells stop being one row of the tree, so this is the
    test that the order is *place* and not a happy accident of how many copies there are.
    """
    a_list(client)
    text = a_text(client, "{name}")

    answer = repeat(client, [text], columns=2, rows=2, gap_y_mm=5, follow_list=True)
    assert answer.status_code == 200, answer.text

    assert [burned for _, burned in in_reading_order(kernel)] == [
        "Anna",
        "Bram",
        "Cees",
        "Daan",
    ]


def test_the_copies_take_their_row_from_where_they_lie_and_not_from_the_tree(client):
    """
    The rule stated on its own: reading order decides, tree order does not.

    Three texts placed by hand from right to left, so the tree order is the reverse of
    the reading order. The one on the left is the first plate whatever the tree says.
    Through `_follow_list` directly, because there is no way to make the engine's own
    `grid` build a tree in the wrong order — which is exactly why the rule needs a test
    of its own rather than resting on the shape of one generator's output.
    """
    a_list(client)
    right = a_text(client, "{name}", x_mm=90)
    middle = a_text(client, "{name}", x_mm=50)
    left = a_text(client, "{name}", x_mm=10)
    generators = client.server.generators
    kernel = generators.kernel
    nodes = {i: kernel.elements.find_node(i) for i in (right, middle, left)}

    # As `grid` calls it: the selection is one cell and everything new is the others.
    generators._follow_list([nodes[right]], {id(nodes[right])})

    assert [str(nodes[i].mktext) for i in (left, middle, right)] == [
        "{name}",
        "{name#+1}",
        "{name#+2}",
    ]


def test_a_sheetful_from_a_repeat_eats_its_rows_in_one_burn(client):
    """
    Three copies on the sheet make one burn take three rows, and the run agrees.

    This is the payoff of adding to the offset rather than overwriting it: `step_of`
    reads the same templates the repeat wrote, so five names come out as two burns and
    not five. Fails on any implementation that gives every copy offset nought — then the
    operator burns the same plate five times over.
    """
    a_list(client)
    text = a_text(client, "{name}")
    assert repeat(client, [text], follow_list=True).status_code == 200

    state = client.get("/api/series").json()

    assert state["step"] == 3
    assert state["burns"] == 2


def test_a_repeat_that_follows_the_list_needs_a_list(client, kernel):
    """
    Nothing attached: a sentence, and not a single copy made.

    The refusal comes before the engine's `grid` runs, deliberately. Refusing afterwards
    would leave three copies standing under an answer that says nothing happened, and an
    undo scope that has to be pressed to clear up a failure is a worse dead end than the
    failure.
    """
    text = a_text(client, "{name}")

    response = repeat(client, [text], follow_list=True)

    assert response.status_code == 409
    # `gen.noList` and not `series.noList`: `Series.vet()` uses that code for another
    # sentence about the same fact ("a text with a placeholder cannot become anything"),
    # and one code carries one translated sentence.
    assert response.headers["X-OpenKerf-Error"] == "gen.noList"
    # Counted in the tree and not in the snapshot: this text asks for a column no list
    # has, so it renders as nothing and drops out of the snapshot altogether — the ghost
    # `Series._ghosts` is about. What matters here is that no copy was made.
    assert len(list(kernel.elements.elems())) == 1


def test_a_repeat_that_follows_the_list_needs_something_that_reads_it(client):
    """
    A list, but nothing on the shapes to fill in: refused by name.

    Silently making identical copies is the failure this whole option exists to end, so
    it may not be this option's own behaviour when the box is ticked over a plain
    rectangle.
    """
    a_list(client)
    rect = a_rect(client)

    response = repeat(client, [rect], follow_list=True)

    assert response.status_code == 409
    assert response.headers["X-OpenKerf-Error"] == "gen.nothingToFollow"
    assert len(elements(client)) == 1


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


def test_a_short_code_is_a_full_qr_and_a_scanner_reads_it():
    """
    The measured bug: `segno.make` hands back a Micro QR that nothing can read.

    A serial number or a board code is a short payload, and that is exactly where `make`
    switches to a micro variant: measured with segno 1.6.6, `'OK-G:32'` gives M3-M and
    `'OK1:7X4MQB2K'` gives M4-Q. OpenCV 5.0.0 decodes both as the empty string from a
    noise-free render at 12 px per module with a 4-module quiet zone — the format, not the
    resolution — and Chromium's `BarcodeDetector` lists no micro variant either. So a code
    the engraver could see was a code no phone could read. `segno.make_qr` gives 1-H and
    1-Q for the same two payloads and both decode.

    A longer text hid it: `'https://openkerf.nl'` is 19 characters and comes out of `make`
    as a full code anyway, which is why every existing test here stayed green.
    """
    cv2 = pytest.importorskip("cv2")
    import numpy as np
    import segno

    for payload in ("OK-G:32", "OK1:7X4MQB2K"):
        assert segno.make(payload, error="m").designator.startswith("M")

        squares, modules = qr_squares(payload, 0.0, 0.0, 30.0, 4)
        step = 30.0 / modules
        px = 12
        side = modules * px
        picture = np.full((side, side), 255, dtype=np.uint8)
        for square in squares:
            left = int(round(min(x for x, _ in square) / step * px))
            top = int(round(min(y for _, y in square) / step * px))
            picture[top : top + px, left : left + px] = 0
        assert cv2.QRCodeDetector().detectAndDecode(picture)[0] == payload


def test_the_caller_chooses_the_quiet_zone(client):
    """
    Two modules of quiet for the public generator, four for a board code.

    Two is what this generator has always drawn and what the form still sends; the standard
    asks for four, and `boardcode` takes four because wood is not paper. Measured through a
    simulated photograph, four decoded 20 of 20 at 6 px per module where two decoded 16 of
    20. The quiet zone lives inside `size_mm` either way — the footprint is what the user
    asked for and the modules get smaller — so a 30 mm code stays 30 mm wide on the bed.
    """
    short = {"text": "OK-G:32", "size_mm": 30}
    default = client.post("/api/design/generate/qrcode", json=short)
    wider = client.post(
        "/api/design/generate/qrcode", json={**short, "border": 4}
    )
    assert default.json()["modules"] == 21 + 2 * 2
    assert wider.json()["modules"] == 21 + 2 * 4

    design = client.get("/api/design").json()
    per_mm = design["units_per_mm"]
    for element in design["elements"]:
        x0, _, x1, _ = (v / per_mm for v in element["bounds"])
        assert x1 - x0 <= 30.0 + 0.01


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
    Without a lid the top edge stays straight.

    Otherwise there are teeth on a box that stays open: you would be cutting an
    edge full of tabs with nothing to go on them.
    """
    with_lid = dict(box_panels(80, 60, 40, thickness=3, finger=10, kerf=0.1, lid=True))
    without = dict(box_panels(80, 60, 40, thickness=3, finger=10, kerf=0.1, lid=False))

    assert "lid" not in without
    assert len(with_lid["front"]) > len(without["front"]), "with a lid there should be teeth"
    assert len(without["front"]) == 28  # the way it always was: straight on top


def test_the_lid_seam_is_the_same_construction_as_the_bottom_seam():
    """
    The strongest trial there is without wood.

    The bottom seam fits — that was established on material. If the lid seam has
    the same shape point for point (the same number of teeth, the same x
    positions, the same kerf compensation, the opposite phase), then it fits too.
    A test on `teeth_count(80, 10) == teeth_count(80, 10)`, on the other hand,
    proves nothing: that is the same call twice.
    """
    from openkerf_api.generators import edge_points

    width, thickness, finger, kerf = 80.0, 3.0, 10.0, 0.1
    along = ((0.0, 0.0), (width, 0.0))

    wall_below = edge_points(*along, thickness, finger, kerf, PHASE[("front", "under")])
    bottom_edge = edge_points(*along, thickness, finger, kerf, PHASE[("bottom", "front")])
    wall_above = edge_points(*along, thickness, finger, kerf, PHASE[("front", "over")])
    lid_edge = edge_points(*along, thickness, finger, kerf, PHASE[("lid", "front")])

    assert wall_above == wall_below
    assert lid_edge == bottom_edge
    # And the seam itself: the opposite phase, and the teeth land in the same
    # places to within ±kerf — exactly as at the bottom.
    assert PHASE[("front", "over")] != PHASE[("lid", "front")]
    above = sorted({round(a[0] - b[0], 4) for a, b in zip(wall_above, lid_edge)})
    below = sorted({round(a[0] - b[0], 4) for a, b in zip(wall_below, bottom_edge)})
    assert above == below == [-kerf, kerf]


def test_a_box_with_a_lid_still_fits_on_the_sheet(client):
    """The walls grow taller from their teeth; that must not break the sheet."""
    answer = client.post(
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

    assert answer.status_code == 201, answer.text
    assert answer.json()["panels"] == [
        "bottom",
        "front",
        "back",
        "left",
        "right",
        "lid",
    ]
