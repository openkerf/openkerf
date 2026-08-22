"""
Het voorbeeld naast de werkelijkheid.

A preview that lies is worse than no preview: anybody going by the sketch and getting
something else out of the machine does not trust the screen anywhere after that. So these
tests lay every generator's preview and its *real* result side by side and demand that they
come out in the same place and at the same size — to within a hundredth of a millimetre.

That is also exactly how the two faults in the first version surfaced: the star came out too
tall (`corners` counts corner points, not star points) and the circle repeat was 45 mm out
(the centre lies beside the selection, not above it). Both looked convincing on their own.
"""

import math
import re

import pytest
from fastapi.testclient import TestClient

from openkerf_api.server import ApiServer

UNITS_PER_MM = 65535 / 25.4


@pytest.fixture
def client(kernel, tmp_path):
    with TestClient(ApiServer(kernel, library_path=tmp_path / "p.db").build_app()) as c:
        yield c


def a_rect(client):
    return client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 10, "y_mm": 10, "width_mm": 20, "height_mm": 10},
    ).json()["ids"][0]


def drawn_extent(client):
    """The box around everything on the sheet now, in mm."""
    elements = client.get("/api/design").json()["elements"]
    boxes = [e["bounds"] for e in elements if e.get("bounds")]
    assert boxes, "there is nothing on the sheet"
    return [
        min(b[0] for b in boxes) / UNITS_PER_MM,
        min(b[1] for b in boxes) / UNITS_PER_MM,
        max(b[2] for b in boxes) / UNITS_PER_MM,
        max(b[3] for b in boxes) / UNITS_PER_MM,
    ]


def preview(client, what, body):
    response = client.post(
        "/api/design/generate/preview", json=dict(body, what=what)
    )
    assert response.status_code == 200, response.json()
    return response.json()


# Every case: what, the form, and whether something has to be selected first.
CASES = [
    ("polygon", {"corners": 6, "cx_mm": 50, "cy_mm": 50, "radius_mm": 20}, False),
    (
        "polygon",
        {"corners": 5, "cx_mm": 40, "cy_mm": 60, "radius_mm": 25, "inner_radius_mm": 10},
        False,
    ),
    ("grid", {"columns": 3, "rows": 2, "gap_x_mm": 5, "gap_y_mm": 5}, True),
    ("grid", {"columns": 2, "rows": 4, "gap_x_mm": 0, "gap_y_mm": 12.5}, True),
    ("radial", {"repeats": 8, "radius_mm": 40}, True),
    ("radial", {"repeats": 6, "radius_mm": 30, "rotate": False}, True),
    ("radial", {"repeats": 5, "radius_mm": 25, "end_deg": 180.0}, True),
    (
        "arctext",
        {"text": "OPENKERF", "cx_mm": 100, "cy_mm": 100, "radius_mm": 40, "font_size_mm": 10},
        False,
    ),
    (
        "arctext",
        {"text": "ONDERLANGS", "cx_mm": 80, "cy_mm": 90, "radius_mm": 30,
         "font_size_mm": 8, "inside": True},
        False,
    ),
    ("qrcode", {"text": "https://openkerf.nl", "size_mm": 30}, False),
    ("qrcode", {"text": "1", "size_mm": 45, "border": 0}, False),
    ("barcode", {"text": "OPENKERF-1", "kind": "code128", "width_mm": 60, "height_mm": 20}, False),
    ("barcode", {"text": "4006381333931", "kind": "ean13", "width_mm": 40, "height_mm": 15}, False),
    (
        "hinge",
        {"pattern": "staggered", "x_mm": 10, "y_mm": 10, "width_mm": 60, "height_mm": 40,
         "slit_mm": 8, "gap_mm": 3, "row_mm": 2},
        False,
    ),
    (
        "hinge",
        {"pattern": "wavy", "x_mm": 5, "y_mm": 5, "width_mm": 40, "height_mm": 30,
         "slit_mm": 6, "gap_mm": 2, "row_mm": 2.5},
        False,
    ),
]


@pytest.mark.parametrize("what,body,needs_selection", CASES)
def test_the_preview_lands_where_the_real_thing_lands(client, what, body, needs_selection):
    if needs_selection:
        body = dict(body, ids=[a_rect(client)])

    sketch = preview(client, what, body)
    assert client.post(f"/api/design/generate/{what}", json=body).status_code < 400

    for expected, measured in zip(sketch["bounds"], drawn_extent(client)):
        assert expected == pytest.approx(measured, abs=0.01)


