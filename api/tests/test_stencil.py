"""
Stencils: what falls out of a cut-out shape, and whether the bridges really hold it.

Three things are measured here, and they are the three that can be wrong without looking
wrong:

1. **Which parts are islands.** Miscount that and the app either bridges nothing — and the
   counter of every O drops out on the bench — or bridges the letter itself to the sheet,
   which is a stencil that sprays a blank.
2. **That the gaps come in pairs.** A gap in the island's own outline joins it to the
   opening, which is a void. Only a gap in the island *and* one in the contour around it,
   at the same place, leave a strip of material that holds. If those two drift apart, the
   picture still looks right and the island still falls out.
3. **That a single-stroke typeface is refused, in its own words.** It is the commonest way
   to arrive at "nothing to do", and it is a different problem from a shape that has no
   holes.

Nothing here has been cut in cardboard. Every number is geometry.
"""

import pytest
from fastapi.testclient import TestClient

from openkerf_api.bridges import path_length
from openkerf_api.server import ApiServer
from openkerf_api.stencil import _cumulative, contours, islands, plan_stencil

#: An outline typeface that is on every machine this is developed on. If it is missing the
#: tests skip rather than fail: they are about the analysis, not about somebody's fonts.
ARIAL = "/System/Library/Fonts/Supplemental/Arial.ttf"


@pytest.fixture
def client(kernel, tmp_path):
    server = ApiServer(kernel, library_path=tmp_path / "l.db")
    with TestClient(server.build_app()) as c:
        c.server = server
        yield c


def has_arial() -> bool:
    from pathlib import Path

    return Path(ARIAL).exists()


def lettering(client, kernel, text, font=ARIAL, size=40):
    """One text on the bed, and its geometry."""
    client.post("/api/project/new", json={})
    answer = client.post(
        "/api/design/elements",
        json={"type": "text", "x_mm": 20, "y_mm": 60, "text": text,
              "font_size_mm": size, "font": font},
    )
    assert answer.status_code == 201, answer.text
    node = [n for n in kernel.elements.elems()][0]
    return node, node.as_geometry()


# ------------------------------------------------------------------ the islands


@pytest.mark.skipif(not has_arial(), reason="no outline typeface on this machine")
@pytest.mark.parametrize(
    "text, contour_count, island_count",
    [
        # Measured through this app's own text route, Arial at 40 mm. The counts are what a
        # reader can check by eye: one counter in an O, one in an A, one in the 'e' of
        # Stencil, and in OpenKerf the O, the p and *both* e's.
        ("O", 2, 1),
        ("A", 2, 1),
        ("Stencil", 9, 1),
        ("OpenKerf", 12, 4),
        ("Bo88ie", 15, 8),
    ],
)
def test_the_islands_are_the_parts_that_would_fall_out(
    client, kernel, text, contour_count, island_count
):
    _node, geometry = lettering(client, kernel, text)
    found = contours(geometry)
    assert len(found) == contour_count, [c["depth"] for c in found]
    assert len(islands(found)) == island_count


@pytest.mark.skipif(not has_arial(), reason="no outline typeface on this machine")
def test_the_probe_point_may_not_be_the_middle_of_the_contour(client, kernel):
    """
    The trap the first version fell into, kept as a test because it looks right when wrong.

    The centroid of the outer ring of an **O** lies inside the counter, so probing with it
    puts *both* contours at depth 1 and an O reads as two islands — a stencil that bridges
    the letter to the sheet and sprays a blank. Probing with a vertex gives [0, 1].
    """
    _node, geometry = lettering(client, kernel, "O")
    found = contours(geometry)
    assert sorted(c["depth"] for c in found) == [0, 1]

    from openkerf_api.tiling import _inside_outline

    outer = next(c for c in found if c["depth"] == 0)
    middle = complex(
        sum(p.real for p in outer["points"]) / len(outer["points"]),
        sum(p.imag for p in outer["points"]) / len(outer["points"]),
    )
    inner = next(c for c in found if c["depth"] == 1)
    assert _inside_outline(middle, [inner["points"]]), (
        "if the centroid of the O's outer ring is no longer inside the counter this test "
        "has stopped measuring the trap it was written for"
    )


# ------------------------------------------------------------------ the bridges


@pytest.mark.skipif(not has_arial(), reason="no outline typeface on this machine")
def test_every_gap_has_its_partner_across_the_opening(client, kernel):
    """
    A bridge is a *pair* of gaps facing each other, or it is not a bridge.

    Measured on Arial 'O' at 40 mm: the shortest crossing is 3.24 mm — the stroke width of
    the letter — and each of the four gaps has another gap 3.24 to 3.26 mm away. If a gap's
    nearest neighbour drifts far beyond the crossing, the strip between them is no longer
    material and the counter drops out with the picture still looking right.
    """
    from meerk40t.core.units import UNITS_PER_MM

    _node, geometry = lettering(client, kernel, "O")
    plan = plan_stencil(geometry, 3.0, 2, UNITS_PER_MM)
    assert plan["islands"] == 1
    assert plan["bridges"] == 2
    assert len(plan["positions"]) == 4, "two gaps per bridge, or it holds nothing"

    total = path_length(geometry)
    before, rulers, _ = _cumulative(geometry)

    def point_at(percent):
        want = percent / 100.0 * total
        last = max(before)
        for index in sorted(before):
            if before[index] + rulers[index].length >= want or index == last:
                return geometry.position(index, rulers[index].t_at(want - before[index]))
        return None

    points = [point_at(p) for p in plan["positions"]]
    for i, here in enumerate(points):
        nearest = min(abs(here - there) for j, there in enumerate(points) if j != i)
        span = nearest / UNITS_PER_MM
        assert span <= plan["shortest_mm"] * 1.5, (
            f"gap {i} has no partner across the opening: its nearest neighbour is "
            f"{span:.2f} mm away and the crossing is {plan['shortest_mm']} mm"
        )


