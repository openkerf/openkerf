"""
Filling a plate: as many pieces as the material holds, each with the next name.

The arithmetic is the part everybody does in their head and gets wrong — the gap is
between the pieces, so a plate of 500 mm does not hold eight 60 mm tags with 5 mm
between them but seven — so that is tested on numbers, without a kernel.

What is worth testing beyond it is the seam: that the copies really do take the next
row (and not the same one twenty times, which is the bug this exists to prevent), that
the places the list cannot fill are not left standing on the plate, and that filling a
plate makes the run count plates rather than names.
"""

import pytest
from fastapi.testclient import TestClient

from openkerf_api.edits import DesignError
from openkerf_api.plating import MAX_PLACES, plan_plate
from openkerf_api.server import ApiServer

NAMES = ("Anna", "Bram", "Cees", "Daan", "Eva", "Fien", "Gijs", "Hanna", "Ids", "Joke")


@pytest.fixture
def server(kernel, tmp_path):
    return ApiServer(kernel, library_path=tmp_path / "plate.db")


@pytest.fixture
def client(server):
    with TestClient(server.build_app()) as c:
        c.server = server
        yield c


def a_list(client, names=NAMES):
    """A list of names on the server, attached."""
    csv = ("name\n" + "\n".join(names) + "\n").encode("utf-8")
    uploaded = client.post(
        "/api/series/upload", files={"file": ("names.csv", csv, "text/csv")}
    )
    assert uploaded.status_code == 200, uploaded.text
    attached = client.post("/api/series/attach", json={"file": uploaded.json()["file"]})
    assert attached.status_code == 200, attached.text
    return attached.json()


def a_plate(client, width=500.0, height=300.0):
    """
    The sheet these tests lay out on, said out loud.

    The test kernel's dummy device has a bed of 320 × 220 mm, and a plate whose size
    comes from whatever machine happens to be active is a test whose numbers change
    with the fixture. The sheet is the plate here (`Plating._sheet_mm` prefers it over
    the bed, which is what a sheet is for), so setting it makes the arithmetic below
    read the way the handbook does.
    """
    sheets = client.get("/api/sheets").json()
    sheet_id = sheets["active"]
    changed = client.patch(
        f"/api/sheets/{sheet_id}", json={"width_mm": width, "height_mm": height}
    )
    assert changed.status_code == 200, changed.text


def a_tag(client, x=200.0, y=120.0, width=60.0, height=30.0):
    """One piece: a rectangle with a name in it, the two grouped as one tag."""
    outline = client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": x, "y_mm": y, "width_mm": width, "height_mm": height},
    )
    assert outline.status_code == 201, outline.text
    text = client.post(
        "/api/design/elements",
        json={"type": "text", "x_mm": x + 5, "y_mm": y + 20, "text": "{name}", "font_size_mm": 8},
    )
    assert text.status_code == 201, text.text
    ids = outline.json()["ids"] + text.json()["ids"]
    grouped = client.post("/api/design/group", json={"ids": ids})
    assert grouped.status_code == 200, grouped.text
    return ids


def templates(client) -> list[str]:
    """Every template on the bed, in tree order."""
    return [
        element["text"]["text"]
        for element in client.get("/api/design").json()["elements"]
        if element.get("text") and "{" in (element["text"]["text"] or "")
    ]


# ----------------------------------------------------------------- the arithmetic


def test_the_gap_is_between_the_pieces_and_not_around_them():
    """
    The sum everybody does in their head and gets wrong.

    A 500 × 300 plate, a 60 × 30 piece, 5 mm between them and 10 mm free at the edge:
    the room is 480 × 280, the pitch is 65 × 35, and (480 + 5) / 65 = 7.46 — so seven
    across and eight down. Counting the gap round every piece instead gives six, and
    counting no gap at all gives eight: both put a cut over the clamp.
    """
    plan = plan_plate((60, 30), (500, 300), margin_mm=10, gap_mm=5)

    assert (plan["columns"], plan["rows"]) == (7, 8)
    assert plan["places"] == 56
    # And the block it lays down really is inside the room it measured.
    assert plan["block_mm"][0] <= 480 + 1e-6
    assert plan["block_mm"][1] <= 280 + 1e-6


