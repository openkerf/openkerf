"""
Het pure rekenwerk achter de tiles: opdelen, scheidslijn, marks, uitlijnen.

No kernel, no files, no HTTP. This is the part where the mistakes are that you pay for on
material, so it is the part that is fully tested.
"""

import math

import pytest
from meerk40t.core.geomstr import Geomstr

from openkerf_api.tiling import (
    Alignment,
    Point,
    Rect,
    TilingError,
    TilingSettings,
    alignment,
    alignment_from_corner,
    best_split,
    clip_geometry,
    marker_spots,
    tile_layout,
)


def settings(**kw):
    base = {"margin_mm": 10.0, "overlap_mm": 25.0, "marker_size_mm": 8.0}
    base.update(kw)
    return TilingSettings(**base)


def test_a_plate_that_fits_is_one_tile():
    """If it fits there is nothing to divide — and then there is no seam either."""
    tiles = tile_layout(300.0, 200.0, 500.0, 300.0, settings())

    assert len(tiles) == 1
    assert tiles[0].burn == Rect(0.0, 0.0, 300.0, 200.0)


def test_a_wide_plate_splits_only_on_the_wide_axis():
    """
    900 mm on a bed of 500: divide in the width, not in the height.

    Two tiles, not three. The usable window is 480 mm, so two windows cover 900 mm with 60 mm
    of overlap — well above the 25 that was asked for. A third tile would mean shifting and
    aligning one more time, and every alignment is a chance to get it wrong.
    """
    tiles = tile_layout(900.0, 250.0, 500.0, 300.0, settings())

    assert len(tiles) == 2
    assert {t.row for t in tiles} == {0}
    assert [t.column for t in tiles] == [0, 1]
    for tile in tiles:
        assert tile.burn.y0 == 0.0 and tile.burn.y1 == 250.0


def test_the_tile_count_is_the_fewest_that_still_overlap_enough():
    """
    Het aantal volgt out één eis: second opeenvolgende vensters delen minstens
    `overlap_mm`. From that follows n ≥ (board − overlap) / (window − overlap), and that is
    exactly what should be computed — not one more.
    """
    assert len(tile_layout(900.0, 200.0, 500.0, 300.0, settings())) == 2
    assert len(tile_layout(1000.0, 200.0, 500.0, 300.0, settings())) == 3
    assert len(tile_layout(1400.0, 200.0, 500.0, 300.0, settings())) == 4


def test_the_burn_regions_tile_the_plate_exactly():
    """Aan elkaar, zonder gat en zonder overlap: anders brandt iets dubbel."""
    tiles = tile_layout(900.0, 250.0, 500.0, 300.0, settings())

    assert tiles[0].burn.x0 == 0.0
    assert tiles[-1].burn.x1 == pytest.approx(900.0)
    for left, right in zip(tiles, tiles[1:]):
        assert left.burn.x1 == pytest.approx(right.burn.x0)


def test_every_tile_fits_the_usable_window():
    """The window is the bed minus twice the margin; the head cannot reach further."""
    tiles = tile_layout(900.0, 250.0, 500.0, 300.0, settings())

    for tile in tiles:
        assert tile.window.x1 - tile.window.x0 <= 480.0 + 1e-9


def test_the_windows_are_spread_evenly_instead_of_leaving_a_sliver():
    """
    'Full, full, full, remainder' gives a last tile no mark fits in.

    What is divided equally are the **windows**: the board shifts the same distance every
    time. So the burn areas are not equally wide, and they should not be — a middle tile gives
    up half an overlap on both sides and so burns less than the outer ones. What matters is
    that no strip is left over.
    """
    tiles = tile_layout(1000.0, 200.0, 500.0, 300.0, settings())

    stappen = [b.window.x0 - a.window.x0 for a, b in zip(tiles, tiles[1:])]
    assert max(stappen) - min(stappen) < 1e-6


def test_no_tile_burns_less_than_the_strip_it_shares():
    """
    A tile that burns less than the overlap it gives away is not a tile but a strip: then it
    costs a shift and an alignment for almost nothing. Computed over board sizes from 490 to
    3000 mm the narrowest burn area is 227.6 mm, well above the overlap.
    """
    for plate in (490.0, 700.0, 935.1, 1000.0, 1500.0, 2400.0):
        tiles = tile_layout(plate, 200.0, 500.0, 300.0, settings())
        for tile in tiles:
            assert tile.burn.width >= settings().overlap_mm


def test_a_plate_too_big_in_both_directions_is_refused():
    """
    This design cannot divide in two directions: every seam has its own marks, the order of
    the tiles starts to matter and the aligning becomes a chain. Delivering it half working is
    worse here than not delivering — then there is a grid with marks lying on top of each
    other.
    """
    with pytest.raises(TilingError) as fout:
        tile_layout(900.0, 600.0, 500.0, 300.0, settings())

    assert "both directions" in str(fout.value)