@pytest.mark.skipif(not has_arial(), reason="no outline typeface on this machine")
def test_two_bridges_on_one_island_are_not_neighbours(client, kernel):
    """
    An island on two bridges a millimetre apart hangs on one bridge.

    Both shortest crossings of a ring are at its thinnest place, so without a spread the
    two land side by side. Measured on Arial 'O': with the spread the two island-side gaps
    are on opposite parts of the counter.
    """
    from meerk40t.core.units import UNITS_PER_MM

    _node, geometry = lettering(client, kernel, "O")
    plan = plan_stencil(geometry, 3.0, 2, UNITS_PER_MM)
    spread = max(plan["positions"]) - min(plan["positions"])
    assert spread > 20, f"all four gaps sit within {spread:.1f}% of the path"


# ------------------------------------------------------------------ the refusals


@pytest.mark.skipif(not has_arial(), reason="no outline typeface on this machine")
def test_a_single_stroke_typeface_is_refused_in_its_own_words(client, kernel):
    """
    Measured: 'Stencil' in the engine's own Hershey font is ten contours of which nine are
    open lines; in Arial it is nine closed ones. A single stroke has no inside, so nothing
    can fall out of it — and that is a different problem from a shape without holes, which
    is why it gets its own sentence.
    """
    node, geometry = lettering(client, kernel, "Stencil", font="meerk40t.jhf")
    from meerk40t.core.units import UNITS_PER_MM

    plan = plan_stencil(geometry, 3.0, 2, UNITS_PER_MM)
    assert plan["islands"] == 0
    assert plan["open_contours"] >= 8

    answer = client.post("/api/design/stencil", json={"ids": [node.id]})
    assert answer.status_code == 409, answer.text
    assert answer.headers["X-OpenKerf-Error"] == "stencil.singleStroke"
    assert "outline typeface" in answer.json()["detail"]


def test_a_shape_with_no_holes_says_so_differently(client, kernel):
    """A rectangle needs no bridges: it *is* the opening, and nothing sits inside it."""
    made = client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 20, "y_mm": 20, "width_mm": 60, "height_mm": 40},
    ).json()
    answer = client.post("/api/design/stencil", json={"ids": made["ids"]})
    assert answer.status_code == 409, answer.text
    assert answer.headers["X-OpenKerf-Error"] == "stencil.noIslands"


def test_a_bridge_thinner_than_the_cut_is_refused(client, kernel):
    made = client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 20, "y_mm": 20, "width_mm": 60, "height_mm": 40},
    ).json()
    answer = client.post(
        "/api/design/stencil", json={"ids": made["ids"], "bridge_mm": 0.2}
    )
    assert answer.status_code == 409
    assert answer.headers["X-OpenKerf-Error"] == "stencil.bridgeTooThin"


# ------------------------------------------------------------------ end to end


@pytest.mark.skipif(not has_arial(), reason="no outline typeface on this machine")
def test_the_stencil_lands_on_the_shape_and_the_preview_does_not(client, kernel):
    """
    The preview measures and writes nothing; the real thing writes the same two attributes
    an ordinary bridge writes, so the cut plan, the burn time and the RD stream need
    nothing new.
    """
    node, _geometry = lettering(client, kernel, "OpenKerf")

    look = client.post(
        "/api/design/stencil", json={"ids": [node.id], "preview": True}
    )
    assert look.status_code == 200, look.text
    assert look.json()["islands"] == 4
    assert look.json()["bridges"] == 8
    assert getattr(node, "mktabpositions", None) in (None, "", "*0")

    done = client.post("/api/design/stencil", json={"ids": [node.id], "bridge_mm": 2.5})
    assert done.status_code == 200, done.text
    assert done.json() == {**look.json(), "bridge_mm": 2.5}

    from meerk40t.core.units import UNITS_PER_MM

    assert node.mktabpositions.count(",") == 15, "sixteen gaps for eight bridges"
    assert abs(node.mktablength / UNITS_PER_MM - 2.5) < 1e-6

    # And the engine really takes it out of the contour: `final_geometry` is what the cut
    # plan uses for a cut layer.
    plain = path_length(node.as_geometry())
    gapped = path_length(node.final_geometry())
    assert gapped < plain, "the gaps are not in the geometry the machine gets"
    taken = (plain - gapped) / UNITS_PER_MM
    assert 30 < taken < 50, f"sixteen gaps of 2.5 mm should take about 40 mm, took {taken:.1f}"
