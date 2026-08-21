"""
The running tile series: the plan per tile, and where you are in the series.

The clipping and moving happens on the **copy** `plan copy` makes.
`copy_children_as_real` (meerk40t/core/node/node.py:805) dereferences the ReferenceNodes and
copies the shapes themselves, so everything that happens here leaves the user's element tree
alone. That is not a side issue but the reason this design has to touch so little.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from .edits import DesignError
from .tiling import (
    Alignment,
    Point,
    Rect,
    TilingError,
    TilingSettings,
    alignment,
    alignment_from_corner,
    best_split,
    clip_geometry,
    marker_spots,
    tile_layout,
)

#: The speed and power of an alignment mark. A mark does not have to be deep, it has to be
#: visible: burning it in hard actually makes the edge vaguer to aim at, and on thin
#: material you cut straight through.
MARKER_SPEED_MM_S = 60.0
MARKER_POWER = 300.0  # 30 %


#: The two digits we will ever need, as a polyline in a unit box: x and y from 0 to 1, y
#: downwards as in the scene itself. Drawn ourselves, because pulling in a font engine for
#: two glyphs is out of proportion — and besides, `linetext` overwrites `last_font` on every
#: call (CLAUDE.md). One continuous stroke per digit: a laser burns that in one movement.
DIGITS = {
    1: [(0.15, 0.22), (0.5, 0.0), (0.5, 1.0)],
    2: [
        (0.08, 0.22),
        (0.26, 0.0),
        (0.62, 0.0),
        (0.8, 0.22),
        (0.8, 0.42),
        (0.1, 1.0),
        (0.86, 1.0),
    ],
}


def digit_geometry(digit: int, x: float, y: float, height: float):
    """
    One digit as geometry, with its top-left corner at (x, y).

    `height` is the full height; the width follows from the digit's shape.
    """
    from meerk40t.core.geomstr import Geomstr

    points = DIGITS.get(digit)
    if points is None:
        raise ValueError(f"No digit drawn for {digit}.")
    geom = Geomstr()
    vorig = None
    for px, py in points:
        nu = complex(x + px * height, y + py * height)
        if vorig is not None:
            geom.line(vorig, nu)
        vorig = nu
    return geom


def marker_geometry(points, size_mm: float, units_per_mm: float, along_y: bool = True):
    """
    The alignment marks as geometry: a circle with a cross in it, *and* its number.

    The circle gives an edge to aim the head at that a bare cross does not have; the cross's
    intersection is the point you tap.

    **The number is burned along, and that is the whole reason it exists.** Saying "mark 1"
    on screen is worth nothing when two identical circles lie on the board — then a word for
    a position ("the left one") is still better, and that word was precisely the problem: it
    depends on `flip_x`, `swap_xy` and the home corner, and so can be reversed. A burned digit
    depends on nothing.

    `along_y` says whether the zone is tall and narrow (digit below the circle) or wide and
    low (digit beside it). That is all the drawing needs from the zone, so that is what we
    pass along instead of the rectangle — for the same reason as in `mark_footprint`: the
    width of the overlap is the tight measure, so nothing is ever added there.
    """
    from meerk40t.core.geomstr import Geomstr

    from .tiling import CIJFER_FRACTIE, CIJFER_GAT_MM

    straal = size_mm / 2 * units_per_mm
    height = size_mm * CIJFER_FRACTIE * units_per_mm
    gat = CIJFER_GAT_MM * units_per_mm
    geom = Geomstr()
    for nummer, punt in enumerate(points, 1):
        cx = punt.x_mm * units_per_mm
        cy = punt.y_mm * units_per_mm
        geom.append(Geomstr.circle(straal, cx, cy))
        geom.line(complex(cx - straal, cy), complex(cx + straal, cy))
        geom.end()
        geom.line(complex(cx, cy - straal), complex(cx, cy + straal))
        geom.end()
        if along_y:
            hoek_x, hoek_y = cx - height / 2, cy + straal + gat
        else:
            hoek_x, hoek_y = cx + straal + gat, cy - height / 2
        geom.append(digit_geometry(nummer, hoek_x, hoek_y, height))
        geom.end()
    return geom


class TileMutator:
    """
    One tile: clip the plan to the burn area and put it where the board lies.

    Scene coordinates are board coordinates — the design is drawn on the board and the engine
    reads the scene as the bed. So the alignment matrix may be applied directly in the scene,
    just as `Drawing.shifted` applies the zero point.
    """

    def __init__(
        self,
        burn_mm: Rect,
        alignment: Alignment,
        units_per_mm: float,
        marker_geometry=None,
    ):
        self.burn_mm = burn_mm
        self.alignment = alignment
        self.units_per_mm = units_per_mm
        self.marker_geometry = marker_geometry
        #: how much clipped geometry this tile burns, in engine units. Counted here and not
        #: read from the plan afterwards: `blob` replaces the operations with one CutCode, and
        #: then this can no longer be recovered. The marks do not count — they belong to the
        #: machine, not to the work.
        self.burned_length_units = 0.0

    # ------------------------------------------------------------- rekenen

    @property
    def burn_units(self) -> Rect:
        u = self.units_per_mm
        return Rect(
            self.burn_mm.x0 * u,
            self.burn_mm.y0 * u,
            self.burn_mm.x1 * u,
            self.burn_mm.y1 * u,
        )

    def matrix(self):
        """The alignment as a matrix in engine units."""
        from meerk40t.svgelements import Matrix

        u = self.units_per_mm
        mx = Matrix()
        mx.post_rotate(math.radians(self.alignment.angle_deg))
        mx.post_translate(self.alignment.dx_mm * u, self.alignment.dy_mm * u)
        return mx

    # ------------------------------------------------------------ bewerken

    def __call__(self, steps):
        blijft = []
        for step in steps:
            children = getattr(step, "children", None)
            if children is None:
                blijft.append(step)
                continue
            if self._reshape(step):
                blijft.append(step)
        if self.marker_geometry is not None and self.marker_geometry.index:
            blijft.append(self._marker_operation())
        return blijft

    def _marker_operation(self):
        """
        The marks as the tile's last operation.

        They undergo the same alignment as the rest: they are burned on the board, so they
        have to land on the board where the division computed them.
        """
        from meerk40t.core.node.elem_path import PathNode
        from meerk40t.core.node.op_engrave import EngraveOpNode
        from meerk40t.svgelements import Color, Matrix

        geom = type(self.marker_geometry)(self.marker_geometry)
        geom.transform(self.matrix())
        operation = EngraveOpNode(
            label="Alignment marks",
            speed=MARKER_SPEED_MM_S,
            power=MARKER_POWER,
        )
        operation.add_node(
            PathNode(geom, matrix=Matrix(), stroke=Color("black"), fill=None)
        )
        return operation

    def _reshape(self, operation) -> bool:
        """Clip the children of this operation. Returns whether anything is left."""
        from meerk40t.core.node.elem_path import PathNode
        from meerk40t.svgelements import Matrix

        window = self.burn_units
        mx = self.matrix()
        vervangers = []
        for child in list(operation.children):
            geom = self._geometry(child)
            if geom is None:
                # A node without geometry — an image. See `_belongs_here`: it comes along
                # as a whole or not at all.
                if self._belongs_here(child):
                    vervangers.append(self._moved_image(child, mx))
                continue
            clipped = clip_geometry(geom, window)
            if clipped.index == 0:
                continue
            self.burned_length_units += sum(
                abs(clipped.length(i)) for i in range(clipped.index)
            )
            clipped.transform(mx)
            vervangers.append(
                PathNode(
                    clipped,
                    matrix=Matrix(),
                    stroke=getattr(child, "stroke", None),
                    fill=getattr(child, "fill", None),
                    stroke_width=getattr(child, "stroke_width", 1000.0),
                )
            )

        for child in list(operation.children):
            child.remove_node()
        for node in [v for v in vervangers if v is not None]:
            operation.add_node(node)
        return bool(operation.children)

    def _belongs_here(self, node) -> bool:
        """
        Does this image belong to this tile? All or nothing.

        An image has no `as_geometry`, so clipping as with a shape is impossible. Burning half
        a photo would require cropping the bitmap itself, and a rotated image cannot be
        cropped on a straight seam without burning an edge twice in *both* tiles — precisely
        what we carefully avoid with shapes.

        So: an image falls entirely within one burn area, or it does not come along. If it
        lies across a seam, that is refused with a sentence when dividing (`TileRun.layout`),
        not silently doubled into two tiles here. Without this test a photo was burned in
        *every* tile, in the wrong place.
        """
        bounds = getattr(node, "bounds", None)
        if not bounds:
            # No bounding box means: we do not know where it lies. Sending it along would
            # burn it in every tile, so we leave it be.
            return False
        window = self.burn_units
        x0, y0, x1, y1 = bounds
        return (
            window.x0 <= x0
            and x1 <= window.x1
            and window.y0 <= y0
            and y1 <= window.y1
        )

    @staticmethod
    def _geometry(node):
        maker = getattr(node, "as_geometry", None)
        if maker is None:
            return None
        try:
            return maker()
        except Exception:
            return None

    @staticmethod
    def _moved_image(node, mx):
        """An image moves along; it carries its own matrix."""
        matrix = getattr(node, "matrix", None)
        if matrix is None:
            return node
        node.matrix.post_cat(mx)
        marker = getattr(node, "set_dirty_bounds", None)
        if marker is not None:
            # A raw matrix assignment reports nothing to the node; without this it carries
            # the bounding box of its old place.
            marker()
        return node


class TileRun:
    """
    Where you are in a tile series, and what the next step is.

    The series is on disk beside `sheets.json`: a board of 900 mm is hours of work, and that
    has to survive a page refresh. The alignment is emphatically *not* in it — see `align`.
    """

    def __init__(self, kernel, drawing, sheets, runner, path):
        self.kernel = kernel
        self.drawing = drawing
        self.sheets = sheets
        self.runner = runner
        self.path = Path(path)
        self._alignment = None

    # ------------------------------------------------------------- opslag

    def _read(self) -> dict | None:
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def _write(self, data: dict | None) -> None:
        if data is None:
            self.path.unlink(missing_ok=True)
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=1, ensure_ascii=False))

    # ------------------------------------------------------------ layout

    def _sheet(self) -> dict:
        for sheet in self.sheets.state()["sheets"]:
            if sheet.get("active"):
                return sheet
        raise DesignError("There is no active sheet.")

    def _settings(self, sheet) -> TilingSettings:
        blok = sheet.get("tiling") or {}
        return TilingSettings(
            margin_mm=float(blok.get("margin_mm", 10.0)),
            overlap_mm=float(blok.get("overlap_mm", 25.0)),
            marker_size_mm=float(blok.get("marker_size_mm", 8.0)),
        )

    def layout(self) -> dict:
        """
        The active sheet's division. Computed, never stored.

        It is a function of the measures, the settings and the design, so it holds by itself
        as soon as something about them changes.
        """
        sheet = self._sheet()
        bed = self.drawing.bed_mm()
        if bed is None:
            raise DesignError("This machine reports no bed size.")
        settings = self._settings(sheet)
        try:
            tiles = tile_layout(
                sheet["width_mm"], sheet["height_mm"], bed[0], bed[1], settings
            )
        except TilingError as e:
            raise DesignError(str(e)) from e

        spans = self._shape_spans()
        tiles = self._nudge_seams(tiles, spans, settings)
        self._check_images(tiles)
        return {
            "tiles": [
                self._tile_json(t, tiles[i - 1] if i else None)
                for i, t in enumerate(tiles)
            ],
            "marks": self._marks(tiles, settings),
            "crossings": self._crossings(tiles, spans),
        }

    def _shape_spans(self) -> list:
        """The bounding boxes of every shape, in millimetres."""
        u = self.drawing._units_per_mm()
        vakken = []
        for node in self.kernel.elements.elems():
            bounds = getattr(node, "bounds", None)
            if not bounds:
                continue
            x0, y0, x1, y1 = bounds
            vakken.append(Rect(x0 / u, y0 / u, x1 / u, y1 / u))
        return vakken

    def _nudge_seams(self, tiles, spans, settings):
        """
        The seam within the overlap zone moved to where it crosses the fewest shapes.

        Only on the axis the division runs along; on the other axis there is no seam. Both
        axes at once does not exist — `tile_layout` refuses that.

        **Read from `adjusted`, not from `tiles`.** Every seam touches two tiles, so the
        middle tile is written twice: first its start by the seam before it, then its end by
        the seam after it. Anybody taking the original as the basis for that second write
        throws the first away — and then tile 0 ends on the moved seam while tile 1 still
        starts on the old one. Measured on a board of 200×500: tile 0 up to 150.0 and tile 1
        from 175.0, a gap of 25 mm that belongs to no tile and so is never burned. That
        stayed hidden as long as the moving changed nothing, which is the case when there is
        nothing to avoid.
        """
        if len(tiles) < 2:
            return tiles
        horizontal = len({t.column for t in tiles}) > 1
        adjusted = list(tiles)
        for index in range(len(tiles) - 1):
            left, right = adjusted[index], adjusted[index + 1]
            if horizontal:
                # The window does not move along, so the zone stays the zone.
                seam = best_split(
                    right.window.x0, left.window.x1, [(s.x0, s.x1) for s in spans]
                )
                adjusted[index] = left._replace(burn=left.burn._replace(x1=seam))
                adjusted[index + 1] = right._replace(
                    burn=right.burn._replace(x0=seam)
                )
            else:
                seam = best_split(
                    right.window.y0, left.window.y1, [(s.y0, s.y1) for s in spans]
                )
                adjusted[index] = left._replace(burn=left.burn._replace(y1=seam))
                adjusted[index + 1] = right._replace(
                    burn=right.burn._replace(y0=seam)
                )
        return adjusted

    def _check_images(self, tiles) -> None:
        """
        Refuse an image that lies across a seam.

        Shapes are cut in half on the seam; an image is not — it has no geometry to split,
        and cropping a bitmap on a seam would burn an edge twice in both tiles for a rotated
        image. So an image belongs entirely in one tile, and when that is impossible we say
        so, instead of silently leaving it out or repeating it in every tile.
        """
        u = self.drawing._units_per_mm()
        for node in self.kernel.elements.elems():
            if str(getattr(node, "type", "")) != "elem image":
                continue
            bounds = getattr(node, "bounds", None)
            if not bounds:
                continue
            x0, y0, x1, y1 = (v / u for v in bounds)
            past = any(
                t.burn.x0 <= x0
                and x1 <= t.burn.x1
                and t.burn.y0 <= y0
                and y1 <= t.burn.y1
                for t in tiles
            )
            if not past:
                name = getattr(node, "label", None) or "an image"
                raise DesignError(
                    f"{name} lies across the seam between two tiles. An image "
                    "cannot be cut in half: move it so that it falls within one tile, "
                    "or make the overlap larger."
                )

    def _marks(self, tiles, settings) -> list[dict]:
        """
        Two marks per boundary. Refuses when there is no room somewhere.

        Deliberately here and not only at that tile: without room on boundary 2 the whole
        series is unworkable, and you should know that before the first tile.
        """
        blokkade = self._shape_spans()
        marks = []
        for left, right in zip(tiles, tiles[1:]):
            zone = Rect(
                max(left.window.x0, right.window.x0),
                max(left.window.y0, right.window.y0),
                min(left.window.x1, right.window.x1),
                min(left.window.y1, right.window.y1),
            )
            try:
                een, twee = marker_spots(zone, blokkade, settings.marker_size_mm)
            except TilingError as e:
                raise DesignError(
                    f"Tussen tile {left.index + 1} and {right.index + 1}: {e}"
                ) from e
            marks.append(
                {
                    "boundary": left.index,
                    # Which axis is the long one: a mark's digit sits along it, and the
                    # canvas has to put it on the same side.
                    "along_y": zone.height >= zone.width,
                    "points": [
                        {"x_mm": een.x_mm, "y_mm": een.y_mm},
                        {"x_mm": twee.x_mm, "y_mm": twee.y_mm},
                    ],
                }
            )
        return marks

    @staticmethod
    def _crossings(tiles, spans) -> int:
        """
        Hoeveel vormen door een seam gaan.

        On the axis the division runs along, and that is not always x: a board that is only
        too *tall* is divided into bands and then has no x seam at all. Counting on x alone
        gave zero there while shapes were
        indeed being cut in half — silently wrong, and this is the very number on which
        somebody decides to move a shape. Both axes at once does not exist: `tile_layout`
        refuses that.
        """
        if len(tiles) < 2:
            return 0
        if len({t.column for t in tiles}) > 1:
            seams = sorted({t.burn.x1 for t in tiles[:-1]})
            return sum(1 for x in seams for s in spans if s.x0 < x < s.x1)
        seams = sorted({t.burn.y1 for t in tiles[:-1]})
        return sum(1 for y in seams for s in spans if s.y0 < y < s.y1)

    def _tile_json(self, tile, vorige=None) -> dict:
        """
        One tile for the outside world, with how far the board has to shift.

        That shift is the step between the **windows**, not between the burn areas. That
        difference is not academic: the burn areas sit half an overlap further apart than the
        windows, and anybody shifting the board over that larger distance shifts the marks
        off the bed. Measured on a board of 500 mm with a bed of 235: with the burn step
        (178.75 mm) the marks land at bed-x −31.5 and 28.5 — the first is unreachable. With
        the window step (142.5 mm) they land at 5.0 and 65.0.

        The window itself does not come out: that is an internal concept, and what the user
        needs is the distance, not the rectangle.
        """
        return {
            "index": tile.index,
            "row": tile.row,
            "column": tile.column,
            "burn": {
                "x0_mm": tile.burn.x0,
                "y0_mm": tile.burn.y0,
                "x1_mm": tile.burn.x1,
                "y1_mm": tile.burn.y1,
            },
            "shift_mm": (
                None
                if vorige is None
                else {
                    "x": round(tile.window.x0 - vorige.window.x0, 2),
                    "y": round(tile.window.y0 - vorige.window.y0, 2),
                }
            ),
        }

    # ------------------------------------------------------------- de reeks

    def _fingerprint(self, sheet) -> str:
        """
        Een goedkope samenvatting van ontwerp en board.

        Enough to see *that* something has changed; not meant to say *what*. Declaring it
        invalid when in doubt is the cheap answer here.

        **With sha1 and emphatically not with `hash()`.** Python salts the hash of strings
        per process, so a `hash()` that goes to disk is guaranteed to come back different
        after a restart — and then *every* resumed series is invalid, precisely the case this
        file exists for. That cannot be seen in a test that makes two servers in the same
        process; only a real restart shows it. Measured: the same tuple gave
        1444352915328149249 and 5992177919278113137 in two processes.
        """
        import hashlib

        stukken = [
            f"{sheet['width_mm']}x{sheet['height_mm']}",
            json.dumps(sheet.get("tiling"), sort_keys=True),
        ]
        for node in self.kernel.elements.elems():
            bounds = getattr(node, "bounds", None)
            stukken.append(
                f"{node.type}:"
                + ("-".join(f"{v:.1f}" for v in bounds) if bounds else "?")
            )
        return hashlib.sha1("|".join(stukken).encode()).hexdigest()

    def state(self) -> dict | None:
        data = self._read()
        if data is None:
            return None
        try:
            sheet = self._sheet()
        except DesignError:
            # Vangnet, geen pad: `Sheets` houdt er altijd precies één actief
            # (`remove` activates another one first, `_ensure` repairs a broken reference),
            # so nobody comes here along the normal route. It is here because `state()` is
            # read from the status payload: if this ever does throw, it is not this series
            # that falls over but the whole status request. Throwing a sheet away during a
            # series ends up below, at the ordinary comparison on sheet_id.
            return {
                **data,
                "aligned": False,
                "stale": True,
                "message": (
                    "The sheet this tile run belongs to is gone or is no longer "
                    "active. Choose that sheet again, or stop the run."
                ),
            }
        stale = data.get("sheet_id") != sheet["id"] or data.get(
            "fingerprint"
        ) != self._fingerprint(sheet)
        return {
            **data,
            "aligned": self._alignment is not None,
            # The measured pose belongs with the alignment and therefore with the state, not
            # only with `align`'s answer. Without this "1.2°
            # out · 0.3 mm error" disappeared from the screen at the next status report, a
            # few seconds after the user had read it — and that number is precisely their
            # confirmation that the board lies right.
            "angle_deg": (
                round(self._alignment.angle_deg, 3) if self._alignment else None
            ),
            "distance_error_mm": (
                round(self._alignment.distance_error_mm, 2) if self._alignment else None
            ),
            "stale": stale,
            "message": (
                "The design or the plate has changed since this run began. The "
                "tiles already burned belong to the old design; carrying on "
                "would give you half old and half new."
                if stale
                else ""
            ),
        }

    def start(self) -> dict:
        sheet = self._sheet()
        if not (sheet.get("tiling") or {}).get("enabled"):
            raise DesignError(
                "Tiles are switched off for this sheet. Switch them on at the plate size."
            )
        layout = self.layout()  # refuses here already when no marks fit
        self._alignment = None
        self._write(
            {
                "sheet_id": sheet["id"],
                "tiles": len(layout["tiles"]),
                "done": [],
                "current": 0,
                "fingerprint": self._fingerprint(sheet),
            }
        )
        return self.state()

    def align(self, points, reference: str = "markers") -> dict:
        """
        Turning the tapped points into a pose for the board.

        The result stays in this run's memory. As soon as you leave the app or finish a tile
        it lapses and you have to tap again: a stored alignment is an assumption about where
        the board lies, and that is exactly what you must not trust after a break.
        """
        # The same gate as with `burn`: if the series has lapsed — sheet gone, design changed
        # — the user should read *that*, and not a message about sheets rising up from the
        # depths while they are tapping a mark.
        state = self.state()
        if state is None:
            raise DesignError("There is no tile run going.")
        if state["stale"]:
            raise DesignError(state["message"])
        data = self._read()
        gemeten = [Point(float(p["x_mm"]), float(p["y_mm"])) for p in points]
        try:
            if reference == "plate_corner":
                if not gemeten:
                    raise DesignError("Tap the corner of the plate first.")
                self._alignment = alignment_from_corner(Point(0.0, 0.0), gemeten[0])
            else:
                if len(gemeten) != 2:
                    raise DesignError("Uitlijnen vraagt twee aangetikte marks.")
                marks = self._marks_for(data["current"] - 1)
                self._alignment = alignment(
                    marks[0], marks[1], gemeten[0], gemeten[1]
                )
        except TilingError as e:
            self._alignment = None
            raise DesignError(str(e)) from e
        # `state()` now carries `angle_deg`/`distance_error_mm` itself, so this is no longer
        # the only answer that passes them along.
        return self.state()

    def _marks_for(self, boundary: int) -> tuple:
        for mark in self.layout()["marks"]:
            if mark["boundary"] == boundary:
                return tuple(Point(p["x_mm"], p["y_mm"]) for p in mark["points"])
        raise DesignError("No marks have been calculated for this tile.")

    def burn(self, confirm_reburn: bool = False) -> dict:
        # First whether the series is still valid, only then whether it is aligned. The
        # other way round, somebody with a lapsed series is told they "still have to align" —
        # an invitation to tap marks on a division that no longer holds. The same gate as with
        # `align`.
        state = self.state()
        if state is None:
            raise DesignError("There is no tile run going.")
        if state["stale"]:
            raise DesignError(state["message"])
        if self._alignment is None:
            raise DesignError(
                "This tile has not been aligned yet. Tap the two marks first, "
                "otherwise the machine does not know where the plate is."
            )
        data = self._read()
        index = data["current"]
        if index in data.get("burned", []) and not confirm_reburn:
            raise DesignError(
                "This tile has already been burned. Burning it again means the "
                "laser goes over work that is already there — only do that when the "
                "previous attempt was aborted. Confirm to carry on."
            )

        layout = self.layout()
        tile = layout["tiles"][index]
        burn = self._brandgebied(tile, layout["tiles"])
        u = self.drawing._units_per_mm()
        marks = [m for m in layout["marks"] if m["boundary"] == index]
        geom = (
            marker_geometry(
                [Point(p["x_mm"], p["y_mm"]) for p in marks[0]["points"]],
                self._settings(self._sheet()).marker_size_mm,
                u,
                marks[0].get("along_y", True),
            )
            if marks
            else None
        )
        mutator = TileMutator(burn, self._alignment, u, marker_geometry=geom)
        mark_points = [Point(p["x_mm"], p["y_mm"]) for m in marks for p in m["points"]]
        self._check_bed(burn, mutator, mark_points)
        # Two shifts on top of each other is a mistake you only see on material: the tile
        # matrix already does what the zero point would do, and it is measured rather than
        # set.
        with self.drawing.verschoven(None):
            self.runner.start_job(f"Tegel {index + 1}", mutators=[mutator])
        data["burned"] = sorted(set(data.get("burned", [])) | {index})
        self._write(data)
        return {
            **self.state(),
            # What this tile really burns. Counted while clipping, because afterwards the
            # plan consists of cutcode and it can no longer be seen.
            "burned_length_mm": round(mutator.burned_length_units / u, 2),
        }

    #: What the board's outer edge is stretched by. `clip_geometry` keeps its upper edge
    #: open so that geometry exactly on a seam falls into precisely one tile; on the board's
    #: outer edge there is no next tile to catch it, so there a line lying exactly on the
    #: edge would drop out. A hair is enough: this is a tie-break, not a measure.
    BOARD_EDGE_MARGIN_MM = 1e-6

    def _brandgebied(self, tile, alle) -> Rect:
        """
        This tile's burn area, with the board's outer edge stretched.

        See `BOARD_EDGE_MARGIN_MM`: the upper edge of a burn area belongs to the next tile,
        but the last tile has none, so there the edge does have to take part.
        """
        x1 = tile["burn"]["x1_mm"]
        y1 = tile["burn"]["y1_mm"]
        if x1 >= max(t["burn"]["x1_mm"] for t in alle) - 1e-9:
            x1 += self.BOARD_EDGE_MARGIN_MM
        if y1 >= max(t["burn"]["y1_mm"] for t in alle) - 1e-9:
            y1 += self.BOARD_EDGE_MARGIN_MM
        return Rect(tile["burn"]["x0_mm"], tile["burn"]["y0_mm"], x1, y1)

    def _check_bed(self, burn, mutator, marks=()) -> None:
        """
        Does this tile still fit in the bed after the correction?

        Half a degree out pushes a tile of 480 mm 4 mm over the edge in no time, and then the
        head runs into its end stop while there is already work in the board.

        The marks count, and that is not obvious: they lie in the overlap zone and therefore
        *outside* the burn area. A check on the burn area alone let a tile through whose marks
        were burned nine millimetres beside the bed — measured, with the head against its end
        stop and material in the machine.
        """
        bed = self.drawing.bed_mm()
        if bed is None:
            return
        straal = self._settings(self._sheet()).marker_size_mm / 2
        corners = [
            (burn.x0, burn.y0),
            (burn.x1, burn.y0),
            (burn.x0, burn.y1),
            (burn.x1, burn.y1),
        ]
        for mark in marks:
            # A mark is a circle: its edge lies half a size further than its centre, and
            # that edge is burned.
            corners.extend(
                [
                    (mark.x_mm - straal, mark.y_mm - straal),
                    (mark.x_mm + straal, mark.y_mm - straal),
                    (mark.x_mm - straal, mark.y_mm + straal),
                    (mark.x_mm + straal, mark.y_mm + straal),
                ]
            )
        angle = math.radians(mutator.alignment.angle_deg)
        rotation = complex(math.cos(angle), math.sin(angle))
        # How far it sticks out, on *whichever* side. Looking only at the bottom gave "0 mm
        # off the bed" as soon as the tile ran out on the right or along the bottom — a
        # message that tells the user nothing about the only thing they need to know: by how
        # much.
        outside = 0.0
        for x, y in corners:
            punt = complex(x, y) * rotation
            mx = punt.real + mutator.alignment.dx_mm
            my = punt.imag + mutator.alignment.dy_mm
            outside = max(outside, -mx, -my, mx - bed[0], my - bed[1])
        if outside > 0:
            raise DesignError(
                f"After the correction this tile falls {outside:.1f} mm outside the bed. "
                "Lay the plate straighter or a little further in and tap again."
            )

    def advance(self) -> dict:
        data = self._read()
        if data is None:
            raise DesignError("There is no tile run going.")
        done = sorted(set(data["done"]) | {data["current"]})
        volgende = data["current"] + 1
        self._alignment = None  # de board gaat verschuiven; de oude state vervalt
        if volgende >= data["tiles"]:
            self._write(None)
            return {"finished": True, "tiles": data["tiles"], "done": done}
        data.update({"done": done, "current": volgende})
        self._write(data)
        return self.state()

    def cancel(self) -> dict:
        self._alignment = None
        self._write(None)
        return {"finished": False, "cancelled": True}
