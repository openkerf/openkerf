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

**What a bridge is here, and the mistake worth keeping written down.** The first version left
a gap in the island contour and a gap in the contour around it, facing each other, and called
that a bridge. It is not. The ring between the two contours is the paint opening and has to
come *out*, and with a gap on each side it stays attached to the sheet at one gap and to the
island at the other: nothing falls out at all, and the stencil is a sheet of cardboard with
some notches in it. The user found it on the first shape they tried, with a picture.

A bridge is four cuts: the two gaps, **and the two short cuts across the opening that join
their ends**. Those two are the sides of the bridge. With them the ring is bounded all round
by cut lines and drops out; the strip between them is cut on neither long side and holds the
island to the sheet. Measured on the version without them: zero segments ran from the outer
contour to the inner one, which is exactly as many as the reasoning above predicts.

The crossing is chosen where the two contours are closest, so the bridge is short: it is the
strongest that way, and it costs the least of the sprayed edge.

**Why this cannot ride on the engine's own tabs.** Two reasons, and the second is the one
that decides it. The ordinary bridges action spreads its positions over the *concatenated*
length of every contour in the shape — measured on "OO", four contours and 318 mm of path,
`*4` gives 12.5/37.5/62.5/87.5 %, which can put all four bridges on one letter. That one is
only arithmetic and could be fixed with explicit percentages. But the engine's tabs can only
ever *remove* pieces of a contour, and a stencil bridge has to *add* two cuts that belong to
no contour. So the finished stencil is geometry: the gapped contours plus the crossing cuts,
written back over the shape the way rounding a corner is.

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
    pairs: list[tuple[float, float]] = []
    shortest = None
    bridged = 0
    for index in loose:
        island = found[index]
        parent = found[island["parent"]] if island["parent"] is not None else None
        if parent is None:
            continue
        for gap, i, j in _crossings(island, parent, per_island):
            here = _percent(before, rulers, total, island["places"][i])
            there = _percent(before, rulers, total, parent["places"][j])
            positions.extend((here, there))
            # Kept as a pair, and not only as two numbers in a list: the two crossing cuts
            # of a bridge join *these* two gaps, and a sorted list of positions no longer
            # says which gap belongs to which.
            pairs.append((here, there))
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
        "pairs": pairs,
        "open_contours": len(open_ones),
        "contours": len(found),
        "shortest_mm": None if shortest is None else round(shortest, 3),
        "bridge_mm": bridge_mm,
        "length_mm": round(total / units_per_mm, 3),
    }


def plan_many(shapes, bridge_mm: float, per_island: int, units_per_mm: float) -> dict:
    """
    The same analysis over a whole selection, because nesting is not a property of one shape.

    Measured on the case that found this: three separate rectangles drawn inside one another
    — an outer rounded square, an inner one and a little square in the middle — gave "nothing
    would fall out". Each shape on its own has one contour at depth 0 and no island; the ring
    that has to come out lies *between* two shapes. Whether a design is one path with three
    contours or three shapes on top of each other is a drawing decision, not a stencil one.

    `shapes` is a list of `(key, geometry)`. The answer carries, per key, the gap positions
    for that shape's own path, and the crossing cuts as absolute points — a bridge can join
    two contours that live in different shapes, and then the two cuts belong to neither more
    than the other. They are drawn into the island's shape, since that is the one whose
    holding they are.
    """
    tagged = []
    rulers = {}
    for key, geom in shapes:
        before, ruler, total = _cumulative(geom)
        rulers[key] = (before, ruler, total)
        for contour in contours(geom):
            contour["key"] = key
            tagged.append(contour)

    if not tagged:
        return {"islands": 0, "bridges": 0, "per_shape": {}, "crossings": [], "shortest_mm": None}

    # Depths again, now across everything: a contour of shape A can sit inside one of shape B.
    for i, contour in enumerate(tagged):
        probe = contour["points"][0]
        inside = [
            (other["depth_own"] if False else j)
            for j, other in enumerate(tagged)
            if j != i and _inside_outline(probe, [other["points"]])
        ]
        contour["depth"] = len(inside)
        contour["holders"] = inside
    for contour in tagged:
        # The parent is the deepest contour containing this one, wherever it lives.
        holders = [(tagged[j]["depth"], j) for j in contour["holders"]]
        contour["parent"] = max(holders)[1] if holders else None

    loose = [i for i, c in enumerate(tagged) if c["depth"] % 2 == 1]
    per_shape: dict = {key: [] for key, _g in shapes}
    crossings: list[tuple] = []
    shortest = None
    bridged = 0
    for index in loose:
        island = tagged[index]
        if island["parent"] is None:
            continue
        parent = tagged[island["parent"]]
        for gap, i, j in _crossings(island, parent, per_island):
            i_before, i_ruler, i_total = rulers[island["key"]]
            p_before, p_ruler, p_total = rulers[parent["key"]]
            here = _percent(i_before, i_ruler, i_total, island["places"][i])
            there = _percent(p_before, p_ruler, p_total, parent["places"][j])
            per_shape[island["key"]].append(here)
            per_shape[parent["key"]].append(there)
            crossings.append((island["key"], here, parent["key"], there))
            bridged += 1
            span = gap / units_per_mm
            shortest = span if shortest is None else min(shortest, span)

    return {
        "islands": len(loose),
        "bridges": bridged,
        "per_shape": {
            key: sorted(float(round(float(v), 6)) for v in values)[:MAX_COUNT]
            for key, values in per_shape.items()
        },
        "crossings": crossings,
        "contours": len(tagged),
        "open_contours": sum(1 for c in tagged if not c["closed"]),
        "shortest_mm": None if shortest is None else round(shortest, 3),
        "bridge_mm": bridge_mm,
    }


