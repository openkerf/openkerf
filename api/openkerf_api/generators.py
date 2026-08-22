"""
Generators: things you would otherwise draw by hand.

Comparable to xTool Studio's "Applications" tab, see XTOOL-VERGELIJKING.md. What is here
was chosen on what really saves a laser user work:

- **Grid and circle repeat** — you do not lay twenty key fobs out by copy and paste.
- **Polygon and star** — the engine can already do it (`shape`), there was simply no route
  to it.
- **Box with finger joints** — the only generator that really saves arithmetic: finger
  width, material thickness and kerf have to be right or the box does not fit.
- **QR code** — engraving an address or a serial number without hunting for an image.
- **Living hinge** — a field of slits that makes plywood bend. Drawing a hundred and
  twenty slits by hand is not the point; getting the bridge between them right is.

Not built: jewellery, key fob and card generators. Those make one specific product; the
box makes a category.
"""

from __future__ import annotations

import math

from .edits import DesignError, _finite, _positive


class Generators:
    def __init__(self, kernel, runner, drawing=None, sheets=None):
        self.kernel = kernel
        self.runner = runner
        self.drawing = drawing
        # For a box that does not fit on one sheet; see box().
        self.sheets = sheets

    @property
    def elements(self):
        return self.kernel.elements

    # ------------------------------------------------------------ herhalen

    def grid(self, ids, columns, rows, gap_x_mm=5.0, gap_y_mm=5.0) -> dict:
        """
        Repeating the selection in rows and columns.

        The spacing is a **gap** between the shapes, not centre to centre: that is what you
        want to be able to choose on material, because that is where the cut goes.
        """
        columns, rows = self._count(columns, "columns"), self._count(rows, "rows")
        if columns * rows <= 1:
            raise DesignError("A grid of one cell is not a grid.")
        gap_x = _finite(gap_x_mm, "gap_x_mm")
        gap_y = _finite(gap_y_mm, "gap_y_mm")
        if gap_x < 0 or gap_y < 0:
            raise DesignError("A negative gap makes the shapes overlap.")

        with self._selection(ids), self.elements.undoscope("Grid repeat"):
            self.runner.run(
                f"grid {columns} {rows} {gap_x:.4f}mm {gap_y:.4f}mm --relative"
            )
        return self._added("grid", columns * rows)

    def radial(self, ids, repeats, radius_mm, start_deg=0.0, end_deg=360.0, rotate=True) -> dict:
        """Repeat the selection around a centre point."""
        count = self._count(repeats, "herhalingen")
        if count < 2:
            raise DesignError("Fewer than two copies is not a circle.")
        radius = _positive(radius_mm, "radius_mm")
        start = _finite(start_deg, "start_deg")
        end = _finite(end_deg, "end_deg")
        if abs(end - start) < 1:
            raise DesignError("The arc has to span more than one degree.")

        command = f"radial {count} {radius:.4f}mm {start}deg {end}deg"
        if not rotate:
            command += " --unrotated"
        with self._selection(ids), self.elements.undoscope("Radial repeat"):
            self.runner.run(command)
        return self._added("radial", count)

    # -------------------------------------------------------------- shapes

    def polygon(
        self,
        corners,
        cx_mm,
        cy_mm,
        radius_mm,
        inner_radius_mm=None,
        start_deg=0.0,
    ) -> dict:
        """
        A regular polygon, or a star when an inner radius is given.

        The engine makes a star by alternating the radius (`--radius_inner` with
        `--alternate_seq 1`); without that second option you get a polygon with doubled
        points instead of a star.
        """
        count = self._count(corners, "corners")
        if count < 3:
            raise DesignError("A polygon needs at least three corners.")
        radius = _positive(radius_mm, "radius_mm")
        cx = _finite(cx_mm, "cx_mm")
        cy = _finite(cy_mm, "cy_mm")

        command = (
            f"shape {count} {cx:.4f}mm {cy:.4f}mm {radius:.4f}mm "
            f"--startangle {_finite(start_deg, 'start_deg')}deg"
        )
        if inner_radius_mm is not None:
            inner = _positive(inner_radius_mm, "inner_radius_mm")
            if inner >= radius:
                raise DesignError("The inner radius has to be smaller than the radius.")
            command += f" --radius_inner {inner:.4f}mm --alternate_seq 1"

        with self.elements.undoscope("Polygon"):
            self.runner.run(command)
        return self._added("polygon", 1)

    # ----------------------------------------------------------- boogtekst

    def arc_text(
        self,
        text,
        cx_mm,
        cy_mm,
        radius_mm,
        font_size_mm=10.0,
        font=None,
        spacing=None,
        inside=False,
    ) -> dict:
        """
        Text along an arc, for a round sign or a lid for instance.

        The engine does not know arc text. We simply have it set the text straight and then
        bend the geometry: every point moves to the circle, with the distance to the baseline
        becoming the distance to the centre. That way the letter height stays right and
        nothing stretches.

        After the bending it is **no longer text but a path**: the source is let go, because
        the engine would render the text straight again at the next change and silently wipe
        the arc away.
        """
        from meerk40t.core.units import UNITS_PER_MM

        radius = _positive(radius_mm, "radius_mm")
        cx = _finite(cx_mm, "cx_mm") * UNITS_PER_MM
        cy = _finite(cy_mm, "cy_mm") * UNITS_PER_MM
        size = _positive(font_size_mm, "font_size_mm")

        drawn = self.drawing.create(
            "text",
            x_mm=0,
            y_mm=0,
            text=text,
            font_size_mm=size,
            font=font,
            spacing=spacing,
        )
        node = self.elements.find_node(drawn["ids"][0])
        geometry = node.as_geometry()
        bounds = node.bounds
        if not bounds:
            raise DesignError("The text yielded no shape.", code="gen.noShape")
        _bend_in_place(geometry, bounds, cx, cy, radius * UNITS_PER_MM, inside)

        with self.elements.undoscope("Arc text"):
            node.geometry = geometry
            node.matrix.reset()
            # Let the source go: otherwise the engine renders the text straight again at
            # the next change.
            for attribute in ("mktext", "mkfont", "mkfontsize"):
                if hasattr(node, attribute):
                    setattr(node, attribute, None)
            node.altered()
            self.elements.validate_ids()
        self._refresh()
        return {"generator": "arc_text", "ids": [node.id] if node.id else []}

    # --------------------------------------------------------------- barcode

    def barcode(
        self, text, kind="code128", x_mm=0.0, y_mm=0.0, width_mm=60.0, height_mm=20.0
    ) -> dict:
        """
        A barcode as filled areas.

        The encoding comes from `python-barcode`; we draw the bars ourselves, as with the
        QR code. An engraved bitmap goes vague on wood, and a barcode that does not scan is
        useless.

        The arithmetic is in `_plan_barcode`, so that the preview gets the same bars and
        the same error messages as the real work.
        """
        content, bars = self._plan_barcode(text, kind, x_mm, y_mm, width_mm, height_mm)

        with self.elements.undoscope("Barcode"):
            node = self._add_polygon(
                bars, f"{kind} — {content[:24]}", subpaths=True, intent="engrave"
            )
            self.elements.validate_ids()
        self._refresh()
        return {
            "generator": "barcode",
            "kind": kind,
            "ids": [node.id] if node.id else [],
            "bars": len(bars),
        }

    # ---------------------------------------------------------------- doos

    def box(
        self,
        width_mm,
        depth_mm,
        height_mm,
        thickness_mm,
        finger_mm=10.0,
        kerf_mm=0.0,
        gap_mm=5.0,
        lid=True,
        spread=True,
    ) -> dict:
        """
        Panels with finger joints, laid out side by side for cutting.

        Why this arithmetic should not be done by hand: two panels that join have to have
        **complementary** teeth — where one has a tooth, the other has a gap. One panel the
        wrong way round and the box does not fit. `PHASE` records per edge which side has the
        tooth; there is a test that checks every pair is opposite.

        The kerf is added to the teeth and not subtracted from the gaps: the laser takes
        material off both sides of every cut, so a tooth that fits exactly on paper is too
        small in wood.

        The arithmetic is in `_plan_box`, so that the preview gets the same panels, the
        same layout and the same error messages as the real work.
        """
        panels, pages, (bed_width, bed_height) = self._plan_box(
            width_mm, depth_mm, height_mm, thickness_mm, finger_mm, kerf_mm,
            gap_mm, lid,
        )

        if len(pages) > 1 and not (spread and self.sheets):
            raise DesignError(
                f"This box does not fit on one sheet of {bed_width:.0f} x "
                f"{bed_height:.0f} mm; {len(pages)} are needed. Switch 'spread over "
                "sheets' on, or choose smaller sizes.",
                code="gen.boxTooBig",
            )

        started_on = self.sheets.state()["active"] if self.sheets else None
        ids = []
        for index, page in enumerate(pages):
            if index:
                # Next sheet, the same size as this one: then the layout agrees with what
                # was computed.
                self.sheets.add(
                    name=f"Box {index + 1}",
                    width_mm=bed_width,
                    height_mm=bed_height,
                )
                self.sheets.activate(self.sheets.state()["sheets"][-1]["id"])
            with self.elements.undoscope("Box"):
                for name, points, at_x, at_y in page:
                    node = self._add_polygon(
                        [(px + at_x, py + at_y) for px, py in points],
                        f"Box — {name}",
                    )
                    if index == 0:
                        ids.append(node)
                self.elements.validate_ids()
            self._refresh()

        if len(pages) > 1 and self.sheets:
            # Back to where the user was: letting the canvas slide out from under you is
            # more confusing than clicking through yourself.
            self.sheets.activate(started_on)
            self._refresh()

        return {
            "generator": "box",
            "ids": [n.id for n in ids if n.id],
            "panels": [name for name, _ in panels],
            "sheets": len(pages),
        }

    # ------------------------------------------------------------- qr-code

    def qrcode(self, text: str, x_mm=0.0, y_mm=0.0, size_mm=30.0, border=2) -> dict:
        """
        A QR code as little squares, ready to engrave.

        Not an image but real areas: an engraved bitmap often goes vague on wood, filled
        squares do not. One path per module, though, because that lets the user choose
        whether they fill or outline.

        The arithmetic is in `_plan_qrcode`, so that the preview gets the same modules and
        the same error messages as the real work.
        """
        content, squares, modules = self._plan_qrcode(
            text, x_mm, y_mm, size_mm, border
        )

        with self.elements.undoscope("QR code"):
            node = self._add_polygon(
                squares, f"QR — {content[:24]}", subpaths=True, intent="engrave"
            )
            self.elements.validate_ids()
        self._refresh()
        return {
            "generator": "qrcode",
            "ids": [node.id] if node.id else [],
            "modules": modules,
        }

    # -------------------------------------------------------- living hinge

    def hinge(
        self,
        ids=None,
        pattern="staggered",
        slit_mm=8.0,
        gap_mm=3.0,
        row_mm=2.0,
        x_mm=0.0,
        y_mm=0.0,
        width_mm=60.0,
        height_mm=40.0,
        from_selection=False,
    ) -> dict:
        """
        A field of slits that lets rigid sheet material bend.

        The slits run horizontally, so the sheet bends around a horizontal line: the
        material between two slits in a row twists, and that is the whole mechanism. Turn
        the group a quarter and it bends the other way — that is why there is no direction
        field here, a rotation already exists.

        One path with every slit as its own open subpath, in a cut layer: so the field
        moves as one thing and the laser cuts every slit once. `_add_polygon` cannot do
        this — it closes every ring, and a closed slit is cut twice.

        The arithmetic is in `_plan_hinge`, so that the preview gets the same slits and the
        same refusals as the real work.
        """
        geometry, info = self._plan_hinge(
            ids, pattern, slit_mm, gap_mm, row_mm,
            x_mm, y_mm, width_mm, height_mm, from_selection,
        )

        with self.elements.undoscope("Living hinge"):
            node = self._add_geometry(
                geometry, f"Living hinge — {PATTERN_LABELS[info['pattern']]}"
            )
            self.elements.validate_ids()
        self._refresh()
        return {
            "generator": "hinge",
            "ids": [node.id] if node.id else [],
            "pattern": info["pattern"],
            "slits": info["slits"],
            "rows": info["rows"],
        }

    # ------------------------------------------------------------- the preview

    # How many copies we draw out before we keep it to one outline per copy. Five hundred
    # key fobs are 500 paths and that stays fast, because every copy reuses the same path
    # (see `parts` below).
    PREVIEW_LIMIT = 500

    def preview(self, what: str, body: dict) -> dict:
        """
        What would be laid down, without making it.

        Hands back shapes as SVG path data **in millimetres**, plus where every copy goes.
        Two layers, because a QR code of 15,000 little squares and a grid of 500 copies both
        have to go through this hole:

        - `shapes` — the unique outlines, each one d-string (with subpaths).
        - `parts`  — where they go: `{shape, x, y, rot}` in mm and degrees.

        The shape is not added to the drawing and nothing about the document changes; so
        this may run on every key stroke.
        """
        maker = {
            "grid": self._preview_grid,
            "radial": self._preview_radial,
            "polygon": self._preview_polygon,
            "box": self._preview_box,
            "qrcode": self._preview_qrcode,
            "barcode": self._preview_barcode,
            "arctext": self._preview_arctext,
            "hinge": self._preview_hinge,
        }.get(str(what))
        if maker is None:
            raise DesignError(f"No preview can be made of '{what}'.")

        result = maker(body or {})
        sheet_width, sheet_height = self._surface()
        result.setdefault("notes", [])
        result.setdefault("sheets", 1)
        result["what"] = what
        result["sheet"] = {"width_mm": sheet_width, "height_mm": sheet_height}
        # The boxes per shape only serve to work out how far the preview has to zoom out;
        # the browser has no use for them.
        result["bounds"] = _extent(result.pop("boxes"), result["parts"])
        return result

    # The individual previews. Each reuses the real work's sum; what is not in it is
    # deliberately not in it (see `_preview_arctext`).

    def _preview_grid(self, body: dict) -> dict:
        columns = self._count(body.get("columns"), "columns")
        rows = self._count(body.get("rows"), "rows")
        if columns * rows <= 1:
            raise DesignError("A grid of one cell is not a grid.")
        gap_x = _finite(body.get("gap_x_mm", 5.0), "gap_x_mm")
        gap_y = _finite(body.get("gap_y_mm", 5.0), "gap_y_mm")
        if gap_x < 0 or gap_y < 0:
            raise DesignError("A negative gap makes the shapes overlap.")

        shape, box, (left, top, width, height) = self._selection_outline(
            body.get("ids")
        )
        # The same pitch as `grid --relative`: the space given is the gap, so the distance
        # from copy to copy is that space *plus* the shape itself
        # (core/elements/grid.py:210).
        pitch_x, pitch_y = width + gap_x, height + gap_y
        parts, notes = [], []
        if columns * rows > self.PREVIEW_LIMIT:
            notes.append(
                f"{columns * rows} copies is more than the preview draws; "
                f"the first {self.PREVIEW_LIMIT} are below."
            )
        for row in range(rows):
            for column in range(columns):
                if len(parts) >= self.PREVIEW_LIMIT:
                    break
                parts.append(
                    {
                        "shape": 0,
                        "x": left + column * pitch_x,
                        "y": top + row * pitch_y,
                        "rot": 0.0,
                    }
                )
        return {"shapes": [shape], "boxes": [box], "parts": parts, "notes": notes}

    def _preview_radial(self, body: dict) -> dict:
        count = self._count(body.get("repeats"), "herhalingen")
        if count < 2:
            raise DesignError("Fewer than two copies is not a circle.")
        radius = _positive(body.get("radius_mm"), "radius_mm")
        start = _finite(body.get("start_deg", 0.0), "start_deg")
        end = _finite(body.get("end_deg", 360.0), "end_deg")
        if abs(end - start) < 1:
            raise DesignError("The arc has to span more than one degree.")
        rotate = body.get("rotate", True) is not False

        shape, box, (left, top, width, height) = self._selection_outline(
            body.get("ids")
        )
        # The centre lies `radius` to the **left** of the selection's middle, not above it,
        # so that the original itself lies on the circle (core/elements/grid.py:337). The
        # angle runs in steps of (end − start) / count, and the start angle only decides the
        # step length — the first copy is the original at zero degrees.
        cx, cy = left + width / 2 - radius, top + height / 2
        step = (end - start) / count
        parts = []
        for index in range(min(count, self.PREVIEW_LIMIT)):
            angle = index * step
            if rotate:
                # Rotating about the centre, with the shape in its own place. The minus sign
                # is not cosmetic: the copies run anticlockwise across the screen ("perceived
                # angle travel is CCW",
                # core/elements/grid.py:335). A full circle is symmetric and hides that;
                # only an arc of 180° showed that the preview laid them down mirrored.
                parts.append(
                    {
                        "shape": 0,
                        "x": left,
                        "y": top,
                        "rot": -angle,
                        "rx": cx - left,
                        "ry": cy - top,
                    }
                )
            else:
                # Without rotating along, the engine slides the copy along the same circle,
                # and so anticlockwise as well.
                radians = math.radians(angle)
                parts.append(
                    {
                        "shape": 0,
                        "x": left - radius + radius * math.cos(radians),
                        "y": top - radius * math.sin(radians),
                        "rot": 0.0,
                    }
                )
        return {"shapes": [shape], "boxes": [box], "parts": parts, "notes": []}

    def _preview_polygon(self, body: dict) -> dict:
        points = self._plan_polygon(
            body.get("corners"),
            body.get("cx_mm"),
            body.get("cy_mm"),
            body.get("radius_mm"),
            body.get("inner_radius_mm"),
            body.get("start_deg", 0.0),
        )
        shape, box = _as_d([points])
        return {
            "shapes": [shape],
            "boxes": [box],
            "parts": [{"shape": 0, "x": 0.0, "y": 0.0, "rot": 0.0}],
            "notes": [],
        }

    def _preview_box(self, body: dict) -> dict:
        panels, pages, (bed_width, bed_height) = self._plan_box(
            body.get("width_mm"),
            body.get("depth_mm"),
            body.get("height_mm"),
            body.get("thickness_mm"),
            body.get("finger_mm", 10.0),
            body.get("kerf_mm", 0.0),
            body.get("gap_mm", 5.0),
            body.get("lid", True) is not False,
        )
        shapes, boxes, parts, labels = [], [], [], []
        for name, points, at_x, at_y in pages[0]:
            parts.append({"shape": len(shapes), "x": at_x, "y": at_y, "rot": 0.0})
            labels.append(name)
            shape, box = _as_d([points])
            shapes.append(shape)
            boxes.append(box)

        notes = []
        if len(pages) > 1:
            spread = body.get("spread", True) is not False
            notes.append(
                f"Does not fit on one sheet; {len(pages)} are needed. "
                + (
                    "The first one is below."
                    if spread and self.sheets
                    else "Switch 'spread over sheets' on, or choose smaller sizes."
                )
            )
        return {
            "shapes": shapes,
            "boxes": boxes,
            "parts": parts,
            "labels": labels,
            "sheets": len(pages),
            "notes": notes,
        }

    def _preview_qrcode(self, body: dict) -> dict:
        _, squares, modules = self._plan_qrcode(
            body.get("text"),
            body.get("x_mm", 0.0),
            body.get("y_mm", 0.0),
            body.get("size_mm", 30.0),
            body.get("border", 2),
        )
        # All the little squares in one path: a version 40 QR code has well over fifteen
        # thousand of them, and those are not worth fifteen thousand separate messages.
        shape, box = _as_d(squares)
        return {
            "shapes": [shape],
            "boxes": [box],
            "parts": [{"shape": 0, "x": 0.0, "y": 0.0, "rot": 0.0}],
            "modules": modules,
            "notes": [],
        }

    def _preview_barcode(self, body: dict) -> dict:
        _, bars = self._plan_barcode(
            body.get("text"),
            body.get("kind") or "code128",
            body.get("x_mm", 0.0),
            body.get("y_mm", 0.0),
            body.get("width_mm", 60.0),
            body.get("height_mm", 20.0),
        )
        shape, box = _as_d(bars)
        return {
            "shapes": [shape],
            "boxes": [box],
            "parts": [{"shape": 0, "x": 0.0, "y": 0.0, "rot": 0.0}],
            "bars": len(bars),
            "notes": [],
        }

    def _preview_hinge(self, body: dict) -> dict:
        """
        The slit field, exactly as it lands on the bed.

        One shape with every slit as a subpath — the same Geomstr the real work adds, only
        not scaled to Tats. So this cannot drift apart from what burns.
        """
        geometry, info = self._plan_hinge(
            body.get("ids"),
            body.get("pattern") or "staggered",
            body.get("slit_mm", 8.0),
            body.get("gap_mm", 3.0),
            body.get("row_mm", 2.0),
            body.get("x_mm", 0.0),
            body.get("y_mm", 0.0),
            body.get("width_mm", 60.0),
            body.get("height_mm", 40.0),
            body.get("from_selection", False) is True,
        )
        x0, y0, x1, y1 = geometry.bbox()
        return {
            "shapes": [geometry.as_path().d()],
            "boxes": [(x0, y0, x1, y1)],
            "parts": [{"shape": 0, "x": 0.0, "y": 0.0, "rot": 0.0}],
            "pattern": info["pattern"],
            "slits": info["slits"],
            "rows": info["rows"],
            "bridge_mm": info["bridge_mm"],
            "notes": info["notes"],
        }

    def _preview_arctext(self, body: dict) -> dict:
        """
        The arc text in the typeface it will be burned in.

        Normally the engine renders text in a node, and that would end up in the document
        here. It can be done differently: `cfont.render()` writes into a loose `FontPath`
        (extra/hershey.py:352), so we fetch the same geometry without creating anything. What
        we do *not* do is set `context.last_font` — `create_linetext_node` does
        (hershey.py:492), and a preview that silently changes your typeface choice is a
        preview with side effects.
        """
        from meerk40t.core.units import UNITS_PER_MM

        radius = _positive(body.get("radius_mm"), "radius_mm")
        cx = _finite(body.get("cx_mm", 0.0), "cx_mm") * UNITS_PER_MM
        cy = _finite(body.get("cy_mm", 0.0), "cy_mm") * UNITS_PER_MM
        size = _positive(body.get("font_size_mm", 10.0), "font_size_mm")
        text = str(body.get("text") or "").strip()
        if not text:
            raise DesignError("Text cannot be empty.", code="draw.emptyText")

        geometry = self._text_geometry(
            text, size * UNITS_PER_MM, body.get("font"), body.get("spacing")
        )
        bounds = geometry.bbox()
        if bounds is None:
            raise DesignError("The text yielded no shape.", code="gen.noShape")
        _bend_in_place(
            geometry, bounds, cx, cy, radius * UNITS_PER_MM,
            bool(body.get("inside")),
        )
        geometry.uscale(1 / UNITS_PER_MM)
        x0, y0, x1, y1 = geometry.bbox()
        return {
            "shapes": [geometry.as_path().d()],
            "boxes": [(x0, y0, x1, y1)],
            "parts": [{"shape": 0, "x": 0.0, "y": 0.0, "rot": 0.0}],
            "notes": [],
        }

    def _text_geometry(self, text, font_size, font, spacing):
        """Straight text as loose geometry, without a node and without side effects."""
        from meerk40t.extra.hershey import FontPath

        registry = getattr(self.kernel.root, "fonts", None)
        if registry is None:
            raise DesignError("Geen lettertype-ondersteuning beschikbaar.")
        registry.context.setting(str, "last_font", "")
        name, path = registry.retrieve_font(font or None)
        if not name:
            raise DesignError("There is not one usable font on this computer.", code="gen.noFont")
        rendered = FontPath(False)
        try:
            registry.cached_fontclass(path).render(
                rendered,
                self.elements.wordlist_translate(text),
                horizontal=True,
                font_size=float(font_size),
                h_spacing=float(spacing) if spacing else 1.0,
                align="start",
            )
        except Exception as e:
            raise DesignError(f"This font cannot be drawn: {e}") from e
        return rendered.geometry

    def _selection_outline(self, ids):
        """
        The selection's outline as one path in mm, plus where it lies.

        One path for the whole selection, so that a grid of 500 copies is 500 references to
        the same path and not the geometry 500 times.
        """
        from meerk40t.core.node.node import Node
        from meerk40t.core.units import UNITS_PER_MM

        nodes = []
        for element_id in ids or []:
            node = self.elements.find_node(element_id)
            if node is None:
                raise DesignError(f"Element {element_id} does not exist (any more).")
            nodes.append(node)
        if not nodes:
            raise DesignError("Choose what should be repeated first.", code="gen.needsSelection")

        bounds = Node.union_bounds(nodes)
        if not bounds:
            raise DesignError("The selection has no size.")
        x0, y0, x1, y1 = bounds

        from meerk40t.core.geomstr import Geomstr

        together = Geomstr()
        for node in nodes:
            if not hasattr(node, "as_geometry"):
                continue
            try:
                together.append(node.as_geometry())
            except Exception:
                continue
        if together.index == 0:
            # An image has no outline; then the bounding box is the most honest thing we
            # can show.
            together.line(complex(x0, y0), complex(x1, y0))
            together.line(complex(x1, y0), complex(x1, y1))
            together.line(complex(x1, y1), complex(x0, y1))
            together.line(complex(x0, y1), complex(x0, y0))
        together.translate(-x0, -y0)
        together.uscale(1 / UNITS_PER_MM)
        width, height = (x1 - x0) / UNITS_PER_MM, (y1 - y0) / UNITS_PER_MM
        return (
            together.as_path().d(),
            (0.0, 0.0, width, height),
            (x0 / UNITS_PER_MM, y0 / UNITS_PER_MM, width, height),
        )

    # ------------------------------------------------------- het rekenwerk
    #
    # Everything below computes and does not touch the drawing. The real work *and* the
    # preview both run through it, and that is the whole reason they exist: a preview that
    # does its own sum will one day say something other than what comes out of the machine,
    # and then it is worse than no preview. The same rule for the error messages — anybody
    # who reads in the preview why it cannot be done does not suddenly get a different
    # story later.

    # The crest of a wavy slit, as a share of the distance between two rows. At 0.4 the
    # crest stays 0.2 x that distance away from the next row's line, so no two rows run
    # into each other; measured on 60 x 40 mm with rows 2 mm apart, the field spans
    # y 1.2 .. 38.8 and one wavy slit is 4.39 mm of cut for 8 mm of span.
    WAVE_CREST = 0.4
    # A clipped remnant shorter than this is a dot, not a slit: about two kerfs of a CO2
    # cut (0.1 to 0.3 mm each) laid end to end. Measured on a staggered field of 60 mm with
    # a pitch of 11 mm: the remnants at the edge are 2.5 mm and stay, and only what a
    # rounding leaves over goes.
    MIN_SLIT_MM = 0.5
    # Above this the cut plan is the problem and not the hinge: `plan copy` copies the
    # cutcode per pass and the optimisation after it scales quadratically in the number of
    # pieces (see the upstream list in CLAUDE.md).
    MAX_SLITS = 4000

    def _plan_hinge(
        self, ids, pattern, slit_mm, gap_mm, row_mm,
        x_mm, y_mm, width_mm, height_mm, from_selection,
    ):
        """
        The slit field as a Geomstr in millimetres, plus what to say about it.

        Rows are laid out from the middle of the area outwards, so no row lands exactly on
        the boundary — a slit on the edge weakens the edge and hinges nothing. Along the row
        the slits are tiled from the left edge and the field is **clipped** to the area, and
        that is on purpose: the outer slit of a staggered row is supposed to be half a slit,
        otherwise the stagger stops at the edge.

        Clipping goes through `tiling.clip_geometry` and not through the engine's own `Clip`:
        that one asks for its midpoints in one go and walks into the infinite recursion of
        `Geomstr._arc_position` (upstream #3262), and drops segments besides (#3263). Ours
        splits on the parameter, so a wavy slit stays two quads instead of becoming a
        polyline.
        """
        from meerk40t.core.geomstr import Geomstr

        from .tiling import Rect, clip_geometry

        if pattern not in PATTERN_LABELS:
            raise DesignError(
                f"Unknown pattern: {pattern}. Choose from "
                f"{', '.join(PATTERN_LABELS)}."
            )
        slit = _positive(slit_mm, "slit_mm")
        gap = _positive(gap_mm, "gap_mm")
        row = _positive(row_mm, "row_mm")

        if from_selection:
            x0, y0, width, height = self._selection_area(ids)
        else:
            x0 = _finite(x_mm, "x_mm")
            y0 = _finite(y_mm, "y_mm")
            width = _positive(width_mm, "width_mm")
            height = _positive(height_mm, "height_mm")

        if slit >= width:
            raise DesignError(
                f"A slit of {slit:.4g} mm is as long as the {width:.4g} mm area is wide: "
                "that cuts the piece in two instead of bending it. Shorten the slit."
            )
        crest = row * self.WAVE_CREST if pattern == "wavy" else 0.0
        usable = height - 2 * crest
        rows = int(usable // row) if usable > 0 else 0
        if rows < 2:
            raise DesignError(
                f"This area is {height:.4g} mm high; at {row:.4g} mm between rows that is "
                "not two rows of slits. Make the area taller or the rows closer together."
            )

        pitch = slit + gap
        columns = int(math.ceil(width / pitch)) + 1
        if rows * columns > self.MAX_SLITS:
            raise DesignError(
                f"This comes to about {rows * columns} slits; above {self.MAX_SLITS} the "
                "cut plan takes longer than the burn. Choose a bigger gap or fewer rows."
            )
        top = y0 + crest + (usable - (rows - 1) * row) / 2

        field = Geomstr()
        for index in range(rows):
            y = top + index * row
            # Half a pitch to the left on every other row: that is what makes a staggered
            # field bend evenly — the bridge in one row sits opposite a slit in the next.
            shift = -pitch / 2 if (pattern == "staggered" and index % 2) else 0.0
            for column in range(columns):
                left = x0 + shift + column * pitch
                if left > x0 + width or left + slit < x0:
                    continue
                if pattern == "wavy":
                    # Two quads, as MeerK40t's own wave cell does (fill/patterns.py:352). A
                    # quad reaches half its control offset, so the control sits at twice the
                    # crest. Not an arc: `Geomstr.split` has no arc branch and would lose
                    # the piece at the edge (#3263).
                    middle = left + slit / 2
                    field.quad(
                        complex(left, y),
                        complex(left + slit / 4, y - 2 * crest),
                        complex(middle, y),
                    )
                    field.quad(
                        complex(middle, y),
                        complex(left + 3 * slit / 4, y + 2 * crest),
                        complex(left + slit, y),
                    )
                else:
                    field.line(complex(left, y), complex(left + slit, y))

        clipped = clip_geometry(field, Rect(x0, y0, x0 + width, y0 + height))
        kept, dropped = Geomstr(), 0
        for index in range(clipped.index):
            if float(clipped.length(index)) < self.MIN_SLIT_MM:
                dropped += 1
                continue
            kept.append_segment(*clipped.segments[index])
        if kept.index == 0:
            raise DesignError(
                "Nothing is left of this field inside the area.", code="gen.hingeEmpty"
            )

        notes = []
        if gap <= 0.4:
            notes.append(
                f"The bridges between the slits are {gap:.4g} mm wide, and a CO2 cut is "
                "0.1 to 0.3 mm wide itself: they burn away and the field falls apart."
            )
        if dropped:
            notes.append(
                f"{dropped} slit remnants shorter than {self.MIN_SLIT_MM:.4g} mm at the "
                "edge were left out; that short, a cut frees nothing."
            )
        return kept, {
            "pattern": pattern,
            "slits": _subpaths(kept),
            "rows": rows,
            "bridge_mm": gap,
            "notes": notes,
        }

    def _selection_area(self, ids):
        """The box around the selection in millimetres: x, y, width, height."""
        from meerk40t.core.node.node import Node
        from meerk40t.core.units import UNITS_PER_MM

        nodes = []
        for element_id in ids or []:
            node = self.elements.find_node(element_id)
            if node is None:
                raise DesignError(f"Element {element_id} does not exist (any more).")
            nodes.append(node)
        if not nodes:
            # Its own code and not `gen.needsSelection`: that one translates as "choose what
            # should be repeated first", and nothing is being repeated here.
            raise DesignError(
                "Choose the shape whose area the slits have to fill first.",
                code="gen.hingeNeedsSelection",
            )
        bounds = Node.union_bounds(nodes)
        if not bounds:
            raise DesignError("The selection has no size.")
        x0, y0, x1, y1 = (value / UNITS_PER_MM for value in bounds)
        return x0, y0, x1 - x0, y1 - y0

    def _plan_barcode(self, text, kind, x_mm, y_mm, width_mm, height_mm):
        content = str(text or "").strip()
        if not content:
            raise DesignError("A barcode without content does not exist.")
        width = _positive(width_mm, "width_mm")
        height = _positive(height_mm, "height_mm")
        x0 = _finite(x_mm, "x_mm")
        y0 = _finite(y_mm, "y_mm")

        try:
            import barcode as barcodes
        except ImportError as e:  # pragma: no cover - only on a bare installation
            raise DesignError(
                "Barcodes need the 'python-barcode' package.", code="gen.noBarcodeLib"
            ) from e

        if kind not in barcodes.PROVIDED_BARCODES:
            raise DesignError(
                f"Unknown type: {kind}. Choose from {', '.join(barcodes.PROVIDED_BARCODES)}."
            )
        try:
            bits = "".join(barcodes.get_barcode_class(kind)(content).build())
        except Exception as e:
            # EAN and friends make demands about length and check digit; that message is
            # more useful to the user than a 500.
            raise DesignError(f"'{content}' does not fit in a {kind}: {e}",
                code="gen.badBarcode",) from e
        if "1" not in bits:
            raise DesignError("The encoding yielded no bars.")

        step = width / len(bits)
        bars, index = [], 0
        while index < len(bits):
            if bits[index] == "0":
                index += 1
                continue
            run = index
            while run < len(bits) and bits[run] == "1":
                run += 1
            left = x0 + index * step
            right = x0 + run * step
            bars.append(
                [(left, y0), (right, y0), (right, y0 + height), (left, y0 + height)]
            )
            index = run
        return content, bars

    def _plan_qrcode(self, text, x_mm, y_mm, size_mm, border):
        content = str(text or "").strip()
        if not content:
            raise DesignError("A QR code without content does not exist.")
        if len(content) > 1000:
            raise DesignError("This text is too long for a readable QR code.", code="gen.qrTooLong")
        size = _positive(size_mm, "size_mm")
        quiet = int(_finite(border, "border"))
        if not 0 <= quiet <= 8:
            raise DesignError("The quiet zone has to be between 0 and 8 modules.")

        try:
            import segno
        except ImportError as e:  # pragma: no cover - only on a bare installation
            raise DesignError(
                "QR codes need the 'segno' package; install it beside the API.",
                code="gen.noQrLib",
            ) from e

        code = segno.make(content, error="m")
        matrix = [list(row) for row in code.matrix]
        modules = len(matrix) + 2 * quiet
        step = size / modules
        x0 = _finite(x_mm, "x_mm")
        y0 = _finite(y_mm, "y_mm")

        squares = []
        for row, cells in enumerate(matrix):
            for column, dark in enumerate(cells):
                if not dark:
                    continue
                left = x0 + (column + quiet) * step
                top = y0 + (row + quiet) * step
                squares.append(
                    [
                        (left, top),
                        (left + step, top),
                        (left + step, top + step),
                        (left, top + step),
                    ]
                )
        return content, squares, modules

    def _plan_box(
        self, width_mm, depth_mm, height_mm, thickness_mm, finger_mm, kerf_mm,
        gap_mm, lid,
    ):
        width = _positive(width_mm, "width_mm")
        depth = _positive(depth_mm, "depth_mm")
        height = _positive(height_mm, "height_mm")
        thickness = _positive(thickness_mm, "thickness_mm")
        finger = _positive(finger_mm, "finger_mm")
        kerf = _finite(kerf_mm, "kerf_mm")
        gap = _finite(gap_mm, "gap_mm")
        if not 0 <= kerf <= 2:
            raise DesignError("A kerf outside 0–2 mm is not right.")
        if gap < 0:
            raise DesignError("The gap between the panels cannot be negative.")
        if thickness * 3 >= min(width, depth, height):
            raise DesignError(
                "The material is too thick for these outside sizes; the walls would "
                "touch each other.",
                code="gen.tooThick",
            )
        if finger < thickness:
            raise DesignError(
                "A finger narrower than the material is thick snaps off. "
                f"Choose at least {thickness} mm.",
                code="gen.fingerTooNarrow",
            )
        if finger * 3 > min(width, depth, height):
            raise DesignError(
                "The finger is too wide: three of them do not fit on an edge.",
                code="gen.fingerTooWide",
            )

        panels = box_panels(
            width, depth, height, thickness, finger, kerf, lid=lid
        )

        # Laying them on the bed in rows, not in one long row: six panels side by side are
        # a metre wide in no time, and what falls off the bed can no longer be pointed at to
        # bring it back.
        bed_width, bed_height = self._surface()
        widest = max(
            max(px for px, _ in points) - min(px for px, _ in points)
            for _, points in panels
        )
        if widest > bed_width:
            raise DesignError(
                f"The widest panel is {widest:.0f} mm and does not fit on a sheet of "
                f"{bed_width:.0f} mm. Choose smaller outside sizes.",
                code="gen.panelTooWide",
            )

        # Work out where everything goes first, only then draw. Otherwise half a box is
        # off the sheet before you know it does not fit.
        pages = _lay_out(panels, bed_width, bed_height, gap)
        return panels, pages, (bed_width, bed_height)

    def _plan_polygon(self, corners, cx_mm, cy_mm, radius_mm, inner_radius_mm, start_deg):
        """
        The polygon's corner points, in mm.

        The real polygon comes from the engine's `shape` command; this is the sum beside it.
        `test_polygon_preview_matches_the_real_thing` lays both side by side, because a
        second sum can only be trusted once something falls over as soon as they drift apart.
        """
        count = self._count(corners, "corners")
        if count < 3:
            raise DesignError("A polygon needs at least three corners.")
        radius = _positive(radius_mm, "radius_mm")
        cx = _finite(cx_mm, "cx_mm")
        cy = _finite(cy_mm, "cy_mm")
        start = _finite(start_deg, "start_deg")
        inner = None
        if inner_radius_mm is not None:
            inner = _positive(inner_radius_mm, "inner_radius_mm")
            if inner >= radius:
                raise DesignError("The inner radius has to be smaller than the radius.")

        # `corners` counts the corner points, not the star's points: a five-pointed star
        # has five, alternating outside and inside on steps of 360°/5
        # (extra/param_functions.py:868). That is the trap the preview fell into at first —
        # it drew ten and so came out too tall.
        points = []
        for index in range(count):
            r = inner if (inner is not None and index % 2) else radius
            angle = math.radians(start) + index / count * math.tau
            points.append((cx + math.cos(angle) * r, cy + math.sin(angle) * r))
        return points

    # --------------------------------------------------------------- intern

    def _surface(self) -> tuple[float, float]:
        """What it has to fit on: the active sheet, or the bed when there is none."""
        if self.sheets is not None:
            for sheet in self.sheets.state()["sheets"]:
                if sheet["active"]:
                    return float(sheet["width_mm"]), float(sheet["height_mm"])
        return self._bed()

    def _bed(self) -> tuple[float, float]:
        from meerk40t.core.units import Length

        device = getattr(self.kernel, "device", None)

        def side(name, fallback):
            try:
                return float(Length(getattr(device, name)).mm)
            except Exception:
                return fallback

        return side("bedwidth", 500.0), side("bedheight", 300.0)

    def _add_polygon(
        self, points, label: str, subpaths: bool = False, intent: str = "cut"
    ):
        """
        Adding a closed shape straight in as geometry.

        *Not* through the `path` command: that reads its d-string as SVG user units and
        then scales it again, which made a box of 100 mm come out as 72 metres. Geomstr
        computes in Tats and leaves no room for that confusion.
        """
        from meerk40t.core.geomstr import Geomstr
        from meerk40t.core.units import UNITS_PER_MM

        geometry = Geomstr()
        groups = points if subpaths else [points]
        for group in groups:
            corners = [complex(px * UNITS_PER_MM, py * UNITS_PER_MM) for px, py in group]
            for start, end in zip(corners, corners[1:] + corners[:1]):
                geometry.line(start, end)
        node = self.elements.elem_branch.add(
            geometry=geometry,
            type="elem path",
            stroke=self.elements.default_stroke,
            stroke_width=self.elements.default_strokewidth,
            label=label,
        )
        # Put it in one layer explicitly, not through colour classification: that puts a
        # box panel in an *engrave* layer *and* straight away in a second layer claiming the
        # same colour. Then the same panel burns twice, and you only notice that on
        # material.
        if intent:
            self._file_under(node, intent)
        return node

    def _add_geometry(self, geometry, label: str, intent: str = "cut"):
        """
        A finished Geomstr in millimetres straight in as one element.

        The open-path sibling of `_add_polygon`: that one closes every ring
        (`corners[1:] + corners[:1]`), and a slit is a line. Closed, the laser would run
        every slit twice — once there and once back over the same cut.
        """
        from meerk40t.core.geomstr import Geomstr
        from meerk40t.core.units import UNITS_PER_MM

        scaled = Geomstr(geometry)
        scaled.uscale(UNITS_PER_MM)
        node = self.elements.elem_branch.add(
            geometry=scaled,
            type="elem path",
            stroke=self.elements.default_stroke,
            stroke_width=self.elements.default_strokewidth,
            label=label,
        )
        if intent:
            self._file_under(node, intent)
        return node

    def _file_under(self, node, intent: str):
        """The shape in one layer of the requested kind, and in nothing else."""
        label = {"cut": "Cut", "engrave": "Engrave"}.get(intent, "Cut")
        for operation in self.elements.ops():
            if operation.type == f"op {intent}" and getattr(operation, "label", "") == label:
                target = operation
                break
        else:
            made = self.drawing.create_operation(kind=intent, label=label)
            target = self.elements.find_node(made["id"])
        if target is not None:
            target.add_reference(node)

    def _refresh(self):
        self.elements.signal("rebuild_tree", "all")
        self.elements.signal("refresh_scene", "Scene")

    def _count(self, value, what: str) -> int:
        try:
            count = int(value)
        except (TypeError, ValueError) as e:
            raise DesignError(f"The number of {what} has to be a whole number.") from e
        if not 1 <= count <= 500:
            raise DesignError(f"The number of {what} has to be between 1 and 500.")
        return count

    def _selection(self, ids):
        from contextlib import contextmanager

        @contextmanager
        def scope():
            nodes = []
            for element_id in ids or []:
                node = self.elements.find_node(element_id)
                if node is None:
                    raise DesignError(f"Element {element_id} does not exist (any more).")
                nodes.append(node)
            if not nodes:
                raise DesignError("Choose what should be repeated first.", code="gen.needsSelection")
            self.elements.set_emphasis(nodes)
            yield nodes

        return scope()

    def _added(self, generator: str, expected: int) -> dict:
        self.elements.validate_ids()
        self._recalculate_bounds()
        self.elements.signal("rebuild_tree", "all")
        self.elements.signal("refresh_scene", "Scene")
        return {"generator": generator, "expected": expected}

    def _recalculate_bounds(self):
        """
        De omhullende again laten uitrekenen na een herhaling.

        `grid` and `radial` make their copies with `copy(node)` and then shift them with a
        raw `e.matrix *= ...` (core/elements/grid.py:240,360). That assignment reports
        nothing to the node, so the copy keeps the bounding box it got from the original —
        `bounds` points at the old place while `as_geometry()` gives the new one. On the
        canvas that is exactly what you see: the copy you clicked gets its thick border, but
        the handles sit around the original.

        We cannot fix that in the engine from here (core principle 1), so we ask the nodes to
        forget their bounding box. See the upstream list.
        """
        for node in self.elements.elems():
            marker = getattr(node, "set_dirty_bounds", None)
            if marker is not None:
                marker()


# The three slit shapes of the living hinge, and what each one does. The key is data (it
# travels in the request and out again); the value is the English name the window shows —
# "staggered rows" and not "pattern 2", because that is the difference you have to be able
# to see without burning it first.
PATTERN_LABELS = {
    "straight": "straight slits",
    "staggered": "staggered rows",
    "wavy": "wavy slits",
}


def _subpaths(geometry) -> int:
    """
    How many loose pieces are in this geometry.

    Not the same as the number of segments: a wavy slit is two quads. A piece begins where
    a segment does not carry on from the previous one, and `clip_geometry` keeps the order,
    so the two halves of one wave stay next to each other.
    """
    count, previous = 0, None
    for index in range(geometry.index):
        start = complex(geometry.segments[index][0])
        if previous is None or abs(start - previous) > 1e-9:
            count += 1
        previous = complex(geometry.segments[index][4])
    return count


def _as_d(groups) -> tuple[str, tuple[float, float, float, float]]:
    """Closed polygons as one d-string, with the box around them."""
    parts, xs, ys = [], [], []
    for points in groups:
        if not points:
            continue
        parts.append(
            "M" + " L".join(f"{x:.4g},{y:.4g}" for x, y in points) + " Z"
        )
        xs += [x for x, _ in points]
        ys += [y for _, y in points]
    if not parts:
        raise DesignError("No shape comes out of this.")
    return " ".join(parts), (min(xs), min(ys), max(xs), max(ys))


def _extent(boxes, parts):
    """
    The box around everything, in mm.

    For a rotated copy we rotate the four corners of its box along. That is slightly more
    generous than the shape itself, and that is allowed: this only decides how far the
    preview zooms out.
    """
    xs, ys = [], []
    for part in parts:
        x0, y0, x1, y1 = boxes[part["shape"]]
        corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        angle = math.radians(part.get("rot") or 0.0)
        px, py = part.get("rx", 0.0), part.get("ry", 0.0)
        for cx, cy in corners:
            dx, dy = cx - px, cy - py
            rx = px + dx * math.cos(angle) - dy * math.sin(angle)
            ry = py + dx * math.sin(angle) + dy * math.cos(angle)
            xs.append(part["x"] + rx)
            ys.append(part["y"] + ry)
    if not xs:
        return [0.0, 0.0, 0.0, 0.0]
    return [min(xs), min(ys), max(xs), max(ys)]


def _bend_in_place(geometry, bounds, cx, cy, scale, inside):
    """
    Bending straight text around a circle. Everything in Tats.

    Every point moves to the circle: the distance to the baseline becomes the distance to
    the centre, the place along the line becomes the angle. That way the letter height stays
    right and nothing stretches.

    Stands apart because the preview has to make exactly the same bend as the real work —
    including the bound above which the text runs over itself, because that is the message
    the form shows.
    """
    x0, _, x1, y1 = bounds
    if x1 - x0 >= 2 * math.pi * scale * 0.98:
        raise DesignError(
            "This text is too long for this radius; it would run over itself. "
            "Choose a larger radius or a smaller letter.",
            code="gen.arcTooLong",
        )
    middle = (x0 + x1) / 2
    baseline = y1  # the bottom of the text

    def bend(point):
        if point != point:  # NaN: not a point but a marker
            return point
        angle = (point.real - middle) / scale
        above = baseline - point.imag
        if inside:
            distance = scale - above
            return complex(
                cx + distance * math.sin(-angle), cy + distance * math.cos(-angle)
            )
        distance = scale + above
        return complex(
            cx + distance * math.sin(angle), cy - distance * math.cos(angle)
        )

    for row in geometry.segments[: geometry.index]:
        # Column 2 carries the segment type, not a point; that one is left alone.
        for column in (0, 1, 3, 4):
            row[column] = bend(complex(row[column]))


# Which side has the tooth and which the gap. Two panels that join have to be opposite
# here; `test_generators.py` checks that for every pair. Key: (panel, edge) → True when this
# panel has the tooth on that edge.
PHASE = {
    ("front", "left"): True,
    ("front", "right"): True,
    ("front", "under"): True,
    ("back", "left"): True,
    ("back", "right"): True,
    ("back", "under"): True,
    ("left", "front"): False,
    ("left", "back"): False,
    ("left", "under"): True,
    ("right", "front"): False,
    ("right", "back"): False,
    ("right", "under"): True,
    ("bottom", "front"): False,
    ("bottom", "back"): False,
    ("bottom", "left"): False,
    ("bottom", "right"): False,
    ("lid", "front"): False,
    ("lid", "back"): False,
    ("lid", "left"): False,
    ("lid", "right"): False,
    # The top edge of every wall, the mirror image of the bottom edge: that is where the
    # lid engages, just as the bottom engages below. Only drawn when there is a lid — see
    # `box_panels`.
    ("front", "over"): True,
    ("back", "over"): True,
    ("left", "over"): True,
    ("right", "over"): True,
}

# Which edge of which panel fits which edge of which other panel.
JOINTS = [
    (("front", "left"), ("left", "front")),
    (("front", "right"), ("right", "front")),
    (("back", "left"), ("left", "back")),
    (("back", "right"), ("right", "back")),
    (("front", "under"), ("bottom", "front")),
    (("back", "under"), ("bottom", "back")),
    (("left", "under"), ("bottom", "left")),
    (("right", "under"), ("bottom", "right")),
    # The same again, at the top. These were missing, which is why the lid came out of the
    # machine as a bottom without counterparts: cut-outs all round and a dead straight top
    # edge on every wall for them to drop into. Found on the wood.
    (("front", "over"), ("lid", "front")),
    (("back", "over"), ("lid", "back")),
    (("left", "over"), ("lid", "left")),
    (("right", "over"), ("lid", "right")),
]


def teeth_count(length: float, finger: float) -> int:
    """
    Always odd, so that an edge begins *and* ends with material.

    Two panels that join compute this with the same length and so arrive at the same number
    — that is why the teeth fit each other.
    """
    count = max(3, int(length // finger))
    return count if count % 2 else count - 1


def edge_points(start, end, thickness, finger, kerf, tab_first: bool):
    """
    One edge, from start to end, with teeth sticking outwards.

    The kerf is added to the tooth (half a kerf on each side): the laser takes material off
    both sides of the cut, so a tooth that fits exactly on paper is too narrow in wood.
    """
    (x0, y0), (x1, y1) = start, end
    length = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
    if length <= 0:
        return []
    count = teeth_count(length, finger)
    step = length / count
    dx, dy = (x1 - x0) / length, (y1 - y0) / length
    # Perpendicular, outwards (the edge runs clockwise around the panel).
    nx, ny = dy, -dx
    depth = thickness

    points = []
    for index in range(count):
        tab = (index % 2 == 0) == tab_first
        a = index * step
        b = (index + 1) * step
        if tab:
            a -= kerf / 2
            b += kerf / 2
        else:
            a += kerf / 2
            b -= kerf / 2
        out = depth + kerf / 2 if tab else 0.0
        for value in (a, b):
            points.append(
                (x0 + dx * value + nx * out, y0 + dy * value + ny * out)
            )
    return points


def panel_outline(name, w, h, thickness, finger, kerf, edges):
    """
    One panel as a closed outline, clockwise: bottom, right, top, left.

    `edges` says which box edge each side is; edges that join nothing (the top of a wall on
    an open box, for instance) become straight.
    """
    corners = [((0.0, 0.0), (w, 0.0)), ((w, 0.0), (w, h)), ((w, h), (0.0, h)), ((0.0, h), (0.0, 0.0))]
    points = []
    for (start, end), edge in zip(corners, edges):
        if edge is None:
            points.append(start)
            points.append(end)
            continue
        points += edge_points(
            start, end, thickness, finger, kerf, PHASE[(name, edge)]
        )
    return points


def box_panels(width, depth, height, thickness, finger, kerf, lid=True):
    """
    The box's panels, each as a closed outline starting at (0, 0).

    The edges run clockwise: bottom, right, top, left. Which box edge that is differs per
    panel — a wall touches the bottom at its lower edge, the bottom touches that wall at its
    own front edge.
    """
    # The top edge of a wall: straight on an open box, with teeth as soon as a lid has to go
    # on. Without this choice, on an open box you cut an edge full of protrusions with
    # nothing to go on them.
    top = "over" if lid else None
    panels = [
        ("bottom", width, depth, ("front", "right", "back", "left")),
        ("front", width, height, ("under", "right", top, "left")),
        ("back", width, height, ("under", "right", top, "left")),
        ("left", depth, height, ("under", "front", top, "back")),
        ("right", depth, height, ("under", "back", top, "front")),
    ]
    if lid:
        panels.append(("lid", width, depth, ("front", "right", "back", "left")))
    return [
        (name, panel_outline(name, w, h, thickness, finger, kerf, edges))
        for name, w, h, edges in panels
    ]


def _lay_out(panels, width, height, gap):
    """
    Laying the panels out in rows, and starting a new sheet as soon as one is full.

    Hands back a list of sheets, each with (name, points, x, y). Pure arithmetic: only once
    it is settled how many sheets it becomes is anything drawn.
    """
    pages, page = [], []
    x, y, shelf = gap, gap, 0.0
    for name, points in panels:
        span = max(px for px, _ in points) - min(px for px, _ in points)
        high = max(py for _, py in points) - min(py for _, py in points)
        if x > gap and x + span > width - gap:
            x = gap
            y += shelf + gap
            shelf = 0.0
        if y + high + gap > height:
            pages.append(page)
            page, x, y, shelf = [], gap, gap, 0.0
        page.append((name, points, x, y))
        x += span + gap
        shelf = max(shelf, high)
    if page:
        pages.append(page)
    return pages
