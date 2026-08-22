"""
The design as the browser needs it: element outlines and the operations
(layers) they belong to.

Geometry leaves the engine in its native unit — the Tat, 65535 per inch — as
SVG path data. Converting the numbers here would mean rewriting path strings;
instead the snapshot carries `units_per_mm` and the frontend applies a single
scale transform. One multiplication, no parsing.
"""

import math
import re

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


# Layers the engine creates itself are called "Engrave 20.0mm/s @1000 #0000ff": the
# settings crammed into the name. Those are already neatly beside it, so we show what the
# layer is about.
LAYER_NAMES = {
    "op cut": "Cut",
    "op engrave": "Engrave",
    "op raster": "Raster",
    "op image": "Image",
    "op dots": "Dots",
}


def operation_label(op) -> str:
    """
    A layer's name: the user's, or the kind of operation.

    The hallmark of an engine name is the colour code in it ("Engrave 20.0mm/s @1000
    #0000ff"). A test grid cell is deliberately called "5.0mm/s @40.0%" — that *is*
    information, and we leave it.
    """
    # Have it rendered first: the raw name is a template with placeholders like "{percent}",
    # and those do not belong in the layer list.
    rendered = _label(op, str(op.type).replace("op ", ""))
    if rendered and not re.search(r"#[0-9a-fA-F]{6}", rendered):
        return rendered
    return LAYER_NAMES.get(str(op.type), str(op.type).replace("op ", "").title())


def _label(node, fallback: str) -> str:
    """
    A readable name.

    A plain `label` is the user's own name and wins. Templated labels like
    "Engrave ({percent}, {speed}mm/s)" are not: `display_label()` blanks keys
    it cannot resolve, which leaves "Engrave (, 12.0mm/s)". `str(node)` renders
    the node's formatter against the full default map and produces what the
    wxPython tree shows, so templates go through there instead.
    """
    label = _attr_or_none(node, "label")
    if label and "{" not in label:
        return label
    try:
        rendered = str(node)
        if rendered and "{" not in rendered:
            return rendered
    except Exception:
        pass
    if label:
        try:
            resolved = node.display_label()
            if resolved:
                return resolved
        except Exception:
            pass
    return fallback


def _attr_or_none(node, name):
    try:
        return getattr(node, name, None)
    except Exception:
        return None


def _xy(point):
    """
    A point from a matrix transformation to (x, y).

    `point_in_matrix_space` hands back a Point; that is indexable but not sliceable, so
    unpacking has to be explicit.
    """
    try:
        return float(point[0]), float(point[1])
    except (TypeError, IndexError):
        return float(point.x), float(point.y)


def _bridges_of(node, geometry) -> dict | None:
    """
    The bridges (tabs) that keep this part attached to the sheet.

    `None` for a shape whose type does not carry them, so the panel can say that rather
    than offer a field that would do nothing. For a shape that does, the block is always
    there — with `count: 0` when there are none — because the panel needs the path length to
    judge a length the user types, and `path_length_mm` is the only place it comes from.

    `path` is the contour with the gaps cut out of it, and only when there are bridges: that
    is what the canvas strokes. See `bridges.py` for why it is not `final_geometry()`.
    """
    from .bridges import TAB_TYPES, bridged_geometry, parse_positions, path_length

    if getattr(node, "type", None) not in TAB_TYPES or geometry is None:
        return None
    from meerk40t.core.units import UNITS_PER_MM

    try:
        length = float(getattr(node, "mktablength", 0) or 0)
    except (TypeError, ValueError):
        # A project saved before our SVG parameters were registered hands the length back
        # as a string; then it is not a length yet and there is nothing to show.
        length = 0.0
    positions = parse_positions(getattr(node, "mktabpositions", ""))
    # `float()` around the length: `Geomstr.length` gives a numpy scalar, and that is not
    # JSON serialisable — it took the whole snapshot down with it, not just this block.
    total = float(path_length(geometry))
    block = {
        "count": len(positions),
        "length_mm": length / UNITS_PER_MM,
        "positions_percent": [round(float(value), 4) for value in positions],
        "path_length_mm": total / UNITS_PER_MM,
        "path": "",
    }
    if positions and length > 0:
        carved = bridged_geometry(geometry, positions, length)
        if carved is not None:
            block["path"] = carved.as_path().d()
    return block


