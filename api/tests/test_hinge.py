"""
De levende scharnier: een veld sleuven waardoor stijf plaatmateriaal buigt.

What is measured here is what you pay for on material. Three things, and they are the three
things that can be wrong without looking wrong:

1. **How many slits.** Too few and it does not bend, too many and it snaps. The count
   follows from the area, the pitch and the row distance, and there is exactly one right
   answer for a given form.
2. **Nothing outside the area.** A slit that runs on past the edge is not a hinge but a saw
   cut through the workpiece — and it is invisible on a preview that zooms to fit.
3. **That a staggered pattern really staggers.** In phase it looks the same at a glance and
   it bends over one line instead of over the whole field.
"""

import re

import pytest
from fastapi.testclient import TestClient

from openkerf_api.server import ApiServer

UNITS_PER_MM = 65535 / 25.4

# One form used by nearly every test below: 60 x 40 mm, slits of 8 mm with 3 mm between
# them (so a pitch of 11) and 2 mm between the rows.
FORM = {
    "x_mm": 0, "y_mm": 0, "width_mm": 60, "height_mm": 40,
    "slit_mm": 8, "gap_mm": 3, "row_mm": 2,
}


@pytest.fixture
def client(kernel, tmp_path):
    with TestClient(ApiServer(kernel, library_path=tmp_path / "h.db").build_app()) as c:
        yield c


def preview(client, body):
    response = client.post(
        "/api/design/generate/preview", json=dict(body, what="hinge")
    )
    assert response.status_code == 200, response.json()
    return response.json()


def make(client, body):
    return client.post("/api/design/generate/hinge", json=body)


def subpaths(d: str):
    """The d-string cut into subpaths: every one begins at an M."""
    return [piece.strip() for piece in d.split("M") if piece.strip()]


def rows_of(d: str):
    """Per row height, the x where each slit in it begins."""
    rows: dict[float, list[float]] = {}
    for x, y in re.findall(r"M ([-\d.]+),([-\d.]+)", d):
        rows.setdefault(round(float(y), 4), []).append(float(x))
    return rows


def points_of(d: str):
    return [
        (float(x), float(y))
        for x, y in re.findall(r"([-\d.]+),([-\d.]+)", d)
    ]


# ------------------------------------------------------------ hoeveel sleuven


def test_the_number_of_slits_follows_from_the_area(client):
    """
    60 mm wide at a pitch of 11 mm is six slits per row (the sixth one clipped by the edge),
    40 mm high at 2 mm per row is twenty rows: 120 slits. Measured, and it is the same number
    for straight and for staggered — the stagger shifts them, it does not add any.
    """
    for pattern in ("straight", "staggered"):
        sketch = preview(client, dict(FORM, pattern=pattern))
        assert sketch["rows"] == 20
        assert sketch["slits"] == 120, pattern
        assert len(subpaths(sketch["shapes"][0])) == 120


def test_a_wavy_field_gives_up_one_row_to_its_crests(client):
    """
    A wave sticks out above and below its row line, so the field needs 2 x 0.8 mm more room
    than the rows themselves: nineteen rows instead of twenty, spanning y 1.2 .. 38.8.
    """
    sketch = preview(client, dict(FORM, pattern="wavy"))

    assert sketch["rows"] == 19
    assert sketch["slits"] == 114
    assert sketch["bounds"][1] == pytest.approx(1.2, abs=0.001)
    assert sketch["bounds"][3] == pytest.approx(38.8, abs=0.001)
    # Two quads per slit and not a polyline: a wave that is interpolated away cuts a
    # different length than the one you saw.
    assert sketch["shapes"][0].count("Q") == 228


def test_wider_rows_mean_fewer_slits(client):
    """The pitch is slit plus gap; twice the gap is roughly half the slits."""
    dense = preview(client, dict(FORM, pattern="straight", gap_mm=3))
    thin = preview(client, dict(FORM, pattern="straight", gap_mm=14))

    assert dense["slits"] == 120
    # Pitch 22: three slits per row instead of six.
    assert thin["slits"] == 60