def placed_box(part, shape_box):
    """Where a shape's box lands, rotation and all."""
    x0, y0, x1, y1 = shape_box
    angle = math.radians(part["rot"])
    px, py = part.get("rx", 0.0), part.get("ry", 0.0)
    xs, ys = [], []
    for cx, cy in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        dx, dy = cx - px, cy - py
        xs.append(part["x"] + px + dx * math.cos(angle) - dy * math.sin(angle))
        ys.append(part["y"] + py + dx * math.sin(angle) + dy * math.cos(angle))
    return [min(xs), min(ys), max(xs), max(ys)]


COPIES = [
    ("grid", {"columns": 3, "rows": 2, "gap_x_mm": 5, "gap_y_mm": 5}),
    ("radial", {"repeats": 8, "radius_mm": 40}),
    ("radial", {"repeats": 5, "radius_mm": 25, "end_deg": 180.0}),
    ("radial", {"repeats": 5, "radius_mm": 25, "end_deg": 180.0, "rotate": False}),
    ("radial", {"repeats": 4, "radius_mm": 18, "end_deg": 90.0}),
    ("radial", {"repeats": 4, "radius_mm": 18, "end_deg": 90.0, "rotate": False}),
    ("radial", {"repeats": 7, "radius_mm": 35, "end_deg": 270.0}),
    ("radial", {"repeats": 7, "radius_mm": 35, "end_deg": 270.0, "rotate": False}),
    ("radial", {"repeats": 3, "radius_mm": 22, "rotate": False}),
    ("grid", {"columns": 1, "rows": 5, "gap_x_mm": 0, "gap_y_mm": 2.5}),
    ("grid", {"columns": 5, "rows": 1, "gap_x_mm": 3, "gap_y_mm": 0}),
]


@pytest.mark.parametrize("what,body", COPIES)
def test_every_single_copy_lands_where_the_preview_put_it(client, what, body):
    """
    The box around the whole is too coarse: on a full circle it is symmetric, and then a
    mirrored direction of rotation does not stand out in it. That is how the circle repeat was
    out at first — only an arc of 180° showed that the copies ran the other way.
    """
    body = dict(body, ids=[a_rect(client)])
    sketch = preview(client, what, body)
    # The selection is one rectangle of 20 x 10 mm; that is the shape.
    voorspeld = sorted(
        placed_box(part, (0.0, 0.0, 20.0, 10.0)) for part in sketch["parts"]
    )

    assert client.post(f"/api/design/generate/{what}", json=body).status_code < 400
    elements = client.get("/api/design").json()["elements"]
    werkelijk = sorted(
        [v / UNITS_PER_MM for v in element["bounds"]] for element in elements
    )

    assert len(voorspeld) == len(werkelijk)
    for verwacht, gemeten in zip(voorspeld, werkelijk):
        assert verwacht == pytest.approx(gemeten, abs=0.01)


def test_a_selection_of_more_than_one_shape_is_repeated_as_a_whole(client):
    """
    The engine repeats the selection as a whole and computes its pitch on the box around
    everything (`Node.union_bounds`). With one shape it does not show whether the preview does
    that too.
    """
    eerste = a_rect(client)
    tweede = client.post(
        "/api/design/elements",
        json={"type": "circle", "cx_mm": 45, "cy_mm": 30, "r_mm": 8},
    ).json()["ids"][0]
    body = {"ids": [eerste, tweede], "columns": 3, "rows": 2, "gap_x_mm": 4, "gap_y_mm": 4}

    sketch = preview(client, "grid", body)
    assert client.post("/api/design/generate/grid", json=body).status_code < 400

    assert len(sketch["parts"]) == 6
    for expected, measured in zip(sketch["bounds"], drawn_extent(client)):
        assert expected == pytest.approx(measured, abs=0.01)


