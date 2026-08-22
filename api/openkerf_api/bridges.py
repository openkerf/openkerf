"""
Bridges (tabs) in a cut line: the small gaps that keep a part attached to the sheet.

Without them a cut part drops into the machine the moment the contour closes — and a part
that drops shifts, so the last millimetres of the cut land beside the line. Every cutter
leaves a few tabs; there is no way round it.

**The engine already does the geometry, and it does it well.** Every shape node carries
`mktablength` (the length of one bridge, in engine units) and `mktabpositions` (a string:
`"*4"` for four spread evenly, or a comma/space separated list of percentages along the
path). `final_geometry()` applies them with `Geomstr.wobble_tab`, and `core/cutplan.py:630`
prefers `final_geometry()` for `op cut` and `op engrave`. Measured on a 60x40 mm rectangle
in a 10 mm/s cut layer, through our own exact estimate: 35.7 s without bridges and 34.5 s
with four of 2 mm, and the engine's own contour goes from 200.00 mm to 191.75 mm. So the
plan, the time and the RD stream are right for free.

What is *not* free is two things, and both live here.

**The picture.** The design snapshot draws from `as_geometry()`, and that is the ideal path:
measured on the same rectangle, 149 characters of `d` and one subpath, identical before and
after setting `*4`. So the gaps were invisible on the bed. Shipping `final_geometry()`
instead is not the fix: `wobble_tab` resamples at 0.05 mm, and the same rectangle goes from
4 segments and 149 bytes of `d` to 3839 segments and 114,661 bytes — 770x, in a snapshot the
frontend polls. `bridged_geometry` below carves the same gaps out of the ideal path on the
parameter, so a line stays a line and an arc stays an arc: 4 segments become 8, and the
result lands within 0.05 mm of the engine's own answer (measured: our gap runs 34.00 -> 36.00
where the engine cuts 34.00 -> 36.05, exactly one resample step of overshoot on its side).

**The guard.** The engine's only check is `len(positions) * tablen < total_length`
(`fill/fills.py:603`) and it is far too lax in one direction and silent in the other.
Measured on that 200 mm perimeter: four bridges of 49.9 mm pass the check and leave 0.15 mm
of cut in the whole contour — the part is not cut at all — while `"*100"` of 2 mm fails it
and the geometry comes back *empty*: index 0, zero subpaths, zero length, no word said. So
we refuse before the engine can, and we refuse on a bound that means something: the bridges
may take at most half the path.
"""

from __future__ import annotations

import math

#: The element types whose `final_geometry()` really applies tabs.
#:
#: `elem line` carries both attributes but ignores them: `LineNode.final_geometry` sets
#: `numtabs = 4` and then `numtabs = 0` on the next line (`core/node/elem_line.py:157-159`).
#: Measured: a 100 mm line with `"*4"` stays 100.0 mm and one subpath. `elem point`,
#: `elem text` and `elem image` have no such attributes at all.
TAB_TYPES = ("elem rect", "elem path", "elem ellipse", "elem polyline")

#: How much of the contour the bridges may take together.
#:
#: The engine allows anything below the whole path length, and that is not a bound: four
#: bridges of 49.9 mm on a 200 mm perimeter pass it and leave 0.15 mm of cut spread over
#: four pieces. Half is a bound a person can reason about — as much material as cut — and it
#: still allows the wide tabs somebody uses on a thick sheet.
MAX_FRACTION = 0.5

#: How many bridges at most. Not a technical limit but a readable one: at 200 bridges the
#: contour is a dotted line and the panel's read-back is unusable. The engine has no limit
#: and simply empties the geometry once they no longer fit.
MAX_COUNT = 200


def positions_for(count: int) -> list[float]:
    """
    Where `count` bridges spread evenly along the path, as percentages.

    The same arithmetic the engine uses for `"*N"` (`fill/fills.py:565`): `(i + 0.5) * 100
    / N`, so the first and the last bridge sit half a gap from the seam instead of on it.
    """
    return [round((i + 0.5) * 100.0 / count, 6) for i in range(count)]


