"""
Stencils: which parts of a cut-out shape fall out, and where to bridge them.

A spray stencil is a sheet with the design cut *out* of it. So the material and the opening
swap roles compared with an ordinary cut, and that swap is the whole problem: the inside of
an **O** becomes an island of cardboard floating in the opening, held by nothing. Cut it and
it drops on the bench, or worse, into the machine halfway through the job.

**How an island is recognised.** Count, for each closed contour, how many other contours
contain it. The sheet is material at depth 0, the letter's interior is the opening at
depth 1, and anything inside *that* is material again at depth 2 — so a contour whose depth
is **odd** encloses an island. That is the even-odd rule a fill is drawn with, and it is
the same `_inside_outline` the living hinge clips with. Measured on real font geometry
(Arial, `font_size_mm: 40`, through this app's own text route):

    'O'         2 contours, depths [0, 1]   -> 1 island
    'A'         2 contours                  -> 1 island
    'Stencil'   9 contours                  -> 1 island   (the e)
    'OpenKerf' 12 contours                  -> 4 islands  (O, p, and both e's)
    'Bo88ie'   15 contours                  -> 8 islands  (B and the two eights count twice)

A trap worth naming, because the first version fell into it: the probe point may not be the
contour's centroid. The centroid of the outer ring of an **O** lies inside the counter, so
every contour came back at depth 1 and an O looked like two islands. A vertex of the contour
is the right probe.

**What a bridge is here.** Not a gap in the island's own outline — that would join it to the
opening, which is a void. A bridge is a *pair* of gaps, one in the island contour and one in
the contour around it, at the same place: the strip of material between them is cut by
neither, so it holds the island to the sheet. Its length is the stroke width of the letter,
which is why the crossing is chosen where the two contours are closest.

**Why the existing bridges action cannot do this.** It spreads its positions over the
*concatenated* length of every contour in the shape. Measured on "OO" — four contours, 318
mm of path in total — `*4` gave 12.5/37.5/62.5/87.5 %, which can put all four bridges on one
letter and none on the other. The mechanism is right and the arithmetic is not, so this
module computes explicit percentages and hands them to the same machinery.

Nothing here has been cut in cardboard yet. The geometry is exact; how narrow a bridge may
be before it burns away or tears under a spray can is a measurement on material.
"""

import math

from .bridges import MAX_COUNT, TAB_TYPES, _Ruler, _carries, path_length
from .tiling import _inside_outline

#: The node types a stencil can work on. The same list the ordinary bridges use, because
#: the mechanism underneath is theirs: a type that cannot carry `mktabpositions` cannot
#: carry a stencil bridge either.
TAB_TYPES_NOTE = TAB_TYPES

#: Points sampled along each contour when looking for the shortest crossing. 240 puts the
#: samples about 1.3 mm apart on the counter of a 40 mm 'O' (perimeter ~ 63 mm), which is
#: finer than any bridge is wide, and the pairing is O(n·m) over two contours at a time.
SAMPLES = 240

#: How far apart two bridges on the same island have to be, as a fraction of that island's
#: perimeter. Without it the two shortest crossings are neighbours: on an 'O' both would
#: land within a few millimetres at the thinnest point of the ring, and the island would
#: hang on what is effectively one bridge.
APART = 0.28

#: A bridge narrower than this is a promise the material will not keep. Same figure as the
#: living hinge uses for the same reason: a CO2 cut is 0.1 to 0.3 mm wide itself.
MIN_BRIDGE_MM = 0.6


def _subpaths(geom) -> list[list[int]]:
    """
    The segment indices of each subpath, in order.

    A `Geomstr` is one flat list of segments with `TYPE_END` markers between subpaths, and
    a shape from a font is one node holding a dozen of them. Everything below works per
    subpath, because a contour is what has an inside.
    """
    from meerk40t.core.geomstr import TYPE_END

    runs: list[list[int]] = []
    current: list[int] = []
    for index in range(geom.index):
        kind = int(geom.segments[index][2].real)
        if kind == TYPE_END:
            if current:
                runs.append(current)
            current = []
            continue
        if _carries(geom, index):
            current.append(index)
    if current:
        runs.append(current)
    return runs


def _walk(geom, indices: list[int]):
    """
    Points along one contour, each with where it came from.

    Returns `(points, places)` where `places[i]` is `(segment index, t)` for `points[i]`.
    Keeping the provenance is the point: a crossing found here has to become a percentage
    along the whole path, and going back from a bare coordinate would mean searching for it.
    """
    lengths = [abs(float(geom.length(i))) for i in indices]
    lengths = [value if math.isfinite(value) else 0.0 for value in lengths]
    total = sum(lengths)
    if total <= 0:
        return [], []
    per = max(2, int(SAMPLES * 1))
    points, places = [], []
    for index, length in zip(indices, lengths):
        if length <= 0:
            continue
        # Samples in proportion to the segment's share of the contour, so a long straight
        # side is not measured more coarsely than a short curve.
        count = max(2, int(round(per * length / total)))
        for step in range(count):
            t = step / count
            points.append(geom.position(index, t))
            places.append((index, t))
    return points, places


