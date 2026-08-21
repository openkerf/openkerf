"""
Tiles: burning a board that is bigger than the bed.

This file is deliberately kernel-free. Everything here is arithmetic on numbers in
millimetres — the division, where the seam falls, where the marks fit, and what two tapped
points say about the board's pose. That is exactly the part you pay for on material when it
is wrong, and therefore the part that has to be fully testable without a machine.

The conversion to engine units (Tats) happens in `tilerun.py`, on the boundary.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import NamedTuple


class TilingError(Exception):
    """What the user has to know before any material goes in."""


class Rect(NamedTuple):
    """Een rechthoek in plaatcoördinaten, in millimeters."""

    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0


@dataclass(frozen=True)
class TilingSettings:
    margin_mm: float = 10.0
    overlap_mm: float = 25.0
    marker_size_mm: float = 8.0


class Tile(NamedTuple):
    """
    One tile: what it burns, and what the head can reach when the board lies like this.

    A NamedTuple and not a dataclass, because the seam shift later uses
    `tile._replace(burn=...)` — that is a NamedTuple method.
    """

    index: int
    row: int
    column: int
    #: wat deze tile brandt
    burn: Rect
    #: what the head can reach when the board is in this position
    window: Rect


def _axis(
    plate: float, bed: float, settings: TilingSettings
) -> list[tuple[float, float]]:
    """
    De vensters op één as: paren (begin, eind) in plaatcoördinaten.

    The number follows from the requirement that consecutive windows share at least
    `overlap_mm`. After that they are **divided equally** instead of full-full-remainder, so
    that the overlap becomes more generous than the minimum and no last strip is ever left
    over that no mark fits in.
    """
    if bed >= plate:
        # The board fits. The margin is there to keep marks off the bed edge, and with one
        # window there is no seam and therefore no mark — measuring with `bed - 2·margin`
        # declared a sheet of exactly the bed size 'too big', which on Jelle's 5030 is the
        # default size.
        return [(0.0, plate)]

    usable = bed - 2 * settings.margin_mm
    if usable <= 0:
        raise TilingError(
            "The bed is smaller than twice the margin, so nothing is left "
            "to burn in. Set the margin lower."
        )
    if usable <= settings.overlap_mm:
        raise TilingError(
            f"The usable bed is {usable:.0f} mm and the overlap {settings.overlap_mm:.0f} mm. "
            "Two tiles would then overlap completely. Set the overlap "
            "lower or the margin smaller."
        )
    count = math.ceil((plate - settings.overlap_mm) / (usable - settings.overlap_mm))
    step = (plate - usable) / (count - 1)
    return [(i * step, i * step + usable) for i in range(count)]


def tile_layout(
    plate_w_mm: float,
    plate_h_mm: float,
    bed_w_mm: float,
    bed_h_mm: float,
    settings: TilingSettings,
) -> list[Tile]:
    """
    The division of this board on this machine.

    Never stored: it is a function of the measures and the settings, so it holds by itself as
    soon as something changes.
    """
    columns = _axis(plate_w_mm, bed_w_mm, settings)
    rows = _axis(plate_h_mm, bed_h_mm, settings)

    if len(columns) > 1 and len(rows) > 1:
        # Dividing in two directions is a design of its own: every seam gets its own marks,
        # the order of the tiles starts to matter and the aligning becomes a chain instead of
        # a step. Delivering it half working is worse here than refusing — measured: `_marks`
        # then puts the row boundary's and the column boundary's marks on the same point, so
        # that one circle is burned twice.
        raise TilingError(
            "This plate is larger than the bed in both directions. Dividing in two "
            "directions is not possible yet: every seam would then have its own marks "
            "and its own order. Cut the plate to bed height first, or take "
            "a narrower plate."
        )

    x_splits = _splits([c[0] for c in columns], [c[1] for c in columns], plate_w_mm)
    y_splits = _splits([r[0] for r in rows], [r[1] for r in rows], plate_h_mm)

    tiles: list[Tile] = []
    for row, (wy0, wy1) in enumerate(rows):
        for column, (wx0, wx1) in enumerate(columns):
            tiles.append(
                Tile(
                    index=len(tiles),
                    row=row,
                    column=column,
                    burn=Rect(
                        x_splits[column],
                        y_splits[row],
                        x_splits[column + 1],
                        y_splits[row + 1],
                    ),
                    window=Rect(wx0, wy0, wx1, wy1),
                )
            )
    return tiles


def _splits(starts: list[float], ends: list[float], plate: float) -> list[float]:
    """
    The boundaries of the burn areas: 0, the seams, and the board size.

    The seam falls in the middle of the overlap zone. Task 2 may then move it within that
    zone to where it crosses the fewest shapes.
    """
    bounds = [0.0]
    for left, right in zip(range(len(starts) - 1), range(1, len(starts))):
        bounds.append((starts[right] + ends[left]) / 2)
    bounds.append(plate)
    return bounds


def best_split(low_mm: float, high_mm: float, spans) -> float:
    """
    Where the seam between two tiles falls best.

    `spans` are the extents of the shapes along the division axis. A shape counts as cut as
    soon as the seam falls strictly inside it. Candidates are the edges of the overlap zone,
    the middle, and just beside every shape boundary that lies in the zone — more positions
    than that do not make the answer better.

    A tie goes to the position closest to the middle: that keeps the tiles as equal in size
    as possible.
    """
    middle = (low_mm + high_mm) / 2
    if not spans:
        return middle

    nudge = 0.01
    candidates = {low_mm, high_mm, middle}
    for a, b in spans:
        for edge in (a - nudge, b + nudge):
            if low_mm <= edge <= high_mm:
                candidates.add(edge)

    def crossings(x: float) -> int:
        return sum(1 for a, b in spans if a < x < b)

    return min(sorted(candidates), key=lambda x: (crossings(x), abs(x - middle)))


class Point(NamedTuple):
    x_mm: float
    y_mm: float


def _overlaps(a: Rect, b: Rect) -> bool:
    return not (a.x1 <= b.x0 or b.x1 <= a.x0 or a.y1 <= b.y0 or b.y1 <= a.y0)


#: The width of the burned digit beside a mark, as a fraction of the marker size. A digit
#: does not have to be large: it stands beside a circle you have already found, and only has
#: to tell 1 from 2.
DIGIT_FRACTION = 0.7

#: The space between the circle and its digit.
DIGIT_GAP_MM = 1.5


def mark_footprint(point: Point, size_mm: float, zone: Rect) -> Rect:
    """
    What a mark takes up: the circle *and* its digit.

    The digit sits along the **long axis** of the overlap zone, not across it. That is not
    taste: the width of the overlap is the tight measure — when setting it up it is already
    required that a mark fits in it (`Sheets._tiling`) — and if the digit went that way,
    existing settings would suddenly become too narrow. Lengthwise there is room to spare:
    measured, those zones are 150 to 200 mm long against 50 to 72 mm wide.
    """
    half = size_mm / 2
    extra = size_mm * DIGIT_FRACTION + DIGIT_GAP_MM
    if zone.height >= zone.width:
        return Rect(
            point.x_mm - half,
            point.y_mm - half,
            point.x_mm + half,
            point.y_mm + half + extra,
        )
    return Rect(
        point.x_mm - half, point.y_mm - half, point.x_mm + half + extra, point.y_mm + half
    )


def marker_spots(
    zone: Rect, blocked: list[Rect], size_mm: float, clearance_mm: float = 2.0
) -> tuple[Point, Point]:
    """
    Two free places in the overlap zone, as far apart as possible.

    The zone is divided into cells the size of a mark plus clearance; a cell drops out as
    soon as it touches a shape's bounding box. Of what is left we take the two outermost
    along the zone's long axis — further apart means a more accurate angle, and the outermost
    are deterministic where 'the furthest pair' is not on a tie.
    """
    half = size_mm / 2 + clearance_mm / 2
    extra = size_mm * DIGIT_FRACTION + DIGIT_GAP_MM
    along_y = zone.height >= zone.width
    # The step is larger lengthwise, because that is where the digit is.
    step_x = size_mm + clearance_mm + (0.0 if along_y else extra)
    step_y = size_mm + clearance_mm + (extra if along_y else 0.0)

    vrij: list[Point] = []
    y = zone.y0 + half
    while y <= zone.y1 - half + 1e-9:
        x = zone.x0 + half
        while x <= zone.x1 - half + 1e-9:
            point = Point(x, y)
            vak = mark_footprint(point, size_mm, zone)
            binnen = (
                zone.x0 <= vak.x0
                and vak.x1 <= zone.x1
                and zone.y0 <= vak.y0
                and vak.y1 <= zone.y1
            )
            if binnen and not any(_overlaps(vak, b) for b in blocked):
                vrij.append(point)
            x += step_x
        y += step_y

    if len(vrij) < 2:
        raise TilingError(
            "There is no room in the overlap strip for two alignment marks that lie "
            "clear of the work. Make the overlap larger, or move a shape "
            "away from the seam."
        )

    along_y = zone.height >= zone.width
    sleutel = (lambda p: p.y_mm) if along_y else (lambda p: p.x_mm)
    geordend = sorted(vrij, key=sleutel)
    return geordend[0], geordend[-1]


@dataclass(frozen=True)
class Alignment:
    """How the plate lies now, relative to how it was drawn."""

    angle_deg: float
    dx_mm: float
    dy_mm: float
    #: how far the measured distance deviates from the burned one — a check, not a correction
    distance_error_mm: float


def alignment(
    p1: Point,
    p2: Point,
    m1: Point,
    m2: Point,
    max_angle_deg: float = 3.0,
    tolerance_mm: float = 1.0,
) -> Alignment:
    """
    The board's pose, from two burned marks and two tapped points.

    Scale is **not** adopted and *is* checked. The distance between two burned marks does not
    change; if the measured distance deviates, something was tapped wrong. If you did adopt
    the scale, one 2 mm tapping error would compute the whole tile apart.
    """
    board = complex(p2.x_mm - p1.x_mm, p2.y_mm - p1.y_mm)
    measured = complex(m2.x_mm - m1.x_mm, m2.y_mm - m1.y_mm)
    if abs(board) < 1e-6 or abs(measured) < 1e-6:
        raise TilingError("The two tapped points lie on top of each other.")

    afwijking = abs(measured) - abs(board)
    if abs(afwijking) > tolerance_mm:
        raise TilingError(
            f"These two points lie {abs(afwijking):.1f} mm "
            f"{'further' if afwijking > 0 else 'closer'} "
            "apart than the marks I burned. Did you tap the right mark?"
        )

    angle = math.atan2(measured.imag, measured.real) - math.atan2(board.imag, board.real)
    angle = math.atan2(math.sin(angle), math.cos(angle))
    graden = math.degrees(angle)
    if abs(graden) > max_angle_deg:
        raise TilingError(
            f"The plate would lie {abs(graden):.1f}° askew. That is more than a "
            "plate *can* lie askew without you seeing it — the wrong mark was "
            "probably tapped. Lay it straight and tap again."
        )

    gedraaid = complex(p1.x_mm, p1.y_mm) * complex(math.cos(angle), math.sin(angle))
    return Alignment(
        angle_deg=graden,
        dx_mm=m1.x_mm - gedraaid.real,
        dy_mm=m1.y_mm - gedraaid.imag,
        distance_error_mm=afwijking,
    )


def alignment_from_corner(plate_corner: Point, measured: Point) -> Alignment:
    """
    Tile 1: there are no marks yet, so aligning happens on the board itself.

    Without a second point there is no angle to measure, and then we compute with zero — and
    say so, because an assumption you cannot see is an assumption you pay for on material.
    """
    return Alignment(
        angle_deg=0.0,
        dx_mm=measured.x_mm - plate_corner.x_mm,
        dy_mm=measured.y_mm - plate_corner.y_mm,
        distance_error_mm=0.0,
    )


#: The segment types that carry real geometry. The rest (end, nop, point) has no length and
#: does not belong in a clipped result.
def _carrying_types():
    from meerk40t.core.geomstr import TYPE_ARC, TYPE_CUBIC, TYPE_LINE, TYPE_QUAD

    return (TYPE_LINE, TYPE_QUAD, TYPE_CUBIC, TYPE_ARC)


def _rand_segmenten(rect_units: Rect):
    """The four edges of the clip window, each as a separate line segment."""
    from meerk40t.core.geomstr import Geomstr

    corners = (
        (complex(rect_units.x0, rect_units.y0), complex(rect_units.x1, rect_units.y0)),
        (complex(rect_units.x1, rect_units.y0), complex(rect_units.x1, rect_units.y1)),
        (complex(rect_units.x1, rect_units.y1), complex(rect_units.x0, rect_units.y1)),
        (complex(rect_units.x0, rect_units.y1), complex(rect_units.x0, rect_units.y0)),
    )
    edges = Geomstr()
    for begin, eind in corners:
        edges.line(begin, eind)
        edges.end()
    return edges


def _stukken(geom, index: int, ts):
    """
    The pieces of one segment, split at the given parameters.

    Lines, quads and cubics we let the engine split itself; those branches exist and work.
    **Arcs not:** `Geomstr.split` has no branch for `TYPE_ARC` and returns zero pieces for
    one, which makes an arc that crosses the seam in the middle disappear from both tiles.
    Measured on a circle with the seam beside the weld lines: half a circle without a trace.

    Splitting it ourselves can be exact, because an arc through three points of a circle *is*
    that circle: every piece is built up from its start, its middle and its end, all three
    asked for with `position`.
    """
    from meerk40t.core.geomstr import Geomstr, TYPE_ARC

    if not ts:
        return [geom.segments[index]]
    if int(geom.segments[index][2].real) != TYPE_ARC:
        return list(geom.split(index, sorted(ts)))

    grenzen = [0.0] + sorted(ts) + [1.0]
    hulp = Geomstr()
    for begin, eind in zip(grenzen, grenzen[1:]):
        if eind - begin < 1e-12:
            continue
        hulp.arc(
            geom.position(index, begin),
            geom.position(index, (begin + eind) / 2),
            geom.position(index, eind),
        )
    return [hulp.segments[i] for i in range(hulp.index)]


def clip_geometry(geom, rect_units: Rect):
    """
    The geometry that falls within this burn area, as a new Geomstr.

    Every segment is split at its intersections with the four window edges, and of the pieces
    we keep what has its middle inside. Splitting happens on the parameter, so **an arc stays
    an arc** — nothing is interpolated, and that is visible on the workpiece.

    `rect_units` is in engine units, not in millimetres: the clipping happens in the same
    space as the geometry. The original is not touched.

    **The lower edge counts, the upper edge does not.** A line lying exactly on a seam is cut
    by neither tile — it crosses nothing — so without that difference its middle would fall
    in both rectangles and the laser would go over it twice. With `x0 <= middle < x1` it
    always falls in the next tile, and never in neither. The outermost edge of the board is
    therefore the only place where something falls through; that is why `TileRun.burn`
    stretches the last tile's burn area by a hair.

    **Why not `geomstr.Clip`, which appears to do this?** Because it breaks on arcs:
    `Clip.inside` asks for its middles in one go and lands in the infinite recursion of
    `Geomstr._arc_position` (`geomstr.py:5784`, `line` instead of `_line`), and `Clip.polycut`
    drops an arc segment that does not even cross the boundary. Upstream does not notice
    because their own `Clip` test only clips lines. We change nothing in `meerk40t/`; this is
    the way around it, and for our case the simpler one too.
    """
    from meerk40t.core.geomstr import Geomstr

    edges = _rand_segmenten(rect_units)
    dragend = _carrying_types()

    # Collect all the pieces first, only then filter: a piece's middle can only be asked of
    # a Geomstr that already contains the piece.
    pieces = Geomstr()
    for index in range(geom.index):
        if int(geom.segments[index][2].real) not in dragend:
            continue
        snijpunten = set()
        for edge in range(edges.index):
            if int(edges.segments[edge][2].real) not in dragend:
                continue
            for t, _ander in geom.intersections(index, edges.segments[edge]):
                # The end points themselves are not a split: the segment already stops
                # there, and splitting at 0 or 1 produces an empty piece.
                if 1e-9 < float(t) < 1 - 1e-9:
                    snijpunten.add(round(float(t), 9))
        for stuk in _stukken(geom, index, sorted(snijpunten)):
            pieces.append_segment(*stuk)

    binnen = Geomstr()
    for index in range(pieces.index):
        middle = pieces.position(index, 0.5)
        if (
            rect_units.x0 <= middle.real < rect_units.x1
            and rect_units.y0 <= middle.imag < rect_units.y1
        ):
            binnen.append_segment(*pieces.segments[index])
    return binnen