def test_a_piece_that_fits_exactly_still_fits():
    """
    The edge case that a naive `//` gets wrong by one.

    Two 100 mm pieces with 10 mm between them need exactly 210 mm, and a plate with 210
    mm free must hold both — otherwise the app refuses a plate that is right to the
    millimetre, which is exactly the plate somebody cut to size for this job.
    """
    plan = plan_plate((100, 100), (210, 210), margin_mm=0, gap_mm=10)

    assert (plan["columns"], plan["rows"]) == (2, 2)


def test_a_piece_bigger_than_the_plate_is_refused_with_both_measurements():
    with pytest.raises(DesignError) as refusal:
        plan_plate((300, 50), (200, 200), margin_mm=10, gap_mm=5)

    assert refusal.value.code == "plate.tooBig"
    # Both sizes in the sentence: "it does not fit" without the numbers leaves the
    # reader guessing which of the two to change.
    assert "300" in str(refusal.value) and "180" in str(refusal.value)


def test_the_count_stops_at_the_number_of_rows_there_are():
    """
    Fifty-six places for a ten-name list would leave forty-six of them engraving
    nothing on every single plate.
    """
    plan = plan_plate((60, 30), (500, 300), margin_mm=10, gap_mm=5, wanted=10)

    assert plan["places"] == 10
    # What the plate *could* hold is still reported: the window says both when they
    # differ, because "ten of the fifty-six places" is the useful sentence.
    assert plan["fit"] == 56


def test_more_places_than_the_plan_can_carry_are_refused():
    with pytest.raises(DesignError) as refusal:
        plan_plate((1, 1), (1000, 1000), margin_mm=0, gap_mm=0)

    assert refusal.value.code == "plate.tooMany"
    assert refusal.value.values["max"] == MAX_PLACES


def test_a_negative_gap_and_a_negative_margin_are_refused():
    for kwargs, code in (
        ({"gap_mm": -1}, "plate.badGap"),
        ({"margin_mm": -1}, "plate.badMargin"),
    ):
        with pytest.raises(DesignError) as refusal:
            plan_plate((10, 10), (100, 100), **kwargs)
        assert refusal.value.code == code


# --------------------------------------------------------------------- the plate


def test_filling_gives_every_copy_the_next_name(client):
    """
    The whole point, and the bug it replaces: `grid` on its own copies the node and
    knows nothing about a list, so twenty tags all read `Anna`.
    """
    a_plate(client)
    a_list(client, NAMES[:6])
    a_tag(client, width=100, height=60)

    filled = client.post("/api/series/plate", json={"gap_mm": 5, "margin_mm": 10})

    assert filled.status_code == 201, filled.text
    assert filled.json()["filled"] == 6
    assert sorted(templates(client)) == sorted(
        ["{name}", "{name#+1}", "{name#+2}", "{name#+3}", "{name#+4}", "{name#+5}"]
    )


def test_a_filled_plate_makes_the_run_count_plates_and_not_names(client):
    """
    Everything downstream already works off one number — how many rows a burn eats —
    so filling a plate must move *that*, and nothing else has to know about plates.
    A 200 × 130 piece goes four to a 500 × 300 plate, so ten names is three burns: four,
    four, and a last plate holding two.
    """
    a_plate(client)
    a_list(client)
    a_tag(client, width=200, height=130)
    client.post("/api/series/plate", json={"gap_mm": 5, "margin_mm": 10})

    state = client.get("/api/series").json()

    assert state["step"] == 4
    assert state["burns"] == 3


