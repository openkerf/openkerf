"""
The design as the browser needs it: element outlines and the operations
(layers) they belong to.

Geometry leaves the engine in its native unit — the Tat, 65535 per inch — as
SVG path data. Converting the numbers here would mean rewriting path strings;
instead the snapshot carries `units_per_mm` and the frontend applies a single
scale transform. One multiplication, no parsing.
"""

from meerk40t.core.units import UNITS_PER_MM

# Operation types that carry a laser setting and therefore read as a layer.
OPERATION_PREFIX = ("op ", "effect ")


def _plain(value):
    """numpy scalars and Color objects must survive JSON."""
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, (int, float)):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return str(value)


def _color(value) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text.startswith("#") else None


class DesignReader:
    """Builds a render-ready snapshot of the element tree."""

    def __init__(self, kernel):
        self.kernel = kernel

    @property
    def elements(self):
        return self.kernel.elements

    def snapshot(self) -> dict:
        # Give every node a stable identifier. The engine's own mechanism:
        # existing ids are kept, missing ones get "meerk40t:N", duplicates are
        # reassigned. SVG loading calls this too, so it is the identity the
        # rest of MeerK40t already uses — and `elements.find_node(id)` resolves
        # it back. Index-based ids would shift the moment the tree changes,
        # which would make a selection point at the wrong element.
        self.elements.validate_ids()

        element_ids = {}
        elements = []
        for index, node in enumerate(self.elements.elems()):
            entry = self._element(node, node.id or f"e{index}")
            if entry is not None:
                element_ids[id(node)] = entry["id"]
                elements.append(entry)

        operations = []
        for index, op in enumerate(self.elements.ops()):
            entry = self._operation(op, op.id or f"o{index}", element_ids)
            # An operation with no elements is not a layer the user sees; the
            # engine keeps a stack of unused defaults around.
            if entry is not None and entry["element_ids"]:
                operations.append(entry)

        # Which operations claim each element. This is genuinely many-to-many:
        # MeerK40t classifies elements into every operation whose colour
        # matches, so an element commonly sits in several at once. Rendering
        # therefore uses the element's own stroke, not a "layer colour".
        claims: dict[str, list[str]] = {}
        for op in operations:
            for element_id in op["element_ids"]:
                claims.setdefault(element_id, []).append(op["id"])
        for element in elements:
            operation_ids = claims.get(element["id"], [])
            element["operation_ids"] = operation_ids
            element["operation_id"] = operation_ids[0] if operation_ids else None

        return {
            "units_per_mm": UNITS_PER_MM,
            "elements": elements,
            "operations": operations,
        }

    def _element(self, node, element_id) -> dict | None:
        path = self._path(node)
        if path is None:
            return None
        return {
            "id": element_id,
            "type": node.type,
            "label": getattr(node, "label", None) or node.type.replace("elem ", ""),
            "hidden": bool(getattr(node, "hidden", False)),
            "stroke": _color(getattr(node, "stroke", None)),
            "fill": _color(getattr(node, "fill", None)),
            "bounds": [_plain(v) for v in (node.bounds or [])] or None,
            "path": path,
        }

    def _path(self, node) -> str | None:
        """SVG path data in native units, or None for nodes without outlines."""
        if not hasattr(node, "as_geometry"):
            return None
        try:
            geometry = node.as_geometry()
            data = geometry.as_path().d()
        except Exception:
            # Images and text may have no vector form; they are skipped rather
            # than breaking the whole snapshot.
            return None
        return data or None

    def _operation(self, op, operation_id, element_ids) -> dict | None:
        if not str(op.type).startswith(OPERATION_PREFIX):
            return None
        referenced = []
        for child in op.children:
            target = getattr(child, "node", None)
            if target is not None and id(target) in element_ids:
                referenced.append(element_ids[id(target)])
        return {
            "id": operation_id,
            "type": op.type,
            "label": getattr(op, "label", None) or op.type.replace("op ", ""),
            "color": _color(getattr(op, "color", None)),
            "speed": _plain(getattr(op, "speed", None)),
            "power": _plain(getattr(op, "power", None)),
            "passes": _plain(getattr(op, "passes", None)),
            "output": bool(getattr(op, "output", True)),
            "element_ids": referenced,
        }
