"""
Filling a plate: as many copies of one piece as the material holds, each with the next name.

A series is one design burned once per row (`series.py`). That is right when the piece
is big, and wasteful when it is a keyring: a plate of 500 × 300 mm holds twenty tags,
and burning it twenty times over — swapping the material each time for one tag — is an
afternoon spent at the lid.

So this is the other half of the same idea. Work out how many pieces fit, put them
there, and give each copy the next row of the list. The engine's own placeholder does
the rest: copy one reads `{name#+1}`, copy two `{name#+2}`, and `Series.step_of()` then
reports that one burn eats as many rows as there are places. Everything downstream —
the burn list in the window, how many plates are still to come, the short last plate
whose empty places are taken out of the job — already works off that one number and
needs nothing new.

## What this is not

It is not a nesting algorithm. The pieces are laid on a plain grid of the piece's own
bounding box, because that is what a plate of identical pieces wants and because the
honest alternative — real outline nesting — would put the tags at angles nobody can
read (`nesting.py` explains the same trade-off for a mixed selection).

And it does not make a sheet per plate. The plates after the first are *burns* of this
same plate, counted by the run: fifty names on a twenty-up plate is three burns, and the
third one leaves ten places empty. That is deliberate, and it is worth writing down
because "make the rest of the sheets automatically" is the obvious next wish:

- The document would carry a hundred copies of one drawing where twenty do, and every
  one of them would be in the cut plan, the undo stack and the file.
- They could not follow a changed list. A sheet full of copies is a photograph of the
  list as it was; a plate plus a pointer is the list as it is.
- A sheet of copies has to name its rows outright (`{name#12}`, the engine's absolute
  form), and then the run's count of plates and the sheets' own order are two answers to
  one question — precisely the shape this project keeps refusing.

So the answer to "and the other thirty names?" is a number, not more sheets: `plan()`
below says how many plates it is and how many places the last one leaves empty, and the
run does them one press at a time with the same marks, the same redo and the same
refusals as any other series.
"""

from .edits import DesignError, _finite
from .series import placeholders, step_of

#: How much material stays free around the edge, by default. Not nought: a plate is
#: never quite where the bed says it is, and the last millimetre of a sheet is where
#: the clamps live.
DEFAULT_MARGIN_MM = 10.0

#: The gap between two pieces. Enough for two kerfs and the burn edge between them.
DEFAULT_GAP_MM = 5.0

#: More places than this on one plate and the plan gets slower than the burn — the
#: quadratic row in CLAUDE.md. Twenty-five hundred keyrings is not a plate anyway.
MAX_PLACES = 400