def _closed(points) -> bool:
    """Does this contour come back to where it started?"""
    if len(points) < 3:
        return False
    return abs(points[0] - points[-1]) < max(1.0, abs(points[0]) * 1e-9)


def contours(geom) -> list[dict]:
    """
    Every contour of a geometry, with its points, its provenance and its nesting depth.

    `depth` is the number of *other* contours containing it. Odd means the region it
    encloses is material with an opening around it — an island.
    """
    found = []
    for indices in _subpaths(geom):
        points, places = _walk(geom, indices)
        if len(points) < 3:
            continue
        found.append(
            {
                "indices": indices,
                "points": points,
                "places": places,
                "closed": _closed(points + [geom.position(indices[-1], 1.0)]),
            }
        )
    for i, contour in enumerate(found):
        probe = contour["points"][0]
        contour["depth"] = sum(
            1 for j, other in enumerate(found) if j != i and _inside_outline(probe, [other["points"]])
        )
    for i, contour in enumerate(found):
        # The parent is the deepest contour that contains this one: on a letter that is the
        # outline the counter sits in, and the crossing has to reach *that* and not some
        # outer frame the design may also have.
        probe = contour["points"][0]
        parents = [
            (found[j]["depth"], j)
            for j in range(len(found))
            if j != i and _inside_outline(probe, [found[j]["points"]])
        ]
        contour["parent"] = max(parents)[1] if parents else None
    return found


def islands(found: list[dict]) -> list[int]:
    """The contours that enclose material with an opening all round it."""
    return [i for i, contour in enumerate(found) if contour["depth"] % 2 == 1]


def _cumulative(geom):
    """Arc length before each segment, and the total, in engine units."""
    before = {}
    total = 0.0
    rulers = {}
    for index in range(geom.index):
        if not _carries(geom, index):
            continue
        length = abs(float(geom.length(index)))
        if not math.isfinite(length):
            length = 0.0
        before[index] = total
        rulers[index] = _Ruler(geom, index, length)
        total += length
    return before, rulers, total


def _percent(before, rulers, total, place) -> float:
    """Where a `(segment, t)` sits along the whole path, as a percentage."""
    index, t = place
    if total <= 0:
        return 0.0
    along = before.get(index, 0.0) + rulers[index].length_at(t)
    return max(0.0, min(100.0, 100.0 * along / total))


def _crossings(island: dict, parent: dict, count: int) -> list[tuple]:
    """
    Where to bridge: the shortest crossings from the island to the contour around it.

    Shortest, because the bridge spans the opening and a short bridge wastes less of the
    paint edge. Spread, because the two shortest are usually neighbours — see `APART`.
    """
    pairs = []
    for i, point in enumerate(island["points"]):
        best = None
        for j, other in enumerate(parent["points"]):
            gap = abs(point - other)
            if best is None or gap < best[0]:
                best = (gap, j)
        pairs.append((best[0], i, best[1]))
    pairs.sort()

    apart = max(1, int(len(island["points"]) * APART))
    chosen: list[tuple] = []
    for gap, i, j in pairs:
        if all(
            min(abs(i - other), len(island["points"]) - abs(i - other)) >= apart
            for _, other, _ in chosen
        ):
            chosen.append((gap, i, j))
        if len(chosen) == count:
            break
    # Fewer crossings than asked for is not a failure: a small counter has room for one
    # bridge, and forcing a second on top of the first would be worse than saying so.
    return chosen


def plan_stencil(geom, bridge_mm: float, per_island: int, units_per_mm: float) -> dict:
    """
    The bridge positions for one shape, as percentages along its whole path.

    Everything is measured here and nothing is drawn: the caller hands the positions to the
    same node attributes the ordinary bridges use, so the plan, the burn time and the RD
    stream come out of the engine as they always did.
    """
    found = contours(geom)
    loose = islands(found)
    open_ones = [c for c in found if not c["closed"]]

    if not found:
        return {"islands": 0, "bridges": 0, "positions": [], "open_contours": 0, "shortest_mm": None}

    before, rulers, total = _cumulative(geom)
    positions: list[float] = []
    shortest = None
    bridged = 0
    for index in loose:
        island = found[index]
        parent = found[island["parent"]] if island["parent"] is not None else None
        if parent is None:
            continue
        for gap, i, j in _crossings(island, parent, per_island):
            positions.append(_percent(before, rulers, total, island["places"][i]))
            positions.append(_percent(before, rulers, total, parent["places"][j]))
            bridged += 1
            span = gap / units_per_mm
            shortest = span if shortest is None else min(shortest, span)

    # Plain floats: `round()` on a numpy scalar hands back a numpy scalar, and one of those
    # in the answer is a 500 from the JSON encoder rather than a number.
    positions = sorted(float(round(float(value), 6)) for value in positions)
    return {
        "islands": len(loose),
        "bridges": bridged,
        "positions": positions[:MAX_COUNT],
        "open_contours": len(open_ones),
        "contours": len(found),
        "shortest_mm": None if shortest is None else round(shortest, 3),
        "bridge_mm": bridge_mm,
        "length_mm": round(total / units_per_mm, 3),
    }