def _line_of(node) -> dict | None:
    """
    A line's two end points.

    From the bounds alone you cannot see which way a line runs, so without these fields the
    UI cannot offer an end point to drag.
    """
    if getattr(node, "type", None) != "elem line":
        return None
    from meerk40t.core.units import UNITS_PER_MM

    try:
        # Rotating puts a matrix on the node and leaves x1..y2 alone. So anybody drawing the
        # raw points puts the handles in the place from before the rotation.
        matrix = getattr(node, "matrix", None)
        points = [(float(node.x1), float(node.y1)), (float(node.x2), float(node.y2))]
        if matrix is not None:
            points = [_xy(matrix.point_in_matrix_space(p)) for p in points]
        (x1, y1), (x2, y2) = points
        return {
            "x1_mm": x1 / UNITS_PER_MM,
            "y1_mm": y1 / UNITS_PER_MM,
            "x2_mm": x2 / UNITS_PER_MM,
            "y2_mm": y2 / UNITS_PER_MM,
        }
    except (AttributeError, TypeError, ValueError):
        return None


def _text_of(node) -> dict | None:
    """
    Editable vector text.

    `linetext` makes a path, but the engine keeps the source on the node (`mktext`,
    `mkfont`, `mkfontsize`, ...) and can render it again. Without these fields text would be
    frozen once placed.
    """
    text = _attr_or_none(node, "mktext")
    if text is None:
        return None
    from meerk40t.core.units import UNITS_PER_MM

    size = _attr_or_none(node, "mkfontsize")
    try:
        size_mm = round(float(size) / UNITS_PER_MM, 2) if size is not None else None
    except (TypeError, ValueError):
        size_mm = None
    return {
        "text": str(text),
        "font": str(_attr_or_none(node, "mkfont") or ""),
        "font_size_mm": size_mm,
        "spacing": _plain(_attr_or_none(node, "mkfontspacing")) or 1,
        "align": str(_attr_or_none(node, "mkalign") or "start"),
    }


def _image_of(node) -> dict | None:
    """Frame and resolution of an image, in millimetres."""
    if getattr(node, "type", None) != "elem image":
        return None
    from meerk40t.core.units import UNITS_PER_MM

    bounds = getattr(node, "bounds", None)
    if not bounds:
        return None
    x0, y0, x1, y1 = (v / UNITS_PER_MM for v in bounds)
    image = _attr_or_none(node, "active_image") or _attr_or_none(node, "image")
    size = getattr(image, "size", None) if image is not None else None
    return {
        "x_mm": x0,
        "y_mm": y0,
        "width_mm": x1 - x0,
        "height_mm": y1 - y0,
        "pixels": list(size) if size else None,
        "dpi": _plain(_attr_or_none(node, "dpi")),
    }


def _effect_of(node) -> dict | None:
    """
    A hatch or wobble effect this element is in.

    Effects are not operations but containers in the element tree: the command hangs the node
    off `first_node.parent` and takes the shapes in as children. Anybody looking for them in
    the operation tree does not find them.
    """
    parent = _attr_or_none(node, "parent")
    depth = 0
    while parent is not None and depth < 20:
        kind = getattr(parent, "type", "") or ""
        if kind.startswith("effect "):
            return {
                "id": getattr(parent, "id", None),
                "type": kind.replace("effect ", ""),
                "label": _label(parent, kind),
            }
        parent = _attr_or_none(parent, "parent")
        depth += 1
    return None


def _group_of(node) -> str | None:
    """
    The nearest group this element is in.

    The canvas draws elements flat, so without this reference you could drag a test grid's
    individual squares apart — while the grid is precisely one thing.
    """
    parent = _attr_or_none(node, "parent")
    depth = 0
    while parent is not None and depth < 20:
        if getattr(parent, "type", None) == "group":
            return getattr(parent, "id", None)
        parent = _attr_or_none(parent, "parent")
        depth += 1
    return None