def point_at(geom, percent: float):
    """The point at a percentage along a path — the inverse of `_percent`."""
    before, rulers, total = _cumulative(geom)
    if total <= 0 or not before:
        return None
    want = percent / 100.0 * total
    last = max(before)
    for index in sorted(before):
        if before[index] + rulers[index].length >= want or index == last:
            return geom.position(index, rulers[index].t_at(max(0.0, want - before[index])))
    return None


def stencil_paths(shapes, plan: dict, bridge_units: float) -> dict:
    """
    The finished stencil, per shape: contours with their gaps, plus the crossing cuts.

    Two steps, and the second is the one the first version was missing. `bridged_geometry`
    takes the gaps out on the parameter, so an arc stays an arc and the letters keep their
    curves. Then, per bridge, two straight cuts join the ends of the two gaps: those are the
    sides of the bridge, and without them the ring between the contours is still attached to
    the sheet at one gap and to the island at the other, so nothing comes out.

    The ends are paired the short way round. Taken the other way the two cuts cross in the
    middle of the bridge, which turns the strip that should hold the island into two loose
    triangles.

    The crossings are drawn into the island's shape. Which of the two shapes carries them
    matters only for tidiness — they are the same cut in the same layer either way — but a
    cut has to belong to something, and the island is the thing the bridge exists for.
    """
    from meerk40t.core.geomstr import Geomstr

    from .bridges import bridged_geometry

    geoms = dict(shapes)
    lengths = {key: path_length(geom) for key, geom in shapes}
    out: dict = {}
    for key, geom in shapes:
        positions = plan["per_shape"].get(key) or []
        opened = bridged_geometry(geom, positions, bridge_units) if positions else None
        if opened is None:
            opened = Geomstr()
            for index in range(geom.index):
                opened.append_segment(*geom.segments[index])
        out[key] = opened

    for island_key, here, parent_key, there in plan.get("crossings", []):
        island, parent = geoms.get(island_key), geoms.get(parent_key)
        if island is None or parent is None:
            continue
        if lengths[island_key] <= 0 or lengths[parent_key] <= 0:
            continue
        # A gap is centred on its position — the rule `gap_spans` follows — so its ends are
        # half a bridge either side, in the percentage of *that* shape's own path.
        i_half = 100.0 * (bridge_units / 2.0) / lengths[island_key]
        p_half = 100.0 * (bridge_units / 2.0) / lengths[parent_key]
        a1, a2 = point_at(island, here - i_half), point_at(island, here + i_half)
        b1, b2 = point_at(parent, there - p_half), point_at(parent, there + p_half)
        if None in (a1, a2, b1, b2):
            continue
        straight = abs(a1 - b1) + abs(a2 - b2)
        crossed = abs(a1 - b2) + abs(a2 - b1)
        first, second = (b1, b2) if straight <= crossed else (b2, b1)
        target = out[island_key]
        target.line(a1, first)
        target.end()
        target.line(a2, second)
        target.end()
    return out