def test_a_plate_that_exactly_fits_the_bed_needs_no_tiles():
    """
    A board that fits on the bed does not have to be divided — not even when it is exactly
    the size of the bed.

    Measured fault: the axis computed with `bed − 2·margin`, so a sheet of 500×300 on a bed of
    500×300 counted as 'too big in both directions' and was refused. That is exactly the
    default size of Jelle's 5030, and it produced a 409 on every page load. The margin is
    there for the marks on a seam; with one tile there is no seam and therefore no mark, and
    then the board may use the whole bed.
    """
    assert len(tile_layout(500.0, 300.0, 500.0, 300.0, settings())) == 1
    assert len(tile_layout(499.0, 299.0, 500.0, 300.0, settings())) == 1

    # One millimetre too tall *is* dividing, and then only in the height.
    tiles = tile_layout(500.0, 301.0, 500.0, 300.0, settings())
    assert len(tiles) > 1
    assert {t.column for t in tiles} == {0}


def test_a_bed_smaller_than_the_overlap_is_refused_with_a_sentence():
    with pytest.raises(TilingError) as fout:
        tile_layout(900.0, 200.0, 40.0, 300.0, settings(overlap_mm=25.0))

    assert "overlap" in str(fout.value).lower()


def test_the_seam_falls_in_empty_space_when_there_is_any():
    """
    A seam through the emptiness you do not see back on the workpiece. Shapes from 100-140
    and 180-220: between 140 and 180 it crosses nothing.
    """
    x = best_split(120.0, 200.0, [(100.0, 140.0), (180.0, 220.0)])

    assert 140.0 <= x <= 180.0


def test_the_seam_takes_the_least_bad_place_when_everything_is_covered():
    """
    Everything covered: then the position that cuts the fewest shapes in half.

    Here the shapes run out beyond the zone, because otherwise the zone's own edge is already
    crossing-free — a shape starting exactly on the seam is not cut through, it is touched.
    That is not a trick in the test but the reason the zone's edges may simply be candidates:
    the whole overlap zone is reachable from both tiles.
    """
    spans = [(-10.0, 110.0), (-10.0, 40.0), (-10.0, 40.0)]

    x = best_split(0.0, 100.0, spans)

    def kruisingen(punt: float) -> int:
        return sum(1 for a, b in spans if a < punt < b)

    assert kruisingen(x) == 1
    assert kruisingen(x) < kruisingen(0.0)


def test_without_shapes_the_seam_falls_in_the_middle():
    assert best_split(100.0, 200.0, []) == pytest.approx(150.0)


def test_two_marks_land_as_far_apart_as_the_zone_allows():
    """The further apart, the more accurate the angle that follows."""
    first, second = marker_spots(Rect(400.0, 0.0, 440.0, 600.0), [], size_mm=8.0)

    assert abs(second.y_mm - first.y_mm) > 500.0


def test_a_mark_never_lands_on_a_shape():
    """Marks belong in the waste; on the workpiece you would see them back."""
    blocker = Rect(400.0, 100.0, 440.0, 500.0)

    first, second = marker_spots(Rect(400.0, 0.0, 440.0, 600.0), [blocker], size_mm=8.0)

    for punt in (first, second):
        assert not (100.0 <= punt.y_mm <= 500.0)


def test_no_room_is_a_refusal_and_not_a_single_mark():
    """
    Silently falling back on one mark costs the skew correction without anybody noticing.
    So: refuse, with what can be done about it.
    """
    vol = Rect(400.0, 0.0, 440.0, 600.0)

    with pytest.raises(TilingError) as fout:
        marker_spots(Rect(400.0, 0.0, 440.0, 600.0), [vol], size_mm=8.0)

    assert "overlap" in str(fout.value).lower()


def test_in_a_wide_zone_the_marks_spread_sideways():
    """
    A board divided in the height gives a wide, low overlap zone. Then the marks have to be
    apart along the long axis — the same rule, a different axis, and otherwise that branch is
    never walked.

    That they do not come out at the same height is not a shortcoming: the aligning computes
    with the line between two points, not with an axis. What counts is the distance, because
    that decides how accurate the angle becomes.
    """
    zone = Rect(0.0, 400.0, 600.0, 440.0)

    first, second = marker_spots(zone, [], size_mm=8.0)

    assert abs(second.x_mm - first.x_mm) > 500.0
    for punt in (first, second):
        assert zone.x0 <= punt.x_mm <= zone.x1
        assert zone.y0 <= punt.y_mm <= zone.y1


def test_a_plate_that_only_moved_gives_a_pure_shift():
    merk1, merk2 = Point(470.0, 40.0), Point(470.0, 560.0)
    gemeten1, gemeten2 = Point(30.0, 45.0), Point(30.0, 565.0)

    out = alignment(merk1, merk2, gemeten1, gemeten2)

    assert out.angle_deg == pytest.approx(0.0, abs=1e-6)
    assert out.dx_mm == pytest.approx(-440.0)
    assert out.dy_mm == pytest.approx(5.0)


