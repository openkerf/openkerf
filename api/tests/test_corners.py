"""
Rounding or bevelling corners.

Pure arithmetic on geometry, so no kernel and no HTTP. What is tested here is not
"does it run through" but "does the shape you meant come out" — and above all:
what happens at the corners where it cannot be done. Quietly cutting a corner
wrong is the mistake you only see on material.
"""

import math

import pytest
from meerk40t.core.geomstr import TYPE_ARC, TYPE_LINE, Geomstr

from openkerf_api.corners import CornerError, corner_geometry


def square(side=100.0):
    """A closed square of four separate line segments."""
    geom = Geomstr()
    corners = [
        complex(0, 0),
        complex(side, 0),
        complex(side, side),
        complex(0, side),
    ]
    for a, b in zip(corners, corners[1:] + corners[:1]):
        geom.line(a, b)
    return geom


def kinds(geom):
    return [int(geom.segments[i][2].real) for i in range(geom.index)]


def length(geom):
    return sum(abs(geom.length(i)) for i in range(geom.index))


def test_chamfering_a_square_cuts_all_four_corners():
    """
    Four corners off means four sides plus four bevels.

    The bevel of a right angle where you set back 10 mm on both sides is 10·√2
    long. That can be worked out by hand, and that is why it is here instead of
    "something comes out".
    """
    out, changed, skipped = corner_geometry(square(), 10.0, "chamfer")

    assert (changed, skipped) == (4, 0)
    assert len(kinds(out)) == 8
    assert set(kinds(out)) == {TYPE_LINE}
    bevel = 10.0 * math.sqrt(2)
    assert length(out) == pytest.approx(4 * 80.0 + 4 * bevel, rel=1e-6)


def test_rounding_a_square_gives_real_arcs():
    """
    Rounding gives arcs, not little polygons.

    At a right angle the setback equals the radius, so this is the same shape the
    engine draws for a rectangle with `rx` — which makes a rounded rectangle and a
    rounded polygon look the same.
    """
    out, changed, skipped = corner_geometry(square(), 10.0, "round")

    assert (changed, skipped) == (4, 0)
    assert kinds(out).count(TYPE_ARC) == 4
    quarter = 2 * math.pi * 10.0 / 4
    assert length(out) == pytest.approx(4 * 80.0 + 4 * quarter, rel=1e-3)


def test_a_size_too_large_for_every_corner_is_a_refusal():
    """
    Two bevels that would overlap each other give a shape nobody meant. The bound
    is half the shortest side: on a square of 10 mm the size may go up to 5 mm,
    and 8 mm may not.

    If it fits at no corner at all, that is a refusal and not "done, 4 skipped".
    Handing back the same geometry would mean the layer replaces the design with
    something identical and the user gets a message about work that was not done —
    refusing is more honest, and it says what to do about it.
    """
    with pytest.raises(CornerError) as error:
        corner_geometry(square(10.0), 8.0, "chamfer")

    assert "smaller size" in str(error.value)


def test_the_bound_is_half_the_shortest_edge():
    """Exactly half is still allowed: then two corners join seamlessly."""
    out, changed, skipped = corner_geometry(square(10.0), 5.0, "chamfer")

    assert (changed, skipped) == (4, 0)
    # Every straight piece is cut away; what is left are four bevels.
    assert length(out) == pytest.approx(4 * 5.0 * math.sqrt(2), rel=1e-6)


def test_a_corner_against_a_curve_is_skipped():
    """
    Setting back along an arc is a different problem from setting back along a
    line. We leave such corners alone instead of making something up.
    """
    geom = Geomstr()
    geom.line(complex(0, 0), complex(100, 0))
    geom.line(complex(100, 0), complex(100, 100))
    geom.arc(complex(100, 100), complex(50, 150), complex(0, 100))
    geom.line(complex(0, 100), complex(0, 0))

    out, changed, skipped = corner_geometry(geom, 10.0, "chamfer")

    # Only the two corners between two lines take part: (100,0) and (0,0).
    assert changed == 2
    assert skipped == 2
    assert TYPE_ARC in kinds(out)


def test_an_open_polyline_has_no_corner_at_its_loose_ends():
    """A loose end is not a corner: only one side arrives there."""
    geom = Geomstr()
    geom.line(complex(0, 0), complex(100, 0))
    geom.line(complex(100, 0), complex(100, 100))

    out, changed, skipped = corner_geometry(geom, 10.0, "chamfer")

    assert (changed, skipped) == (1, 0)
    assert len(kinds(out)) == 3


def test_nothing_to_do_is_a_refusal_with_a_sentence():
    """
    A selection without a single usable corner has to say so. Doing nothing
    quietly leaves the user thinking the button is broken.
    """
    geom = Geomstr()
    geom.line(complex(0, 0), complex(100, 0))

    with pytest.raises(CornerError) as error:
        corner_geometry(geom, 10.0, "chamfer")

    assert "corner" in str(error.value).lower()


def test_the_original_geometry_is_left_alone():
    original = square()
    before = original.index

    corner_geometry(original, 10.0, "chamfer")

    assert original.index == before


def test_an_unknown_style_is_refused():
    with pytest.raises(CornerError):
        corner_geometry(square(), 10.0, "obliquely")


def test_a_sharp_corner_gets_the_right_arc():
    """
    Every other test here uses right angles, and at 90° the setback coincides
    with the radius — then the trigonometry checks out even when you have it
    wrong. An equilateral triangle has corners of 60°, and there the two come
    apart: radius = size · tan(30°), and the arc turns 120°.
    """
    side = 100.0
    height = side * math.sqrt(3) / 2
    points = [complex(0, 0), complex(side, 0), complex(side / 2, height)]
    geom = Geomstr()
    for a, b in zip(points, points[1:] + points[:1]):
        geom.line(a, b)

    size = 10.0
    out, changed, skipped = corner_geometry(geom, size, "round")

    assert (changed, skipped) == (3, 0)
    radius = size * math.tan(math.radians(30))
    arc = radius * math.radians(120)
    straight = 3 * (side - 2 * size)
    assert length(out) == pytest.approx(straight + 3 * arc, rel=2e-3)


def test_a_sharp_corner_chamfers_to_the_right_width():
    """
    At 60° the bevel is shorter than at 90°: by the cosine rule it is
    size·√(2−2·cos60°) = size. That can be worked out by hand and pins down that
    the setback is measured along the *side* and not somewhere else.
    """
    side = 100.0
    height = side * math.sqrt(3) / 2
    points = [complex(0, 0), complex(side, 0), complex(side / 2, height)]
    geom = Geomstr()
    for a, b in zip(points, points[1:] + points[:1]):
        geom.line(a, b)

    size = 10.0
    out, _changed, _skipped = corner_geometry(geom, size, "chamfer")

    bevel = size * math.sqrt(2 - 2 * math.cos(math.radians(60)))
    assert length(out) == pytest.approx(3 * (side - 2 * size) + 3 * bevel, rel=1e-6)