def parse_positions(text) -> list[float]:
    """
    The positions the engine has stored, read back as percentages.

    Mirrors the engine's own parser so the panel shows what will really be cut: `"*N"` is
    N spread evenly, anything else is a comma and/or whitespace separated list clamped to
    [0, 100], and unreadable pieces are dropped.
    """
    if not text:
        return []
    text = str(text).strip()
    if text.startswith("*"):
        head = text[1:].split()
        try:
            count = int(head[0]) if head else 0
        except ValueError:
            return []
        return positions_for(count) if 0 < count <= MAX_COUNT else []
    found = []
    for part in text.replace(",", " ").split():
        try:
            value = float(part)
        except ValueError:
            continue
        found.append(max(0.0, min(100.0, value)))
    return found


def format_positions(count: int | None, positions: list[float] | None) -> str:
    """
    The string to put on the node.

    `"*N"` when the count is what was asked for: that is the engine's own shorthand and it
    survives a resize — the bridges stay spread evenly instead of drifting to where they
    happened to be when the shape was smaller.
    """
    if positions is not None:
        return ",".join(f"{value:g}" for value in positions)
    return f"*{int(count)}"


def path_length(geom) -> float:
    """
    The length of a geometry in engine units, summed over its real segments.

    A non-finite segment length is skipped rather than added. `Geomstr.length` can hand back
    NaN: its closed-form cubic branch (`geomstr.py:5899`) divides by zero on a degenerate
    curve, and vector text on an arc produces those. Measured before this: a NaN travelled
    into `path_length_mm` and took the *whole* design snapshot down with a
    "Out of range float values are not JSON compliant" — one bad segment and the canvas went
    blank.
    """
    total = 0.0
    for index in range(geom.index):
        if not _carries(geom, index):
            continue
        value = abs(geom.length(index))
        if math.isfinite(value):
            total += float(value)
    return total


def _carries(geom, index: int) -> bool:
    from meerk40t.core.geomstr import TYPE_ARC, TYPE_CUBIC, TYPE_LINE, TYPE_QUAD

    return int(geom.segments[index][2].real) in (TYPE_LINE, TYPE_QUAD, TYPE_CUBIC, TYPE_ARC)


def gap_spans(total: float, positions_percent, length_units: float) -> list[tuple[float, float]]:
    """
    Where the gaps fall along the path, in engine units, merged and sorted.

    A gap is centred on its position, so a bridge asked for at 0 % straddles the seam. The
    engine wraps that round to the end of the path rather than clipping it
    (`fill/fills.py:623`), and so do we: on a closed contour that is the same place, and on
    an open one it keeps our picture equal to what the machine does.
    """
    if total <= 0 or length_units <= 0:
        return []
    half = length_units / 2.0
    raw: list[tuple[float, float]] = []
    for percent in positions_percent:
        centre = percent / 100.0 * total
        start, end = centre - half, centre + half
        if start < 0:
            raw.append((0.0, end))
            raw.append((start + total, total))
        elif end > total:
            raw.append((start, total))
            raw.append((0.0, end - total))
        else:
            raw.append((start, end))

    merged: list[tuple[float, float]] = []
    for start, end in sorted(raw):
        if end - start <= 0:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