def test_the_preview_draws_the_panels_the_box_is_made_of(client):
    body = {
        "width_mm": 60, "depth_mm": 50, "height_mm": 40,
        "thickness_mm": 3, "finger_mm": 10, "kerf_mm": 0.15, "lid": True,
    }
    sketch = preview(client, "box", body)

    # Every panel its own outline: the finger joints differ per panel, so they must not
    # borrow each other's shape.
    assert sketch["sheets"] == 1
    assert len(sketch["shapes"]) == len(sketch["parts"]) == 6
    assert sketch["labels"] == ["bottom", "front", "back", "left", "right", "lid"]
    # Front and back are each other's equal, as are left/right and bottom/lid; so three
    # different outlines is right, six would actually be suspicious.
    assert len(set(sketch["shapes"])) == 3

    zonder_deksel = preview(client, "box", dict(body, lid=False))
    assert "lid" not in zonder_deksel["labels"]
    assert len(zonder_deksel["parts"]) == 5


def test_the_box_panels_lie_where_they_get_cut(client):
    body = {
        "width_mm": 60, "depth_mm": 50, "height_mm": 40,
        "thickness_mm": 3, "finger_mm": 10, "kerf_mm": 0.15, "lid": True,
    }
    sketch = preview(client, "box", body)
    assert client.post("/api/design/generate/box", json=body).status_code < 400

    elements = client.get("/api/design").json()["elements"]
    werkelijk = sorted(
        [v / UNITS_PER_MM for v in element["bounds"]] for element in elements
    )
    voorspeld = sorted(
        [
            part["x"] + box[0], part["y"] + box[1],
            part["x"] + box[2], part["y"] + box[3],
        ]
        for part, box in zip(sketch["parts"], _shape_boxes(sketch))
    )

    for verwacht, gemeten in zip(voorspeld, werkelijk):
        assert verwacht == pytest.approx(gemeten, abs=0.01)


def _shape_boxes(sketch):
    """The box around every shape, back out of the d-string: only M/L paths here."""
    boxes = []
    for shape in sketch["shapes"]:
        pairs = [
            [float(v) for v in blok.split(",")]
            for blok in re.findall(r"-?[\d.eE+-]+,-?[\d.eE+-]+", shape)
        ]
        boxes.append(
            [
                min(p[0] for p in pairs), min(p[1] for p in pairs),
                max(p[0] for p in pairs), max(p[1] for p in pairs),
            ]
        )
    return boxes


def test_a_box_that_needs_two_sheets_says_so(client):
    sketch = preview(
        client,
        "box",
        {"width_mm": 200, "depth_mm": 190, "height_mm": 120, "thickness_mm": 4,
         "finger_mm": 20, "kerf_mm": 0.1},
    )
    assert sketch["sheets"] > 1
    assert any("not fit on one sheet" in note for note in sketch["notes"])


def test_the_preview_stops_drawing_at_five_hundred_copies(client):
    sketch = preview(
        client,
        "grid",
        {"ids": [a_rect(client)], "columns": 30, "rows": 30, "gap_x_mm": 1, "gap_y_mm": 1},
    )
    assert len(sketch["parts"]) == 500
    assert any("900" in note for note in sketch["notes"])


# ----------------------------------------------- foute invoer, zelfde verhaal

BAD = [
    ("grid", {"columns": 1, "rows": 1}, True),
    ("grid", {"columns": 3, "rows": 3, "gap_x_mm": -5}, True),
    ("radial", {"repeats": 1, "radius_mm": 20}, True),
    ("polygon", {"corners": 2, "cx_mm": 10, "cy_mm": 10, "radius_mm": 20}, False),
    (
        "polygon",
        {"corners": 5, "cx_mm": 10, "cy_mm": 10, "radius_mm": 20, "inner_radius_mm": 30},
        False,
    ),
    (
        "box",
        {"width_mm": 100, "depth_mm": 80, "height_mm": 50, "thickness_mm": 3,
         "finger_mm": 90},
        False,
    ),
    (
        "box",
        {"width_mm": 20, "depth_mm": 20, "height_mm": 20, "thickness_mm": 9,
         "finger_mm": 10},
        False,
    ),
    ("qrcode", {"text": "", "size_mm": 30}, False),
    ("barcode", {"text": "abc", "kind": "ean13", "width_mm": 40, "height_mm": 15}, False),
    ("barcode", {"text": "x", "kind": "geenidee", "width_mm": 40, "height_mm": 15}, False),
    (
        "arctext",
        {"text": "EEN VEEL TE LANGE ZIN VOOR DIT CIRKELTJE", "cx_mm": 50, "cy_mm": 50,
         "radius_mm": 3, "font_size_mm": 10},
        False,
    ),
    (
        "hinge",
        {"pattern": "straight", "width_mm": 60, "height_mm": 40, "slit_mm": 60,
         "gap_mm": 3, "row_mm": 2},
        False,
    ),
    (
        "hinge",
        {"pattern": "straight", "width_mm": 60, "height_mm": 3, "slit_mm": 8,
         "gap_mm": 3, "row_mm": 2},
        False,
    ),
]