def plan_plate(
    piece: tuple[float, float],
    sheet: tuple[float, float],
    margin_mm=DEFAULT_MARGIN_MM,
    gap_mm=DEFAULT_GAP_MM,
    wanted=None,
) -> dict:
    """
    How many copies of a piece fit on a plate, and in what grid.

    Pure arithmetic on two rectangles: bytes in, numbers out, no kernel. The gap is
    *between* the pieces and the margin is at the edge, so a plate of 500 mm holding a
    60 mm piece with 5 mm gaps and a 10 mm margin fits eight across:
    (500 − 20 + 5) / (60 + 5) = 7.46 → 7… and that is the sum this function is here to
    get right, because it is the one everybody does in their head and gets wrong.

    `wanted` caps the count at the number of rows there are to burn: twelve places for
    a five-name list would leave seven of them engraving nothing on every plate.
    """
    piece_w, piece_h = (_finite(v, "piece") for v in piece)
    sheet_w, sheet_h = (_finite(v, "sheet") for v in sheet)
    margin = _finite(margin_mm, "margin_mm")
    gap = _finite(gap_mm, "gap_mm")
    if piece_w <= 0 or piece_h <= 0:
        raise DesignError(
            "This piece has no size, so there is nothing to lay out.",
            code="plate.noSize",
        )
    if margin < 0:
        raise DesignError(
            "A negative margin lays the work over the edge of the plate.",
            code="plate.badMargin",
        )
    if gap < 0:
        raise DesignError(
            "A negative gap makes two pieces overlap, and then it is one cut.",
            code="plate.badGap",
        )

    room_w = sheet_w - 2 * margin
    room_h = sheet_h - 2 * margin
    if piece_w > room_w + 1e-6 or piece_h > room_h + 1e-6:
        raise DesignError(
            f"This piece is {piece_w:.0f}×{piece_h:.0f} mm and the plate has "
            f"{room_w:.0f}×{room_h:.0f} mm free inside its margin, so not even one fits. "
            "Make the piece smaller, the margin narrower, or the sheet bigger.",
            code="plate.tooBig",
            values={
                "piece_w": round(piece_w, 1),
                "piece_h": round(piece_h, 1),
                "room_w": round(room_w, 1),
                "room_h": round(room_h, 1),
            },
        )

    # The gap is between the pieces, so there is one fewer gap than pieces: adding one
    # gap to the room and dividing by the pitch is the whole sum.
    columns = int((room_w + gap + 1e-6) // (piece_w + gap))
    rows = int((room_h + gap + 1e-6) // (piece_h + gap))
    fit = max(1, columns) * max(1, rows)

    places = fit
    if wanted is not None:
        try:
            places = max(1, min(fit, int(wanted)))
        except (TypeError, ValueError):
            places = fit
    if places > MAX_PLACES:
        raise DesignError(
            f"{places} pieces on one plate is more than this app lays out; keep it "
            f"under {MAX_PLACES}. Above that the plan takes longer to build than the "
            "job takes to burn.",
            code="plate.tooMany",
            values={"places": places, "max": MAX_PLACES},
        )

    # The grid is filled row by row, so the last row is the one that is short.
    across = max(1, min(columns, places))
    down = max(1, -(-places // across))
    return {
        "columns": across,
        "rows": down,
        "places": places,
        # What the plate would hold if the list were long enough. The window says both
        # when they differ: "eight fit, and your list has five".
        "fit": fit,
        "margin_mm": round(margin, 3),
        "gap_mm": round(gap, 3),
        "piece_mm": [round(piece_w, 3), round(piece_h, 3)],
        "block_mm": [
            round(across * piece_w + (across - 1) * gap, 3),
            round(down * piece_h + (down - 1) * gap, 3),
        ],
    }


class Plating:
    """Filling the plate, and saying beforehand what filling it would do."""

    def __init__(self, kernel, drawing, sheets, generators, series, editor):
        self.kernel = kernel
        self.drawing = drawing
        self.sheets = sheets
        self.generators = generators
        self.series = series
        self.editor = editor

    @property
    def elements(self):
        return self.kernel.elements

    # ------------------------------------------------------------------ the piece

    def _piece(self, element_ids=None) -> list:
        """
        What gets repeated: what you picked, or everything on this sheet.

        Both, because both gestures are the ordinary one. With a tag selected you mean
        that tag; with nothing selected on a sheet that holds one tag you mean the sheet.
        Anything else on the plate would be repeated too, which is why the answer says
        how many shapes it took.
        """
        if element_ids:
            nodes = self.drawing._nodes(element_ids)
        else:
            nodes = [
                node
                for node in self.elements.elems()
                if not getattr(node, "hidden", False)
            ]
        if not nodes:
            raise DesignError(
                "There is nothing on the plate to lay out. Draw the piece first.",
                code="plate.nothing",
            )
        return nodes

    @staticmethod
    def _box_mm(nodes) -> tuple[float, float, float, float]:
        from meerk40t.core.node.node import Node
        from meerk40t.core.units import UNITS_PER_MM

        bounds = Node.union_bounds(nodes)
        if not bounds or not all(value == value for value in bounds):
            raise DesignError(
                "This piece has no size on the plate, so there is nothing to lay out. "
                "A text that reads a column the list has not got is the usual reason.",
                code="plate.noSize",
            )
        x0, y0, x1, y1 = (value / UNITS_PER_MM for value in bounds)
        return x0, y0, x1 - x0, y1 - y0

    def _sheet_mm(self) -> tuple[float, float]:
        sheet = self.sheets.active() or {}
        width = sheet.get("width_mm")
        height = sheet.get("height_mm")
        if width and height:
            return float(width), float(height)
        return self.drawing.bed_mm()

    # -------------------------------------------------------------------- the sum

    def plan(self, element_ids=None, margin_mm=None, gap_mm=None) -> dict:
        """
        What filling this plate would do, without doing it.

        Read by the window on every change of a number, so it stays cheap: two bounding
        boxes and the arithmetic above. It also carries what happens to the *rest* of the
        list, because that is the question this feature raises the moment it answers the
        first one — twenty places out of fifty names is three burns, not one.
        """
        nodes = self._piece(element_ids)
        _, _, width, height = self._box_mm(nodes)
        rows = len(self.series.rows()) if self.series is not None else 0
        plan = plan_plate(
            (width, height),
            self._sheet_mm(),
            DEFAULT_MARGIN_MM if margin_mm is None else margin_mm,
            DEFAULT_GAP_MM if gap_mm is None else gap_mm,
            wanted=rows or None,
        )
        places = plan["places"]
        # Whole plates, and then whatever is left over: fifty names twenty-up is two
        # full plates and one holding ten.
        burns = max(1, -(-rows // places)) if rows else 1
        return {
            **plan,
            "shapes": len(nodes),
            # `row_count` and not `rows`: the grid already has rows, and one dict with
            # two meanings of the word is how the fill came out 2 × 6 instead of 2 × 3 —
            # twelve places for a six-name list, six of them engraving their own syntax.
            # The series state calls the length of the list `row_count` too.
            "row_count": rows,
            "burns": burns,
            "last_places": (rows - (burns - 1) * places) if rows else 0,
            "attached": bool(rows),
            "already": step_of(self._templates(nodes)),
        }

    @staticmethod
    def _templates(nodes) -> list[str]:
        return [
            str(getattr(node, "mktext", "") or "")
            for node in nodes
            if getattr(node, "mktext", None)
        ]

    # ------------------------------------------------------------------ the doing

    def fill(self, element_ids=None, margin_mm=None, gap_mm=None) -> dict:
        """
        Lay the piece out over the plate, each copy taking the next row.

        The order matters and is not free. The refusals come first, then the piece is
        moved into the corner of its margin, and only then is it repeated — a grid grows
        to the right and downwards (`core/elements/grid.py:210`), so a piece drawn in the
        middle of the plate would fill a quarter of it. Moving is part of what "fill the
        plate" means, and it is one undo away.

        The repeating itself is `Generators.grid(..., follow_list=True)`: the same code
        path as the Repeat tab, so there is one way of copying and one way of giving a
        copy the next name. Two would disagree, and the one that disagreed would be the
        one nobody tested.
        """
        nodes = self._piece(element_ids)
        if self.series is None or not self.series.rows():
            raise DesignError(
                "No list is attached, so every copy would say the same thing. Import a "
                "list in the Series window first, or use Repeat if you want plain "
                "copies.",
                code="plate.noList",
            )
        templates = self._templates(nodes)
        if not templates:
            raise DesignError(
                "Nothing in this piece reads from the list, so the copies would all be "
                "the same. Put a column into a text first.",
                code="plate.nothingReads",
            )
        if step_of(templates) > 1:
            raise DesignError(
                "This plate is already laid out: its pieces read further down the list "
                "than the first row. Undo that first, or lay out the single piece you "
                "started from.",
                code="plate.alreadyFilled",
            )
        if any(holder.absolute for text in templates for holder in placeholders(text)):
            # An absolute `{name#3}` says "row four, whatever the pointer" — every copy
            # of it engraves that same row, so shifting the copies would be a lie.
            raise DesignError(
                "This piece names a fixed row, so its copies would all engrave that one "
                "row. Take the row number out of the placeholder first.",
                code="plate.fixedRow",
            )

        plan = self.plan(element_ids, margin_mm, gap_mm)
        if plan["places"] < 2:
            raise DesignError(
                "Only one of these fits on the plate, so there is nothing to lay out. "
                "The series burns them one plate at a time.",
                code="plate.onlyOne",
            )

        left, top, _, _ = self._box_mm(nodes)
        ids = [node.id for node in nodes if getattr(node, "id", None)]
        with self.elements.undoscope("Fill the plate"):
            # Into the corner first, in one move for the whole piece, so that the grid
            # has the whole plate to grow into.
            margin = plan["margin_mm"]
            if abs(left - margin) > 1e-6 or abs(top - margin) > 1e-6:
                self.editor.move(ids, margin - left, margin - top)
            self.generators.grid(
                ids,
                plan["columns"],
                plan["rows"],
                plan["gap_mm"],
                plan["gap_mm"],
                follow_list=True,
            )
            self._trim(plan)
            grouped = self._group_cells(plan)
        self.elements.validate_ids()
        self.elements.signal("rebuild_tree", "all")
        self.elements.signal("refresh_scene", "Scene")
        # What it did, and not a fresh plan: measured again afterwards the "piece" is the
        # whole filled plate, which would answer "one place, four burns" about a plate
        # that has just been filled. The window reads `/api/series` for the run's own
        # numbers, which is where they belong.
        return {**plan, "filled": plan["places"], "pieces": grouped}

    def _cells(self, plan: dict) -> list[tuple[float, float, float, float]]:
        """
        Where every place on the plate is, in millimetres.

        The grid arithmetic and not the tree: `grid` copies shape by shape and drops the
        group on the way (measured: the original tag keeps its group id and the nine
        copies come out as eighteen loose shapes), so which shapes belong to one place
        cannot be read off the tree afterwards. It *can* be read off the plate — the
        pieces are on a grid this module laid out itself — and that holds whatever the
        engine does with its copies.
        """
        width, height = plan["piece_mm"]
        gap = plan["gap_mm"]
        margin = plan["margin_mm"]
        boxes = []
        for index in range(plan["columns"] * plan["rows"]):
            column = index % plan["columns"]
            row = index // plan["columns"]
            x = margin + column * (width + gap)
            y = margin + row * (height + gap)
            boxes.append((x, y, x + width, y + height))
        return boxes

    def _in_cell(self, box) -> list:
        """Every shape whose middle lies in this place. A hair of slack for rounding."""
        from meerk40t.core.units import UNITS_PER_MM

        x0, y0, x1, y1 = box
        found = []
        for node in self.elements.elems():
            bounds = getattr(node, "bounds", None)
            if not bounds or not all(value == value for value in bounds):
                continue
            middle_x = (bounds[0] + bounds[2]) / 2 / UNITS_PER_MM
            middle_y = (bounds[1] + bounds[3]) / 2 / UNITS_PER_MM
            if x0 - 0.01 <= middle_x <= x1 + 0.01 and y0 - 0.01 <= middle_y <= y1 + 0.01:
                found.append(node)
        return found

    def _group_cells(self, plan: dict) -> int:
        """
        Every place on the plate becomes one thing you can drag.

        `grid` leaves its copies as loose shapes — the original tag keeps its group and
        the copies come out as separate rectangles and texts — so dragging a tag would
        take its outline and leave its name behind. The same argument `nesting.py` makes
        for a mixed selection: what belongs together moves together.
        """
        made = 0
        for box in self._cells(plan)[: plan["places"]]:
            members = self._in_cell(box)
            if len(members) < 2:
                continue
            if len({self._group_of(node) for node in members}) == 1 and self._group_of(
                members[0]
            ) is not None:
                # Already one group — the piece you started from, which keeps its own.
                continue
            self.elements.set_emphasis(members)
            self.drawing.runner.run("group")
            made += 1
        return made

    def _trim(self, plan: dict) -> None:
        """
        Take away the places the grid made and the list cannot fill.

        `grid` can only make a rectangle, so seven places on a plate five wide come out
        as ten. The three extra copies read past the end of the list, and the engine
        engraves a placeholder it cannot resolve as those nine characters
        (`core/wordlist.py:597`). The overrun mutator would take them off the *job*, but
        they would still be on the plate, in the burn list and in every count the window
        shows.

        By place and not by placeholder: the copies come out of `grid` as loose shapes,
        so deleting the shape that holds the name would leave a nameless outline behind —
        measured, three empty rectangles on a plate of seven tags.
        """
        extra = plan["columns"] * plan["rows"] - plan["places"]
        if extra <= 0:
            return
        going = []
        for box in self._cells(plan)[plan["places"] :]:
            going.extend(self._in_cell(box))
        if not going:
            return
        self.elements.set_emphasis(going)
        self.drawing.runner.run("element delete")

    def _group_of(self, node):
        parent = getattr(node, "parent", None)
        found = None
        while parent is not None and getattr(parent, "type", "") == "group":
            found = parent
            parent = getattr(parent, "parent", None)
        return found

    @staticmethod
    def _members(group) -> list:
        return [node for node in group.flat() if node is not group]
