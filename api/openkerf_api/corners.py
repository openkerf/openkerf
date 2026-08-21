"""
Hoeken afronden of afschuinen.

Pure arithmetic on geometry: no kernel, no files, no HTTP. The conversion to engine units
and the replacing of nodes happens in `edits.py`.

**Why this exists, when the engine can already do rounded rectangles.** An `elem rect`
carries `rx`/`ry` and the engine draws it rounded; we leave that path alone, because that is
where it belongs. But the engine *also* decides that a rectangle always ends *round* — it
cannot do a chamfer, and there is no fillet or chamfer tool anywhere in the engine (the
`bevel` you find there is a line join for drawing a stroke width, and a laser follows the
path, not the stroke). So we do it here, and then straight away for every shape with
straight sides: polygons, stars, imported contours.

The size is the **setback along the side**, not the radius. At a right angle those are
equal — which is why a rounded polygon looks exactly like a rounded rectangle with the same
`rx`. At a sharper or blunter angle they diverge, and then "how much comes off my side" is
the number somebody at a machine has any use for.
"""

from __future__ import annotations

import math

STYLES = ("round", "chamfer")

#: Setting back further than half a side makes two corners overlap. So the bound per corner
#: is half the shortest adjoining side: then two corners still fit exactly beside each other
#: on one side.
FRACTION_PER_SIDE = 0.5


class CornerError(Exception):
    """
    What the user has to know before anything changes.

    Carries the same optional `code` as `DesignError`, for the same reason: the
    interface can then say the refusal in the reader's language while the message
    stays the English source.
    """

    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.code = code


def _eenheid(z: complex) -> complex:
    lengte = abs(z)
    return z / lengte if lengte else 0j


def corner_geometry(geom, size_units: float, style: str):
    """
    De geometrie met afgeronde of afgeschuinde corners.

    Hands back `(new_geomstr, changed, skipped)`: how many corners were dealt with and how
    many were skipped. That second number is not cosmetic — it is the difference between
    "done" and "nothing happened to half your corners", and the user should read that.

    Het origineel blijft ongemoeid.

    A corner takes part when two **straight** sides meet at it and the size fits on both
    sides. A corner where an arc arrives stays: setting back along a curve is a different
    problem, and making half a job of it is worse than leaving it.
    """
    from meerk40t.core.geomstr import TYPE_LINE, Geomstr

    if style not in STYLES:
        raise CornerError(
            f"Unknown corner style: {style}. Choose 'round' to round them off or "
            "'chamfer' to bevel them."
        )
    if size_units <= 0:
        raise CornerError("The size of a corner has to be greater than zero.")

    out = Geomstr()
    changed = 0
    skipped = 0

    for subpad in geom.as_subpaths():
        rows = [subpad.segments[i] for i in range(subpad.index)]
        rows = [r for r in rows if int(r[2].real) != 0x80]  # einde-markeringen weg
        if not rows:
            continue
        gesloten = abs(rows[0][0] - rows[-1][4]) < 1e-9 and len(rows) > 2

        # Per segment: hoeveel er aan begin en eind af gaat.
        trim_start = [0.0] * len(rows)
        trim_end = [0.0] * len(rows)
        corners = []  # (index of the first side, index of the second)
        pairs = list(zip(range(len(rows) - 1), range(1, len(rows))))
        if gesloten:
            pairs.append((len(rows) - 1, 0))

        for eerste, tweede in pairs:
            a, b = rows[eerste], rows[tweede]
            if int(a[2].real) != TYPE_LINE or int(b[2].real) != TYPE_LINE:
                skipped += 1
                continue
            if abs(a[4] - b[0]) > 1e-9:
                # Geen aansluitende hoek maar twee losse stukken.
                continue
            len_a, len_b = abs(a[4] - a[0]), abs(b[4] - b[0])
            bound = FRACTION_PER_SIDE * min(len_a, len_b)
            if size_units > bound + 1e-9:
                skipped += 1
                continue
            trim_end[eerste] = size_units
            trim_start[tweede] = size_units
            corners.append((eerste, tweede))
            changed += 1

        if not corners:
            for rij in rows:
                out.append_segment(*rij)
            continue

        ingekort = _inkorten(rows, trim_start, trim_end)
        verbinding = {eerste: tweede for eerste, tweede in corners}
        for index, rij in enumerate(ingekort):
            out.append_segment(*rij)
            tweede = verbinding.get(index)
            if tweede is None:
                continue
            _join(out, rij[4], rows[index][4], ingekort[tweede][0], style)

    if not changed:
        raise CornerError(
            "Not one corner can be rounded or bevelled: no two straight sides meet "
            "there, or the size is too big for the sides. Choose a smaller size.",
            code="corners.none",
        )
    return out, changed, skipped


def _inkorten(rows, trim_start, trim_end):
    """Shorten every line at both ends by what the corners ask for."""
    ingekort = []
    for index, rij in enumerate(rows):
        start, control, info, control2, eind = rij
        richting = _eenheid(eind - start)
        nieuw_start = start + richting * trim_start[index]
        nieuw_eind = eind - richting * trim_end[index]
        ingekort.append((nieuw_start, control, info, control2, nieuw_eind))
    return ingekort


def _join(out, start: complex, corner_point: complex, end: complex, style: str) -> None:
    """
    The piece that joins the two shortened sides.

    For a chamfer that is a straight line. For a round, a *real* arc: it comes out tangent to
    both sides, so the centre lies on the corner's bisector. The arc is given by three points,
    so we work out the middle point — `Geomstr.arc` wants a point *on* the arc, not a radius.
    """
    if style == "chamfer":
        out.line(start, end)
        return

    naar_a = _eenheid(start - corner_point)
    naar_b = _eenheid(end - corner_point)
    bisector = _eenheid(naar_a + naar_b)
    if bisector == 0:
        # The sides lie in one line: there is no corner to round.
        out.line(start, end)
        return

    cos_hoek = max(
        -1.0, min(1.0, (naar_a.real * naar_b.real + naar_a.imag * naar_b.imag))
    )
    halve = math.acos(cos_hoek) / 2
    terug = abs(start - corner_point)
    radius = terug * math.tan(halve)
    to_centre = terug / math.cos(halve)
    middle = corner_point + bisector * (to_centre - radius)
    out.arc(start, middle, end)
