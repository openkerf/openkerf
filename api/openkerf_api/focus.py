"""
A focus test: the same short line burned at a series of heights.

Why this exists: the focal point of a lens is a plane a few tenths of a millimetre
thick, and where it lies depends on the lens, the nozzle, the material thickness
and whatever the last person to touch the machine did. Guessing costs a cut that
does not go through, or an engraving that comes out grey. The trade answer is a
sweep: burn the same mark at ten heights, look at which one is thinnest and
darkest, and set the head there. LightBurn has *Focus Test* for exactly this.

## Why it is only offered on some machines

It needs a Z axis the software can move, and that is not a matter of taste: on a
Ruida the driver does not know the word `z_move` at all (see
`Drawing.z_step_supported`). A focus board on such a machine would burn ten
identical marks at one height — ten times the same answer, and material gone. So
the refusal is real, and the interface does not offer the tab there either.

## How the height gets into the job

The engine cannot carry a Z per operation: all passes of an operation share one
settings dict (see the note in CLAUDE.md), and there is no per-layer Z field. What
it *does* have is a console step in the plan, and that is the seam the Z step per
pass already uses. So every mark is an operation of its own carrying
`focus_z_mm` — its offset from the height the head starts at — and
`CommandRunner._with_focus_moves` puts a `z_move` of the *difference* in front of
each one, plus one at the end that brings the head back where it was.

Offsets follow the same sign as the Z step per pass: **positive drops the head**.
That is one convention for both features rather than two, and the label on the
board says which way it went in words as well.
"""

from .edits import DesignError

# What a sweep may span, from the highest mark to the lowest. Beyond this you are no
# longer looking for the focus but driving the head into the work or into its own
# end stop, and the machine will not thank you. The same bound as the Z step per
# pass, for the same reason.
SPAN_LIMIT_MM = 20.0

# Two marks is the fewest that compares anything; beyond this many the marks are so
# close together that the labels no longer fit beside each other, and a board you
# cannot read is a board you burn twice.
MIN_MARKS = 2
MAX_MARKS = 30

# Below this the difference between two neighbouring marks is smaller than what you
# can see on wood with the naked eye, and a sweep of steps you cannot tell apart is
# a sweep that answers nothing.
MIN_STEP_MM = 0.05

# The label layer's settings, and the mark layer's defaults. Engraving numbers at
# cutting power burns them away; the same two numbers as the test grid uses.
DEFAULT_LABEL_SPEED_MM_S = 200.0
DEFAULT_LABEL_POWER_PERCENT = 30.0

# The label under a mark, and how much room a character of it takes. Measured on the
# Hershey font the board actually uses: "-1.5" came out 9.6 mm wide at 3 mm high, so
# 0.8 × the text height per character. The test grid estimates 0.62 for the same font
# and lands on labels that touch — here the numbers stand right next to each other,
# so the estimate has to be the measured one.
LABEL_HEIGHT_MM = 3.0
CHAR_WIDTH_FACTOR = 0.8

BOARD_LABEL = "Focus test"


