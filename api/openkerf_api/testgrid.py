"""
Parametric test grids.

The verification loop from ARCHITECTUUR.md: burn a grid of squares that sweeps
power against speed, photograph the result, point at the best cell, and turn
that into a verified preset. This module covers the first half — planning the
grid and drawing it into the element tree.

Each cell needs its own laser settings, so each cell gets its own operation
with one square referenced from it. That is exactly how MeerK40t models a job,
and it means the existing plan → spool route runs the grid without changes.
"""

import re
import unicodedata

from .edits import DesignError

MAX_CELLS = 400  # A 20x20 sweep is already more than anyone reads off a photo.

# The layer all the captions of all the boards go into. One name in one place, because
# both the generator and the drawing part have to recognise it: it is a layer *of the
# board* and not a layer of the user's, and so must never catch fresh work (see
# Drawing._single_layer).
LABEL_LAYER = "Raster-labels"

# The name of the group that holds one board together.
BOARD_LABEL = "Testraster"


def _positive(value, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as e:
        raise DesignError(f"{name} has to be a number.") from e
    if number <= 0:
        raise DesignError(f"{name} has to be greater than zero.")
    return number


def _steps(value, name: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as e:
        raise DesignError(f"{name} has to be a whole number.") from e
    if number < 2:
        raise DesignError(f"{name} has to be at least 2 — otherwise you vary nothing.")
    return number


def _passes(value) -> int:
    """
    How many times the head goes over each square, for the whole board at once.

    Strict about half passes: `int(2.5)` is 2, and that is exactly the kind of silent
    rounding somebody finds out about on material. An empty field is fine — the form sends
    "" for "not filled in".
    """
    if value in (None, ""):
        return 1
    try:
        number = float(value)
    except (TypeError, ValueError) as e:
        raise DesignError("passes has to be a whole number of 1 or more.") from e
    if number != int(number) or int(number) < 1:
        raise DesignError("passes has to be a whole number of 1 or more.")
    return int(number)


# The steps a human works in. A grid that cuts rows at 11.667 mm/s is not a reference
# work: you will never type that setting again.
# The finest steps are there for the interval: that runs from 0.05 to 0.3 mm, and on a
# grain of 0.1 three of the four rows would get the same number.
_TIDY_STEPS = (
    0.01, 0.02, 0.025, 0.05,
    0.1, 0.2, 0.25, 0.5, 1, 2, 2.5, 5, 10, 20, 25, 50, 100, 200, 250, 500,
)


# ---------------------------------------------------------------- de drie axes
#
# Decision B12: the interval (the line spacing) is the third quantity you can sweep. You
# choose which two sit on the axes yourself; the third stays fixed. Passes is deliberately
# not among them: that multiplies the burn time of the whole board, and then you are
# testing your patience instead of your material.

AXES = {
    "speed": {
        "cell_key": "speed_mm_s",
        "fixed_key": "speed_mm_s",
        "unit": "mm/s",
        "label": "speed",
    },
    "power": {
        "cell_key": "power_percent",
        "fixed_key": "power_percent",
        "unit": "%",
        "label": "power",
    },
    "interval": {
        "cell_key": "interval_mm",
        "fixed_key": "interval_mm",
        "unit": "mm",
        "label": "interval",
    },
}

# Where the interval means something. When cutting the head lays one line and there is no
# line spacing; offering it there would be a button that does nothing.
INTERVAL_OPERATIONS = ("graveren-raster",)

# What the interval comes out at when you say nothing about it: 0.1 mm ≈ 254 dpi, the
# working point most CO2 engravings sit at.
DEFAULT_INTERVAL_MM = 0.1

# -------------------------------------------------- the typeface on the board
#
# A test board is a piece of evidence: in two weeks' time you still have to be able to read
# off it which square was 200 mm/s at 40%. So which typeface is on it must not depend on
# what you happened to choose last in the text dialog.
#
# And that did happen. Without `-f`, `linetext` falls back on `context.last_font`
# (meerk40t/extra/hershey.py:895), a setting the engine keeps and that *every* text
# placement overwrites — including one the user has long forgotten. A board with the
# captions in Apple Chancery is exactly what you do not want.
#
# `meerk40t.jhf` is the engine's built-in Hershey typeface: it does not come from the disk,
# so it is always there, and it is single-line — exactly what an engraved caption wants (a
# TrueType outline engraves the contour of the letter, not the letter). The rest is a
# fallback in case upstream ever renames it.
LABEL_FONTS = ("meerk40t.jhf", "rowmans.jhf", "romant.shx", "arial.ttf")

# The size we have the typeface rendered at. The height is set exactly afterwards with
# `_scale_to_height` anyway, but a fixed starting size keeps the result reproducible
# instead of dependent on the console default.
LABEL_FONT_SIZE_PX = 20

# How wide a character of that typeface is, as a fraction of the text height. Measured on
# the captions as actually drawn (0.53–0.66 depending on which characters are in them); we
# compute on the generous side, because this reserves room and a shortfall lets the caption
# stick out beyond the board.
CAPTION_CHAR_RATIO = 0.62

# Where an engraved caption stops being readable. Smaller than this it is no longer a
# caption but a stripe, so it shrinks no further — it breaks onto a next line instead.
MIN_CAPTION_MM = 2.0

# How much higher one caption line sits above the other, as a fraction of the text
# height. 1.4 is the usual line spacing; tighter and the ascenders and descenders of two
# lines run into each other and it is no longer readable once engraved.
CAPTION_LINE_PITCH = 1.4

# --------------------------------------------------- where the board will lie
#
# Gap T9: Start X/Y referred to the top-left corner of the grid. You put a test board on
# an offcut, and then you know where the *centre* of that piece is — not where the corner
# of a grid you have not seen yet should go. LightBurn asks X Center/Y Center; we leave the
# choice, because from a corner is actually handier on a fresh plate.
#
# The centre refers to the whole board including labels and caption. Centring the grid
# while the row labels stick out to the left of it lays the board askew — and those very
# labels were the reason for T11.
ANCHORS = ("corner", "center")

# How far the border frame (T10) lies around the board. Generous enough not to run into
# the captions, tight enough not to waste plate.
BORDER_PAD_MM = 2.0

# The label layer does not join the sweep: it has to be readable whatever comes out of the
# trial. These two were hardcoded; since T10 they can be set, with the same numbers as the
# fallback.
DEFAULT_LABEL_SPEED_MM_S = 80.0
DEFAULT_LABEL_POWER_PERCENT = 30.0


def _tidy(value: float, raw_step: float) -> float:
    """
    Nudging an intermediate value to the nearest tidy number.

    The grain follows the step size: with steps of ~13 you round to tens, with steps of
    ~0.4 to tenths. That way the grid keeps climbing recognisably instead of showing the
    same number four times.
    """
    # The coarsest tidy step that is at most half a step: then a value never moves further
    # than a quarter of a step and the series keeps climbing tidily.
    bound = raw_step / 2 if raw_step else 1
    fitting = [k for k in _TIDY_STEPS if k <= bound]
    grain = fitting[-1] if fitting else _TIDY_STEPS[0]
    rounded = round(value / grain) * grain
    # Floating point leaves 3 * 0.1 behind as 0.30000000000000004.
    return round(rounded, 3)


def _spread(low: float, high: float, steps: int) -> list[float]:
    """
    The series of values for one axis.

    The start and the end stay exactly what was asked for — that is the range the user
    wants to sweep. Only the intermediate steps move to a tidy number, and when two of them
    come out the same the raw value stays: better an ugly number than two identical rows.
    """
    if steps == 1:
        return [low]
    span = (high - low) / (steps - 1)
    raw = [low + span * i for i in range(steps)]
    tidy = [raw[0]] + [_tidy(v, span) for v in raw[1:-1]] + [raw[-1]]
    if len(set(tidy)) < len(tidy) or any(
        tidy[i] >= tidy[i + 1] for i in range(len(tidy) - 1)
    ):
        return raw
    return tidy


def _range(name: str, lo, hi, count) -> list[float]:
    """The values on one axis, checked and rounded to tidy numbers."""
    # Since point 2 the reason is on screen *beside* the preview instead of below the
    # fold, so it is now text for a human and not a field name from the API. "speed_max
    # must be at least speed_min" is not a sentence.
    label = AXES[name]["label"]
    layer = _positive(lo, f"The {label} at 'from'")
    high = _positive(hi, f"The {label} at 'to'")
    if high < layer:
        raise DesignError(
            f"The {label} at 'to' has to be at least the {label} at 'from'."
        )
    if name == "power" and high > 100:
        raise DesignError("Power cannot go above 100 per cent.")
    if name == "interval" and high > 5:
        raise DesignError("An interval above 5 mm is no longer an engraving.")
    return _spread(layer, high, _steps(count, f"The number of steps {label}"))


def _fixed(name: str, value, fallback) -> float:
    """The value of the quantity that is *not* on an axis."""
    if value in (None, ""):
        value = fallback
    if value in (None, ""):
        raise DesignError(
            f"Set a fixed value for {AXES[name]['label']}; it is not on an axis."
        )
    number = _positive(value, AXES[name]["fixed_key"])
    if name == "power" and number > 100:
        raise DesignError("Power cannot go above 100 per cent.")
    return number


def plan_grid(
    operation: str,
    speed_min=None,
    speed_max=None,
    speed_steps=None,
    power_min=None,
    power_max=None,
    power_steps=None,
    interval_min=None,
    interval_max=None,
    interval_steps=None,
    speed_mm_s=None,
    power_percent=None,
    interval_mm=None,
    row_axis="speed",
    column_axis="power",
    # One number for the whole board. As an axis it would produce a board nobody reads
    # back: passes multiplies the burn time and changes the outcome of every square, so two
    # columns with different passes are two trials on one plank.
    passes=1,
    cell_mm=8.0,
    gap_mm=2.0,
    origin_x_mm=10.0,
    origin_y_mm=10.0,
    anchor="corner",
    text=True,
    border=False,
    label_speed_mm_s=None,
    label_power_percent=None,
    material_id=None,
    machine_id=None,
    thickness_mm=None,
    # The caption belongs to the board and not to the sweep, but it does decide how wide
    # the board becomes — so the planner has to know it. Leaving it out is allowed: then it
    # computes with the caption it can derive itself.
    caption=None,
    material_name=None,
    stamp=None,
) -> tuple[dict, list[dict]]:
    """
    Work out the cells without touching the engine, so it can be previewed.

    Two of the three quantities sit on an axis (`row_axis` downwards, `column_axis` to the
    right), the third stays fixed. By default that is what it always was: speed down, power
    to the right.
    """
    if row_axis not in AXES or column_axis not in AXES:
        raise DesignError(
            f"Unknown axis: choose from {', '.join(AXES)}."
        )
    if row_axis == column_axis:
        raise DesignError(
            "The two axes have to be different quantities — otherwise you vary "
            "one thing in two directions."
        )
    axes = (row_axis, column_axis)
    interval_telt = operation in INTERVAL_OPERATIONS
    if "interval" in axes and not interval_telt:
        raise DesignError(
            "Interval is only an axis when rastering: with cutting and vector engraving "
            "the head lays one line and there is no line spacing."
        )

    reeksen = {
        "speed": (speed_min, speed_max, speed_steps),
        "power": (power_min, power_max, power_steps),
        "interval": (interval_min, interval_max, interval_steps),
    }
    values = {
        name: _range(name, *reeksen[name]) if name in axes else None
        for name in AXES
    }
    fixed_values = {
        "speed": None if "speed" in axes else _fixed("speed", speed_mm_s, speed_min),
        "power": None if "power" in axes else _fixed("power", power_percent, power_min),
        "interval": (
            None
            if "interval" in axes or not interval_telt
            else _fixed(
                "interval",
                interval_mm,
                interval_min if interval_min else DEFAULT_INTERVAL_MM,
            )
        ),
    }

    rows = len(values[row_axis])
    columns = len(values[column_axis])
    if rows * columns > MAX_CELLS:
        raise DesignError(
            f"{rows}×{columns} cells is too many; keep it under {MAX_CELLS}."
        )

    pass_count = _passes(passes)
    cell = _positive(cell_mm, "cell_mm")
    gap = float(gap_mm)
    if gap < 0:
        raise DesignError("gap_mm cannot be negative.")
    pitch = cell + gap

    if anchor not in ANCHORS:
        raise DesignError("Choose 'corner' (from the corner) or 'center' (from the middle).")
    text = bool(text)
    frame = bool(border)
    label_speed = _positive(
        DEFAULT_LABEL_SPEED_MM_S if label_speed_mm_s in (None, "") else label_speed_mm_s,
        "label_speed_mm_s",
    )
    label_power = _positive(
        DEFAULT_LABEL_POWER_PERCENT
        if label_power_percent in (None, "")
        else label_power_percent,
        "label_power_percent",
    )
    if label_power > 100:
        raise DesignError("The power of the label layer cannot go above 100 per cent.")

    width = round(columns * pitch - gap, 3)
    height = round(rows * pitch - gap, 3)

    # What else gets burned around the squares, and therefore counts towards "does this fit
    # on my plate". Computed here before the placement, because with `anchor="center"` it is
    # precisely this measure that decides where the top-left corner lands.
    #
    # How much room the row labels need to the left of the grid. They are engraved there,
    # and at Start X 10 with three-digit speeds they are off the bed — then the machine does
    # not burn them and the board is unreadable. The vector font is about 0.62 × the text
    # height wide per character; so this is an estimate, and it is reported as one.
    text_height = max(2.0, cell * 0.35)
    caption_height = max(2.5, cell * 0.4)
    langste = max(
        (len(show(row_axis, value)) for value in values[row_axis]), default=0
    )
    margin = round(2 + 0.62 * text_height * langste, 1)

    # The caption adapts to the board, not the other way round.
    #
    # It was on one line and the board got room added on the right until that line fitted:
    # on a grid of 38 mm the board became 134 mm wide. That is no longer a board but a
    # flapping banner, and it makes the test panel unusably wide on screen. Now the caption
    # shrinks first until it falls within the board width, and only breaks onto a second
    # line when it would drop below the readability bound. So the board never becomes wider
    # than its own squares plus the row labels — only slightly taller.
    caption_rows = (
        caption_lines(
            {
                "caption": caption,
                "material_name": material_name,
                "stamp": stamp,
                "thickness_mm": thickness_mm,
                "operation": operation,
                "passes": pass_count,
                "row_axis": row_axis,
                "column_axis": column_axis,
                # The fixed quantity belongs with it: without it the board cannot be
                # converted back into a setting in two weeks' time. This was already ready
                # in `caption_text`, but the keys were never passed along — so the branch
                # never fired.
                **{
                    f"{name}_min": fixed_values[name]
                    for name in AXES
                    if fixed_values[name] is not None
                },
            }
        )
        if text
        else []
    )
    if caption_rows:
        available = margin + width
        # Shrink first: the height at which the longest line just fits.
        tight = available / (
            CAPTION_CHAR_RATIO * max(len(r) for r in caption_rows)
        )
        if tight < MIN_CAPTION_MM:
            # Even at the floor it does not fit — so add a line.
            per_line = max(8, int(available / (CAPTION_CHAR_RATIO * MIN_CAPTION_MM)))
            caption_rows = _breek(caption_rows, per_line)
            tight = available / (
                CAPTION_CHAR_RATIO * max(len(r) for r in caption_rows)
            )
        caption_height = round(max(MIN_CAPTION_MM, min(caption_height, tight)), 3)

    # Above the grid: the column labels 2 mm above it, and above those the caption again.
    # `_caption` puts the *bottom* of the lowest caption line at `origin_y - 4 - height`, so
    # the top of the highest one lies a text height plus the line spacings above that.
    # Measured against the shapes as actually drawn (see
    # `test_the_reported_size_covers_everything_that_is_drawn`).
    above = round(
        max(
            2 + text_height,
            4
            + 2 * caption_height
            + max(0, len(caption_rows) - 1) * CAPTION_LINE_PITCH * caption_height,
        ),
        1,
    )

    pad_left = (margin if text else 0.0) + (BORDER_PAD_MM if frame else 0.0)
    pad_above = (above if text else 0.0) + (BORDER_PAD_MM if frame else 0.0)
    pad_right = pad_below = BORDER_PAD_MM if frame else 0.0

    outer_width = round(pad_left + width + pad_right, 3)
    outer_height = round(pad_above + height + pad_below, 3)

    if anchor == "center":
        outer_x = round(float(origin_x_mm) - outer_width / 2, 3)
        outer_y = round(float(origin_y_mm) - outer_height / 2, 3)
        origin_x_mm = round(outer_x + pad_left, 3)
        origin_y_mm = round(outer_y + pad_above, 3)
    else:
        origin_x_mm = float(origin_x_mm)
        origin_y_mm = float(origin_y_mm)
        outer_x = round(origin_x_mm - pad_left, 3)
        outer_y = round(origin_y_mm - pad_above, 3)

    cells = []
    for row in range(rows):
        for column in range(columns):
            entry = {
                "row": row,
                "column": column,
                "x_mm": round(origin_x_mm + column * pitch, 3),
                "y_mm": round(origin_y_mm + row * pitch, 3),
                "width_mm": cell,
                "height_mm": cell,
            }
            for name, as_ in AXES.items():
                if name == row_axis:
                    number = values[name][row]
                elif name == column_axis:
                    number = values[name][column]
                else:
                    number = fixed_values[name]
                entry[as_["cell_key"]] = None if number is None else round(number, 4)
            cells.append(entry)

    plan = {
        "material_id": material_id,
        "machine_id": machine_id,
        "thickness_mm": thickness_mm,
        "operation": operation,
        "passes": pass_count,
        "row_axis": row_axis,
        "column_axis": column_axis,
        "rows": rows,
        "columns": columns,
        "cell_mm": cell,
        "gap_mm": gap,
        "origin_x_mm": origin_x_mm,
        "origin_y_mm": origin_y_mm,
        "width_mm": width,
        "height_mm": height,
        # T9/T10: where the board lies and how big it really is. `origin_*` is and stays
        # the top-left corner of the *squares* — that is what the photo overlay computes
        # with — and `outer_*` is the whole board including captions and frame.
        "anchor": anchor,
        "text": text,
        "border": frame,
        "label_speed_mm_s": label_speed,
        "label_power_percent": label_power,
        "outer_x_mm": outer_x,
        "outer_y_mm": outer_y,
        "outer_width_mm": outer_width,
        "outer_height_mm": outer_height,
        "center_x_mm": round(outer_x + outer_width / 2, 3),
        "center_y_mm": round(outer_y + outer_height / 2, 3),
        # The caption belongs to the planning because it decides the width. `caption_text`
        # is computed here already so that the drawer sets exactly the same line as the room
        # reserved for it here.
        "caption": str(caption or "").strip(),
        "material_name": material_name,
        "stamp": stamp,
        "caption_lines": caption_rows,
        "caption_text": " · ".join(caption_rows),
        # The size at which the caption fits; then the drawer does not have to guess it
        # again and sets exactly what was measured here.
        "caption_height_mm": caption_height if caption_rows else 0.0,
    }
    # What this board is going to cost in time, before anything has been drawn.
    #
    # Needed because interval as an axis can silently multiply the burn time: a row at
    # 0.05 mm lays six times as many lines as a row at 0.3 mm, and no number in the form
    # shows that. The same sum as `DrawingService._geometry_estimate`: length divided by
    # speed, plus the jump to the next square. The board has not been drawn yet, so this
    # cannot come from the element tree.
    RAPID_MM_S = 100.0
    seconds = 0.0
    for entry in cells:
        speed = entry["speed_mm_s"] or 0
        if speed <= 0:
            continue
        interval = entry.get("interval_mm")
        if interval_telt and interval:
            # Rasteren: line na line over het area, plus één regelsprong.
            lines = cell / interval
            burn_mm = lines * cell + cell
        else:
            # Cutting or vector engraving: the outline of the square.
            burn_mm = 4 * cell
        # Every pass burns the whole route again; the jump to the next square happens
        # once. Without this factor a board of two
        # passes reports half its time, and we also use that number to say whether it
        # fits within a day.
        seconds += pass_count * burn_mm / speed + pitch / RAPID_MM_S
    plan["seconds"] = round(seconds, 1)

    plan["label_margin_mm"] = margin if text else 0.0
    # Are the row labels still on the bed? Without captions that question is gone.
    plan["label_room"] = (not text) or origin_x_mm >= margin
    # And the board as a whole: since T9 the centre can be the anchor, and then "set Start
    # X higher" is no longer an answer the user can give.
    plan["board_room"] = outer_x >= 0 and outer_y >= 0

    # Every quantity gets its min/max/steps, the fixed one as well: then one row in the
    # database stays enough to rebuild the grid, and the columns that were already there
    # keep meaning what they meant.
    for name in AXES:
        series = values[name]
        if series is None:
            fixed = fixed_values[name]
            plan[f"{name}_min"] = fixed
            plan[f"{name}_max"] = fixed
            plan[f"{name}_steps"] = 1 if fixed is not None else None
        else:
            plan[f"{name}_min"] = series[0]
            plan[f"{name}_max"] = series[-1]
            plan[f"{name}_steps"] = len(series)
    return plan, cells


# ----------------------------------------------------- marking out the cell
#
# M4: the provenance says "row 2, column 3", but nothing is marked on the photo — the
# evidence is there, the pointer is not. With the alignment from T4 in the database the
# same image can be used here to point out the square on the photo itself, so that the
# marker comes along in every <img> that shows the photo.

# The corners the overlay starts at when nothing has been aligned yet: the same 10% margin
# the frontend proposes.
DEFAULT_CORNERS = [
    {"x": 0.1, "y": 0.1},
    {"x": 0.9, "y": 0.1},
    {"x": 0.9, "y": 0.9},
    {"x": 0.1, "y": 0.9},
]


def _homography(corners: list[dict]):
    """
    Projective mapping from the unit square to the four corners.

    The same standard homography as in TestGridResult.svelte: standing at an angle above
    the board you photograph a trapezium, and an affine transform does not catch that.
    """
    p0, p1, p2, p3 = corners
    dx1, dx2 = p1["x"] - p2["x"], p3["x"] - p2["x"]
    dx3 = p0["x"] - p1["x"] + p2["x"] - p3["x"]
    dy1, dy2 = p1["y"] - p2["y"], p3["y"] - p2["y"]
    dy3 = p0["y"] - p1["y"] + p2["y"] - p3["y"]
    noemer = dx1 * dy2 - dy1 * dx2
    g = h = 0.0
    if abs(noemer) > 1e-9 and (dx3 or dy3):
        g = (dx3 * dy2 - dy3 * dx2) / noemer
        h = (dx1 * dy3 - dy1 * dx3) / noemer
    return (
        p1["x"] - p0["x"] + g * p1["x"],
        p3["x"] - p0["x"] + h * p3["x"],
        p0["x"],
        p1["y"] - p0["y"] + g * p1["y"],
        p3["y"] - p0["y"] + h * p3["y"],
        p0["y"],
        g,
        h,
    )


def cell_polygon(grid: dict, cell: dict) -> list[tuple[float, float]]:
    """The four corners of one square in photo coordinates (0–1)."""
    pitch = grid["cell_mm"] + grid["gap_mm"]
    columns = grid.get("columns") or grid["power_steps"]
    rows = grid.get("rows") or grid["speed_steps"]
    width = columns * pitch - grid["gap_mm"]
    height = rows * pitch - grid["gap_mm"]
    a, b, c, d, e, f, g, h = _homography(grid.get("alignment") or DEFAULT_CORNERS)

    def to_photo(u, v):
        w = g * u + h * v + 1 or 1e-9
        return ((a * u + b * v + c) / w, (d * u + e * v + f) / w)

    u0 = (cell["x_mm"] - grid["origin_x_mm"]) / width
    v0 = (cell["y_mm"] - grid["origin_y_mm"]) / height
    u1 = u0 + cell["width_mm"] / width
    v1 = v0 + cell["height_mm"] / height
    return [to_photo(u0, v0), to_photo(u1, v0), to_photo(u1, v1), to_photo(u0, v1)]


# ---------------------------------------------------- is this node ours?
#
# The link grid → node is in the database and survives a restart; ids are handed out per
# document. So `meerk40t:3` on sheet 2 is a *different* thing from `meerk40t:3` on sheet 1.
# Anybody removing a grid from the canvas while they are on another sheet erased the work
# there — measured: thirteen layers of another grid, without a word. So the removal looks
# not only at the id but also at whether the node found really is this cell. The same
# requirement `DesignReader._grid_for` makes when marking.

SIZE_SLACK_MM = 0.6  # de lijndikte telt mee in `bounds`


def is_raster_group(node) -> bool:
    return str(getattr(node, "type", "")).startswith("group")


def is_cel_operatie(node, cell: dict) -> bool:
    speed = getattr(node, "speed", None)
    power = getattr(node, "power", None)
    if speed is None or power is None:
        return False
    try:
        return (
            abs(float(speed) - float(cell["speed_mm_s"])) <= 0.01
            and abs(float(power) - float(cell["power_percent"]) * 10) <= 0.1
        )
    except (TypeError, ValueError):
        return False


def is_cel_element(node, cell: dict) -> bool:
    from meerk40t.core.units import UNITS_PER_MM

    bounds = getattr(node, "bounds", None)
    if not bounds or len(bounds) != 4:
        return False
    x0, y0, x1, y1 = (float(v) / UNITS_PER_MM for v in bounds)
    gemeten = (x0, y0, x1 - x0, y1 - y0)
    verwacht = (cell["x_mm"], cell["y_mm"], cell["width_mm"], cell["height_mm"])
    return all(abs(a - b) <= SIZE_SLACK_MM for a, b in zip(gemeten, verwacht))


def markeer_foto(grid: dict, path, row: int, column: int) -> bytes:
    """
    The grid photo with one square circled, as JPEG bytes.

    Server-side and not in the browser, so that the marker comes along everywhere the photo
    is shown as an image — including on the provenance card in the library.
    """
    from io import BytesIO

    from PIL import Image, ImageDraw

    cell = next(
        (c for c in grid["cells"] if c["row"] == row and c["column"] == column), None
    )
    if cell is None:
        raise DesignError(f"Cell row {row}, column {column} does not belong to this grid.")

    photo = Image.open(path).convert("RGB")
    width, height = photo.size
    points = [(x * width, y * height) for x, y in cell_polygon(grid, cell)]
    thick = max(3, round(min(width, height) / 160))
    draw = ImageDraw.Draw(photo)
    # White underneath, accent on top: on dark scorched wood a single line vanishes.
    draw.polygon(points, outline=(255, 255, 255), width=thick * 2)
    draw.polygon(points, outline=(42, 166, 177), width=thick)

    buffer = BytesIO()
    photo.save(buffer, format="JPEG", quality=88)
    return buffer.getvalue()


def axis_value(cell: dict, name: str):
    """The value of one quantity in a cell, or None when it does not take part."""
    return cell.get(AXES[name]["cell_key"])


def show(name: str, value) -> str:
    """An axis value with its unit, as it ends up on the wood."""
    if value is None:
        return ""
    unit = AXES[name]["unit"]
    if name == "interval":
        return f"{value:g}{unit}"
    return f"{value:g}{'' if unit == '%' else ' '}{unit}"


def _words(text) -> list[str]:
    """The separate words of a piece of text, lower case and without accents."""
    flat = unicodedata.normalize("NFKD", str(text or "").lower())
    flat = "".join(c for c in flat if not unicodedata.combining(c))
    return [w for w in re.split(r"[^0-9a-z]+", flat) if w]


def _already_said(word: str, said: list[str]) -> bool:
    """
    Is this word already in the caption the user typed themselves?

    On the stem and not on the letter: anybody typing "3MM Acryl Engrave" has already named
    the material "Acrylic (extruded)", even with a different ending on it. Short words do
    not take part — "mm" or "cm" occurs everywhere and would wipe out half the captions.
    """
    if len(word) < 4:
        return False
    return any(w.startswith(word) or word.startswith(w) for w in said if len(w) >= 4)


# What an operation is called on the wood. `graveren-raster` is a key from our database,
# not a word you engrave on a plank.
OPERATION_LABELS = {
    "snijden": "cut",
    "graveren-vector": "engrave vector",
    "graveren-raster": "engrave raster",
    "markeren": "mark",
}


def caption_lines(plan: dict) -> list[str]:
    """
    The caption as it goes onto the wood, as separate lines.

    Two lines and not a banner. The first says what this is about — the word the user chose
    themselves, or otherwise the material — and the second how it was burned. They sit
    under each other because the board has to stay a board: a caption running on for one
    line was a good 130 mm wide on a grid of 38 mm, and then the board is three times as
    wide as the trial on it.

    What the user has already said we do not repeat. "3MM Acryl Engrave" beside "Acrylic
    (extruded) · 3 mm · engrave raster" is the same sentence three times; that makes the
    caption long without adding anything to it.

    Here and not in the drawer, because `plan_grid` has to reserve room for it — and what
    we report as a measure has to cover what burns.
    """
    own = str(plan.get("caption") or "").strip()
    said = _words(own)

    head = [own] if own else []
    material = str(plan.get("material_name") or "").strip()
    if material:
        stem = _words(material)
        if not (stem and _already_said(stem[0], said)):
            head.append(material)
    thickness = plan.get("thickness_mm")
    if thickness and not re.search(rf"(?<![0-9]){thickness:g}\s*mm", " ".join(said)):
        head.append(f"{thickness:g} mm")

    operation = plan.get("operation") or ""
    name = OPERATION_LABELS.get(operation, str(operation))
    # Only the part that has not been said yet: anybody who typed "Engrave" does not need
    # a second "engrave" on their plank, but "raster" against "vector" *is* the difference
    # between two entirely different trials.
    resterend = " ".join(w for w in name.split() if not _already_said(w, said))
    foot = [resterend] if resterend else []

    # Which axis carries which quantity. Without this a board with freely chosen axes
    # cannot be read: "0.05" on the left could be speed or interval. LightBurn puts the axis
    # names beside the values; we need them more badly, because with us what is on the axis
    # is not fixed.
    axes = (plan.get("row_axis", "speed"), plan.get("column_axis", "power"))
    foot.append(f"{AXES[axes[0]]['label']} v / {AXES[axes[1]]['label']} >")
    # The quantity that is *not* on an axis belongs on it too: without it a board cannot be
    # converted back into a setting in two weeks' time.
    for axis_name in AXES:
        if axis_name in axes or plan.get(f"{axis_name}_min") is None:
            continue
        foot.append(f"{AXES[axis_name]['label']} {show(axis_name, plan[f'{axis_name}_min'])}")
    # The number of passes belongs with the outcome: the same square at 8 mm/s is a
    # different trial in one pass than in two. With one pass it is not there — that is the
    # normal state of affairs, and the caption decides the board width.
    passes = int(plan.get("passes") or 1)
    if passes > 1:
        foot.append(f"{passes} passes")
    if plan.get("stamp"):
        foot.append(str(plan["stamp"]))

    lines = [" · ".join(head), " · ".join(foot)]
    return [r for r in lines if r]


def caption_text(plan: dict) -> str:
    """The same lines one after another — for where one string is enough."""
    return " · ".join(caption_lines(plan))


def _breek(lines: list[str], chars: int) -> list[str]:
    """
    Breaking lines that are too long at the separators already in them.

    Only when it really does not fit: the caption shrinks first (see `plan_grid`), and only
    below the readability bound does a line get added. A part that is too long on its own
    stays whole — breaking in the middle of
    "Acrylic" does not make the board any easier to read.
    """
    out: list[str] = []
    for line in lines:
        running = ""
        for part in line.split(" · "):
            candidate = f"{running} · {part}" if running else part
            if running and len(candidate) > chars:
                out.append(running)
                running = part
            else:
                running = candidate
        if running:
            out.append(running)
    return out


def _cell_label(plan: dict, cell: dict) -> str:
    """
    One square's layer label: exactly the quantities that vary.

    The fixed quantity is in the caption on the board; repeating it in sixteen layer names
    makes the layers panel unreadable.
    """
    return " · ".join(
        show(name, axis_value(cell, name))
        for name in (plan.get("row_axis", "speed"), plan.get("column_axis", "power"))
    )


def raster_supported(kernel) -> bool:
    """
    Can this engine actually burn a raster layer?

    No, when no rasteriser is registered. During planning `op raster` turns its shapes into
    a bitmap through `render-op/make_raster`, and that service is **only registered by the
    wxPython GUI** (`meerk40t/gui/plugin.py:79`, with the comment "used to do cut
    planning"). If it is absent, `OpRasterNode.preprocess` takes the `strip_rasters` branch:
    the layer throws its own children away and produces no cutcode.

    Measured on our headless server: a design with only raster layers gives
    `/api/job/estimate?exact=1` → 0.0 s over 0 parts. The board comes out of the machine
    blank. So this is reported rather than hoped for.
    """
    try:
        return kernel.root.lookup("render-op/make_raster") is not None
    except Exception:
        return False


# Which MeerK40t operation type a library operation maps to.
OPERATION_TYPES = {
    "snijden": "op cut",
    "graveren-vector": "op engrave",
    "graveren-raster": "op raster",
    "markeren": "op engrave",
}


class TestGridGenerator:
    def __init__(self, kernel):
        self.kernel = kernel

    @property
    def elements(self):
        return self.kernel.elements

    def draw(self, plan: dict, cells: list[dict]) -> tuple[list[dict], str | None]:
        """
        Draw the grid: one square per cell, each in its own operation.

        Returns the cells enriched with the element and operation ids, so a
        photo overlay can later map a tap back to speed and power — plus the id of the
        group that holds the board together.

        The grouping happens within the same action as the drawing. A board is one thing, so
        making it is one undo; with the grouping outside it, the first `undo` would only
        remove the group and nineteen loose shapes would be left lying on the bed.
        """
        op_type = OPERATION_TYPES.get(plan["operation"])
        if op_type is None:
            raise DesignError(f"Onbekende operation: {plan['operation']}")

        # The whole board, not only the squares: captions and border frame get burned just
        # the same, and those are exactly what stuck out on the left and top (T11).
        outer_x = plan.get("outer_x_mm", plan["origin_x_mm"])
        outer_y = plan.get("outer_y_mm", plan["origin_y_mm"])
        outer_w = plan.get("outer_width_mm", plan["width_mm"])
        outer_h = plan.get("outer_height_mm", plan["height_mm"])
        bed = self._bed_mm()
        # Only to the right and below is this a refusal. On the left and top the captions
        # were already sticking out since T11, and there reporting was deliberately chosen
        # over blocking: the grid part then simply burns, only the labels do not.
        # `label_room` and `board_room` say so in the preview.
        if bed and (outer_x + outer_w > bed[0] or outer_y + outer_h > bed[1]):
            raise DesignError(
                f"Het board ({outer_w:.0f}×{outer_h:.0f} mm vanaf "
                f"{outer_x:.0f},{outer_y:.0f}) falls outside the bed "
                f"of {bed[0]:.0f}×{bed[1]:.0f} mm."
            )

        # Without this every cell *also* lands in every existing operation whose colour
        # matches — the engine classifies new elements automatically. The grid would then be
        # burned twice: once on the cell's setting and once on the other layer's. That makes
        # the test worthless and burns material.
        classify = getattr(self.elements, "classify_new", None)
        if classify is not None:
            self.elements.classify_new = False
        try:
            drawn, group = self._draw_cells(plan, cells)
        finally:
            if classify is not None:
                self.elements.classify_new = classify

        self.elements.signal("rebuild_tree", "all")
        self.elements.signal("refresh_scene", "Scene")
        return drawn, (getattr(group, "id", None) if group is not None else None)

    def _group_board(self, members: list):
        """
        Vouw dít board tot één groep — cells, aslabels, caption en frame.

        A grid is one thing: half-dragging it makes no sense, and as loose squares it fills
        the selection and the canvas with noise. The cells do each keep their own operation —
        otherwise the sweep does not burn.

        Who belongs to it is what this board drew itself, not what a walk through the
        document turns up. That walk looked for the captions on the label layer — and that is
        shared by *all* the boards, so a second board pulled the first one's captions into
        its own group. After that one axis label from board 1 selected the whole of board 2,
        and it moved along as soon as you dragged board 2.
        """
        if len(members) < 2:
            return None
        self.elements.set_emphasis(members)
        self.kernel.console("group\n")
        for node in self.elements.elem_branch.flat():
            if node.type == "group" and any(c in members for c in node.children):
                # A name, so that the panel and the selection bar can say "Test grid"
                # instead of "group".
                node.label = BOARD_LABEL
                return node
        return None

    def _draw_cells(self, plan: dict, cells: list[dict]) -> tuple[list[dict], object]:
        op_type = OPERATION_TYPES[plan["operation"]]
        drawn = []
        # Everything that is *not* a square but does belong to this board.
        extras: list = []
        with self.elements.undoscope("Generate test grid"):
            for cell in cells:
                node = self._square(cell, filled=op_type == "op raster")
                settings = {
                    "type": op_type,
                    "speed": cell["speed_mm_s"],
                    # MeerK40t's power runs 0-1000, not 0-100.
                    "power": cell["power_percent"] * 10,
                    "label": _cell_label(plan, cell),
                    # The same for the whole board; the sweep is in speed, power and
                    # interval.
                    #
                    # Two fields, and the second is not optional: the planner reads
                    # `implicit_passes`, and that gives 1 as long as `passes_custom` is off
                    # (`core/parameters.py:401`). Setting only `passes` gave a board that had
                    # "2 passes" on its caption and burned once — found on material.
                    "passes": int(plan.get("passes") or 1),
                    "passes_custom": int(plan.get("passes") or 1) > 1,
                }
                # The engine calls the line spacing dpi. Only a raster operation knows it;
                # on the others it would be an ignored key.
                if op_type == "op raster" and cell.get("interval_mm"):
                    settings["dpi"] = int(round(25.4 / cell["interval_mm"]))
                operation = self.elements.op_branch.add(**settings)
                operation.add_reference(node)
                drawn.append({**cell, "element_id": None, "operation_id": None,
                              "_node": node, "_op": operation})

            # T10: LightBurn has `Enable Text` and `Enable Border`. For a quick trial on an
            # offcut the caption is a waste; for a board that goes in the cupboard it is half
            # the evidence. On by default.
            if plan.get("text", True):
                self._label_axes(plan, cells, extras)
                self._caption(plan, extras)
            if plan.get("border"):
                self._border(plan, extras)

            # Within the same action: the board is one thing, so also one step in the
            # history.
            group = self._group_board([entry["_node"] for entry in drawn] + extras)

        # Ids only exist once the engine has handed them out.
        self.elements.validate_ids()
        for entry in drawn:
            entry["element_id"] = entry.pop("_node").id
            entry["operation_id"] = entry.pop("_op").id
        return drawn, group

    def _label_axes(self, plan: dict, cells: list[dict], extras: list):
        """
        Engrave the axis labels: the row quantity left, the column one on top.

        Without them the grid is unreadable once it is off the machine — every
        square looks the same and you cannot tell which settings made it. The
        labels go in their own engrave operation, so they are not part of the
        sweep.
        """
        rij_as = plan.get("row_axis", "speed")
        kolom_as = plan.get("column_axis", "power")
        speeds = {c["row"]: axis_value(c, rij_as) for c in cells}
        powers = {c["column"]: axis_value(c, kolom_as) for c in cells}
        pitch = plan["cell_mm"] + plan["gap_mm"]
        # Scale with the square. At true size "25 mm/s" is nearly 20 mm wide and sticks out
        # to the left of the bed.
        text_height = max(2.0, plan["cell_mm"] * 0.35)

        # Only create it when text is really drawn: without a vector font an empty layer
        # would otherwise be left behind.
        labels = None

        for row, speed in sorted(speeds.items()):
            node = self._text(show(rij_as, speed), text_height)
            if node is None:
                return  # Geen vectorfont available; het raster blijft bruikbaar.
            labels = labels or self._label_op(plan)
            self._place(
                node,
                right=plan["origin_x_mm"] - 2,
                middle=plan["origin_y_mm"] + row * pitch + plan["cell_mm"] / 2,
            )
            labels.add_reference(node)
            extras.append(node)

        for column, power in sorted(powers.items()):
            node = self._text(show(kolom_as, power), text_height)
            if node is None or labels is None:
                return
            self._place(
                node,
                center=plan["origin_x_mm"] + column * pitch + plan["cell_mm"] / 2,
                bottom=plan["origin_y_mm"] - 2,
            )
            labels.add_reference(node)
            extras.append(node)

    def _caption(self, plan: dict, extras: list):
        """
        The caption on the board: what is this, of what, when.

        A burned grid without a caption is a puzzling piece of wood in two weeks' time. It
        is in the label layer, so with a fixed, safe setting — the caption has to be readable
        regardless of which cell turns out best.
        """
        # What `plan_grid` already worked out, so that what is burned here is the same
        # lines as the board was measured for — height included.
        lines = plan.get("caption_lines")
        if lines is None:
            lines = caption_lines(plan)
        lines = [r for r in lines if r]
        if not lines:
            return

        height = float(plan.get("caption_height_mm") or 0) or max(
            2.5, plan["cell_mm"] * 0.4
        )
        # Stay within the width of the board. At true size this caption became 70 mm wide
        # on a board of 46 mm — it stuck out to the right, and then the measure we report
        # (T9) does not agree with what burns.
        # `plan_grid` has already chosen the height on this basis; this measurement is the
        # safety tidy for the characters CAPTION_CHAR_RATIO's estimate is out on. The board
        # no longer grows for it: better a slightly smaller line than a board that is wider
        # than its own trial.
        edge = BORDER_PAD_MM if plan.get("border") else 0.0
        available = plan.get("outer_width_mm", plan["width_mm"]) - 2 * edge
        labels = None
        for index, line in enumerate(lines):
            node = self._text(line, height)
            if node is None:
                return
            width = self._width_mm(node)
            if width > available:
                self._scale_to_height(node, height * available / width)
            labels = labels or self._label_op(plan)
            self._place(
                node,
                # Aligned left on the board, not on the squares: the row labels stick out
                # to the left, and a caption starting halfway reads as a caption to the
                # wrong column.
                left=plan.get("outer_x_mm", plan["origin_x_mm"]) + edge,
                # *Above* the column labels, with the same margin as those labels
                # themselves — and in the place `plan_grid` reserved for it, so with the
                # full caption height and not the shrunken measure. Otherwise a shrunken
                # caption drops down and runs straight through the column labels; on a
                # board with large squares that is exactly what happened. The bottom line
                # keeps its old place; every line above it moves up one line spacing.
                bottom=plan["origin_y_mm"]
                - 4
                - height
                - (len(lines) - 1 - index) * CAPTION_LINE_PITCH * height,
            )
            labels.add_reference(node)
            extras.append(node)

    @staticmethod
    def _width_mm(node) -> float:
        from meerk40t.core.units import UNITS_PER_MM

        x0, _, x1, _ = node.bounds
        return (x1 - x0) / UNITS_PER_MM

    def _border(self, plan: dict, extras: list):
        """
        The border frame around the whole board (T10).

        Around *everything*, captions included — a frame straight through the row labels
        makes the board unreadable. It is in the label layer, so with the same safe setting
        as the captions: the frame should stay whatever comes out of the sweep.
        """
        x = plan.get("outer_x_mm", plan["origin_x_mm"])
        y = plan.get("outer_y_mm", plan["origin_y_mm"])
        width = plan.get("outer_width_mm", plan["width_mm"])
        height = plan.get("outer_height_mm", plan["height_mm"])
        before = {id(n) for n in self.elements.elems()}
        self.kernel.console(f"rect {x}mm {y}mm {width}mm {height}mm\n")
        node = next((n for n in self.elements.elems() if id(n) not in before), None)
        if node is None:
            return
        self._label_op(plan).add_reference(node)
        extras.append(node)

    def _label_op(self, plan: dict | None = None):
        """The layer all the captions go into; one for every grid together."""
        # Settable since T10: a hardcoded 80 mm/s @ 30% works on birch and not on acrylic,
        # and then your caption burns straight through it.
        plan = plan or {}
        speed = float(plan.get("label_speed_mm_s") or DEFAULT_LABEL_SPEED_MM_S)
        power = (
            float(plan.get("label_power_percent") or DEFAULT_LABEL_POWER_PERCENT) * 10
        )
        for node in self.elements.op_branch.children:
            if getattr(node, "label", None) == LABEL_LAYER:
                # The layer is already there from a previous board. Anybody asking for a
                # different label setting now gets it too: otherwise you set something in
                # the form that silently does nothing.
                node.speed = speed
                node.power = power
                return node
        return self.elements.op_branch.add(
            type="op engrave",
            speed=speed,
            power=power,
            label=LABEL_LAYER,
        )

    def _label_font(self) -> str | None:
        """
        The typeface a caption on the board goes in.

        Always the same one, and always one that exists: we ask the engine instead of
        assuming a name, because a typeface it cannot open makes `linetext` fall back on —
        quite so — `last_font`.
        """
        registry = getattr(self.kernel.root, "fonts", None)
        if registry is None:
            return None
        for name in LABEL_FONTS:
            try:
                if registry._validate_font(name):
                    return name
            except Exception:
                continue
        return None

    def _text(self, text: str, height_mm: float):
        """
        Vector text via the Hershey fonts; bitmap text has no geometry.

        The typeface and the size are fixed here and passed explicitly. Without `-f` the
        engine takes `last_font` — the typeface of the last text the user placed — and then
        the caption on the board is a matter of luck. Whatever we find that setting on, we
        put back afterwards: the test grid is a guest in somebody else's document.
        """
        before = {id(n) for n in self.elements.elems()}
        font = self._label_font()
        opdracht = ["linetext 0mm 0mm"]
        if font:
            opdracht.append(f'-f "{font}"')
            opdracht.append(f"-s {LABEL_FONT_SIZE_PX}px")
        opdracht.append(f'"{text}"')
        root = self.kernel.root
        root.setting(str, "last_font", "")
        previous = root.last_font
        try:
            self.kernel.console(" ".join(opdracht) + "\n")
        except Exception:
            return None
        finally:
            # `create_linetext_node` sets `last_font` to what it has just used. Here that
            # is our own choice, and it should not become the user's preference.
            root.last_font = previous
        node = next(
            (n for n in self.elements.elems() if id(n) not in before and n.bounds), None
        )
        if node is None:
            return None
        return self._scale_to_height(node, height_mm)

    def _scale_to_height(self, node, height_mm: float):
        from meerk40t.core.units import UNITS_PER_MM

        x0, y0, x1, y1 = (v / UNITS_PER_MM for v in node.bounds)
        current = y1 - y0
        if current <= 0:
            return node
        factor = height_mm / current
        self.elements.set_emphasis([node])
        self.kernel.console(
            f"resize {x0:.4f}mm {y0:.4f}mm "
            f"{max(0.1, (x1 - x0) * factor):.4f}mm {height_mm:.4f}mm\n"
        )
        return node

    def _place(self, node, right=None, center=None, middle=None, bottom=None, left=None):
        """Move a freshly drawn label to where it belongs, measured from its bounds."""
        from meerk40t.core.units import UNITS_PER_MM

        x0, y0, x1, y1 = (v / UNITS_PER_MM for v in node.bounds)
        dx = dy = 0.0
        if right is not None:
            dx = right - x1
        if left is not None:
            dx = left - x0
        if center is not None:
            dx = center - (x0 + x1) / 2
        if bottom is not None:
            dy = bottom - y1
        if middle is not None:
            dy = middle - (y0 + y1) / 2
        self.elements.set_emphasis([node])
        self.kernel.console(f"translate {dx:.4f}mm {dy:.4f}mm\n")

    def _square(self, cell: dict, filled: bool = False):
        """
        One square of the board.

        `filled` for a raster board, and that is not decoration: the rasteriser only burns
        what has a fill. Without a fill it lays down the outline (see
        `test_an_unfilled_shape_burns_its_outline_and_not_its_middle`), and then an
        engraving trial comes out of the machine as a board with nine empty little frames
        instead of nine areas in increasing blackness. A raster trial is precisely about how
        dark the *area* becomes.
        """
        before = set(id(n) for n in self.elements.elems())
        self.kernel.console(
            f"rect {cell['x_mm']}mm {cell['y_mm']}mm "
            f"{cell['width_mm']}mm {cell['height_mm']}mm\n"
        )
        for node in self.elements.elems():
            if id(node) not in before:
                if filled:
                    from meerk40t.svgelements import Color

                    node.fill = Color("black")
                return node
        raise DesignError("The engine created no square.")

    def _bed_mm(self):
        device = getattr(self.kernel, "device", None)
        try:
            from meerk40t.core.units import Length

            return (
                Length(device.bedwidth).mm,
                Length(device.bedheight).mm,
            )
        except Exception:
            return None