def _pose_of(node) -> dict | None:
    """
    How this element is rotated and mirrored.

    The engine already keeps this in `node.matrix`; without these two numbers the panel can
    rotate but not *show* where you are, and then the user goes on clicking in the dark.
    """
    matrix = _attr_or_none(node, "matrix")
    if matrix is None:
        return None
    try:
        rotation = float(matrix.rotation)
        determinant = float(matrix.a) * float(matrix.d) - float(matrix.b) * float(
            matrix.c
        )
    except (AttributeError, TypeError, ValueError):
        return None
    if not math.isfinite(rotation) or not math.isfinite(determinant):
        return None
    mirrored = determinant < 0
    return {"angle_deg": _angle_from(rotation, mirrored), "mirrored": mirrored}


def _angle_from(rotation_rad: float, mirrored: bool) -> float:
    """
    The angle as the user sees it, in degrees within [0, 360).

    A mirrored matrix decomposes as "mirror first, then rotate", and `matrix.rotation` counts
    that mirroring as half a turn: a shape that is *only* mirrored reports 180°. That is not
    an angle but an artefact of the decomposition, so that half turn comes off again.
    Converted back to [0, 360) because -270° and 90° are the same picture, and two names for
    one state make an input field untrustworthy.
    """
    degrees = math.degrees(rotation_rad) - (180.0 if mirrored else 0.0)
    # Round before the modulo, not after: otherwise 359.9999 becomes 360.0, and then there
    # is an angle in the field that by definition does not exist.
    return round(degrees, 3) % 360.0


def _visual_angle(node) -> float | None:
    """The angle of one node, or nothing when the matrix gives nothing away."""
    pose = _pose_of(node)
    return None if pose is None else pose["angle_deg"]


def _color(value) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text.startswith("#") else None