def test_the_places_the_list_cannot_fill_are_not_put_on_the_plate(client):
    """
    A grid can only be a rectangle, so seven places on a plate three wide come out as
    nine. The two extra copies would read past the end of the list, and the engine
    engraves a placeholder it cannot resolve as those nine characters — on the plate,
    in the burn list, and in every count the window shows.
    """
    a_plate(client)
    a_list(client, NAMES[:7])
    # Nine fit (3 × 3 of a 90 × 60 piece), and the list has seven: the grid the engine
    # can make is a rectangle, so two of its cells have no row to read.
    a_tag(client, width=90, height=60)

    filled = client.post("/api/series/plate", json={"gap_mm": 5, "margin_mm": 10})

    assert filled.status_code == 201, filled.text
    assert filled.json()["filled"] == 7
    assert len(templates(client)) == 7
    assert client.get("/api/series").json()["step"] == 7


def test_a_whole_tag_goes_and_not_only_its_name(client):
    """
    The trimmed places are whole pieces. Deleting the text alone would leave a nameless
    outline on the plate, which the laser would happily cut.
    """
    a_plate(client)
    a_list(client, NAMES[:7])
    a_tag(client, width=90, height=60)

    client.post("/api/series/plate", json={"gap_mm": 5, "margin_mm": 10})

    # Seven tags of two shapes each, and nothing over.
    assert len(client.get("/api/design").json()["elements"]) == 14


def test_filling_moves_the_piece_into_the_corner_of_its_margin(client):
    """
    A grid grows to the right and downwards, so a piece drawn in the middle of the plate
    would fill a quarter of it. Moving is part of what "fill the plate" means — and it
    is one undo away, which is why it is inside the same undo scope as the copying.
    """
    a_plate(client)
    a_list(client, NAMES[:4])
    a_tag(client, x=300, y=200, width=100, height=60)

    client.post("/api/series/plate", json={"gap_mm": 5, "margin_mm": 12})

    # The snapshot's boxes are in the engine's own units (65535 to the inch), which is
    # why this converts rather than comparing millimetres to Tats.
    per_mm = client.get("/api/design").json()["units_per_mm"]
    boxes = [
        element["bounds"]
        for element in client.get("/api/design").json()["elements"]
        if element["bounds"]
    ]
    assert round(min(box[0] for box in boxes) / per_mm, 1) == 12.0
    assert round(min(box[1] for box in boxes) / per_mm, 1) == 12.0


def test_undoing_a_fill_leaves_the_piece_where_it_was(client):
    a_plate(client)
    a_list(client, NAMES[:4])
    a_tag(client, x=300, y=200, width=100, height=60)
    before = client.get("/api/design").json()["elements"]
    assert len(before) == 2

    client.post("/api/series/plate", json={"gap_mm": 5, "margin_mm": 10})
    assert client.post("/api/design/undo").status_code == 200

    after = client.get("/api/design").json()["elements"]
    assert len(after) == 2
    assert [round(v, 1) for v in after[0]["bounds"]] == [
        round(v, 1) for v in before[0]["bounds"]
    ]


# ------------------------------------------------------------------ the refusals


def test_filling_without_a_list_is_refused_and_says_where_to_go(client):
    a_tag(client)

    refused = client.post("/api/series/plate", json={})

    assert refused.status_code == 409
    assert refused.headers.get("X-OpenKerf-Error") == "plate.noList"
    assert "Repeat" in refused.json()["detail"]


def test_filling_a_piece_that_reads_nothing_is_refused(client):
    a_list(client)
    client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 10, "y_mm": 10, "width_mm": 40, "height_mm": 40},
    )

    refused = client.post("/api/series/plate", json={})

    assert refused.status_code == 409
    assert refused.headers.get("X-OpenKerf-Error") == "plate.nothingReads"