class _Ruler:
    """
    The arc length along one segment against its parameter.

    For a line and for a circular arc the parameter *is* proportional to arc length, so the
    two are one multiplication apart. For a quad and a cubic they are not. On the cubics an
    ellipse is drawn with it makes no difference — measured on a circle of r = 20 mm, the
    arc length at t = 0.5 is 50.000 % of each segment — but a cubic from an imported drawing
    can bend hard: measured on one of 140.7 mm, t = 0.5 sits at 87.5 mm and not at 70.3 mm,
    so reading the parameter as a fraction of the length would put the bridge 17 mm along
    the path from where it is cut. Twenty-four samples bring that back to 0.05 mm on that
    same curve (measured against a 20,000-sample walk at 25 %, 50 % and 75 %), which is the
    size of the engine's own resample step.
    """

    SAMPLES = 24

    def __init__(self, geom, index: int, length: float):
        import numpy as np
        from meerk40t.core.geomstr import TYPE_ARC, TYPE_LINE, TYPE_QUAD

        self.length = length
        row = geom.segments[index]
        kind = int(row[2].real)
        self.linear = kind in (TYPE_LINE, TYPE_ARC)
        if self.linear:
            return
        # The Bézier is evaluated here rather than through `Geomstr.position`, which takes one
        # parameter at a time and wraps it in a list: measured on a bridged circle of
        # r = 20 mm, 25 such calls per curved segment cost 1.71 ms per shape and the same
        # samples in one numpy expression cost 1.05 ms. The formula is the engine's own
        # (`_quad_position_batch` / `_cubic_position_batch`, geomstr.py:7773) — start,
        # controls in fields 1 and 3, end.
        t = np.linspace(0.0, 1.0, self.SAMPLES + 1)
        rest = 1.0 - t
        start, end = row[0], row[4]
        if kind == TYPE_QUAD:
            points = rest**2 * start + 2 * t * rest * row[1] + t**2 * end
        else:
            points = (
                rest**3 * start
                + 3 * t * rest**2 * row[1]
                + 3 * t**2 * rest * row[3]
                + t**3 * end
            )
        walked = np.concatenate(([0.0], np.cumsum(np.abs(np.diff(points)))))
        self.walked = walked * (length / walked[-1] if walked[-1] else 1.0)

    def length_at(self, t: float) -> float:
        if self.linear:
            return t * self.length
        position = max(0.0, min(1.0, t)) * self.SAMPLES
        low = min(int(position), self.SAMPLES - 1)
        fraction = position - low
        return self.walked[low] + fraction * (self.walked[low + 1] - self.walked[low])

    def t_at(self, distance: float) -> float:
        if self.linear:
            return 0.0 if self.length <= 0 else distance / self.length
        for index in range(self.SAMPLES):
            low, high = self.walked[index], self.walked[index + 1]
            if distance <= high:
                span = high - low
                fraction = 0.0 if span <= 0 else (distance - low) / span
                return (index + fraction) / self.SAMPLES
        return 1.0


def bridged_geometry(geom, positions_percent, length_units: float):
    """
    The same path with the bridges taken out, as a new Geomstr.

    Cut on the parameter, not resampled: a line comes back a line and an arc an arc, so the
    canvas draws the contour it already drew plus the gaps in it. The original is untouched.

    Hands back `None` when nothing is taken out — no positions, no length, or a path with no
    length — so the caller can leave the snapshot as it was instead of shipping a copy.
    """
    from meerk40t.core.geomstr import Geomstr

    from .tiling import _pieces

    total = path_length(geom)
    spans = gap_spans(total, positions_percent, length_units)
    if not spans:
        return None

    out = Geomstr()
    walked = 0.0
    for index in range(geom.index):
        if not _carries(geom, index):
            continue
        seglen = abs(geom.length(index))
        if not math.isfinite(seglen) or seglen <= 0:
            continue
        start, end = walked, walked + seglen
        walked = end

        # A segment no gap touches is copied over whole, and then no ruler is built for it.
        # That is what keeps this affordable: measured on a circle of r = 20 mm (twelve
        # cubics, four bridges), 3.17 ms per shape when every segment was measured against
        # 1.05 ms when only the four that carry a gap are. A rectangle costs 0.05 ms, and
        # only shapes that really have bridges pay anything at all.
        touching = [span for span in spans if span[0] < end and span[1] > start]
        if not touching:
            out.append_segment(*geom.segments[index])
            continue

        ruler = _Ruler(geom, index, seglen)

        # Where the gap edges fall inside this segment, as parameters.
        cuts = sorted(
            {
                round(ruler.t_at(edge - start), 9)
                for span in spans
                for edge in span
                if start + 1e-9 < edge < end - 1e-9
            }
        )
        edges = [0.0] + cuts + [1.0]
        for piece, (a, b) in zip(_pieces(geom, index, cuts), zip(edges, edges[1:])):
            middle = start + ruler.length_at((a + b) / 2.0)
            if any(low <= middle <= high for low, high in spans):
                continue
            out.append_segment(*piece)
    return out