# ---------------------------------------------------- niets buiten het gebied


@pytest.mark.parametrize("pattern", ["straight", "staggered", "wavy"])
def test_nothing_falls_outside_the_area(client, pattern):
    """
    Not the bounding box of the answer but every single point of it: a slit that runs on past
    the edge saws the workpiece in two, and on a preview that zooms to fit that looks exactly
    like a hinge.
    """
    body = dict(FORM, pattern=pattern, x_mm=20, y_mm=15)
    sketch = preview(client, body)

    for x, y in points_of(sketch["shapes"][0]):
        assert 20 - 0.001 <= x <= 80 + 0.001, (x, y)
        assert 15 - 0.001 <= y <= 55 + 0.001, (x, y)


def test_no_row_lies_on_the_boundary(client):
    """
    A slit exactly on the edge weakens the edge and bends nothing. The rows are laid out from
    the middle outwards, so 40 mm at 2 mm per row runs from y=1 to y=39 and not from 0 to 40.
    """
    sketch = preview(client, dict(FORM, pattern="straight"))
    heights = sorted(rows_of(sketch["shapes"][0]))

    assert heights[0] == 1.0
    assert heights[-1] == 39.0


# ------------------------------------------------------- staggert het echt?


def test_a_staggered_pattern_really_staggers(client):
    """
    Every other row half a pitch to the left, so a bridge in one row sits opposite a slit in
    the next. Measured: row y=1 starts at 0, 11, 22 … and row y=3 at 0, 5.5, 16.5 — the 0 is
    the piece the edge clipped off the slit that begins at −5.5.
    """
    rows = rows_of(preview(client, dict(FORM, pattern="staggered"))["shapes"][0])

    assert rows[1.0] == [0.0, 11.0, 22.0, 33.0, 44.0, 55.0]
    assert rows[3.0] == [0.0, 5.5, 16.5, 27.5, 38.5, 49.5]
    assert rows[5.0] == rows[1.0]


def test_a_straight_pattern_does_not_stagger(client):
    """The counter-proof: without it the test above would pass on a broken stagger too."""
    rows = rows_of(preview(client, dict(FORM, pattern="straight"))["shapes"][0])

    assert len(set(tuple(starts) for starts in rows.values())) == 1


# ------------------------------------------------------- wat er terechtkomt


def test_the_field_lands_as_one_shape_in_a_cut_layer(client):
    """
    One element, so the whole field drags along as one thing, and in a cut layer, because a
    slit that is engraved does not bend anything.
    """
    assert make(client, dict(FORM, pattern="staggered")).status_code == 201

    design = client.get("/api/design").json()
    assert len(design["elements"]) == 1
    element = design["elements"][0]
    assert element["label"] == "Living hinge — staggered rows"
    layers = [layer for layer in design["operations"] if layer["element_ids"]]
    assert [layer["label"] for layer in layers] == ["Cut"]
    assert len(element["operation_ids"]) == 1


def test_a_slit_is_a_line_and_not_a_closed_sliver(client):
    """
    `_add_polygon` closes every ring it gets; a slit closed on itself is cut twice, once
    there and once back over the same line. Measured on the geometry the canvas draws: five
    whole slits of 8 mm and one clipped one of 5 mm per row is 45 mm, over twenty rows 900 mm
    of cut, and there is not one Z in it.
    """
    assert make(client, dict(FORM, pattern="straight")).status_code == 201

    d = client.get("/api/design").json()["elements"][0]["path"]
    assert "Z" not in d.upper()
    length = 0.0
    for piece in re.findall(r"M ([-\d.]+),([-\d.]+) L ([-\d.]+),([-\d.]+)", d):
        x0, _, x1, _ = (float(v) for v in piece)
        length += abs(x1 - x0)
    assert length / UNITS_PER_MM == pytest.approx(20 * 45, abs=0.01)


