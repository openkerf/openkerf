"""
Finding shapes that lie on top of each other, and keeping one of each.

Why this exists: a duplicate is invisible and it costs twice. The laser cuts the
same line again — on thin material a second pass through the same kerf burns the
edge, and on thick material it is simply twice the time. And you cannot see it:
two identical rectangles at the same place look like one rectangle.

They arrive by themselves. An SVG exported twice from a CAD tool, a paste that
landed back where it came from, an import on top of work that was already there
(importing adds, since the round that made it add), a generator run twice with the
same numbers. LightBurn has *Delete Duplicates* for exactly this.

## What counts as the same shape

Two shapes are the same when the laser cannot tell them apart, so the comparison
is on what gets burned, not on what the file says:

- the same node type — a rectangle and a path that happens to draw the same
  rectangle stay two shapes, because the engine treats them differently (a rect
  carries width and height, a path carries points);
- the same geometry, compared as points on the path rounded to a tenth of a
  millimetre. That tolerance is a decision: exports round differently, and two
  shapes 0.02 mm apart are one shape as far as a 0.2 mm kerf is concerned. It is
  also the reason this is a separate module and not a one-line grep on the path
  string — the same rectangle can be written as four different `d` attributes.

Deliberately *not* part of the comparison: the layer, the colour, the fill, the
bridges. Two identical outlines in two layers burn twice, which is exactly the
mistake this looks for, and the one that stays keeps the layer of the first.
"""

from .edits import DesignError

# A tenth of a millimetre. Wider than any export rounding, narrower than a kerf.
TOLERANCE_MM = 0.1

# How many points of a path are compared. A shape that matches on start, end and
# these many places along its length is the same shape; sampling instead of walking
# every segment keeps a 10,000-segment text from making this quadratic in segments
# as well as in shapes.
SAMPLES = 24


def _fingerprint(node, units_per_mm: float) -> tuple | None:
    """
    What the laser would see of this shape, rounded, as something hashable.

    None when the shape has no geometry to compare (an image, a group): those are
    left alone rather than guessed at.
    """
    try:
        geometry = node.as_geometry()
    except Exception:  # pragma: no cover - a node type without geometry
        return None
    if geometry is None:
        return None
    try:
        points = list(geometry.as_interpolated_points(interpolate=SAMPLES))
    except Exception:  # pragma: no cover - the engine can refuse on odd paths
        return None
    grid = TOLERANCE_MM * units_per_mm
    rounded = []
    for point in points:
        if point is None:
            # A break between subpaths counts: two shapes with their pieces in a
            # different order are not the same shape.
            rounded.append(None)
            continue
        rounded.append((round(point.real / grid), round(point.imag / grid)))
    if not rounded:
        return None
    return (str(node.type), tuple(rounded))


class Duplicates:
    """Finding and removing shapes that lie on top of each other."""

    def __init__(self, kernel, drawing):
        self.kernel = kernel
        self.drawing = drawing

    @property
    def elements(self):
        return self.kernel.elements

    def _units_per_mm(self) -> float:
        from meerk40t.core.units import UNITS_PER_MM

        return float(UNITS_PER_MM)

    def find(self, element_ids=None) -> dict:
        """
        The groups of identical shapes, without changing anything.

        Looking is a separate step because removing is not undoable in the eye of the
        user: the shapes disappear and the drawing looks the same, so the count is the
        only evidence that something happened. The interface says the number first and
        asks.
        """
        from .edits import _ids

        if element_ids:
            nodes = self.drawing._nodes(_ids(element_ids))
        else:
            nodes = [n for n in self.elements.elems() if not getattr(n, "hidden", False)]
        per_mm = self._units_per_mm()
        groups: dict[tuple, list] = {}
        skipped = 0
        for node in nodes:
            key = _fingerprint(node, per_mm)
            if key is None:
                skipped += 1
                continue
            groups.setdefault(key, []).append(node)
        stacks = [nodes for nodes in groups.values() if len(nodes) > 1]
        return {
            "looked_at": len(nodes),
            "skipped": skipped,
            "stacks": len(stacks),
            # What would go: every shape of every stack except the first.
            "extra": sum(len(stack) - 1 for stack in stacks),
            "groups": [[node.id for node in stack] for stack in stacks],
        }

    def remove(self, element_ids=None) -> dict:
        """
        Keep the first of every stack, take the rest away.

        The first in tree order stays, which is the one that was there first, so a
        shape that was imported on top of your own work is the one that goes. A locked
        shape is never removed — and it is never the one that keeps a stack alive
        either: if the copy is locked and the original is not, the locked one stays and
        the loose one goes.
        """
        found = self.find(element_ids)
        if not found["stacks"]:
            return {**found, "removed": 0}

        from .locking import is_locked

        going = []
        for group in found["groups"]:
            nodes = [self.elements.find_node(node_id) for node_id in group]
            nodes = [node for node in nodes if node is not None]
            # A locked shape is the keeper, whatever its place in the tree.
            keeper = next((node for node in nodes if is_locked(node)), nodes[0])
            going.extend(node for node in nodes if node is not keeper and not is_locked(node))
        if not going:
            return {**found, "removed": 0}
        ids = [node.id for node in going]
        with self.elements.undoscope("Remove duplicates"):
            self.elements.set_emphasis(going)
            self.drawing.runner.run("element delete")
        self.drawing._refresh()
        left = {node.id for node in self.elements.elems()}
        stayed = [node_id for node_id in ids if node_id in left]
        if stayed:
            raise DesignError(
                f"{len(stayed)} of the {len(ids)} duplicates would not go away. "
                "Nothing was removed twice; look at the design and try again.",
                code="duplicates.stuck",
            )
        return {**found, "removed": len(ids), "removed_ids": ids}
