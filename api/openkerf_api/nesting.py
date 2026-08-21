"""
Nesting: laying the chosen shapes as close together on the material as possible.

The engine knows nothing for this, so this is our own work. Deliberately a simple method —
laying shapes on shelves, tallest first — and no more than that:

- It computes on **bounding rectangles**, not on the real outline. So two round shapes can
  lie further apart than strictly necessary. That is more honest than pretending it is
  optimal, and it never goes wrong: rectangles that do not touch, do not have their shapes
  touching either.
- The margin is there for the kerf and the burn edge. Zero margin means two cuts touch, and
  then it is one cut.

**A group is one thing.** What belongs together moves as a whole: the shapes in it keep
their places relative to each other exactly. That is not tidiness but a necessity — a test
board is a measuring instrument, and as soon as the squares are rearranged relative to each
other "row 3, column 5" means nothing and the trial has been thrown away. The same holds for
a gear you built yourself out of four shapes.

If the nesting touches one member of a group, the whole group moves — including the members
that were not passed in. Otherwise "put everything back on the bed" (which only knows the
shapes it sees) would pull a board apart after all.
"""

from .edits import DesignError, _finite


class Nesting:
    def __init__(self, kernel, editor):
        self.kernel = kernel
        self.editor = editor

    @property
    def elements(self):
        return self.kernel.elements

    def nest(self, ids, margin_mm=3.0, origin_x_mm=0.0, origin_y_mm=0.0) -> dict:
        from meerk40t.core.units import UNITS_PER_MM

        margin = _finite(margin_mm, "margin_mm")
        if margin < 0:
            raise DesignError("A negative margin makes the shapes overlap.")
        origin_x = _finite(origin_x_mm, "origin_x_mm")
        origin_y = _finite(origin_y_mm, "origin_y_mm")

        # First fold the loose shapes into units: everything inside the same
        # outermost group is one block with one enclosing rectangle.
        eenheden: dict[int, dict] = {}
        volgorde: list[int] = []
        for element_id in ids or []:
            node = self.elements.find_node(element_id)
            if node is None:
                raise DesignError(f"Element {element_id} does not exist (any more).")
            groep = self._group_of(node)
            leden = self._members(groep) if groep is not None else [node]
            sleutel = id(groep) if groep is not None else id(node)
            if sleutel in eenheden:
                continue
            box = self._bounds_of(leden)
            if box is None:
                continue
            x0, y0, x1, y1 = (value / UNITS_PER_MM for value in box)
            self.elements.validate_ids()
            eenheden[sleutel] = {
                "ids": [n.id for n in leden if n.id],
                "x": x0,
                "y": y0,
                "width": x1 - x0,
                "height": y1 - y0,
            }
            volgorde.append(sleutel)
        boxes = [eenheden[key] for key in volgorde]
        if len(boxes) < 2:
            raise DesignError("Choose at least two shapes to nest.", code="nest.needsTwo")

        width_mm = self._bed_width()
        widest = max(box["width"] for box in boxes)
        usable = max(width_mm - 2 * origin_x, widest + margin)

        # Tallest first: then less air is left above a shelf.
        boxes.sort(key=lambda box: box["height"], reverse=True)

        placed, x, y, shelf = [], origin_x, origin_y, 0.0
        for box in boxes:
            if x > origin_x and x + box["width"] > origin_x + usable:
                x = origin_x
                y += shelf + margin
                shelf = 0.0
            placed.append({**box, "to_x": x, "to_y": y})
            x += box["width"] + margin
            shelf = max(shelf, box["height"])

        moved = 0
        with self.elements.undoscope("Nest"):
            for box in placed:
                dx = box["to_x"] - box["x"]
                dy = box["to_y"] - box["y"]
                if abs(dx) < 0.001 and abs(dy) < 0.001:
                    continue
                # All the unit's members in one move: `translate` works on the whole
                # selection, so the distances between them stay exact.
                self.editor.move(box["ids"], dx, dy)
                moved += len(box["ids"])

        used_height = (y + shelf) - origin_y
        return {
            "moved": moved,
            "used_width_mm": round(usable, 1),
            "used_height_mm": round(used_height, 1),
        }

    @staticmethod
    def _group_of(node):
        """
        The **outermost** group this shape is in, or nothing.

        Outermost and not nearest: a test board with a grouped caption in it is still one
        board. The depth is bounded as everywhere we walk up the tree — a cycle in the tree
        must not become an endless loop.
        """
        parent = getattr(node, "parent", None)
        buitenste = None
        depth = 0
        while parent is not None and depth < 20:
            if getattr(parent, "type", None) == "group":
                buitenste = parent
            parent = getattr(parent, "parent", None)
            depth += 1
        return buitenste

    @classmethod
    def _members(cls, groep) -> list:
        """Every shape under a group, however deeply nested."""
        leden = []
        for child in getattr(groep, "children", []) or []:
            if getattr(child, "type", "") == "group":
                leden.extend(cls._members(child))
            elif getattr(child, "bounds", None):
                leden.append(child)
        return leden

    @staticmethod
    def _bounds_of(nodes):
        """The bounding rectangle of a unit, in engine units."""
        x0 = y0 = float("inf")
        x1 = y1 = float("-inf")
        for node in nodes:
            bounds = getattr(node, "bounds", None)
            if not bounds:
                continue
            a, b, c, d = bounds
            x0, y0, x1, y1 = min(x0, a), min(y0, b), max(x1, c), max(y1, d)
        return None if x0 == float("inf") else (x0, y0, x1, y1)

    def _bed_width(self) -> float:
        from meerk40t.core.units import Length

        device = getattr(self.kernel, "device", None)
        value = getattr(device, "bedwidth", None)
        try:
            return float(Length(value).mm)
        except Exception:
            # Without a known bed we assume half a metre; nesting must not fail on a device
            # that does not tell us its size.
            return 500.0