def test_the_preview_lands_where_the_real_field_lands(client):
    """The whole reason `_plan_hinge` exists once and not twice."""
    body = dict(FORM, pattern="wavy", x_mm=12, y_mm=7)
    sketch = preview(client, body)
    assert make(client, body).status_code == 201

    bounds = client.get("/api/design").json()["elements"][0]["bounds"]
    for expected, measured in zip(sketch["bounds"], bounds):
        assert expected == pytest.approx(measured / UNITS_PER_MM, abs=0.01)


# ------------------------------------------------------------- het gebied


def test_the_selection_can_be_the_area(client):
    """
    A hinge is nearly always a strip in a shape you have already drawn. Then the box around
    that shape is the area, and you do not have to type four numbers you can read off the
    screen.
    """
    rect = client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 30, "y_mm": 20, "width_mm": 50, "height_mm": 24},
    ).json()["ids"][0]

    sketch = preview(
        client,
        {"ids": [rect], "from_selection": True, "pattern": "straight",
         "slit_mm": 8, "gap_mm": 3, "row_mm": 2},
    )

    assert sketch["rows"] == 12
    x0, y0, x1, y1 = sketch["bounds"]
    assert (x0, x1) == pytest.approx((30.0, 80.0), abs=0.001)
    assert (y0, y1) == pytest.approx((21.0, 43.0), abs=0.001)


def test_the_selection_area_needs_a_selection(client):
    response = client.post(
        "/api/design/generate/preview",
        json={"what": "hinge", "from_selection": True, "ids": []},
    )
    assert response.status_code == 409
    assert response.headers["X-OpenKerf-Error"] == "gen.hingeNeedsSelection"


# ---------------------------------------------------- weigeringen en waarschuwingen


BAD = [
    # A slit as long as the area is wide is a cut straight through it.
    (dict(FORM, pattern="straight", slit_mm=60), "cuts the piece in two"),
    (dict(FORM, pattern="straight", slit_mm=61), "cuts the piece in two"),
    # One row of slits is not a hinge.
    (dict(FORM, pattern="straight", height_mm=3, row_mm=2), "not two rows"),
    (dict(FORM, pattern="wavy", height_mm=4, row_mm=2), "not two rows"),
    # Too fine to plan: the optimisation scales quadratically in the number of pieces.
    (dict(FORM, pattern="straight", width_mm=300, height_mm=300, slit_mm=4,
          gap_mm=0.5, row_mm=0.5), "cut plan takes longer"),
    (dict(FORM, pattern="ruitjes"), "Unknown pattern"),
    (dict(FORM, pattern="straight", slit_mm=0), "greater than zero"),
    (dict(FORM, pattern="straight", row_mm=-1), "greater than zero"),
]


@pytest.mark.parametrize("body,fragment", BAD)
def test_the_preview_refuses_with_the_same_words_as_the_real_thing(
    client, body, fragment
):
    sketch = client.post("/api/design/generate/preview", json=dict(body, what="hinge"))
    real = make(client, body)

    assert sketch.status_code == real.status_code == 409
    assert sketch.json()["detail"] == real.json()["detail"]
    assert fragment in sketch.json()["detail"]
    assert client.get("/api/design").json()["elements"] == []


def test_a_gap_thinner_than_the_cut_itself_is_said_out_loud(client):
    """
    The mistake that snaps the wood, and the only one we can name from the numbers: a bridge
    of 0.2 mm is about the width of the cut on either side of it, so there is nothing left of
    it. Not a refusal — how wide the cut is depends on the machine — but it is not left
    unsaid either.
    """
    sketch = preview(client, dict(FORM, pattern="straight", gap_mm=0.2))

    assert any("burn away" in note for note in sketch["notes"])
    assert sketch["bridge_mm"] == 0.2
    # And it stays quiet when there is nothing to say.
    assert preview(client, dict(FORM, pattern="straight"))["notes"] == []
