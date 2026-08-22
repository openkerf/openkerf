"""
Drawing elements and managing layers.

The basics a laser app cannot do without: put a shape or a line of text on the
bed, remove it again, duplicate it, and create the operations that decide how it
is burned.

Everything goes through console commands so the engine stays the single source
of truth — including its automatic classification, which is wanted here: a new
red shape should land in the cut layer by itself.
"""

import re
from contextlib import contextmanager

from .commands import CommandRunner
from .design import _xy, operation_label
from .edits import DesignError, _finite, _positive
from .palette import normalise
from .testgrid import LABEL_LAYER

# What a shape needs, and the console command that draws it. Millimetres in,
# because that is what the user sees.
SHAPES = {
    "rect": ("x_mm", "y_mm", "width_mm", "height_mm"),
    "ellipse": ("cx_mm", "cy_mm", "rx_mm", "ry_mm"),
    "circle": ("cx_mm", "cy_mm", "r_mm"),
    "line": ("x1_mm", "y1_mm", "x2_mm", "y2_mm"),
    "text": ("x_mm", "y_mm"),
}

# Extras for text, all optional.
TEXT_OPTIONS = {
    "font": str,
    "font_size_mm": float,
    "spacing": float,
}

# Library operation names map onto MeerK40t's own console commands.
OPERATIONS = {
    "cut": "cut",
    "engrave": "engrave",
    "raster": "raster",
    "image": "imageop",
    "dots": "dots",
}

# The node type that belongs to each layer kind — needed to find an existing layer of
# the requested kind again instead of creating another one.
_OPERATION_TYPES = {
    "cut": "op cut",
    "engrave": "op engrave",
    "raster": "op raster",
    "image": "op image",
    "dots": "op dots",
}


def _mm(value: float) -> str:
    return f"{value:.4f}mm"


def _passes_of(node) -> int:
    """
    How many times the machine is really going to do this layer.

    Not the `passes` field but `implicit_passes`: the engine ignores the field as long as
    `passes_custom` is off (`core/parameters.py:401`), so a layer with `passes = 3` and
    that flag off burns once. Measured on a test board that had "2 passes" on its caption
    and did one — and the pre-flight and the panel both reported 2, because they read the
    field.
    """
    number = getattr(node, "implicit_passes", None)
    if number is None:
        number = getattr(node, "passes", None)
    try:
        return max(int(number), 1)
    except (TypeError, ValueError):
        return 1


def _is_filled(node) -> bool:
    """Does this shape have an area to raster? An image is one itself."""
    if str(getattr(node, "type", "")) == "elem image":
        return True
    fill = getattr(node, "fill", None)
    if fill is None or getattr(fill, "value", None) is None:
        return False
    return getattr(fill, "alpha", 255) != 0


#: What a shape is called in a refusal, per element type. The engine's own type strings
#: ("elem rect") are not a name a reader recognises.
_SHAPE_WORDS = {
    "elem rect": "a rectangle",
    "elem ellipse": "an ellipse",
    "elem polyline": "a polyline",
    "elem path": "a path",
    "elem line": "a line",
    "elem point": "a point",
    "elem text": "a text",
    "elem image": "an image",
}


def _shape_name(node) -> str:
    """
    The shape by the shortest name that identifies it.

    A label if it has one, because that is the name the user gave it; otherwise the id,
    which is what the interface and the API both key on and what a script can look up.
    The type word is the last resort — it names a kind and not a shape, but it beats
    saying nothing.
    """
    label = getattr(node, "label", None)
    if isinstance(label, str) and label.strip():
        return f'"{label.strip()}"'
    element_id = getattr(node, "id", None)
    if isinstance(element_id, str) and element_id.strip():
        return element_id.strip()
    return _SHAPE_WORDS.get(str(getattr(node, "type", "")), "this shape")


