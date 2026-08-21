"""
Editing nodes: dragging a shape's own points.

Until now you could move, scale and rotate a shape as a whole, but not move one corner. That
is exactly what you need to make a scanned or imported path fit.

Twee dingen om te weten:

- The engine keeps an `elem path` as a **Geomstr**: segments with complex numbers as
  points. Moving a point means adjusting every segment that point occurs in — start *and*
  end point, otherwise the path falls open.
- Shapes (`elem rect`, `elem ellipse`, …) have no separate points; they are parameters.
  Anybody dragging a corner of one means "make it a path". So that is what we do, keeping
  the colour, the layer assignment and the label — otherwise the shape disappears from its
  operation and would no longer burn.
"""

from __future__ import annotations

from .edits import DesignError

# Points within this distance (in Tats) are the same point. 65535 Tats is an inch, so this
# is roughly a hundredth of a millimetre.
SAME_POINT = 30.0

SHAPES = ("elem rect", "elem ellipse", "elem line", "elem polyline", "elem path")


class Nodes:
    def __init__(self, kernel, runner=None):
        self.kernel = kernel
        self.runner = runner

    @property
    def elements(self):
        return self.kernel.elements

    def points(self, element_id: str) -> dict:
        """The nodes of an element, in millimetres."""
        from meerk40t.core.units import UNITS_PER_MM

        node = self._node(element_id)
        geometry = self._geometry(node)
        return {
            "id": element_id,
            "type": node.type,
            "editable": node.type in SHAPES,
            "points": [
                {"index": index, "x_mm": point.real / UNITS_PER_MM, "y_mm": point.imag / UNITS_PER_MM}
                for index, point in enumerate(self._unique(geometry))
            ],
        }

    def move_point(self, element_id: str, index, x_mm, y_mm) -> dict:
        from meerk40t.core.units import UNITS_PER_MM

        node = self._node(element_id)
        if node.type not in SHAPES:
            raise DesignError(f"The nodes of a {node.type} cannot be edited.",
            code="nodes.notEditable",)
        try:
            position = int(index)
            target = complex(float(x_mm) * UNITS_PER_MM, float(y_mm) * UNITS_PER_MM)
        except (TypeError, ValueError) as e:
            raise DesignError("A node needs an index and a position.") from e

        geometry = self._geometry(node)
        points = self._unique(geometry)
        if not 0 <= position < len(points):
            raise DesignError(
                f"Node {position} does not exist; there are {len(points)}."
            )

        moved = self._with_point_moved(geometry, points[position], target)
        with self.elements.undoscope("Move node"):
            new_id = self._replace(node, moved, element_id)
        self.elements.signal("refresh_scene", "Scene")
        return {"id": new_id, "was": element_id, "index": position}

    # --------------------------------------------------------------- intern

    def _node(self, element_id: str):
        node = self.elements.find_node(element_id)
        if node is None:
            raise DesignError(f"Element {element_id} does not exist (any more).")
        return node

    def _geometry(self, node):
        try:
            return node.as_geometry()
        except Exception as e:  # pragma: no cover - only on exotic nodes
            raise DesignError(f"No shape can be read from this element: {e}") from e

    def _unique(self, geometry) -> list[complex]:
        """
        Every node once, in the order the path runs.

        Segments share their end points; without deduplication the user would see two handles
        lying on top of each other and "point 3" would mean nothing.
        """
        found: list[complex] = []
        for segment in geometry.segments[: geometry.index]:
            for point in (segment[0], segment[4]):
                value = complex(point)
                if not any(abs(value - seen) <= SAME_POINT for seen in found):
                    found.append(value)
        return found

    def _with_point_moved(self, geometry, source: complex, target: complex):
        """A copy of the shape with that one point moved."""
        import copy

        moved = copy.deepcopy(geometry)
        shift = target - source
        for segment in moved.segments[: moved.index]:
            for column in (0, 4):
                if abs(complex(segment[column]) - source) <= SAME_POINT:
                    segment[column] = target
            # Straight lines have their control points lying on the ends; leave those and a
            # straight line kinks into a curve.
            for column in (1, 3):
                if abs(complex(segment[column]) - source) <= SAME_POINT:
                    segment[column] = complex(segment[column]) + shift
        return moved

    def _replace(self, node, geometry, element_id: str) -> str:
        """
        Writing the new shape back.

        A path can simply replace its geometry. A rectangle cannot: it becomes a path, and
        then everything that hung off it has to come along — colour, label and above all the
        operations it was in.
        """
        if node.type == "elem path":
            node.geometry = geometry
            # The matrix is already worked into as_geometry(); leaving it would apply the
            # movement a second time.
            node.matrix.reset()
            node.altered()
            return element_id

        operations = [
            reference.parent
            for reference in list(getattr(node, "_references", []))
            if reference.parent is not None
        ]
        parent = node.parent
        replacement = parent.add(
            geometry=geometry,
            type="elem path",
            stroke=getattr(node, "stroke", None),
            stroke_width=getattr(node, "stroke_width", None),
            fill=getattr(node, "fill", None),
            label=getattr(node, "label", None),
        )
        node.remove_node()
        for operation in operations:
            operation.add_reference(replacement)
        self.elements.validate_ids()
        return replacement.id or element_id