def test_filling_a_plate_that_is_already_filled_is_refused(client):
    """
    Filling twice would shift the copies again — offsets of offsets — and the count
    would be wrong in a way nobody can see on the plate.
    """
    a_plate(client)
    a_list(client)
    a_tag(client, width=100, height=60)
    assert client.post("/api/series/plate", json={}).status_code == 201

    again = client.post("/api/series/plate", json={})

    assert again.status_code == 409
    assert again.headers.get("X-OpenKerf-Error") == "plate.alreadyFilled"


def test_a_piece_naming_a_fixed_row_is_refused(client):
    """
    `{name#3}` is row four whatever the pointer says, so every copy of it would engrave
    that one row — twenty identical plates and no sign of why.
    """
    a_list(client)
    client.post(
        "/api/design/elements",
        json={"type": "text", "x_mm": 20, "y_mm": 20, "text": "{name#3}", "font_size_mm": 8},
    )

    refused = client.post("/api/series/plate", json={})

    assert refused.status_code == 409
    assert refused.headers.get("X-OpenKerf-Error") == "plate.fixedRow"


def test_a_piece_that_fills_the_plate_on_its_own_is_refused(client):
    """
    With one place there is nothing to lay out, and the series already burns one plate
    at a time. Saying so beats making a "grid" of one.
    """
    a_plate(client)
    a_list(client)
    # One place: 460 of the 480 mm free, and 260 of the 280.
    a_tag(client, x=20, y=20, width=460, height=260)

    refused = client.post("/api/series/plate", json={})

    assert refused.status_code == 409
    assert refused.headers.get("X-OpenKerf-Error") == "plate.onlyOne"


def test_the_plan_route_puts_nothing_on_the_plate(client):
    """The window asks this on every keystroke; it may not draw."""
    a_plate(client)
    a_list(client)
    a_tag(client, width=200, height=130)
    before = len(client.get("/api/design").json()["elements"])

    looked = client.get("/api/series/plate?margin_mm=10&gap_mm=5")

    assert looked.status_code == 200, looked.text
    assert looked.json()["places"] == 4
    assert looked.json()["burns"] == 3
    assert len(client.get("/api/design").json()["elements"]) == before


def test_every_place_on_the_plate_is_one_thing_you_can_drag(client):
    """
    `grid` leaves its copies as loose shapes: measured on a plate of seven tags, the
    original kept its group and the six copies came out as twelve separate rectangles
    and texts. Dragging a tag would then take its outline and leave its name where it
    was — and on a plate of twenty that is not a mistake you notice before burning.
    """
    a_plate(client)
    a_list(client, NAMES[:6])
    a_tag(client, width=200, height=130)

    client.post("/api/series/plate", json={"gap_mm": 5, "margin_mm": 10})

    elements = client.get("/api/design").json()["elements"]
    groups = {element["group_id"] for element in elements}
    assert None not in groups, "a shape on a filled plate belongs to no piece"
    # Four places (200 × 130 goes four times on 500 × 300), two shapes each.
    assert len(groups) == 4
    assert len(elements) == 8


def test_the_plate_is_filled_from_the_corner_outwards_without_a_gap_in_it(client):
    """
    The places are a grid and the burn list is a straight count, so place three has to
    be the third piece a person would point at: row by row from the corner. Measured
    here on four places of a 200 × 130 piece with 5 mm between them and 10 mm of margin.
    """
    a_plate(client)
    a_list(client, NAMES[:4])
    a_tag(client, width=200, height=130)

    client.post("/api/series/plate", json={"gap_mm": 5, "margin_mm": 10})

    per_mm = client.get("/api/design").json()["units_per_mm"]
    corners = sorted(
        (round(element["bounds"][1] / per_mm, 1), round(element["bounds"][0] / per_mm, 1))
        for element in client.get("/api/design").json()["elements"]
        if element["bounds"] and element["type"] == "elem rect"
    )
    assert corners == [(10.0, 10.0), (10.0, 215.0), (145.0, 10.0), (145.0, 215.0)]