def _number(value):
    """A number, or nothing. The engine sometimes hands a string or numpy here."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class Drawing:
    def __init__(self, kernel, runner: CommandRunner | None = None):
        self.kernel = kernel
        self.runner = runner or CommandRunner(kernel)
        # Layers made by hand, so that they stay visible while they are empty.
        self.user_operations: set[str] = set()
        # A callable that hands back the operations of test grids; those are locked
        # because their values *are* the sweep.
        self.grid_operations = lambda: {}
        # What a palette colour did on this machine before (decision B2). The server
        # hangs the real memory in here; tested in isolation there is nothing.
        self.color_memory = lambda color: None
        # The user's zero point (gap J12). The server hangs `MachineControl.origin` in
        # here; without it there is no zero point and nothing changes about where the work
        # goes.
        self.origin = lambda: None
        # Was there a whole group on the clipboard? See `clipboard_paste`.
        self._clipboard_group = False

    @property
    def elements(self):
        return self.kernel.elements

    # --------------------------------------------------------------- elements

    def create_path(self, points, closed: bool = False, label=None) -> dict:
        """
        A free path from separate points — the pen.

        A point's numbers describe the segment *arriving* at it, exactly as SVG path data
        does, so there is never a question which of the two segments at a point a handle
        belongs to:

        - `[x, y]` — a straight corner.
        - `[x, y, cx, cy]` — a quadratic curve through one control point.
        - `[x, y, c1x, c1y, c2x, c2y]` — a cubic, `c1` leaving the previous point and `c2`
          arriving at this one. A pen drag makes two handles and not one, so without this
          form the pen could only draw quads, and then a dragged handle at both ends of a
          segment had nowhere to go.

        With `closed` the first point's own numbers describe the closing segment — it is
        the only segment that arrives at point one.

        The geometry goes straight into the element tree. The engine's `path` command
        scales its d-string, and then a path of 10 cm draws itself tens of metres wide.
        """
        from meerk40t.core.geomstr import Geomstr
        from meerk40t.core.units import UNITS_PER_MM

        cleaned = []
        for point in points or []:
            if not isinstance(point, (list, tuple)) or len(point) not in (2, 4, 6):
                raise DesignError(
                    "A point is [x, y], [x, y, cx, cy] or [x, y, c1x, c1y, c2x, c2y].",
                    code="draw.pointShape",
                )
            cleaned.append([_finite(value, "point") for value in point])
        if len(cleaned) < 2:
            raise DesignError("A path needs at least two points.", code="draw.needsTwoPoints")

        def at(values, index=0):
            return complex(
                values[index] * UNITS_PER_MM, values[index + 1] * UNITS_PER_MM
            )

        geometry = Geomstr()
        pairs = list(zip(cleaned, cleaned[1:]))
        if closed:
            pairs.append((cleaned[-1], cleaned[0]))
        for start, end in pairs:
            if len(end) == 6:
                geometry.cubic(at(start), at(end, 2), at(end, 4), at(end))
            elif len(end) == 4:
                geometry.quad(at(start), at(end, 2), at(end))
            else:
                geometry.line(at(start), at(end))

        with self.elements.undoscope("Draw path"):
            node = self.elements.elem_branch.add(
                geometry=geometry,
                type="elem path",
                stroke=self.elements.default_stroke,
                stroke_width=self.elements.default_strokewidth,
                label=label,
            )
            self.elements.validate_ids()
            # A drawn shape lands in a layer, and a pen path is a drawn shape. It did not:
            # measured, a pen path came back with `operation_ids []` and the "no layer"
            # stroke #e5484d, so it drew itself grey-dotted on the bed and burned nothing.
            # Inside the same undoscope, for the same reason as in `create`: laying down a
            # shape is one step, so one undo.
            self._single_layer(node)
        self.elements.set_emphasis([node])
        self._refresh()
        return {"ids": [node.id], "type": node.type}

    def create(self, kind: str, **fields) -> dict:
        if kind not in SHAPES:
            raise DesignError(
                f"Unknown shape: {kind}. Choose from {', '.join(sorted(SHAPES))}."
            )
        values = {}
        for name in SHAPES[kind]:
            positive = name.startswith(("width", "height", "r", "rx", "ry"))
            values[name] = (
                _positive(fields.get(name), name)
                if positive
                else _finite(fields.get(name), name)
            )

        before = {id(n) for n in self.elements.elems()}
        before_ops = {id(o) for o in self.elements.ops()}
        # Drawing *and* putting it in a layer within the same action: laying down a
        # shape is one step, so one undo. If finding the layer fell outside it, the first
        # `undo` would only remove that layer and the shape would stay.
        with self.elements.undoscope(f"Draw {kind}"):
            self.runner.run(self._command(kind, values, fields))
            created = [n for n in self.elements.elems() if id(n) not in before]
            if created:
                self.elements.validate_ids()
                for node in created:
                    self._single_layer(node)
                self._seed_from_memory(before_ops)
        if not created:
            raise DesignError("The engine drew nothing.")

        self.elements.set_emphasis(created)
        self._refresh()
        return {"ids": [n.id for n in created], "type": created[0].type}

    def _single_layer(self, node) -> None:
        """
        A fresh shape should land in one layer, not in two — and never in a test board's
        layer.

        The engine's classification looks at the stroke colour, and several operations can
        claim the same colour. Then the same rectangle is in a cut *and* an engrave layer,
        and burns twice — the second time often at 100%. Exactly the trap that caught the
        test grid earlier. Putting an element in several layers stays possible, but then
        because somebody chooses it.

        A test board's layers do not count as candidates. The label layer carries the
        engine's default colour (#0000ff) and is *not* in the palette strip under the
        canvas, so a shape that lands in it is work that disappears: invisible in the
        strip, and burned at 80 mm/s @ 30% because that is a caption's setting. Measured:
        in a document where the user had thrown their own layers away, *every* new shape
        fell into "Grid labels".
        """
        references = [
            reference
            for reference in list(getattr(node, "_references", []))
            if reference.parent is not None
        ]
        own = [r for r in references if not self._is_board_layer(r.parent)]
        # Only board layers? Then this shape does not belong there anyway, and there is
        # no alternative among the references either: strip them all, and through its own
        # stroke colour the shape gets a real layer.
        keep = own[:1]
        for extra in references:
            if extra not in keep:
                extra.remove_node()
        if not keep:
            self._own_layer(node)

    def _own_layer(self, node) -> None:
        """Give a shape without a layer one, on its own stroke colour."""
        colour = normalise(str(getattr(node, "stroke", "") or "")[:7])
        if colour is None:
            return
        try:
            # The same memory as with the palette swatch (decision B2): a fresh layer
            # starts at what this colour did on this machine before.
            remembered = None
            try:
                remembered = self.color_memory(colour)
            except Exception:
                pass
            layer = self.layer_for_color(colour, remembered)
        except DesignError:
            return
        self._operation(layer["id"]).add_reference(node)

    def _is_board_layer(self, operation) -> bool:
        """
        A layer that belongs to a test board rather than to the user.

        Two kinds: the cells (each with its own sweep setting) and the shared label layer
        that all the boards' captions go into.
        """
        if operation is None:
            return False
        if getattr(operation, "label", None) == LABEL_LAYER:
            return True
        return self._is_grid_cell(operation, getattr(operation, "id", "") or "")

    def _command(self, kind: str, v: dict, fields: dict) -> str:
        if kind == "rect":
            row = (
                f"rect {_mm(v['x_mm'])} {_mm(v['y_mm'])} "
                f"{_mm(v['width_mm'])} {_mm(v['height_mm'])}"
            )
            # Rounded corners while drawing: the command has `-x`/`-y` for it, and the
            # engine does the rest. One number, because a corner with two different radii
            # is a designer's thing nobody asks for at a machine.
            radius = fields.get("corner_radius_mm")
            if radius not in (None, ""):
                size = _positive(radius, "corner_radius_mm")
                half = min(v["width_mm"], v["height_mm"]) / 2
                if size > half:
                    raise DesignError(
                        f"A corner radius of {size:g} mm does not fit in a rectangle "
                        f"of {v['width_mm']:g}×{v['height_mm']:g} mm. At most "
                        f"{half:g} mm.",
                        code="draw.radiusTooBig",
                    )
                row += f" -x {_mm(size)} -y {_mm(size)}"
            return row
        if kind == "circle":
            return f"circle {_mm(v['cx_mm'])} {_mm(v['cy_mm'])} {_mm(v['r_mm'])}"
        if kind == "ellipse":
            return f"ellipse {_mm(v['cx_mm'])} {_mm(v['cy_mm'])} {_mm(v['rx_mm'])} {_mm(v['ry_mm'])}"
        if kind == "line":
            return f"line {_mm(v['x1_mm'])} {_mm(v['y1_mm'])} {_mm(v['x2_mm'])} {_mm(v['y2_mm'])}"
        text = str(fields.get("text") or "").strip()
        if not text:
            raise DesignError("Text cannot be empty.", code="draw.emptyText")
        if '"' in text:
            raise DesignError(
                "Quotation marks in text are not supported yet.",
                code="draw.quotesInText",
            )
        # linetext, not text: bitmap text has no geometry and is therefore invisible on
        # the canvas and cannot be positioned.
        parts = ["linetext", _mm(v["x_mm"]), _mm(v["y_mm"])]
        font = str(fields.get("font") or "").strip()
        if font:
            if '"' in font:
                raise DesignError("Ongeldige fontnaam.")
            parts += ["-f", f'"{font}"']
        size = fields.get("font_size_mm")
        if size is not None:
            parts += ["-s", _mm(_positive(size, "font_size_mm"))]
        spacing = fields.get("spacing")
        if spacing is not None:
            parts += ["-g", f"{_positive(spacing, 'spacing'):g}"]
        parts.append(f'"{text}"')
        return " ".join(parts)

    ALIGNMENTS = ("start", "middle", "end")

    def update_text(self, element_id: str, **fields) -> dict:
        """
        Updating existing vector text: contents, font, height,
        spatiëring of alignment.

        The engine keeps the source on the node and re-renders, so text does not have to
        be deleted and placed again.
        """
        from meerk40t.core.units import UNITS_PER_MM

        node = self._nodes([element_id])[0]
        if getattr(node, "mktext", None) is None:
            raise DesignError(
                "This element is not editable text.", code="draw.notText"
            )
        registry = getattr(self.kernel.root, "fonts", None)
        if registry is None:
            raise DesignError("No font support available.", code="draw.noFonts")

        text = node.mktext
        with self.elements.undoscope("Change text"):
            if fields.get("text") is not None:
                new = str(fields["text"]).strip()
                if not new:
                    raise DesignError("Text cannot be empty.", code="draw.emptyText")
                text = new
            if fields.get("font"):
                node.mkfont = str(fields["font"])
            if fields.get("font_size_mm") is not None:
                node.mkfontsize = _positive(fields["font_size_mm"], "font_size_mm") * UNITS_PER_MM
            if fields.get("spacing") is not None:
                node.mkfontspacing = _positive(fields["spacing"], "spacing")
            if fields.get("align") is not None:
                align = str(fields["align"])
                if align not in self.ALIGNMENTS:
                    raise DesignError(
                        f"Alignment has to be one of {', '.join(self.ALIGNMENTS)}."
                    )
                node.mkalign = align
            registry.update_linetext(node, text)
        self.elements.validate_ids()
        self._refresh()
        return {"id": node.id, "text": node.mktext}

    #: The default bridge: four of two millimetres.
    #:
    #: Two millimetres is the engine's own default length (`mktablength` starts at
    #: `2 * 65535 / 2.54 / 10` = 5160.236 units, which is 2.000 mm), and four is what the
    #: right-click row puts on in one go — one per side of a rectangle, so a cut part hangs
    #: in the sheet on four corners instead of tipping on one.
    DEFAULT_COUNT = 4
    DEFAULT_LENGTH_MM = 2.0

    def set_bridges(
        self, element_ids, count=None, length_mm=None, positions_percent=None
    ) -> dict:
        """
        Leave gaps in the cut so the part stays in the sheet.

        Either a count — then they are spread evenly and stay spread when the shape is
        resized — or an explicit list of percentages along the path. The length is one
        bridge, in millimetres; the engine keeps it in its own units.

        Each of the three is optional and what is left out stays as it is. That is what makes
        the panel's two fields independent: typing a length must not silently reset the count
        to four. Measured before this: with six bridges on the shape, changing the length to
        30 mm was refused with "4 bridges of 30 mm" — a sentence about a number the user had
        not asked for.

        The refusals are ours, because the engine has none worth the name. It checks only
        `len(positions) * tablen < total_length` and says nothing either way: measured on a
        200 mm perimeter, four bridges of 49.9 mm pass that check and leave 0.15 mm of cut
        in the whole contour, and `"*100"` of 2 mm fails it and hands back an *empty*
        geometry — no cut at all, no message.
        """
        from meerk40t.core.units import UNITS_PER_MM

        from .bridges import (
            MAX_COUNT,
            MAX_FRACTION,
            TAB_TYPES,
            format_positions,
            parse_positions,
            path_length,
        )

        if length_mm is not None:
            length = _finite(length_mm, "length_mm")
            if length <= 0:
                raise DesignError(
                    "A bridge needs a length greater than zero.", code="bridges.needsLength"
                )
        else:
            length = None

        if positions_percent is not None:
            if not isinstance(positions_percent, (list, tuple)) or not positions_percent:
                raise DesignError(
                    "Name at least one place for a bridge, or ask for a number of them.",
                    code="bridges.needsCount",
                )
            spots = [_finite(value, "positions_percent") for value in positions_percent]
            for value in spots:
                if not 0 <= value <= 100:
                    raise DesignError(
                        "A bridge sits somewhere between 0 and 100 percent along the path.",
                        code="bridges.percentRange",
                    )
            if len(spots) > MAX_COUNT:
                raise DesignError(
                    f"More than {MAX_COUNT} bridges in one contour is not a cut any more.",
                    code="bridges.tooMany",
                    values={"max": MAX_COUNT},
                )
            text = format_positions(None, spots)
        elif count is not None:
            wanted = int(_finite(count, "count"))
            if wanted <= 0:
                raise DesignError(
                    "Ask for at least one bridge, or clear them instead.",
                    code="bridges.needsCount",
                )
            if wanted > MAX_COUNT:
                raise DesignError(
                    f"More than {MAX_COUNT} bridges in one contour is not a cut any more.",
                    code="bridges.tooMany",
                    values={"max": MAX_COUNT},
                )
            spots = None
            text = format_positions(wanted, None)
        else:
            # Neither: only the length changes, and every shape keeps the bridges it has.
            spots = None
            text = None

        nodes = self._nodes(element_ids)
        targets = [node for node in nodes if node.type in TAB_TYPES]
        skipped = len(nodes) - len(targets)
        if not targets:
            raise DesignError(
                "Bridges only work on a rectangle, an ellipse, a polyline or a path.",
                code="bridges.notSupported",
            )

        # What each shape ends up with, worked out per shape: leaving a field out means
        # keeping what is there, and two shapes can hold different bridges.
        plan = []
        for node in targets:
            final_text = text if text is not None else (getattr(node, "mktabpositions", "") or "")
            if not final_text:
                final_text = format_positions(self.DEFAULT_COUNT, None)
            final_length = length
            if final_length is None:
                try:
                    final_length = float(getattr(node, "mktablength", 0) or 0) / UNITS_PER_MM
                except (TypeError, ValueError):
                    final_length = 0.0
                if final_length <= 0:
                    final_length = self.DEFAULT_LENGTH_MM
            number = len(parse_positions(final_text))
            if not number:
                # The stored string says nothing readable — an old project, or a hand-edited
                # SVG. Then there is nothing to keep, so the default lands rather than a
                # write that would leave the shape with no bridges and no message.
                final_text = format_positions(self.DEFAULT_COUNT, None)
                number = self.DEFAULT_COUNT
            plan.append((node, final_text, final_length, number))

        # Per shape, because the bound is the shape's own contour: a 2 mm bridge is nothing
        # on a 200 mm perimeter and everything on a 10 mm one. Refusing here rather than
        # skipping the shape: whoever asks for bridges and gets none on one shape of twenty
        # would find that out on the material.
        #
        # And every shape is measured before the refusal, not just up to the first that
        # fails. Measured before this with three rectangles selected (contours 200, 200 and
        # 12 mm): the sentence named "a contour that is 12.0 mm long" and nothing else, so
        # on a nested sheet of forty parts the offending one could not be found.
        too_tight = []
        for node, _final_text, final_length, number in plan:
            total = path_length(node.as_geometry()) / UNITS_PER_MM
            if number * final_length > total * MAX_FRACTION:
                too_tight.append((node, final_length, number, total))
        if too_tight:
            node, final_length, number, total = min(too_tight, key=lambda row: row[3])
            fine = len(plan) - len(too_tight)
            where = _shape_name(node)
            tally = (
                ""
                if len(plan) == 1
                else f" {fine} of the {len(plan)} shapes would have been fine."
            )
            raise DesignError(
                f"{number} bridges of {final_length:g} mm take "
                f"{number * final_length:g} mm of the contour of {where}, and that "
                f"contour is {total:.1f} mm long; at most half of it may be bridge."
                f"{tally} Use fewer or shorter bridges."
            )

        with self.elements.undoscope("Bridges"):
            for node, final_text, final_length, _number in plan:
                node.mktablength = final_length * UNITS_PER_MM
                node.mktabpositions = final_text
                # A raw assignment reports nothing to the node, so the cached bounds and the
                # scene would keep the version without gaps.
                node.altered()
        self._refresh()
        return {
            "ids": [node.id for node, *_ in plan],
            "bridged": len(plan),
            "skipped": skipped,
            # The count and the length as they now stand on the first shape: with a mixed
            # selection the rest can differ, and the notice says how many shapes it was.
            "count": plan[0][3],
            "length_mm": plan[0][2],
            "positions_percent": spots,
        }

    def clear_bridges(self, element_ids) -> dict:
        """
        Take the bridges away — the cut closes again.

        An empty position string is the engine's own off state: `final_geometry` applies
        tabs only `if tablen and numtabs`. The length stays on the node, so switching them
        back on offers the length that was there.
        """
        from .bridges import TAB_TYPES

        nodes = self._nodes(element_ids)
        targets = [
            node
            for node in nodes
            if node.type in TAB_TYPES and getattr(node, "mktabpositions", "")
        ]
        with self.elements.undoscope("Remove bridges"):
            for node in targets:
                node.mktabpositions = ""
                node.altered()
        self._refresh()
        return {"ids": [node.id for node in targets], "cleared": len(targets)}

    def update_line(self, element_id: str, **fields) -> dict:
        """Move one end of a line, without drawing it again."""
        from meerk40t.core.units import UNITS_PER_MM

        node = self._nodes([element_id])[0]
        if node.type != "elem line":
            raise DesignError("This element is not a line.", code="draw.notALine")

        # The client gives points as they lie on the bed; the node keeps them *before*
        # its matrix. Without converting back, a rotated line would jump as soon as you
        # move an end point.
        matrix = getattr(node, "matrix", None)
        inverse = ~matrix if matrix is not None else None

        def to_raw(x_mm, y_mm):
            point = (x_mm * UNITS_PER_MM, y_mm * UNITS_PER_MM)
            if inverse is None:
                return point
            return _xy(inverse.point_in_matrix_space(point))

        current = {
            "x1_mm": float(node.x1) / UNITS_PER_MM,
            "y1_mm": float(node.y1) / UNITS_PER_MM,
            "x2_mm": float(node.x2) / UNITS_PER_MM,
            "y2_mm": float(node.y2) / UNITS_PER_MM,
        }
        if matrix is not None:
            for index, prefix in ((0, "1"), (1, "2")):
                px, py = _xy(
                    matrix.point_in_matrix_space(
                        (float(getattr(node, f"x{prefix}")), float(getattr(node, f"y{prefix}")))
                    )
                )
                current[f"x{prefix}_mm"] = px / UNITS_PER_MM
                current[f"y{prefix}_mm"] = py / UNITS_PER_MM

        wanted = dict(current)
        for name in ("x1_mm", "y1_mm", "x2_mm", "y2_mm"):
            if fields.get(name) is not None:
                wanted[name] = _finite(fields[name], name)

        with self.elements.undoscope("Adjust line"):
            node.x1, node.y1 = to_raw(wanted["x1_mm"], wanted["y1_mm"])
            node.x2, node.y2 = to_raw(wanted["x2_mm"], wanted["y2_mm"])
            node.altered()
        self._refresh()
        return {"id": element_id}

    ALIGNMENTS_2D = (
        "top", "bottom", "left", "right", "center", "centerh", "centerv",
        "spaceh", "spacev",
    )

    def align(self, element_ids, mode: str) -> dict:
        if mode not in self.ALIGNMENTS_2D:
            raise DesignError(
                f"Unknown alignment: {mode}. Choose from {', '.join(self.ALIGNMENTS_2D)}."
            )
        nodes = self._nodes(element_ids)
        if len(nodes) < 2:
            raise DesignError("Uitlijnen heeft minstens twee elementen needed.")
        self.elements.set_emphasis(nodes)
        with self.elements.undoscope("Align"):
            self.runner.run(f"align {mode}")
        self._refresh()
        return {"aligned": [n.id for n in nodes], "mode": mode}

    def group(self, element_ids) -> dict:
        nodes = self._nodes(element_ids)
        if len(nodes) < 2:
            raise DesignError("Groeperen heeft minstens twee elementen needed.")
        self.elements.set_emphasis(nodes)
        with self.elements.undoscope("Group"):
            self.runner.run("group")
        self.elements.validate_ids()
        self._refresh()
        return {"grouped": [n.id for n in nodes]}

    def ungroup(self, element_ids) -> dict:
        """
        Ungroup. The elements stay; only the wrapper disappears.
        """
        nodes = self._nodes(element_ids)
        groups = []
        for node in nodes:
            parent = getattr(node, "parent", None)
            while parent is not None and getattr(parent, "type", None) != "group":
                parent = getattr(parent, "parent", None)
            if parent is not None and parent not in groups:
                groups.append(parent)
        if not groups:
            raise DesignError(
                "This selection is not in a group.", code="draw.notInGroup"
            )
        self.elements.set_emphasis(groups)
        with self.elements.undoscope("Ungroup"):
            self.runner.run("ungroup")
        self.elements.validate_ids()
        self._refresh()
        return {"ungrouped": len(groups)}

    BOOLEAN = ("union", "difference", "intersection", "xor")

    def mirror(self, element_ids, axis: str) -> dict:
        """
        Mirroring about the centre of the selection.

        There is no `mirror` command; the engine does this with a negative scale
        factor.
        """
        if axis not in ("horizontal", "vertical"):
            raise DesignError("The mirror axis has to be 'horizontal' or 'vertical'.")
        nodes = self._nodes(element_ids)
        self.elements.set_emphasis(nodes)
        factors = "-1 1" if axis == "horizontal" else "1 -1"
        with self.elements.undoscope("Mirror"):
            self.runner.run(f"scale {factors}")
        self._refresh()
        return {"mirrored": [n.id for n in nodes], "axis": axis}

    def boolean(self, element_ids, operation: str) -> dict:
        """
        Uniting, subtracting, intersecting or excluding shapes.

        The commands come from `extra/cag.py` and work on a chain, not on their own:
        `element union` takes the emphasis selection. The result is one new path;
        de oorspronkelijke shapes verdwijnen.
        """
        if operation not in self.BOOLEAN:
            raise DesignError(
                f"Unknown operation: {operation}. Choose from {', '.join(self.BOOLEAN)}."
            )
        nodes = self._nodes(element_ids)
        if len(nodes) < 2:
            raise DesignError(f"{operation} needs at least two shapes.")
        before = {id(n) for n in self.elements.elems()}
        self.elements.set_emphasis(nodes)
        with self.elements.undoscope(operation):
            self.runner.run(f"element {operation}")
        created = [n for n in self.elements.elems() if id(n) not in before]
        if not created:
            raise DesignError(
                f"{operation} yielded nothing — do the shapes actually overlap?",
                code="draw.booleanEmpty",
            )
        self.elements.validate_ids()
        self.elements.set_emphasis(created)
        self._refresh()
        return {"ids": [n.id for n in created], "operation": operation}

    EFFECTS = {"hatch": "effect-hatch", "wobble": "effect-wobble"}

    def offset(self, element_ids, distance_mm) -> dict:
        """A parallel contour at a distance — for kerf compensation or a border."""
        distance = _finite(distance_mm, "distance_mm")
        if distance == 0:
            raise DesignError("An offset of zero yields nothing.")
        nodes = self._nodes(element_ids)
        before = {id(n) for n in self.elements.elems()}
        self.elements.set_emphasis(nodes)
        with self.elements.undoscope("Offset"):
            self.runner.run(f"offset {distance:.4f}mm")
        created = [n for n in self.elements.elems() if id(n) not in before]
        if not created:
            raise DesignError("The engine made no offset.", code="draw.noOffset")
        self.elements.validate_ids()
        self.elements.set_emphasis(created)
        self._refresh()
        return {"ids": [n.id for n in created], "distance_mm": distance}

    def corners(self, element_ids, style: str, size_mm) -> dict:
        """
        Hoeken afronden of afschuinen.

        Two routes, and which one it is the engine decides, not us:

        - **Rounding a rectangle** sets `rx`/`ry` on the node. It *stays* a rectangle:
          width and height keep working, the radius can be changed later, and the SVG
          round-trip holds. The engine already draws that.
        - **Chamfering, or rounding anything else**, becomes geometry we make, and the
          result is a path. That is one-way: a path no longer has a width and height
          field. The engine decides that an `elem rect` always ends *round*, so a
          chamfered rectangle *cannot* stay there — see the head of `corners.py`.
        """
        from meerk40t.core.geomstr import Geomstr
        from meerk40t.svgelements import Matrix

        from .corners import STYLES, CornerError, corner_geometry

        if style not in STYLES:
            raise DesignError(
                f"Onbekende hoekstijl: {style}. Kies 'round' of 'chamfer'."
            )
        size = _positive(size_mm, "size_mm")
        nodes = self._nodes(element_ids)
        units = self._units_per_mm()

        afgerond, paths, skipped = [], [], 0
        with self.elements.undoscope("Corners"):
            for node in nodes:
                if style == "round" and str(getattr(node, "type", "")) == "elem rect":
                    node.rx = node.ry = size * units
                    # A raw assignment reports nothing to the node, so it would
                    # otherwise carry its old bounding box — the same pitfall as with
                    # `grid`/`radial` (see CLAUDE.md).
                    vergeet = getattr(node, "set_dirty_bounds", None)
                    if vergeet is not None:
                        vergeet()
                    node.altered()
                    afgerond.append(node.id)
                    continue
                geom = node.as_geometry()
                try:
                    fresh, _gewijzigd, missed = corner_geometry(
                        geom, size * units, style
                    )
                except CornerError as e:
                    raise DesignError(str(e), code=getattr(e, "code", None)) from e
                skipped += missed
                # `replace_node` hands back the *new* node; the old one is disconnected
                # after that and its id says nothing any more.
                paths.append(
                    node.replace_node(
                        type="elem path",
                        geometry=fresh,
                        matrix=Matrix(),
                        stroke=getattr(node, "stroke", None),
                        fill=getattr(node, "fill", None),
                    )
                )

        self.elements.validate_ids()
        self._refresh()
        return {
            "rounded": afgerond,
            "paths": [n.id for n in paths],
            "skipped": skipped,
            "style": style,
            "size_mm": size,
        }

    def simplify(self, element_ids) -> dict:
        """Fewer nodes, same shape — saves time on complicated paths."""
        nodes = self._nodes(element_ids)
        self.elements.set_emphasis(nodes)
        with self.elements.undoscope("Simplify"):
            self.runner.run("simplify")
        self._refresh()
        return {"simplified": [n.id for n in nodes]}

    def add_effect(self, element_ids, effect: str) -> dict:
        """
        Vulling (hatch) of wobble op de selectie.

        In MeerK40t an effect is not an element property but a node in the operation tree
        that refers to the elements, so it appears as a layer of its own.
        """
        command = self.EFFECTS.get(effect)
        if command is None:
            raise DesignError(
                f"Unknown effect: {effect}. Choose from {', '.join(sorted(self.EFFECTS))}."
            )
        nodes = self._nodes(element_ids)
        self.elements.set_emphasis(nodes)
        with self.elements.undoscope(f"Add {effect}"):
            self.runner.run(command)
        self.elements.validate_ids()
        self._refresh()
        return {"effect": effect, "ids": [n.id for n in nodes]}

    def delete(self, element_ids) -> dict:
        nodes = self._nodes(element_ids)
        self.elements.set_emphasis(nodes)
        with self.elements.undoscope("Delete"):
            # `delete` on its own does not exist on the base context; `element delete`
            # works on the emphasis selection.
            self.runner.run("element delete")
        self._refresh()
        return {"removed": [n.id for n in nodes]}

    def duplicate(self, element_ids) -> dict:
        nodes = self._nodes(element_ids)
        before = {id(n) for n in self.elements.elems()}
        self.elements.set_emphasis(nodes)
        with self.elements.undoscope("Duplicate"):
            self.runner.run("copy")
        created = [n for n in self.elements.elems() if id(n) not in before]
        if not created:
            raise DesignError("The engine duplicated nothing.")
        self.elements.validate_ids()
        self.elements.set_emphasis(created)
        self._refresh()
        return {"ids": [n.id for n in created]}

    # ----------------------------------------------------------------- klembord
    #
    # The engine has a complete clipboard (`core/elements/clipboard.py`:
    # `clipboard copy | cut | paste | clear`). We only set the emphasis and read the state
    # back, so that the engine's clipboard stays the only truth — even when somebody is at
    # it through the console at the same time.
    #
    # One thing we do catch: `clipboard paste` puts more than one shape into a new group
    # ("Group", id "Copy"). A paste that silently groups is a surprise you only notice
    # when you want to drag one shape and three come along. If we asked for that group
    # ourselves, we take it off again. Anybody who copied a *real* group pastes one node
    # and keeps their group — the engine only wraps for more than one.

    def _clipboard_nodes(self) -> list:
        buffer = getattr(self.elements, "_clipboard", None) or {}
        key = getattr(self.elements, "_clipboard_default", "0")
        return list(buffer.get(key) or [])

    def _clipboard_bounds(self):
        from meerk40t.core.units import UNITS_PER_MM

        vakken = [n.bounds for n in self._clipboard_nodes() if getattr(n, "bounds", None)]
        if not vakken:
            return None
        x0 = min(v[0] for v in vakken) / UNITS_PER_MM
        y0 = min(v[1] for v in vakken) / UNITS_PER_MM
        x1 = max(v[2] for v in vakken) / UNITS_PER_MM
        y1 = max(v[3] for v in vakken) / UNITS_PER_MM
        return {
            "x_mm": x0,
            "y_mm": y0,
            "width_mm": max(0.0, x1 - x0),
            "height_mm": max(0.0, y1 - y0),
        }

    def clipboard_state(self) -> dict:
        return {"count": len(self._clipboard_nodes()), "bounds": self._clipboard_bounds()}

    def _whole_group(self, nodes) -> bool:
        """
        Is this exactly one complete group?

        That decides whether the wrapper the engine makes on pasting may stay. Whoever
        copies a group expects a group back; whoever copies three separate shapes expects
        three separate shapes.
        """
        ouders = {getattr(n, "parent", None) for n in nodes}
        if len(ouders) != 1:
            return False
        ouder = ouders.pop()
        if ouder is None or getattr(ouder, "type", None) != "group":
            return False
        return len(list(ouder.children)) == len(nodes)

    def clipboard_copy(self, element_ids) -> dict:
        nodes = self._nodes(element_ids)
        self._clipboard_group = self._whole_group(nodes)
        self.elements.set_emphasis(nodes)
        self.runner.run("clipboard copy")
        return self.clipboard_state()

    def clipboard_cut(self, element_ids) -> dict:
        nodes = self._nodes(element_ids)
        self._clipboard_group = self._whole_group(nodes)
        self.elements.set_emphasis(nodes)
        # The engine puts an undo scope around the deletion itself.
        self.runner.run("clipboard cut")
        self._refresh()
        return self.clipboard_state()

    def clipboard_paste(self, x_mm=None, y_mm=None, offset_mm: float = 5.0) -> dict:
        """
        Pasting, with or without a target place.

        Without `x_mm`/`y_mm` the work comes to lie `offset_mm` beside the original:
        pasting exactly on top looks like "nothing happened", and then you
        accidentally drag the original away. With a target place that is the top-left
        corner of what gets pasted — which is what "paste here" in a context menu
        promises.
        """
        count = len(self._clipboard_nodes())
        if not count:
            raise DesignError("The clipboard is empty.")
        box = self._clipboard_bounds()
        if x_mm is not None and y_mm is not None and box is not None:
            dx = _finite(x_mm, "x_mm") - box["x_mm"]
            dy = _finite(y_mm, "y_mm") - box["y_mm"]
        else:
            dx = dy = float(offset_mm)

        before = {id(n) for n in self.elements.elems()}
        groepen_voor = {id(n) for n in self._alle_groepen()}
        self.runner.run(f"clipboard paste -x {_mm(dx)} -y {_mm(dy)}")
        pasted = [n for n in self.elements.elems() if id(n) not in before]
        if not pasted:
            raise DesignError("The engine pasted nothing.")

        # The same trap as with `grid`/`radial`: `clipboard paste` shifts its copies with
        # a raw `node.matrix *= matrix`, and that assignment reports nothing to the node.
        # So the bounding box stayed in the original's place while the shape was drawn
        # elsewhere — you click the copy and the handles appear around the original. See
        # the upstream list in CLAUDE.md.
        for node in pasted:
            marker = getattr(node, "set_dirty_bounds", None)
            if marker is not None:
                marker()

        # Remove the wrapping group the engine put around it — with the engine's own
        # `ungroup`, so that the tree is rebuilt the same way as when the user does it
        # themselves. Unless a whole group was copied: then that wrapper is exactly what
        # you wanted back.
        if count > 1 and not getattr(self, "_clipboard_group", False):
            wikkels = [
                n
                for n in self._alle_groepen()
                if id(n) not in groepen_voor and getattr(n, "id", None) == "Copy"
            ]
            if wikkels:
                self.elements.set_emphasis(wikkels)
                self.runner.run("ungroup")

        self.elements.validate_ids()
        self.elements.set_emphasis(pasted)
        self._refresh()
        return {"ids": [n.id for n in pasted], "count": len(pasted)}

    def _alle_groepen(self) -> list:
        return [n for n in self.elements.elem_branch.flat() if n.type == "group"]

    def _nodes(self, element_ids):
        from .edits import _ids

        nodes = []
        for node_id in _ids(element_ids):
            node = self.elements.find_node(node_id)
            if node is None:
                raise DesignError(f"Element {node_id} does not exist (any more).")
            nodes.append(node)
        return nodes

    # ------------------------------------------------------------- operations

    # A layer without a name got a label from the engine like
    # "Cut defaultmm/s @default #ff0000" — machine language in the place where you have to
    # recognise your own work.
    LAYER_NAMES = {
        "cut": "Cut",
        "engrave": "Engrave",
        "raster": "Raster",
        "image": "Image",
        "dots": "Dots",
    }

    def create_operation(self, kind: str, label=None, speed=None, power_percent=None) -> dict:
        command = OPERATIONS.get(kind)
        if command is None:
            raise DesignError(
                f"Unknown layer type: {kind}. Choose from {', '.join(sorted(OPERATIONS))}."
            )
        parts = [command]
        if speed is not None:
            parts += ["-s", f"{_positive(speed, 'speed'):g}"]
        if power_percent is not None:
            percent = _finite(power_percent, "power_percent")
            if not 0 < percent <= 100:
                raise DesignError("power_percent has to be between 0 and 100.")
            # The console expects the engine's 0-1000 scale.
            parts += ["-p", f"{percent * 10:g}"]

        before = {id(o) for o in self.elements.ops()}
        with self.elements.undoscope("Add layer"):
            self._ensure_colors()
            self.runner.run(" ".join(parts))
        created = [o for o in self.elements.ops() if id(o) not in before]
        if not created:
            raise DesignError("The engine created no layer.", code="draw.noLayer")
        operation = created[0]
        # A name you recognise, instead of "Cut defaultmm/s @default".
        operation.label = str(label) if label else self.LAYER_NAMES.get(kind, kind)
        # A colour of its own from the start. The engine gives raster layers black and
        # dot layers transparent; as a layer colour those are both nothing — on the canvas
        # *and* in the list you cannot see which layer you are looking at.
        self._set_color(operation, self._next_color())
        # The engine sets passes to 0 for "not set". That reads as "cut zero times", and
        # that is the number a laser operator looks at.
        if not getattr(operation, "passes", 0):
            operation.passes = 1
        self.elements.validate_ids()
        self.user_operations.add(operation.id)
        self._refresh()
        return {"id": operation.id, "type": operation.type}

    # What you may still change about a grid layer.
    GRID_EDITABLE = {"output"}

    def move_operation(self, operation_id: str, direction=None, index=None) -> dict:
        """
        Move a layer in the burn order.

        The order of the children under `branch ops` *is* the order in which the machine
        burns — engrave before cut, otherwise you drop the workpiece out of the sheet
        before the caption is on it. Grid cells are skipped: they belong to one test board
        and have no order of their own among themselves.

        Two ways, one route: `direction` is one step (the ↑/↓ buttons), `index` is a
        destination (dragging, gap L1). When dragging, the list knows exactly where the
        layer has to go and not how many steps that is — converting that into steps would
        go wrong at every intervening grid cell.
        """
        if (direction is None) == (index is None):
            raise DesignError("Give one of the two: 'direction' or 'index'.")
        if direction is not None and direction not in ("up", "down"):
            raise DesignError("direction has to be 'up' or 'down'.")
        operation = self._operation(operation_id)
        parent = operation.parent
        if parent is None:
            raise DesignError("This layer is not in the operations tree.")

        siblings = list(parent.children)
        try:
            here = siblings.index(operation)
        except ValueError:  # pragma: no cover - the tree is already inconsistent then
            raise DesignError("This layer is not in its own branch.")

        # The list counts in layers, we count in children of `branch ops`. To the user
        # "place 3" is the third *layer*, not the third node; with a test grid or an empty
        # default layer in between that is not the same number. Both ways therefore
        # compute in this list.
        plain = [node for node in siblings if self._plain_layer(node)]

        if direction is not None:
            step = -1 if direction == "up" else 1
            # One step is one visible layer further, not one node. If this stepped over
            # nodes, the layer would move past an invisible neighbour and the screen would
            # stay the same — the fault this repair fixes.
            try:
                spot = plain.index(operation)
            except ValueError:
                # Not a visible layer (a grid cell): then the old route counts.
                spot = None
            if spot is None:
                target = here + step
            else:
                buur = spot + step
                if not 0 <= buur < len(plain):
                    return {"id": operation_id, "moved": False, "index": here}
                target = siblings.index(plain[buur])
            below = direction == "down"
        else:
            try:
                wanted = int(index)
            except (TypeError, ValueError):
                raise DesignError("index has to be a whole number.")
            if not 0 <= wanted < len(plain):
                raise DesignError(
                    f"index has to be between 0 and {len(plain) - 1}."
                )
            anchor = plain[wanted]
            if anchor is operation:
                return {"id": operation_id, "moved": False, "index": here}
            target = siblings.index(anchor)
            # Moving down means: come *below* the layer that is there now. Up: above it.
            # Otherwise the layer keeps landing one place beside it and while dragging the
            # list runs a place behind.
            below = target > here
        if not 0 <= target < len(siblings):
            return {"id": operation_id, "moved": False, "index": here}

        with self.elements.undoscope("Reorder layers"):
            # `swap_node` looks like the right move here but *also* swaps both nodes'
            # children, so the references to the shapes move along and on balance nothing
            # changes. `insert_sibling` moves only the node itself — which is what "move a
            # layer up" means.
            siblings[target].insert_sibling(operation, below=below)
        self._refresh()
        return {"id": operation_id, "moved": True, "index": target}

    # How the machine should work: first what touches the surface, then what goes
    # through it. Cutting last, because a cut-out workpiece lies loose in the bed and
    # shifts under the next operation — or falls out.
    BURN_ORDER = {
        "op image": 0,
        "op raster": 1,
        "op engrave": 2,
        "op dots": 3,
        "op cut": 4,
    }

    def _plain_layer(self, node) -> bool:
        """
        A layer as the user sees it.

        Three requirements, and the third is the one that was missing. It has to be an
        operation, it must not be a cell of a test grid, *and* it has to be on screen: **a
        fresh tree contains well over two hundred empty default layers** the engine keeps
        in reserve, and `DesignReader` leaves those out — an operation without shapes is
        not a layer, unless the user has just created it themselves (`user_operations`).

        Without that third requirement the moving computed in a list of two hundred while
        the panel showed two. What you see then: pressing "burn later" moves the layer
        neatly one place — past an invisible default layer. The API reports `moved: true`,
        the order on screen does not change, and dragging lands on a place that does not
        exist in the list you dragged from. Measured with two layers: ten empty `op cut`
        layers in between, every press of the button a feint.
        """
        if not str(getattr(node, "type", "")).startswith("op "):
            return False
        if self._is_grid_cell(node, getattr(node, "id", "") or ""):
            return False
        # The same rule as in `DesignReader.snapshot`: shapes in it, or just created by
        # the user. If those two drift apart, the moving goes wrong again on layers nobody
        # sees.
        if getattr(node, "children", None):
            return True
        return (getattr(node, "id", "") or "") in self.user_operations

    def sort_operations(self) -> dict:
        """
        Engrave before cut, in one action (gap L2).

        LightBurn has `Sort Cuts Last` for this, and that is one click for the most
        expensive mistake there is: the workpiece falls out of the sheet before the caption
        is on it. A stable sort, so that two cut layers keep their order relative to each
        other — the user chose that themselves.

        Within the same kind the strength counts too (gap L7). Two cut layers are not
        interchangeable: a light score line at 5% and a through-cut at 80% belong in that
        order, because as soon as the workpiece is loose it no longer lies still for the
        rest. LightBurn sorts on that too, only the other way round — their strongest goes
        first and then the Line layers to the back; we keep one rule that does the same
        thing for every kind.

        Grid cells stay where they are: their order *is* the sweep.
        """
        parent = self.elements.op_branch
        children = list(parent.children)
        layers = [node for node in children if self._plain_layer(node)]
        if len(layers) < 2:
            return {"sorted": False, "order": [node.id for node in layers]}

        wanted = sorted(
            layers,
            key=lambda node: (
                self.BURN_ORDER.get(str(node.type), 99),
                self._sterkte(node),
            ),
        )
        if wanted == layers:
            return {"sorted": False, "order": [node.id for node in wanted]}

        with self.elements.undoscope("Engrave before cut"):
            # The first layer stays where the first layer was; the rest queues up behind
            # it in order. That way a test grid in between keeps its own place and only
            # what we sort moves.
            previous = wanted[0]
            for node in wanted[1:]:
                previous.insert_sibling(node, below=True)
                previous = node
        self._refresh()
        return {"sorted": True, "order": [node.id for node in wanted]}

    def _sterkte(self, node) -> float:
        """
        How deep this layer goes, as one number (gap L7).

        Power divided by speed times the number of passes: that is the energy per
        millimetre, and it is exactly the quantity a laser operator goes by when they say
        "heavier". It is a ranking, not physics — it only has to tell two layers of the
        same kind apart.

        A layer without a speed or a power gets 0 and therefore stays at the front;
        sorted() is stable, so among themselves those keep their order.
        """
        power = _number(getattr(node, "power", None)) or 0.0
        speed = _number(getattr(node, "speed", None)) or 0.0
        passes = float(_passes_of(node))
        if speed <= 0 or power <= 0:
            return 0.0
        return (power / speed) * max(passes, 1.0)

    # Settings a layer keeps when it changes kind. Deliberately not `dpi`/`overscan`:
    # those belong to rastering and are pointless on a cut layer — the engine gives the
    # new layer its own default for those.
    TYPE_KEEP = ("label", "speed", "power", "passes", "output", "coolant")

    def change_operation_type(self, operation_id: str, kind: str) -> dict:
        """
        Turning a cut layer into an engrave layer, with the shapes in it (gap L3).

        The engine knows no "change the type of this operation": the type is in the node's
        class. What *is* possible is making a new operation, moving the references and
        removing the old one — exactly what you would do by hand, but without losing the
        assignments. All within one undo scope, so one undo puts it back.
        """
        if kind not in OPERATIONS:
            raise DesignError(
                f"Unknown layer type: {kind}. Choose from {', '.join(sorted(OPERATIONS))}."
            )
        old = self._operation(operation_id)
        if self._is_grid_cell(old, operation_id):
            raise DesignError(
                "This is a cell of a test grid; the kind of operation is the test.",
                code="layer.gridCell",
            )
        if str(old.type) == f"op {kind}" or (
            kind == "image" and str(old.type) == "op image"
        ):
            return {"id": operation_id, "type": old.type, "changed": False}

        parent = old.parent
        siblings = list(parent.children)
        here = siblings.index(old)
        colour = self._usable_color(old)
        kept = {
            name: getattr(old, name, None)
            for name in self.TYPE_KEEP
            if getattr(old, name, None) is not None
        }
        # A layer still called "Cut" because it was born that way should be called
        # "Engrave" after the conversion — otherwise there is a cut layer in the list that
        # engraves. A name the user gave *themselves* stays: that says what the layer is
        # for and not what it does.
        default = {f"op {k}": v for k, v in self.LAYER_NAMES.items()}
        if kept.get("label") == default.get(str(old.type)):
            kept["label"] = self.LAYER_NAMES.get(kind, kind)
        shapes = [
            reference.node
            for reference in list(old.children)
            if getattr(reference, "node", None) is not None
        ]

        with self.elements.undoscope("Change layer type"):
            before = {id(o) for o in self.elements.ops()}
            self.runner.run(OPERATIONS[kind])
            created = [o for o in self.elements.ops() if id(o) not in before]
            if not created:
                raise DesignError("The engine created no layer.", code="draw.noLayer")
            fresh = created[0]
            for name, value in kept.items():
                setattr(fresh, name, value)
            if colour:
                self._set_color(fresh, colour)
            for node in shapes:
                fresh.add_reference(node)
            # In the old one's place: the burn order is the reason the list has an order,
            # and that must not jump because you adjust the kind.
            old.insert_sibling(fresh, below=False)
            old.remove_node()

        self.elements.validate_ids()
        self.user_operations.discard(operation_id)
        self.user_operations.add(fresh.id)
        self._refresh()
        return {
            "id": fresh.id,
            "type": fresh.type,
            "changed": True,
            "replaced": operation_id,
            "index": here,
            "elements": len(shapes),
        }

    # ------------------------------------------------------- air assist (B11)
    #
    # The engine puts air assist per operation in `coolant`: 0 is "leave it", 1 is on,
    # 2 is off. `cutplan` translates that into `coolant_on`/`coolant_off` — but *only* when
    # the device has claimed a method. If it has not, the engine writes a complaint on the
    # console channel and nothing else happens. A switch that silently does nothing is
    # worse than no switch, so we only show it when the driver knows it (decision B11).
    COOLANT_ON = 1
    COOLANT_OFF = 2

    # Methods that can be claimed but do nothing to the machine.
    #
    # Gap L8. The engine knows three: `gcode_m7` and `gcode_m8` (grbl-only, which really
    # switch something) and `popup` — "Warnmessage". That third sends no signal at all to
    # the laser; it calls `kernel.yesno`, and outside the wxPython GUI that is an `input()`
    # on stdin (kernel.py:4217). We run headless, so then the spooler thread sits waiting
    # for a key nobody presses — nobody is looking at that terminal, the UI is a browser —
    # or it falls over with EOFError as soon as stdin closes.
    #
    # Offering a switch that leaves the job hanging is worse than no switch. On a Ruida
    # `popup` is the only claimable method (the other two carry `constraints="grbl"`), and
    # so air assist is not something we can promise there. See the finding at L8.
    LOZE_COOLANTS = {"popup"}

    def air_assist_supported(self) -> bool:
        """Does the active machine have a command that really switches the blower?"""
        coolant = getattr(getattr(self.kernel, "root", None), "coolant", None)
        device = getattr(self.kernel, "device", None)
        if coolant is None or device is None:
            return False
        try:
            if coolant.get_device_function(device) is None:
                return False
            chosen = coolant.get_device_coolant(device) or {}
            return str(chosen.get("id", "")) not in self.LOZE_COOLANTS
        except Exception:  # pragma: no cover - a driver that does not co-operate
            return False

    # Dropping more than 20 mm between two passes is no longer a cutting pass but a
    # mistyped number, and a Z axis that runs that far knocks against the head.
    Z_STEP_LIMIT_MM = 20.0

    def z_step_supported(self) -> bool:
        """
        Can this machine move the Z axis between two passes?

        Two requirements, and both are needed. The driver has to **have** a Z axis
        (`supports_z_axis`, a setting only the GRBL device knows) and there has to be a
        `z_move` command registered that moves it. On a Ruida there is neither: that driver
        does not know the word, so this field should not be on the screen there either
        (decision B11).
        """
        device = getattr(self.kernel, "device", None)
        if device is None or not getattr(device, "supports_z_axis", False):
            return False
        # The same question the console parser asks, so the same answer.
        return bool(self.kernel.find("command", "None", "z_move$"))

    def update_operation(self, operation_id: str, **fields) -> dict:
        operation = self._operation(operation_id)
        if self._is_grid_cell(operation, operation_id):
            blocked = sorted(
                k for k, v in fields.items() if v is not None and k not in self.GRID_EDITABLE
            )
            if blocked:
                raise DesignError(
                    "This is a cell of a test grid; speed and power are fixed "
                    f"because they are the test. Only burn-along can be changed "
                    f"({', '.join(blocked)} refused).",
                    code="layer.gridCellValues",
                )
        applied = {}
        with self.elements.undoscope("Change layer"):
            if "label" in fields and fields["label"] is not None:
                operation.label = str(fields["label"])
                applied["label"] = operation.label
            if fields.get("speed") is not None:
                operation.speed = _positive(fields["speed"], "speed")
                applied["speed"] = operation.speed
            if fields.get("power_percent") is not None:
                percent = _finite(fields["power_percent"], "power_percent")
                if not 0 < percent <= 100:
                    raise DesignError("power_percent has to be between 0 and 100.")
                operation.power = percent * 10
                applied["power"] = operation.power
            if fields.get("passes") is not None:
                operation.passes_custom = True
                operation.passes = int(_positive(fields["passes"], "passes"))
                applied["passes"] = operation.passes
            if fields.get("z_step_mm") is not None:
                # Dropping per pass: in thick material you cut in layers and the focus
                # goes down with every pass. The engine does not know this — to it a pass
                # is a counter on one cutcode object, and so all the passes literally share
                # one settings dict. So we build it up in the plan (see
                # CommandRunner.start_job) and only store what the user chose here.
                step = _finite(fields["z_step_mm"], "z_step_mm")
                if step and not self.z_step_supported():
                    raise DesignError(
                        "This machine has no Z axis the driver can move, so a step "
                        "per pass would do nothing. Switch the Z axis on at the "
                        "machine, or leave this field empty.",
                        code="layer.noZAxis",
                    )
                if abs(step) > self.Z_STEP_LIMIT_MM:
                    raise DesignError(
                        f"z_step_mm has to be between -{self.Z_STEP_LIMIT_MM:g} and "
                        f"{self.Z_STEP_LIMIT_MM:g} mm."
                    )
                # 0 is "off", not "drop zero millimetres": without that difference a
                # switched-off step would still produce the split plan.
                operation.z_step_mm = step or None
                applied["z_step_mm"] = operation.z_step_mm
            if fields.get("output") is not None:
                operation.output = bool(fields["output"])
                applied["output"] = operation.output
            if fields.get("color") is not None:
                # A layer colour is identification, not a setting: it decides how the
                # shapes are drawn on the canvas and what the user recognises their layer
                # by. The engine wants a Color, not a string.
                applied["color"] = self._set_color(operation, fields["color"])
            if fields.get("dpi") is not None:
                # The line spacing of a raster engraving; too high costs hours.
                dpi = _positive(fields["dpi"], "dpi")
                if not 10 <= dpi <= 2000:
                    raise DesignError("dpi has to be between 10 and 2000.")
                operation.dpi = dpi
                applied["dpi"] = dpi
            if fields.get("overscan_mm") is not None:
                distance = _finite(fields["overscan_mm"], "overscan_mm")
                if not 0 <= distance <= 50:
                    raise DesignError("overscan_mm has to be between 0 and 50.")
                # The engine wants a length *with* a unit, not a bare number.
                operation.overscan = f"{distance}mm"
                applied["overscan"] = operation.overscan
            if fields.get("bidirectional") is not None:
                operation.bidirectional = bool(fields["bidirectional"])
                applied["bidirectional"] = operation.bidirectional
            if fields.get("air_assist") is not None:
                # Off is explicitly off (2), not "leave it" (0): a layer that burns
                # *after* a layer with air assist has to really shut the blower. With 0 it
                # stays on and the user thinks it is off because the switch says so.
                if not self.air_assist_supported():
                    raise DesignError(
                        "This machine has no command for air assist, so a switch "
                        "here would do nothing. Set up at the machine first which "
                        "method drives the blower.",
                        code="layer.noAirAssist",
                    )
                aan = bool(fields["air_assist"])
                operation.coolant = self.COOLANT_ON if aan else self.COOLANT_OFF
                applied["air_assist"] = aan
        self._refresh()
        return {"id": operation_id, "applied": applied}

    # ---------------------------------------------------------------- palet

    def layer_for_color(self, color: str, memory: dict | None = None) -> dict:
        """
        The layer with this palette colour, freshly created if need be (decision B2).

        For us colour is a layer's identity, so "the layer of red" is an unambiguous
        question: there is at most one. Test grid cells do not count — those belong to a
        test board and their values are fixed.

        A fresh layer starts at what that colour did on this machine before. That is the
        whole point of the memory: a layer that starts blank forces you to think up two
        numbers every time.
        """
        wanted = self._valid_color(color)
        self.elements.validate_ids()
        for op in self.elements.ops():
            # Only real operations: an effect carries a colour too, but it is a container
            # in the element tree and not a layer.
            if not str(op.type).startswith("op "):
                continue
            # A test board's layers do not count: the cells because their values *are*
            # the trial, the label layer because it carries the engine's blue default
            # colour and so would casually turn out to be the layer "of blue".
            if self._is_board_layer(op):
                continue
            if self._usable_color(op) == wanted:
                return {"id": op.id, "type": op.type, "created": False}

        memory = memory or {}
        kind = str(memory.get("type") or "cut")
        if kind not in OPERATIONS:
            kind = "cut"
        made = self.create_operation(
            kind,
            speed=memory.get("speed_mm_s"),
            power_percent=memory.get("power_percent"),
        )
        operation = self._operation(made["id"])
        # create_operation hands out the next free palette colour; here the colour is
        # precisely the reason the layer exists.
        self._set_color(operation, wanted)
        self._refresh()
        return {"id": operation.id, "type": operation.type, "created": True}

    def _seed_from_memory(self, before_ops: set) -> None:
        """
        Putting a layer the classification creates itself onto the memory.

        Whoever picks a palette colour and then draws has the engine make a layer — not
        us. Without this it starts at the factory setting, while the user has just chosen a
        colour they *know* what they did with. B2 promises that a fresh layer does not start
        blank; this is the other half of that promise.
        """
        for op in self.elements.ops():
            if id(op) in before_ops or not str(op.type).startswith("op "):
                continue
            colour = self._usable_color(op)
            if colour is None:
                # The classification gives such a fresh layer the drawing colour *with*
                # alpha zero ("#0090ff00"). That is the same colour and yet not a colour:
                # on the canvas the layer fell back on the first palette colour, so you
                # drew in blue and got red. Taking the alpha off is the whole repair
                # here.
                colour = normalise(str(getattr(op, "color", ""))[:7])
                if colour is None:
                    continue
                self._set_color(op, colour)
            try:
                remembered = self.color_memory(colour) or {}
            except Exception:
                continue
            if remembered.get("speed_mm_s"):
                op.speed = float(remembered["speed_mm_s"])
            if remembered.get("power_percent"):
                op.power = float(remembered["power_percent"]) * 10

    def paint(self, element_ids, color: str, memory: dict | None = None) -> dict:
        """
        Put the selection in the layer of this colour — moving, not adding.

        One click on a palette swatch, where through the layers panel it took three actions
        (tab, find the layer, "into this"). Moving and not adding, because that is what a
        user means by "make this red": a shape that is in two layers afterwards burns
        twice.

        The shape's stroke colour goes along. In MeerK40t the stroke colour *is* what the
        classification works on, so without that the shape jumps back to its old layer when
        an SVG is reloaded.
        """
        from meerk40t.svgelements import Color

        wanted = self._valid_color(color)
        nodes = self._nodes(element_ids)
        layer = self.layer_for_color(wanted, memory)
        operation = self._operation(layer["id"])

        with self.elements.undoscope("Move to layer"):
            for node in nodes:
                for reference in list(getattr(node, "_references", [])):
                    if reference.parent is not None:
                        reference.remove_node()
                operation.add_reference(node)
                if hasattr(node, "stroke"):
                    node.stroke = Color(wanted)
                    # As the engine does it itself in `element_stroke`: no altered(),
                    # because that throws the cached geometry away.
                    node.translated(0, 0)
        self.elements.signal("element_property_reload", nodes)
        self._refresh()
        return {
            "operation_id": operation.id,
            "created": layer["created"],
            "ids": [n.id for n in nodes],
        }

    def set_default_color(self, color: str) -> dict:
        """
        De colour waarin fresh work getekend wordt.

        `default_stroke` is the colour the engine gives every new shape, so this is
        exactly LightBurn's "clicking without a selection sets the colour for new work" —
        no bookkeeping of our own beside it.
        """
        from meerk40t.svgelements import Color

        wanted = self._valid_color(color)
        self.elements.default_stroke = Color(wanted)
        return {"color": wanted}

    def default_color(self) -> str | None:
        """
        The colour new work is drawn in, always a colour from the palette.

        The engine starts at `#0000ff`, and that colour is in none of the ten swatches
        under the canvas. That produced a strip in which no swatch was on while a colour
        *was* active, and — worse — the layer that turned out to be "of blue" was the test
        grid's label layer: `Grid labels`, at 80 mm/s @ 30%. The bottom edge then blithely
        reported "layer 1 · Grid labels" as the layer of your next shape.

        So we shift once to the first palette colour. Only when the engine is on a colour
        the palette does not know: if the user has chosen a swatch themselves, that choice
        stays.
        """
        try:
            colour = normalise(str(self.elements.default_stroke.hexrgb))
        except (AttributeError, TypeError, ValueError):
            colour = None
        palet = {normalise(c) for c in self.PALETTE}
        if colour is not None and colour not in palet:
            try:
                return self.set_default_color(self.PALETTE[0])["color"]
            except (AttributeError, DesignError, TypeError, ValueError):
                return colour
        return colour

    @staticmethod
    def _valid_color(color) -> str:
        wanted = normalise(color)
        if wanted is None:
            raise DesignError("color has to be a #rrggbb value.")
        return wanted

    def delete_operation(self, operation_id: str) -> dict:
        operation = self._operation(operation_id)
        with self.elements.undoscope("Remove layer"):
            # Only the operation disappears; the elements themselves stay, because they
            # can be in several layers.
            operation.remove_node()
        self.user_operations.discard(operation_id)
        self._refresh()
        return {"removed": operation_id}

    # Shapes that have an inside. A line and a point have none, and the engine would set
    # the fill but never do anything with it — a button that switches on and does
    # nothing.
    FILLABLE = ("elem rect", "elem ellipse", "elem path", "elem polyline")

    def fill(self, element_ids, filled: bool = True, color=None) -> dict:
        """
        Giving a shape a fill, or taking it off again.

        Why this is needed: our rasteriser fills what has a `fill` and only draws a line
        around what has none (`rasterizer.py`). A square you draw in OpenKerf has none, so
        in a raster layer it burned its outline. Measured on a 100×100 pixel image: 8%
        black before, over 90% after.

        Watch out when reading an estimate: the **time** does not change because of this.
        A raster layer scans the bounding box line by line, filled or not — measured on a
        30 mm square: 123.7 s in both cases. Only the outcome differs, and that is exactly
        why an empty raster layer is so easy to overlook.

        By default the colour follows the shape's own stroke. In MeerK40t the colour *is*
        what the classification works on; a fill in another colour can make the shape land
        in a different layer from its own stroke at the next classification.
        """
        nodes = self._nodes(element_ids)
        wanted = self._valid_color(color) if color is not None else None

        kan = [n for n in nodes if str(getattr(n, "type", "")) in self.FILLABLE]
        skipped = len(nodes) - len(kan)
        filled_count = 0
        cleared = 0
        with self.elements.undoscope("Fill" if filled else "Remove fill"):
            for node in kan:
                self.elements.set_emphasis([node])
                if not filled:
                    self.runner.run("fill none")
                    cleared += 1
                    continue
                colour = wanted or self._shape_color(node)
                self.runner.run(f"fill {colour}")
                filled_count += 1
        self.elements.set_emphasis(nodes)
        self._refresh()
        return {
            "ids": [n.id for n in nodes],
            "filled": filled_count,
            "cleared": cleared,
            "skipped": skipped,
        }

    def _shape_color(self, node) -> str:
        """The stroke colour of the shape, or else the colour for new work."""
        stroke = getattr(node, "stroke", None)
        hex_value = getattr(stroke, "hexrgb", None) or getattr(stroke, "hex", None)
        if hex_value:
            return str(hex_value)[:7]
        return self.default_color() or "#000000"

    def single_layer(self, element_ids, kind: str = "cut", operation_id=None) -> dict:
        """
        Everything in the selection into one layer, and into no other.

        What an import costs without this action: a drawing comes in in the layer the
        engine finds for it — for a black line that is a raster layer, because
        `classify_black_as_raster` is on — and anybody who wants to cut it first throws away
        the layers they do not want, makes a cut layer and assigns everything again.

        The detaching is the core of it, not the assigning. An element may be in several
        layers (operations hold references, not elements), so assigning alone leaves the
        shape in its old layer and burns it twice.

        This is the same move as `paint`, with a different address: `paint` asks for a
        **colour** (the strip under the canvas), this for a **kind**. That difference is the
        whole point — "this has to be cut" is what somebody means, and which swatch in the
        strip is the cut layer they do not know. The stroke colour goes along for the same
        reason as there: in MeerK40t the stroke colour is what the classification works on,
        so without it the shape jumps back to its old layer at the next classification.
        """
        from meerk40t.svgelements import Color
        nodes = self._nodes(element_ids)

        if operation_id is not None:
            target = self._operation(operation_id)
            created = False
        else:
            wanted = _OPERATION_TYPES.get(kind)
            if wanted is None:
                raise DesignError(
                    f"Unknown layer type: {kind}. Choose from {', '.join(sorted(OPERATIONS))}."
                )
            bestaand = [
                op
                for op in self.elements.ops()
                if str(op.type) == wanted and not self._is_board_layer(op)
            ]
            created = not bestaand
            target = (
                bestaand[0]
                if bestaand
                else self._operation(self.create_operation(kind)["id"])
            )

        colour = getattr(target, "color", None)
        assigned = 0
        removed = 0
        with self.elements.undoscope("Into one layer"):
            for node in nodes:
                # The node knows itself which layers it hangs in; that is shorter than
                # walking all the layers, and it is how `paint` does it too.
                for reference in list(getattr(node, "_references", [])):
                    if reference.parent is None:
                        continue
                    if reference.parent is target:
                        continue
                    reference.remove_node()
                    removed += 1
                if not any(getattr(c, "node", None) is node for c in target.children):
                    target.add_reference(node)
                    assigned += 1
                if colour is not None and hasattr(node, "stroke"):
                    node.stroke = Color(colour)
                    # As the engine does it in `element_stroke`: no altered(), because
                    # that throws the cached geometry away.
                    node.translated(0, 0)
        self.elements.signal("element_property_reload", nodes)
        self.elements.set_emphasis(nodes)
        self._refresh()
        return {
            "operation_id": target.id,
            "type": str(target.type),
            "assigned": assigned,
            "removed": removed,
            "created": created,
        }

    def prune_operations(self) -> dict:
        """
        Empty layers gone.

        An empty project has twelve of them before you have done anything — at startup
        the engine creates a raster layer, two engrave layers and nine cut layers, one per
        palette colour. Anybody classifying a drawing keeps half of those as empty rows in
        the list.

        A layer with only dead references counts as empty: after splitting a path a layer
        keeps a reference to the vanished original, and that layer means nothing any more.
        A test board's layers stay, empty as well: they belong to a board and go out as a
        whole.
        """
        levend = {id(node) for node in self.elements.elems()}

        def heeft_werk(operation) -> bool:
            return any(
                id(getattr(child, "node", None)) in levend
                for child in operation.children
                if str(getattr(child, "type", "")) == "reference"
            ) or any(
                str(getattr(child, "type", "")) != "reference"
                for child in operation.children
            )

        doomed = [
            op
            for op in self.elements.ops()
            if str(op.type).startswith("op ")
            and not self._is_board_layer(op)
            and not heeft_werk(op)
        ]
        if not doomed:
            return {"removed": 0, "ids": []}

        ids = [op.id for op in doomed]
        with self.elements.undoscope("Clear out empty layers"):
            for op in doomed:
                op.remove_node()
        for operation_id in ids:
            self.user_operations.discard(operation_id)
        self._refresh()
        return {"removed": len(ids), "ids": ids}

    def delete_all_operations(self) -> dict:
        """
        Every ordinary layer gone in one action.

        Per layer that costs three clicks (expand, delete, confirm), so anybody wanting
        to reclassify an imported SVG with ten colours clicks thirty times. Here it is once,
        with the same promise as for one layer: **the shapes stay.** Afterwards they are in
        no layer at all and the canvas draws them dotted — visible work without a
        destination, exactly what you want to see before you reclassify.

        A test grid's layers do not count: they belong to one board and go out as a whole
        ("Remove the grid from the design"). Throwing them away separately would leave half
        a test result behind — and that also held for the label layer, which *did* die
        here: every board's captions and border frame were left behind without a layer and
        so no longer burned, on a board where nothing else looked wrong.
        """
        doomed = [
            op
            for op in self.elements.ops()
            if str(op.type).startswith("op ") and not self._is_board_layer(op)
        ]
        if not doomed:
            raise DesignError("There is no layer to throw away.")
        ids = [op.id for op in doomed]
        with self.elements.undoscope("Remove all layers"):
            for op in doomed:
                op.remove_node()
        for operation_id in ids:
            self.user_operations.discard(operation_id)
        self._refresh()
        # The number of shapes with it, because that is the promise: they are still there.
        return {"removed": ids, "kept_elements": sum(1 for _ in self.elements.elems())}

    # The same ten as `--layer-1..10` in tokens.css and LAYER_COLORS in the frontend.
    # They are here a second time because a new layer has to get its colour from the
    # engine, not only from whichever panel happens to show it. In design system v3.3
    # layer 4 went from #46A758 to #0F9B32: under red-green blindness the old green could
    # not be separated from layers 9 and 10.
    PALETTE = (
        "#E5484D", "#F76B15", "#FFC53D", "#0F9B32", "#12A594",
        "#0090FF", "#8E4EC6", "#E93D82", "#8D6E63", "#607D8B",
    )

    @staticmethod
    def _usable_color(op) -> str | None:
        """
        A layer's colour, or nothing when the engine gave none.

        A cut layer gets red, but a raster layer black and a dot layer fully transparent.
        As a layer colour those last two are not a colour: invisible on the canvas and
        indistinguishable in the list.
        """
        color = getattr(op, "color", None)
        if color is None:
            return None
        if getattr(color, "alpha", 255) == 0 or getattr(color, "value", None) is None:
            return None
        text = str(getattr(color, "hexrgb", "") or "").lower()
        return None if text in ("", "#000000") else text

    def _next_color(self) -> str:
        """The first palette colour not in use yet, otherwise in order."""
        ops = list(self.elements.ops())
        used = {c for c in (self._usable_color(op) for op in ops) if c}
        for candidate in self.PALETTE:
            if candidate.lower() not in used:
                return candidate
        return self.PALETTE[len(ops) % len(self.PALETTE)]

    def _ensure_colors(self) -> None:
        """
        Give every layer without a usable colour one after all.

        Without this a new layer collides with the default layer the engine created itself:
        that one is transparent, so for it the frontend falls back on the first palette
        colour — exactly the one we have just handed out.
        """
        for op in list(self.elements.ops()):
            if self._usable_color(op) is None:
                self._set_color(op, self._next_color())

    @staticmethod
    def _set_color(operation, value) -> str:
        """Put a `#rrggbb` on the layer; we leave the alpha out, because a transparent
        layer colour is no longer a colour on the canvas."""
        from meerk40t.svgelements import Color

        text = str(value).strip()
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", text):
            raise DesignError("color has to be a #rrggbb value.")
        operation.color = Color(text)
        return text

    def _is_grid_cell(self, operation, operation_id: str) -> bool:
        """The same verification as the snapshot: id and settings both have to match."""
        cell = self.grid_operations().get(operation_id)
        if not cell:
            return False
        try:
            return (
                abs(float(operation.speed) - float(cell["speed_mm_s"])) <= 0.01
                and abs(float(operation.power) - float(cell["power_percent"]) * 10) <= 0.1
            )
        except (TypeError, ValueError):
            return False

    def _operation(self, operation_id: str):
        node = self.elements.find_node(operation_id)
        if node is None:
            raise DesignError(f"Layer {operation_id} does not exist (any more).")
        if not str(node.type).startswith(("op ", "effect ")):
            raise DesignError(f"{operation_id} is not a layer.")
        return node

    def fonts(self) -> list[dict]:
        """
        Beschikbare vectorfonts.

        The Hershey plugin registers both its own fonts and the system TTFs; names
        beginning with a dot are hidden system fonts.

        Files that no longer exist drop out. The engine keeps its list in a cache that does
        not notice a deleted file, and such a row can only fail: the picker shows it,
        fetches the file for the preview and gets a 409 back. Measured with two deleted
        fonts — two rows in the list, two failed requests, and not a word on the screen
        about what was going on.
        """
        from pathlib import Path

        registry = getattr(self.kernel.root, "fonts", None)
        if registry is None:
            return []
        found = []
        for entry in registry.available_fonts() or []:
            path = entry[0] if len(entry) > 0 else None
            display = entry[1] if len(entry) > 1 else None
            if not path or not display or str(display).startswith("."):
                continue
            # Only test absolute paths. The engine puts its own Hershey fonts in the list
            # as a bare name (`meerk40t.jhf`) and those are perfectly usable — it is even
            # the font we set the captions on a test board in.
            place = Path(str(path))
            if place.is_absolute() and not place.is_file():
                continue
            # The engine only keeps the file name on the node, so that is what we pass
            # along — otherwise the UI cannot see which font is active.
            found.append(
                {
                    "file": str(path),
                    "name": str(display),
                    "basename": str(path).rsplit("/", 1)[-1],
                }
            )
        found.sort(key=lambda f: f["name"].lower())
        return found

    def estimate(self, library=None, provenance=None, sheet=None, exact=False) -> dict:
        """
        How long this job is going to take, before you start it.

        By default computed on the geometry and the layer settings, not on the built cut
        plan. Building that plan was the reason this route cost minutes on a heavy design
        (gap J1): `plan copy` copies the cutcode once per pass, and the optimisation after
        it scales quadratically in the number of pieces. Sixty passes over two hundred
        shapes is twelve thousand objects of which we ultimately only use the total length.

        Length per shape times the number of passes, divided by the layer's speed, plus the
        jumps in between — that is exactly what `duration_cut` and `duration_travel` add up
        to, only without making the plan first. The order the optimisation chooses is not in
        it, so the travel time is an upper bound; the burn time is exactly the same sum.

        `exact=True` builds the full plan after all. Only meant for calibrating the fast
        route against the old one — not for the UI.
        """
        seconds, pieces = (
            self._plan_estimate() if exact else self._geometry_estimate()
        )
        return {
            "seconds": round(seconds, 1),
            # How many shapes get burned. Zero means the machine would do nothing, and
            # that is what the pre-flight hangs its "there is nothing to burn" on.
            "parts": pieces,
            "method": "plan" if exact else "geometry",
            # What is being burned into belongs with what is being burned: without the
            # sheet's material, "a setting for 3 mm birch" is a statement without a
            # counterpart.
            "sheet": sheet,
            "layers": self.job_layers(library, provenance, sheet),
            # What hangs off the bed or off the sheet (gap C2). Here and not only on the
            # canvas: on tablet and phone the canvas is not beside it, and this is the last
            # screen before burning.
            "bounds": self.bounds_report(sheet),
            "engine": self.engine_report(),
        }

    def engine_report(self) -> dict:
        """
        What *this* engine can do with a kind of layer.

        One thing for now: rastering. Without the rasteriser a raster layer comes out of
        the machine blank (see `raster_supported`), and that must not be a surprise you only
        discover *after* burning.
        """
        from .testgrid import raster_supported

        return {"raster": raster_supported(self.kernel)}

    # Half a millimetre of tolerance. Lying exactly on the edge is not a mistake — that
    # is a shape filling the sheet — and measurement noise in the bounding box must not
    # produce a red outline on work that simply fits.
    EDGE_SLACK = 0.5

    def bed_mm(self) -> tuple[float, float] | None:
        """The bed size of the active machine in millimetres."""
        device = getattr(self.kernel, "device", None)
        view = getattr(device, "view", None)
        try:
            from meerk40t.core.units import Length

            return (
                float(Length(view.width).mm),
                float(Length(view.height).mm),
            )
        except Exception:
            return None

    # ----------------------------------------------- user origin (J12)

    @contextmanager
    def shifted(self, origin):
        """
        Putting the whole design aside for a moment, while it goes into the machine.

        This is the whole working of the zero point (gap J12): what you draw at 0,0 burns
        at the zero point, and everything you drew around it moves along. The drawing
        itself does not change — afterwards every shape is back at the coordinates that
        were in the panel, because otherwise one press of start would move your design.

        Deliberately not through the console command `translate`: that works in an undo
        scope of its own, and then every start produces two steps in the undo history the
        user never made. Moving the matrix directly is exactly what that command does,
        without
        die bijwerking.

        The shift is undone in a `finally`: if the planning breaks, the design must not be
        left behind shifted.
        """
        dx = float((origin or {}).get("x_mm") or 0.0)
        dy = float((origin or {}).get("y_mm") or 0.0)
        if not dx and not dy:
            yield False
            return
        units = self._units_per_mm()
        verzet = self._verzet(dx * units, dy * units)
        try:
            yield True
        finally:
            self._verzet(-dx * units, -dy * units, verzet)

    def _verzet(self, dx: float, dy: float, nodes=None) -> list:
        """Move every shape along by a fixed amount, in engine units."""
        from meerk40t.svgelements import Matrix

        matrix = Matrix.translate(dx, dy)
        verzet = []
        for node in list(nodes if nodes is not None else self.elements.elems()):
            try:
                node.matrix *= matrix
                node.translated(dx, dy)
            except AttributeError:
                # A node without a matrix (they exist) we leave alone; it is then in its
                # own place and we do not report that as an error.
                continue
            verzet.append(node)
        return verzet

    def bounds_report(self, sheet=None) -> dict:
        """
        What falls outside the bed or outside the sheet (gap C2).

        Two different mistakes, and the difference counts: off the bed the machine
        *cannot* go — there the head runs into its end stop or the driver skips the
        movement. Off the sheet the machine *can* go, but there is no material there; then
        it burns into the honeycomb or into your worktop. Both cost material and time, and
        both are currently only visible by looking carefully.

        The ids that come out of this have to be the same as those in `/api/design`,
        otherwise the drawing in the pre-flight can do nothing with them — and then it
        redoes the measurement after all. `validate_ids()` hands them out; anybody skipping
        it gets empty strings back for everything that came from an SVG (measured).
        """
        self.elements.validate_ids()
        units = self._units_per_mm()
        bed = self.bed_mm()
        sheet_mm = None
        if sheet and sheet.get("width_mm") and sheet.get("height_mm"):
            sheet_mm = (float(sheet["width_mm"]), float(sheet["height_mm"]))

        # The zero point *does* count for the bed and does *not* for the sheet (gap J12).
        #
        # That is not sloppiness but what the zero point means: you put it on the corner of
        # the material lying on the bed. So the sheet moves along — the work stays on it
        # just as you drew it — while the bed stays where it is, because that is the
        # machine. Without this distinction every zero point set would produce an "off the
        # sheet" warning, and everybody learns to ignore alarms that always go off (see
        # C2). That is why the canvas also draws the sheet in its new place.
        origin = self.origin() or None
        ox = float((origin or {}).get("x_mm") or 0.0)
        oy = float((origin or {}).get("y_mm") or 0.0)

        off_bed: list[str] = []
        off_sheet: list[str] = []
        x0 = y0 = float("inf")
        x1 = y1 = float("-inf")
        for node in self.elements.elems():
            box = getattr(node, "bounds", None)
            if not box:
                continue
            a, b, c, d = (float(v) / units for v in box)
            x0, y0 = min(x0, a), min(y0, b)
            x1, y1 = max(x1, c), max(y1, d)
            name = getattr(node, "id", None) or ""
            if bed and self._outside(a + ox, b + oy, c + ox, d + oy, bed):
                off_bed.append(name)
            if sheet_mm and self._outside(a, b, c, d, sheet_mm):
                off_sheet.append(name)

        work = None
        if x1 > x0:
            work = {
                "x_mm": round(x0, 2),
                "y_mm": round(y0, 2),
                "width_mm": round(x1 - x0, 2),
                "height_mm": round(y1 - y0, 2),
            }
        # Where the work lands as soon as a zero point is set. Without this number the
        # pre-flight would show a frame in the place where you drew, while the machine
        # burns somewhere else — and that is exactly the mistake the zero point is meant to
        # prevent.
        burned = work
        if work and (ox or oy):
            burned = {
                **work,
                "x_mm": round(work["x_mm"] + ox, 2),
                "y_mm": round(work["y_mm"] + oy, 2),
            }

        return {
            "bed": None if not bed else {"width_mm": round(bed[0], 2), "height_mm": round(bed[1], 2)},
            "sheet": None if not sheet_mm else {"width_mm": sheet_mm[0], "height_mm": sheet_mm[1]},
            "work": work,
            "origin": origin,
            "burns_at": burned,
            "outside_bed": len(off_bed),
            "outside_sheet": len(off_sheet),
            "outside_bed_ids": off_bed,
            "outside_sheet_ids": off_sheet,
        }

    @classmethod
    def _outside(cls, x0, y0, x1, y1, frame) -> bool:
        tolerance = cls.EDGE_SLACK
        return (
            x0 < -tolerance
            or y0 < -tolerance
            or x1 > frame[0] + tolerance
            or y1 > frame[1] + tolerance
        )

    def _units_per_mm(self) -> float:
        from meerk40t.core.units import UNITS_PER_MM

        return float(UNITS_PER_MM)

    def _plan_estimate(self) -> tuple[float, int]:
        """The old route: build the whole plan and add up the duration from it."""
        self.runner.run("plan copy preprocess validate blob preopt optimize")
        planner = getattr(self.kernel, "planner", None)
        seconds = 0.0
        pieces = 0
        try:
            plan = getattr(planner, "default_plan", None)
            for item in getattr(plan, "plan", []) or []:
                for name in ("duration_cut", "duration_travel"):
                    fn = getattr(item, name, None)
                    if callable(fn):
                        try:
                            seconds += float(fn())
                        except Exception:
                            pass
                pieces += 1
        finally:
            self.runner.run("plan clear")
        return seconds, pieces

    # Moving without burning. The engine computes with 100 mm/s as soon as a device
    # states nothing else (core/parameters.py:314).
    RAPID_MM_S = 100.0

    def _geometry_estimate(self) -> tuple[float, int]:
        """Burn time and travel time from the element tree, without a plan."""
        seconds = 0.0
        pieces = 0
        rapid = self._rapid_mm_s()
        rasters = self.engine_report()["raster"]
        for operation in self.elements.ops():
            kind = str(operation.type)
            if not kind.startswith("op ") or not getattr(operation, "output", True):
                continue
            # Do not compute time for work this engine does not execute. Without a
            # rasteriser `OpRasterNode.preprocess` throws the layer's children away and
            # produces no cutcode; we *did* compute seconds for it. Measured on one filled
            # area of 60×40 mm: our sum 385.5 s against 70.0 s in the real plan — 315 s
            # promised for a blank plate. The layer still counts as a part: it is on the
            # bed, and the message about it belongs in the pre-flight and not in a zero.
            if kind == "op raster" and not rasters:
                pieces += len(self._burnable(operation))
                continue
            shapes = self._burnable(operation)
            pieces += len(shapes)
            if not shapes:
                continue
            passes = _passes_of(operation)
            if kind == "op dots":
                # A dot costs its dwell time, not its length.
                dwell = _number(getattr(operation, "dwell_time", None)) or 0.0
                seconds += passes * len(shapes) * dwell / 1000
                continue
            speed = _number(getattr(operation, "speed", None))
            if not speed or speed <= 0:
                continue
            if kind in ("op raster", "op image"):
                burn_mm = self._scan_mm(operation, shapes)
                travel_mm = 0.0
            else:
                burn_mm = sum(self._length_mm(node) for node in shapes)
                travel_mm = self._travel_mm(shapes)
            seconds += passes * (burn_mm / speed + travel_mm / rapid)
        return seconds, pieces

    def _rapid_mm_s(self) -> float:
        device = getattr(self.kernel, "device", None)
        value = _number(getattr(device, "rapid_speed", None))
        return value if value and value > 0 else self.RAPID_MM_S

    def _burnable(self, operation) -> list:
        """
        The shapes under a layer, references resolved.

        A layer contains `ReferenceNode`s that point at the element, and an effect (hatch,
        wobble) is itself a container with geometry of its own. What is hidden is not burned
        and therefore does not count here.
        """
        found = []
        stack = list(operation.children)
        depth = 0
        while stack and depth < 5000:
            depth += 1
            node = stack.pop()
            target = getattr(node, "node", None) or node
            if getattr(target, "hidden", False):
                continue
            if hasattr(target, "as_geometry") or getattr(target, "type", "") == (
                "elem image"
            ):
                found.append(target)
            else:
                stack.extend(getattr(target, "children", []) or [])
        return found

    @staticmethod
    def _length_mm(node) -> float:
        """
        The length of the path in mm.

        Two routes, because the first can fall over on valid geometry. Found in a real
        project: text in Chalkduster, 474 contours and 10,026 segments, on which the
        engine's `Geomstr.length()` gives up with "expected a positive input, got -inf" (a
        degenerate segment in the log). We caught that with a 0 — the `except` was there for
        images, which have no path — and so the estimate computed zero seconds for precisely
        the shape that took the longest. Now we measure it ourselves along the points
        instead: measured 0.68 m, where it was 0.0.
        """
        from math import hypot

        from meerk40t.core.units import UNITS_PER_MM

        try:
            geometry = node.as_geometry()
        except Exception:
            # An image has no path; that falls under the raster sum.
            return 0.0
        try:
            return float(geometry.length()) / UNITS_PER_MM
        except Exception:
            pass
        try:
            total, previous = 0.0, None
            for point in geometry.as_interpolated_points(interpolate=20):
                if point is None:
                    previous = None
                    continue
                if previous is not None:
                    total += hypot(point.real - previous.real, point.imag - previous.imag)
                previous = point
            return total / UNITS_PER_MM
        except Exception:
            return 0.0

    @staticmethod
    def _center_mm(node) -> tuple[float, float] | None:
        from meerk40t.core.units import UNITS_PER_MM

        bounds = getattr(node, "bounds", None)
        if not bounds:
            return None
        x0, y0, x1, y1 = bounds
        return (x0 + x1) / 2 / UNITS_PER_MM, (y0 + y1) / 2 / UNITS_PER_MM

    def _travel_mm(self, nodes) -> float:
        """
        The jumps between the shapes, in nearest-first order.

        The engine's optimisation does the same (nearest-neighbour) but on cut pieces
        instead of on whole shapes, so this is a rough upper bound. With many shapes it
        becomes too expensive to do exactly, and it is the smallest term in the sum.
        """
        points = [p for p in (self._center_mm(n) for n in nodes) if p]
        if len(points) < 2:
            return 0.0
        import numpy as np

        # As complex numbers, just like the engine's geometry: then the distance to *all*
        # the remaining points is one numpy operation. Per point in Python this would cost
        # seconds with a thousand shapes, and then we are back at the problem we are
        # solving.
        rest = np.array([complex(x, y) for x, y in points])
        here = rest[0]
        rest = np.delete(rest, 0)
        travel = 0.0
        while rest.size:
            afstanden = np.abs(rest - here)
            index = int(afstanden.argmin())
            travel += float(afstanden[index])
            here = rest[index]
            rest = np.delete(rest, index)
        return travel

    @staticmethod
    def _scan_mm(operation, nodes) -> float:
        """
        How many millimetres the head travels to raster this layer.

        Line by line across every shape, with the line spacing from the dpi and the
        overscan on both sides. One-way traffic doubles it: then the head drives back empty
        on every line.

        Per shape, not across the whole layer's bounding box: two areas in opposite corners
        do not raster the empty middle between them.

        A raster layer burns the **area**, and a shape without a fill has none. Such a shape
        produces no cutcode in the real plan (measured: an outlined rectangle in a raster
        layer gives 0.0 s), so it does not count here either — otherwise it says 8 minutes
        for work that does not happen.
        """
        from meerk40t.core.units import UNITS_PER_MM

        dpi = _number(getattr(operation, "dpi", None)) or 500.0
        step_mm = 25.4 / max(dpi, 1.0)
        area = str(operation.type) == "op raster"
        overscan_mm = 0.0
        raw = getattr(operation, "overscan", None)
        if raw is not None:
            try:
                from meerk40t.core.units import Length

                overscan_mm = float(Length(raw).mm)
            except Exception:
                overscan_mm = 0.0

        scan = 0.0
        for node in nodes:
            bounds = getattr(node, "bounds", None)
            if not bounds:
                continue
            if area and not _is_filled(node):
                continue
            width = (bounds[2] - bounds[0]) / UNITS_PER_MM
            height = (bounds[3] - bounds[1]) / UNITS_PER_MM
            lines = max(1.0, height / step_mm)
            scan += lines * (width + 2 * overscan_mm)
        if not getattr(operation, "bidirectional", True):
            scan *= 2
        return scan

    def job_layers(self, library=None, provenance=None, sheet=None) -> list[dict]:
        """
        Wat de machine straks gaat dóén, per layer.

        The pre-flight only showed the time and the number of parts. Anybody who has
        worked with a laser for ten years looks at something else before starting: which
        speed, which power, how many passes — and where those numbers came from. An
        extrapolated setting on acrylic is a different conversation from a measured one.
        """
        library = library or getattr(self, "library", None)
        presets = []
        if library is not None:
            try:
                presets = library.presets()
            except Exception:
                presets = []

        def source_of(speed, power):
            if speed is None or power is None:
                return None
            for preset in presets:
                if abs(float(preset["speed_mm_s"]) - float(speed)) > 0.01:
                    continue
                if abs(float(preset["power_percent"]) * 10 - float(power)) > 0.1:
                    continue
                return preset["source"]
            return None

        sheet_id = (sheet or {}).get("id")
        rasters = self.engine_report()["raster"]

        layers = []
        for operation in self.elements.ops():
            if not str(operation.type).startswith("op "):
                continue
            if not getattr(operation, "output", True):
                continue
            children = sum(1 for _ in operation.children)
            if not children:
                continue
            speed = getattr(operation, "speed", None)
            power = getattr(operation, "power", None)
            passes = _passes_of(operation)
            percent = None if power is None else round(float(power) / 10, 1)
            operation_id = getattr(operation, "id", None)
            # This layer's own note beats guessing from the numbers: it also knows
            # *which* material those numbers belonged to.
            entry = (
                provenance.lookup(sheet_id, operation_id, speed, percent)
                if provenance is not None
                else None
            )
            layers.append(
                {
                    # Without an id the pre-flight cannot look up the layer colour, and
                    # two operations of the same type are both called "Engrave".
                    "id": operation_id,
                    "label": operation_label(operation),
                    "type": operation.type,
                    "speed_mm_s": None if speed is None else float(speed),
                    "power_percent": percent,
                    "passes": int(passes),
                    "elements": children,
                    # Does this layer actually burn? A raster layer does not on an engine
                    # without a rasteriser, and then the table must not show a speed and a
                    # power as if something is going to happen.
                    "burns": not (str(operation.type) == "op raster" and not rasters),
                    "source": (entry or {}).get("source") or source_of(speed, power),
                    "preset_id": (entry or {}).get("preset_id"),
                    "material_id": (entry or {}).get("material_id"),
                    "material_name": (entry or {}).get("material_name"),
                    "thickness_mm": (entry or {}).get("thickness_mm"),
                    "warnings": _layer_warnings(entry, sheet),
                }
            )
        return layers

    def export_svg(self, filename: str = "ontwerp.svg"):
        """
        Write the design out as an SVG.

        MeerK40t's own writer, including its namespace, so operations and settings come back
        along on reload. The file goes to a temporary directory; the browser fetches it as a
        download.
        """
        import tempfile
        from pathlib import Path

        safe = Path(filename).name or "ontwerp.svg"
        if not safe.lower().endswith(".svg"):
            safe += ".svg"
        target = Path(tempfile.mkdtemp(prefix="openkerf-export-")) / safe
        self.runner.run(f'save "{target}"')
        if not target.is_file():
            raise DesignError("The engine wrote no file.")
        return target

    def export_project(self, library, filename: str = "project.openkerf", sheets=None):
        """
        A project file: the design plus the library context.

        An SVG keeps the shapes and operations, but not which material or which test grid
        belonged with it — those live in the local database. So a project is a zip with the
        SVG and a JSON beside it.
        """
        import json
        import tempfile
        import zipfile
        from pathlib import Path

        safe = Path(filename).name or "project.openkerf"
        if not safe.lower().endswith(".openkerf"):
            safe += ".openkerf"
        target = Path(tempfile.mkdtemp(prefix="openkerf-project-")) / safe

        design = self.export_svg("design.svg")
        context = {
            "version": 1,
            "materials": library.materials(),
            "presets": library.presets(),
            "machines": library.machines(),
            "test_grids": library.test_grids(),
        }
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as bundle:
            # design.svg stays the active sheet, so that an older OpenKerf can still open
            # the project: then you miss the other sheets, but not your work.
            bundle.write(design, "design.svg")
            bundle.writestr("library.json", json.dumps(context, indent=1, default=str))
            if sheets is not None:
                index = sheets.export_into(bundle)
                bundle.writestr(
                    "sheets.json",
                    json.dumps(
                        {"active": sheets.state()["active"], "sheets": index},
                        indent=1,
                        ensure_ascii=False,
                    ),
                )
        return target

    def import_project(self, path, library, sheets=None) -> dict:
        """
        Opening a project: replacing the design and filling in missing library data.

        Existing materials and presets stay; we only fill in what is not there, so that
        opening a project does not overwrite somebody else's work.
        """
        import json
        import zipfile
        from pathlib import Path

        source = Path(path)
        if not zipfile.is_zipfile(source):
            raise DesignError("This is not an OpenKerf project.", code="project.notOurs")
        with zipfile.ZipFile(source) as bundle:
            names = set(bundle.namelist())
            if "design.svg" not in names:
                raise DesignError("The project holds no design.", code="project.noDesign")
            svg = bundle.read("design.svg")
            context = (
                json.loads(bundle.read("library.json")) if "library.json" in names else {}
            )
            # `vellen.json` is what this index was called before the interface became
            # English; a project from that version still opens.
            index_name = next(
                (n for n in ("sheets.json", "vellen.json") if n in names), None
            )
            if sheets is not None and index_name:
                index = json.loads(bundle.read(index_name))
                sheets.import_from(
                    bundle, index.get("sheets") or [], index.get("active")
                )

        import tempfile

        scratch = Path(tempfile.mkdtemp(prefix="openkerf-open-")) / "design.svg"
        scratch.write_bytes(svg)
        self.elements.clear_all()
        self.user_operations.clear()
        self.runner.run(f'load "{scratch}"')
        self.elements.validate_ids()
        self._refresh()

        added = self._merge_library(context, library)
        return {"imported": True, "library": added}

    @staticmethod
    def _merge_library(context: dict, library) -> dict:
        known = {m["name"] for m in library.materials()}
        materials = 0
        mapping = {m["name"]: m["id"] for m in library.materials()}
        for material in context.get("materials", []):
            if material.get("name") and material["name"] not in known:
                created = library.add_material(material["name"], material.get("synonyms"))
                mapping[created["name"]] = created["id"]
                materials += 1

        existing = {
            (p["material_name"], p["operation"], p["speed_mm_s"], p["power_percent"])
            for p in library.presets()
        }
        presets = 0
        for preset in context.get("presets", []):
            key = (
                preset.get("material_name"),
                preset.get("operation"),
                preset.get("speed_mm_s"),
                preset.get("power_percent"),
            )
            material_id = mapping.get(preset.get("material_name"))
            if key in existing or material_id is None:
                continue
            library.add_preset(
                material_id=material_id,
                thickness_mm=preset.get("thickness_mm"),
                operation=preset.get("operation"),
                speed_mm_s=preset.get("speed_mm_s"),
                power_percent=preset.get("power_percent"),
                passes=preset.get("passes") or 1,
                source=preset.get("source") or "geimporteerd",
                origin_id=preset.get("origin_id"),
                note=preset.get("note") or "",
            )
            presets += 1
        return {"materials": materials, "presets": presets}

    def _refresh(self):
        if getattr(self.runner, "document", None) is not None:
            self.runner.document.touch()
        self.elements.signal("rebuild_tree", "all")
        self.elements.signal("refresh_scene", "Scene")


# The difference in thickness at which a setting is still "from the same board". Half a
# millimetre covers the spread of sheet material; above that it is a different thickness
# and therefore a different cut.
THICKNESS_SLACK = 0.51


def _mm_tekst(value) -> str:
    """
    3 rather than 3.0.

    The decimal separator stays a point here: this is the source language of the
    API, and the interface writes the number again in the reader's own notation.
    """
    return f"{float(value):g}"


# How heavily an objection weighs. Not all warnings are equally bad, and showing them
# with equal weight leaves the user to work out what has to come first — exactly at the
# moment they do not feel like it.
#
# A measured setting for the wrong material is the worst: those numbers *are* true, but
# about something else, and nothing on screen contradicts them. A different thickness of
# the same material is a gradation of that. A calculated value on the right material is
# the mildest: it *may* be right, it has simply never been proven.
ERNST = {"ander-materiaal": 3, "andere-dikte": 2, "nooit-gebrand": 1}


def _layer_warnings(entry: dict | None, sheet: dict | None) -> list[dict]:
    """
    Why you should look at this layer once more before starting.

    Three things, in order of how hard they can land: the setting comes from a *different*
    material, from a different thickness, or from nobody — it was calculated or adopted and
    never actually burned.
    """
    if not entry:
        return []

    warnings = []
    sheet = sheet or {}
    vel_materiaal = sheet.get("material_id")
    vel_naam = sheet.get("material_name") or "this sheet"
    vel_dikte = sheet.get("thickness_mm")

    van = entry.get("material_name") or "another material"
    if (
        vel_materiaal is not None
        and entry.get("material_id") is not None
        and entry["material_id"] != vel_materiaal
    ):
        warnings.append(
            {
                "code": "ander-materiaal",
                "text": f"This setting is for {van}; this sheet is {vel_naam}.",
            }
        )
    elif (
        vel_dikte is not None
        and entry.get("thickness_mm") is not None
        and abs(float(entry["thickness_mm"]) - float(vel_dikte)) >= THICKNESS_SLACK
    ):
        warnings.append(
            {
                "code": "andere-dikte",
                "text": (
                    f"This setting is for {_mm_tekst(entry['thickness_mm'])} mm; "
                    f"this sheet is {_mm_tekst(vel_dikte)} mm."
                ),
            }
        )

    if entry.get("source") == "geextrapoleerd":
        warnings.append(
            {
                "code": "nooit-gebrand",
                "text": "Calculated from another thickness — never burned.",
            }
        )
    elif entry.get("source") == "geimporteerd":
        warnings.append(
            {
                "code": "nooit-gebrand",
                "text": "Taken from another machine — never burned here.",
            }
        )

    # The heaviest objection at the top, so that the reader does not have to weigh them.
    for warning in warnings:
        warning["ernst"] = ERNST.get(warning["code"], 1)
    warnings.sort(key=lambda w: -w["ernst"])
    return warnings
