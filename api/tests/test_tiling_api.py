"""
The tile routes, and the coverage test that makes the whole design good.
"""

import pytest
from fastapi.testclient import TestClient

from openkerf_api.server import ApiServer


@pytest.fixture
def client(kernel, tmp_path):
    with TestClient(ApiServer(kernel, library_path=tmp_path / "v.db").build_app()) as c:
        yield c


def wide_plate(client):
    """
    A plate that comes to exactly three tiles on the dummy bed.

    The dummy device measures 320 × 220 mm, so the usable window is 300 mm wide
    and 800 mm of plate gives three tiles. At 900 it becomes four.
    """
    sheet = client.get("/api/sheets").json()["sheets"][0]
    client.patch(
        f"/api/sheets/{sheet['id']}", json={"width_mm": 800.0, "height_mm": 150.0}
    )
    client.patch(f"/api/sheets/{sheet['id']}", json={"tiling": {"enabled": True}})
    for x in (10, 300, 600):
        client.post(
            "/api/design/elements",
            json={
                "type": "rect",
                "x_mm": x,
                "y_mm": 40,
                "width_mm": 40,
                "height_mm": 40,
            },
        )
    _enable_output(client)
    return sheet


def _enable_output(client) -> None:
    """
    The layer a fresh rectangle lands in is off by default ("burn along" off) —
    the factory setting of an engrave layer. Without this `TileRun.burn` puts
    nothing on the spooler and reports "nothing ready to burn", while the geometry
    is very much there.
    """
    for operation in client.get("/api/design").json()["operations"]:
        if not operation["output"] and operation["element_ids"]:
            client.patch(
                f"/api/design/operations/{operation['id']}", json={"output": True}
            )


def test_the_layout_is_readable_without_starting_anything(client):
    """Looking at what it will become should not start a series."""
    wide_plate(client)

    answer = client.get("/api/tiling")

    assert answer.status_code == 200
    assert len(answer.json()["tiles"]) == 3
    assert client.get("/api/status").json()["tiling"] is None


def test_burning_before_aligning_is_refused_in_a_sentence(client):
    wide_plate(client)
    client.post("/api/tiling/start")

    answer = client.post("/api/tiling/burn")

    assert answer.status_code == 409
    # See the test of the same name in test_tilerun.py: the refusal has to name
    # aligning in a word the reader recognises.
    assert "aligned" in answer.json()["detail"].lower()


def test_the_series_shows_up_in_the_status_payload(client):
    """
    Top bar, canvas and phone all three read the same state; a request of its own
    per screen would let them drift apart.
    """
    wide_plate(client)
    client.post("/api/tiling/start")

    state = client.get("/api/status").json()["tiling"]

    assert state["current"] == 0
    assert state["tiles"] == 3
    assert state["aligned"] is False


def test_cancelling_leaves_no_series_behind(client):
    wide_plate(client)
    client.post("/api/tiling/start")

    client.post("/api/tiling/cancel")

    assert client.get("/api/status").json()["tiling"] is None


def test_here_takes_the_position_the_machine_reports(client):
    """
    "Here" is the button every alignment in real life goes through: you jog the
    head to the mark and press it. Until now no test touched that path at all —
    every test passed its points as numbers, which nobody ever does.
    """
    wide_plate(client)
    client.post("/api/tiling/start")

    answer = client.post(
        "/api/tiling/align",
        json={"reference": "plate_corner", "use_current": True},
    )

    assert answer.status_code == 200, answer.json()
    assert answer.json()["aligned"] is True


def test_three_tiles_together_burn_the_whole_design_exactly_once(client, kernel):
    """
    The crown on this design: the tiles together burn exactly the design.

    Nothing twice (the laser would go over the same line twice, visible and on
    thin material fatal), nothing forgotten (a piece would drop out of the work).
    Measured as total geometry length, because that is the only number that
    catches both mistakes at once.
    """
    wide_plate(client)
    # A shape lying straight across a seam, because that is the hard case. The
    # seams are around 275 and 525 mm; this rectangle covers the whole overlap
    # zone of the second seam, so it *cannot* be dodged and really has to be cut
    # in half.
    client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 480, "y_mm": 40, "width_mm": 90, "height_mm": 60},
    )
    # And a circle across the *other* seam. Rectangles have straight segments
    # only, and it is arcs that hold the three engine bugs this branch had to work
    # around: the batch calculation that hangs, the segment that disappears in
    # polycut, and `Geomstr.split` that does not split arcs at all. A coverage
    # trial without a single arc leaves exactly that unmeasured.
    client.post(
        "/api/design/elements",
        json={"type": "ellipse", "cx_mm": 275, "cy_mm": 75, "rx_mm": 45, "ry_mm": 45},
    )

    original = _design_length_mm(kernel)

    client.post("/api/tiling/start")
    burned = 0.0
    for tile in range(3):
        client.post(
            "/api/tiling/align",
            json=(
                {"reference": "plate_corner", "points": [{"x_mm": 0.0, "y_mm": 0.0}]}
                if tile == 0
                else {"reference": "markers", "points": _marks_at(client, tile - 1)}
            ),
        )
        answer = client.post("/api/tiling/burn")
        assert answer.status_code == 200, answer.json()
        burned += answer.json()["burned_length_mm"]
        client.post("/api/tiling/advance")

    assert burned == pytest.approx(original, rel=0.001)


def _design_length_mm(kernel) -> float:
    """The total length of the design, in millimetres."""
    from meerk40t.core.units import UNITS_PER_MM

    total = 0.0
    for node in kernel.elements.elems():
        geom = node.as_geometry()
        total += sum(abs(geom.length(i)) for i in range(geom.index))
    return total / float(UNITS_PER_MM)


def _marks_at(client, boundary: int) -> list[dict]:
    """
    The marks of this boundary, tapped without error.

    In real life you jog to them; here we pretend the plate has shifted exactly as
    far as the layout says, so that the test is about the coverage and not about
    tapping accuracy.
    """
    layout = client.get("/api/tiling").json()
    mark = next(m for m in layout["marks"] if m["boundary"] == boundary)
    tile = layout["tiles"][boundary + 1]
    dx = tile["burn"]["x0_mm"]
    return [{"x_mm": p["x_mm"] - dx, "y_mm": p["y_mm"]} for p in mark["points"]]