def test_a_skewed_plate_gives_the_angle_it_lies_at():
    """Two degrees out: that has to come out as two degrees, not as four."""
    angle = math.radians(2.0)
    merk1, merk2 = Point(0.0, 0.0), Point(0.0, 500.0)
    gemeten1 = Point(0.0, 0.0)
    gemeten2 = Point(-500.0 * math.sin(angle), 500.0 * math.cos(angle))

    out = alignment(merk1, merk2, gemeten1, gemeten2)

    assert out.angle_deg == pytest.approx(2.0, abs=1e-6)


def test_marks_that_moved_apart_are_a_refusal():
    """
    The distance between two burned marks does not change. If it does change, something was
    tapped wrong — and then you have to stop, not compute on.
    """
    with pytest.raises(TilingError) as fout:
        alignment(
            Point(0.0, 0.0), Point(0.0, 500.0), Point(0.0, 0.0), Point(0.0, 504.0)
        )

    assert "apart" in str(fout.value)


def test_an_impossible_angle_is_a_refusal():
    angle = math.radians(12.0)
    with pytest.raises(TilingError) as fout:
        alignment(
            Point(0.0, 0.0),
            Point(0.0, 500.0),
            Point(0.0, 0.0),
            Point(-500.0 * math.sin(angle), 500.0 * math.cos(angle)),
        )

    assert "askew" in str(fout.value).lower()


def test_the_first_tile_aligns_on_the_plate_corner_without_an_angle():
    """Tile 1 has no marks; it aligns on the board, without a skew."""
    out = alignment_from_corner(Point(0.0, 0.0), Point(25.0, 15.0))

    assert out == Alignment(
        angle_deg=0.0, dx_mm=25.0, dy_mm=15.0, distance_error_mm=0.0
    )


def _length(geom) -> float:
    return sum(abs(geom.length(i)) for i in range(geom.index))


def test_a_line_across_the_seam_is_cut_in_two_without_losing_length():
    """Together as long as the original: nothing doubled, nothing lost."""
    line = Geomstr()
    line.line(complex(0, 50), complex(200, 50))

    links = clip_geometry(line, Rect(0, 0, 100, 100))
    rechts = clip_geometry(line, Rect(100, 0, 200, 100))

    assert _length(links) == pytest.approx(100.0, rel=1e-3)
    assert _length(rechts) == pytest.approx(100.0, rel=1e-3)


def test_the_original_geometry_is_left_alone():
    """The user's design must not change because of the clipping."""
    line = Geomstr()
    line.line(complex(0, 50), complex(200, 50))
    voor = line.index

    clip_geometry(line, Rect(0, 0, 100, 100))

    assert line.index == voor


def test_an_arc_cut_off_centre_stays_an_arc():
    """
    The assumption the design rests on: splitting happens on the parameter, nothing is
    interpolated. An arc crossing the seam must not become a polygon — you would see that on
    the workpiece.

    The seam is at 130 and not at 100. A circle from `Geomstr.circle` has its weld lines on
    the axes, so with the seam at 100 no arc is ever cut in half and the test proves nothing.
    """
    from meerk40t.core.geomstr import TYPE_ARC

    cirkel = Geomstr.circle(60, 100, 50)

    geklipt = clip_geometry(cirkel, Rect(-200, -200, 130, 300))

    soorten = {int(geklipt.segments[i][2].real) for i in range(geklipt.index)}
    assert TYPE_ARC in soorten


def test_a_circle_cut_off_centre_keeps_all_of_its_length():
    """
    The regression test on the most expensive of the three engine faults: `Geomstr.split` has
    no branch for arcs and produces zero pieces for one, which makes an arc crossing the seam
    in the middle disappear from *both* tiles. Measured before the repair: 188.49 of 376.97
    left — half a circle without a trace.

    The tolerance is 1·10⁻⁴ and not zero, because the engine estimates an arc's length; the
    difference between one arc and its pieces is 3·10⁻⁵ of that, which on 100 mm comes to
    0.003 mm. No lost geometry, but a sum that does not close to the bit.
    """
    cirkel = Geomstr.circle(60, 100, 50)

    links = clip_geometry(cirkel, Rect(-200, -200, 130, 300))
    rechts = clip_geometry(cirkel, Rect(130, -200, 300, 300))

    assert _length(links) + _length(rechts) == pytest.approx(_length(cirkel), rel=1e-4)


def test_geometry_on_the_seam_lands_in_exactly_one_tile():
    """
    A line lying exactly on the seam belongs to one tile, not to both.

    With both the laser would go over it twice: cut double, visibly burned, sagged through on
    thin material. A burn area's lower edge counts, the upper edge does not — then such a line
    always falls in the next tile, and never in neither.
    """
    op_de_naad = Geomstr()
    op_de_naad.line(complex(100, 0), complex(100, 80))

    links = clip_geometry(op_de_naad, Rect(0, 0, 100, 100))
    rechts = clip_geometry(op_de_naad, Rect(100, 0, 200, 100))

    assert _length(links) + _length(rechts) == pytest.approx(80.0, rel=1e-6)


def test_geometry_entirely_outside_comes_back_empty():
    line = Geomstr()
    line.line(complex(500, 50), complex(600, 50))

    assert clip_geometry(line, Rect(0, 0, 100, 100)).index == 0