@pytest.mark.parametrize("what,body,needs_selection", BAD)
def test_the_preview_refuses_with_the_same_words_as_the_real_thing(
    client, what, body, needs_selection
):
    """
    Otherwise the form teaches you one story and the button another. This is the reason the
    arithmetic is in `_plan_*` and not written twice.
    """
    if needs_selection:
        body = dict(body, ids=[a_rect(client)])

    sketch = client.post("/api/design/generate/preview", json=dict(body, what=what))
    real = client.post(f"/api/design/generate/{what}", json=body)

    assert sketch.status_code == real.status_code == 409
    assert sketch.json()["detail"] == real.json()["detail"]


def test_a_grid_without_a_selection_says_what_to_do(client):
    response = client.post(
        "/api/design/generate/preview",
        json={"what": "grid", "ids": [], "columns": 2, "rows": 2},
    )
    assert response.status_code == 409
    assert "Choose what" in response.json()["detail"]


def test_an_unknown_generator_is_refused(client):
    response = client.post(
        "/api/design/generate/preview", json={"what": "raketmotor"}
    )
    assert response.status_code == 409


# ------------------------------------------------------------- geen sporen


def test_the_preview_leaves_the_drawing_alone(client):
    """
    The preview runs on every key stroke and therefore has *no* write guard. That is only
    allowed when the claim it rests on is really true: it does not touch the tree. Not "it
    cleans up after itself" — then during a running job it would silently change somebody
    else's work, and then the guard would belong on it.

    Hence this compares the whole snapshot and not only a few counts: elements, operations,
    sheets, and everything that hangs off them. If this test fails, the route has changed kind
    and `write` has to go on it — `test_every_mutating_route_requires_the_write_guard` holds
    the other side
    van diezelfde afspraak vast.
    """
    rect = a_rect(client)
    before = client.get("/api/design").json()
    before_sheets = client.get("/api/sheets").json()

    for what, body, needs_selection in CASES + BAD + [
        # The case most likely to leave traces: here the *real* box generator creates a
        # second sheet and jumps to it. The preview only says so.
        (
            "box",
            {"width_mm": 200, "depth_mm": 190, "height_mm": 120, "thickness_mm": 4,
             "finger_mm": 20, "kerf_mm": 0.1},
            False,
        )
    ]:
        if needs_selection:
            body = dict(body, ids=[rect])
        client.post("/api/design/generate/preview", json=dict(body, what=what))

    assert client.get("/api/design").json() == before
    assert client.get("/api/sheets").json() == before_sheets
    # And the comparison's premise holds: there was something to guard. An empty tree that
    # stays empty proves nothing.
    assert len(before["elements"]) == 1
    assert len(before_sheets["sheets"]) == 1


def test_the_preview_adds_nothing_to_undo(client):
    """
    A preview that leaves a step on the undo stack is just as annoying as a preview that
    draws: you press undo and nothing visible happens. Seven steps back is the silent variant
    of the same fault.
    """
    rect = a_rect(client)
    for what, body, needs_selection in CASES:
        if needs_selection:
            body = dict(body, ids=[rect])
        client.post("/api/design/generate/preview", json=dict(body, what=what))

    # One step back removes the rectangle — so there was nothing in between.
    assert client.post("/api/design/undo").status_code < 400
    assert client.get("/api/design").json()["elements"] == []


def test_the_arc_text_preview_does_not_change_the_chosen_font(client, kernel):
    """
    `create_linetext_node` writes the chosen font to `context.last_font`
    (extra/hershey.py:492), and everything placed after that without a font
    inherits it quietly — that is the bug that once put the captions on a test
    board in Apple Chancery. A preview should stay well out of it: you have not
    chosen anything yet.
    """
    registry = kernel.root.fonts
    registry.context.setting(str, "last_font", "")
    registry.context.last_font = "something-the-user-picked"

    preview(
        client,
        "arctext",
        {"text": "OPENKERF", "cx_mm": 100, "cy_mm": 100, "radius_mm": 40,
         "font_size_mm": 10},
    )

    assert registry.context.last_font == "something-the-user-picked"