def _finite(value, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise DesignError(f"{name} has to be a number.", code="focus.notANumber")
    if number != number or number in (float("inf"), float("-inf")):
        raise DesignError(f"{name} has to be a number.", code="focus.notANumber")
    return number


def _positive(value, name: str) -> float:
    number = _finite(value, name)
    if number <= 0:
        raise DesignError(f"{name} has to be greater than zero.", code="focus.notPositive")
    return number


def plan_focus(
    z_from_mm=-2.0,
    z_to_mm=2.0,
    marks=9,
    mark_mm=15.0,
    gap_mm=8.0,
    x_mm=10.0,
    y_mm=10.0,
    speed_mm_s=None,
    power_percent=None,
    text=True,
    label_speed_mm_s=None,
    label_power_percent=None,
    bed=None,
) -> dict:
    """
    Work out the marks without touching the engine, so the form can preview them.

    `z_from_mm` and `z_to_mm` are offsets from the height the head is at when the job
    starts — not absolute machine coordinates, which we cannot know. Positive drops
    the head, as with the Z step per pass.
    """
    low = _finite(z_from_mm, "z_from_mm")
    high = _finite(z_to_mm, "z_to_mm")
    try:
        count = int(marks)
    except (TypeError, ValueError):
        raise DesignError("The number of marks has to be a whole number.", code="focus.notANumber")
    if count < MIN_MARKS:
        raise DesignError(
            f"A focus test needs at least {MIN_MARKS} marks — one mark compares nothing.",
            code="focus.tooFewMarks",
        )
    if count > MAX_MARKS:
        raise DesignError(
            f"{count} marks is more than fits on a board you can still read; "
            f"keep it to {MAX_MARKS}.",
            code="focus.tooManyMarks",
        )
    if low == high:
        raise DesignError(
            "The sweep starts and ends at the same height, so every mark would burn "
            "the same. Give the two ends different numbers.",
            code="focus.noSweep",
        )
    if low > high:
        low, high = high, low
    span = high - low
    if span > SPAN_LIMIT_MM:
        raise DesignError(
            f"A sweep of {span:.1f} mm is further than the head should travel while "
            f"looking for the focus; keep it within {SPAN_LIMIT_MM:g} mm.",
            code="focus.spanTooBig",
        )
    step = span / (count - 1)
    if step < MIN_STEP_MM:
        raise DesignError(
            f"{count} marks over {span:.2f} mm is {step:.3f} mm apart, and that is "
            "closer than you can see on the material. Use fewer marks or a wider sweep.",
            code="focus.stepTooSmall",
        )

    length = _positive(mark_mm, "mark_mm")
    gap = _finite(gap_mm, "gap_mm")
    if gap <= 0:
        raise DesignError(
            "The marks need room between them, otherwise they burn into each other.",
            code="focus.noGap",
        )
    left = _finite(x_mm, "x_mm")
    top = _finite(y_mm, "y_mm")
    with_text = bool(text)

    marks_out = []
    for index in range(count):
        offset = low + step * index
        # A hair of rounding gives labels like "-0.0", and "0" is the height you
        # started at — the one mark whose meaning has to be unmistakable.
        offset = round(offset, 3)
        if offset == 0:
            offset = 0.0
        marks_out.append(
            {
                "index": index,
                "z_mm": offset,
                "x_mm": round(left + index * (gap), 3),
                "y_mm": top,
                "label": _label(offset),
            }
        )

    # How high the numbers can be and still fit in the space one mark has. The pitch
    # is the gap, so a long label ("-12.5") on a tight gap gets small text rather than
    # text that overlaps its neighbour.
    longest = max(len(mark["label"]) for mark in marks_out)
    room = gap * 0.95
    height = LABEL_HEIGHT_MM
    if with_text and longest:
        height = min(LABEL_HEIGHT_MM, room / (CHAR_WIDTH_FACTOR * longest))
        height = round(max(1.2, height), 2)
    label_room = round(height * 2, 2) if with_text else 0.0

    width = round((count - 1) * gap + max(gap * 0.05, 0.5), 3)
    plan = {
        "positions": marks_out,
        "z_from_mm": low,
        "z_to_mm": high,
        "marks": count,
        "step_mm": round(step, 3),
        "mark_mm": length,
        "gap_mm": gap,
        "origin_x_mm": left,
        "origin_y_mm": top,
        "width_mm": width,
        "height_mm": round(length + label_room, 3),
        "text": with_text,
        "label_height_mm": height,
        "speed_mm_s": None if speed_mm_s in (None, "") else _positive(speed_mm_s, "speed_mm_s"),
        "power_percent": (
            None if power_percent in (None, "") else _positive(power_percent, "power_percent")
        ),
        "label_speed_mm_s": _positive(
            DEFAULT_LABEL_SPEED_MM_S if label_speed_mm_s in (None, "") else label_speed_mm_s,
            "label_speed_mm_s",
        ),
        "label_power_percent": _positive(
            DEFAULT_LABEL_POWER_PERCENT
            if label_power_percent in (None, "")
            else label_power_percent,
            "label_power_percent",
        ),
        "notes": [],
    }
    if plan["power_percent"] is not None and plan["power_percent"] > 100:
        raise DesignError("Power cannot go above 100 per cent.", code="focus.powerTooHigh")
    if plan["label_power_percent"] > 100:
        raise DesignError(
            "The power of the label layer cannot go above 100 per cent.",
            code="focus.powerTooHigh",
        )
    if bed:
        bed_width, bed_height = bed
        if left + plan["width_mm"] > bed_width or top + plan["height_mm"] > bed_height:
            raise DesignError(
                f"The board ({plan['width_mm']:.0f}×{plan['height_mm']:.0f} mm from "
                f"{left:.0f},{top:.0f}) falls outside the bed of "
                f"{bed_width:.0f}×{bed_height:.0f} mm.",
                code="focus.offBed",
            )
    return plan


def _label(offset: float) -> str:
    """The number under a mark. Whole numbers stay whole: "2" reads faster than "2.0"."""
    if offset == int(offset):
        return f"{int(offset):+d}" if offset else "0"
    text = f"{offset:+.2f}".rstrip("0").rstrip(".")
    return text


class FocusBoard:
    """Drawing a focus board, and reading back what it takes to burn it."""

    def __init__(self, kernel, drawing):
        self.kernel = kernel
        self.drawing = drawing

    @property
    def elements(self):
        return self.kernel.elements

    def supported(self) -> bool:
        """The same question the Z step per pass asks, so the same answer."""
        return self.drawing.z_step_supported()

    def _bed_mm(self):
        device = getattr(self.kernel, "device", None)
        if device is None:
            return None
        try:
            from meerk40t.core.units import Length

            return (
                float(Length(device.view.width).mm),
                float(Length(device.view.height).mm),
            )
        except Exception:  # pragma: no cover - a device without a view
            return None

    def plan(self, **fields) -> dict:
        return plan_focus(bed=self._bed_mm(), **fields)

    def draw(self, **fields) -> dict:
        """
        Put a focus board on the sheet: one line per height, each in its own layer.

        The refusal for a machine without a movable Z comes first and it is a refusal,
        not a warning: the board would burn every mark at the same height, which looks
        like an answer and is not.
        """
        if not self.supported():
            raise DesignError(
                "This machine has no Z axis the software can move, so a focus test "
                "would burn every mark at the same height. Set the focus by hand here.",
                code="focus.noZAxis",
            )
        plan = self.plan(**fields)
        from .testgrid import TestGridGenerator

        # The label machinery is the test grid's, on purpose: it picks a typeface that
        # exists, puts `last_font` back afterwards, and scales text to a height in
        # millimetres. Writing that a second time would be a second set of bugs.
        labeller = TestGridGenerator(self.kernel)

        classify = getattr(self.elements, "classify_new", None)
        if classify is not None:
            # Without this every mark also lands in whatever layer has a matching
            # colour, and then it burns twice — once at its own height and once at the
            # other layer's. That is a board that answers the wrong question.
            self.elements.classify_new = False
        drawn = []
        try:
            with self.elements.undoscope("Generate focus test"):
                extras = []
                for mark in plan["positions"]:
                    node = self._line(mark, plan)
                    operation = self.elements.op_branch.add(
                        type="op cut",
                        speed=plan["speed_mm_s"] or 20.0,
                        # MeerK40t's power runs 0-1000, not 0-100.
                        power=(plan["power_percent"] or 100.0) * 10,
                        label=f"{BOARD_LABEL} {mark['label']} mm",
                    )
                    operation.add_reference(node)
                    # The seam: the plan turns this into a `z_move` before the layer.
                    operation.focus_z_mm = mark["z_mm"]
                    drawn.append({**mark, "_node": node, "_op": operation})
                    if plan["text"]:
                        label = labeller._text(mark["label"], plan["label_height_mm"])
                        if label is not None:
                            labeller._place(
                                label,
                                center=mark["x_mm"],
                                middle=plan["origin_y_mm"]
                                + plan["mark_mm"]
                                + plan["label_height_mm"],
                            )
                            labeller._label_op(
                                {
                                    "label_speed_mm_s": plan["label_speed_mm_s"],
                                    "label_power_percent": plan["label_power_percent"],
                                }
                            ).add_reference(label)
                            extras.append(label)
                group = labeller._group_board(
                    [entry["_node"] for entry in drawn] + extras
                )
        finally:
            if classify is not None:
                self.elements.classify_new = classify

        self.elements.validate_ids()
        for entry in drawn:
            entry["element_id"] = entry.pop("_node").id
            entry["operation_id"] = entry.pop("_op").id
        self.elements.signal("rebuild_tree", "all")
        self.elements.signal("refresh_scene", "Scene")
        return {
            **{key: value for key, value in plan.items() if key != "positions"},
            "drawn": drawn,
            "group_id": getattr(group, "id", None) if group is not None else None,
            "ids": [entry["element_id"] for entry in drawn],
        }

    def _line(self, mark: dict, plan: dict):
        """One mark: a straight line. A line shows the kerf, a square shows the fill."""
        made = self.drawing.create_path(
            [
                (mark["x_mm"], plan["origin_y_mm"]),
                (mark["x_mm"], plan["origin_y_mm"] + plan["mark_mm"]),
            ],
            closed=False,
            label=f"{BOARD_LABEL} {mark['label']} mm",
        )
        node = self.elements.find_node(made["ids"][0])
        return node