class DesignReader:
    """Builds a render-ready snapshot of the element tree."""

    def __init__(self, kernel, keep_operations=None, grid_operations=None):
        self.kernel = kernel
        # Operations the user created themselves. A fresh tree contains 201 empty default
        # operations, so we normally do not show empty layers — but a layer you have just made
        # yourself should not be invisible straight away.
        self.keep_operations = keep_operations if keep_operations is not None else set()
        # A callable that hands back {operation-id: {grid_id, row, column, ...}}. Grid
        # operations are folded into one row in the UI.
        self.grid_operations = grid_operations or (lambda: {})

    @property
    def elements(self):
        return self.kernel.elements

    def bounds_mm(self):
        """
        The bounding rectangle of everything on the bed, in millimetres.

        `None` when there is nothing there. Hidden elements do not count: they are not burned
        either, so they do not belong in the frame.
        """
        from meerk40t.core.units import UNITS_PER_MM

        x0 = y0 = float("inf")
        x1 = y1 = float("-inf")
        for node in self.kernel.elements.elems():
            if getattr(node, "hidden", False) or not getattr(node, "bounds", None):
                continue
            a, b, c, d = node.bounds
            x0, y0 = min(x0, a), min(y0, b)
            x1, y1 = max(x1, c), max(y1, d)
        if x0 == float("inf"):
            return None
        return (
            x0 / UNITS_PER_MM,
            y0 / UNITS_PER_MM,
            (x1 - x0) / UNITS_PER_MM,
            (y1 - y0) / UNITS_PER_MM,
        )

    def element_ids(self) -> list[str]:
        """
        The ids of the shapes on the bed, in tree order.

        Cheaper than a whole snapshot, and it exists for one thing: the import route
        compares before with after to see what came in. `validate_ids()` first, or a
        freshly loaded shape has no id yet and would look like nothing at all.
        """
        self.elements.validate_ids()
        return [node.id for node in self.elements.elems() if node.id]

    def snapshot(self) -> dict:
        # Give every node a stable identifier. The engine's own mechanism:
        # existing ids are kept, missing ones get "meerk40t:N", duplicates are
        # reassigned. SVG loading calls this too, so it is the identity the
        # rest of MeerK40t already uses — and `elements.find_node(id)` resolves
        # it back. Index-based ids would shift the moment the tree changes,
        # which would make a selection point at the wrong element.
        self.elements.validate_ids()

        grids = self.grid_operations()
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
            if entry is not None:
                entry["grid"] = self._grid_for(op, grids.get(entry["id"]))
            # An operation with no elements is not a layer the user sees; the
            # engine keeps a stack of unused defaults around.
            if entry is not None and (
                entry["element_ids"] or entry["id"] in self.keep_operations
            ):
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

    @staticmethod
    def _grid_for(op, cell):
        """
        Only mark it when the operation really is that cell.

        The link comes from the database and survives a restart, while element ids are handed
        out per document. So an id from an old grid can happen to fit a new operation; then
        that one would be locked wrongly. So the settings have to agree.
        """
        if not cell:
            return None
        speed = _attr_or_none(op, "speed")
        power = _attr_or_none(op, "power")
        if speed is None or power is None:
            return None
        if abs(float(speed) - float(cell["speed_mm_s"])) > 0.01:
            return None
        if abs(float(power) - float(cell["power_percent"]) * 10) > 0.1:
            return None
        return cell

    def _element(self, node, element_id) -> dict | None:
        # One `as_geometry()` for the whole element: the path data and the bridges both come
        # out of it, and asking twice doubles the only measurable cost in the snapshot
        # (0.019 ms per shape, so 4 ms over 200 shapes on a poll).
        geometry = self._geometry(node)
        path = self._path(geometry)
        image = _image_of(node)
        # Images have no path; without this exception they fell out of the snapshot and were
        # invisible on the canvas.
        if path is None and image is None:
            return None
        return {
            "image": image,
            "id": element_id,
            "type": node.type,
            "label": _label(node, node.type.replace("elem ", "")),
            "hidden": bool(getattr(node, "hidden", False)),
            # The engine's own lock (core/node/node.py:85). The canvas draws no
            # handles on a locked shape and the panel offers the way out, so the
            # flag has to travel with every snapshot rather than be asked for.
            "locked": bool(getattr(node, "lock", False)),
            "group_id": _group_of(node),
            "text": _text_of(node),
            "line": _line_of(node),
            "effect": _effect_of(node),
            "pose": _pose_of(node),
            "bridges": _bridges_of(node, geometry),
            "stroke": _color(getattr(node, "stroke", None)),
            "fill": _color(getattr(node, "fill", None)),
            "bounds": [_plain(v) for v in (node.bounds or [])] or None,
            # How many separate pieces the shape consists of. A CAD export is often one path
            # with dozens of panels in it, and the panel has to be able to say how many shapes
            # splitting produces. Free to read off: in the path data every piece starts with
            # an `M`.
            "subpaths": (path or "").count("M"),
            "path": path or "",
        }

    def _geometry(self, node):
        """The ideal outline, or None for nodes without one."""
        if not hasattr(node, "as_geometry"):
            return None
        try:
            return node.as_geometry()
        except Exception:
            # Images and text may have no vector form; they are skipped rather
            # than breaking the whole snapshot.
            return None

    def _path(self, geometry) -> str | None:
        """SVG path data in native units."""
        if geometry is None:
            return None
        try:
            data = geometry.as_path().d()
        except Exception:
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
            "label": operation_label(op),
            "color": _color(getattr(op, "color", None)),
            "speed": _plain(getattr(op, "speed", None)),
            "power": _plain(getattr(op, "power", None)),
            # What the machine is really going to do, and not what is in the field. The
            # engine reads `implicit_passes`, and that gives 1 as long as `passes_custom` is
            # off — a layer with `passes = 3` and that flag off burns once. Measured on a test
            # board that had "2 passes" on its caption and did one; the panel said 2 as well.
            #
            # To the engine 0 means "not set", not "zero times".
            "passes": _plain(getattr(op, "implicit_passes", None))
            or _plain(getattr(op, "passes", None))
            or 1,
            # Only meaningful for raster/image, but every operation carries the fields; the
            # frontend shows them by type.
            "dpi": _plain(getattr(op, "dpi", None)),
            "overscan": _plain(getattr(op, "overscan", None)),
            "bidirectional": bool(getattr(op, "bidirectional", True)),
            # Air assist (decision B11). The engine knows three states in `coolant`: 0 leave
            # it, 1 on, 2 off. To the user it is a switch, so anything that is not 1 is off.
            "air_assist": _plain(getattr(op, "coolant", None)) == 1,
            # Dropping per pass; ours, not the engine's (see Drawing.z_step_supported).
            # `null` means off.
            "z_step_mm": _plain(getattr(op, "z_step_mm", None)),
            "output": bool(getattr(op, "output", True)),
            "element_ids": referenced,
        }
