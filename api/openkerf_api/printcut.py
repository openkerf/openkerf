"""
Print and cut: laying a job over marks that are already on the material.

Why this exists: sometimes the material comes in printed. A sheet of stickers, a
printed label, a plate somebody else engraved — and the cut has to land on the
print, not near it. You cannot drag the drawing there by eye, because the sheet
lies where it lies: a couple of millimetres off and a degree askew, and both matter
at kerf scale. LightBurn calls this *Print and Cut*.

## Why it is a refinement and not a new machine

A tile of a series has exactly the same problem: the plate has moved between two
burns and two burned marks say where it is now. That maths is in
`tiling.alignment()` — turn and shift from two point pairs, with two refusals worth
keeping:

- the **distance check**. The distance between two marks does not change, so if the
  measured distance differs, something was pointed at wrongly. Scale is checked and
  never adopted: adopt it, and one 2 mm slip stretches the whole job.
- the **skew bound**. Beyond a few degrees a sheet does not lie askew, you pointed
  at the wrong mark.

So print and cut is that same alignment with a different source for the pairs: not
marks we burned, but two shapes *you* point out in your own drawing — the crosses,
holes or corners that are also on the material — and the head driven over each of
them in turn.

## What it does to the job

Nothing to your drawing. The pose is applied once while the plan is being built,
on the same seam the zero point and the rotary use (`Drawing.shifted`,
`rotary_applied`), through `tiling.pose_matrix` — the very matrix a tile uses. What
is on screen stays where you drew it, which is what you want: the sheet moves, your
design does not.

The pose lives in memory and is deliberately not written to disk. It is a statement
about where a sheet lies *now*; after a restart that sheet is off the bed, and an
alignment you cannot see is one you pay for in material.
"""

from .edits import DesignError
from .tiling import Alignment, Point, TilingError, alignment, pose_matrix

#: How far the measured distance between the two marks may differ from the drawn one.
#: Wider than the tile run's millimetre, because here the two points are pointed at by
#: driving the head — by eye, through a lens, sometimes with a laser pointer — and
#: because a printed sheet really does stretch a little with the weather. Still a
#: check and not a correction: beyond this you have pointed at the wrong thing.
TOLERANCE_MM = 2.0

#: Beyond this the sheet is not askew but wrongly identified. Same number as the tile
#: run's, for the same reason: nobody lays a sheet down five degrees out without seeing
#: it.
MAX_ANGLE_DEG = 3.0


class PoseMutator:
    """
    The whole plan turned and shifted onto the sheet, without clipping anything.

    The tile version of this (`tilerun.TileMutator`) does the same and clips to the
    tile's burn area as well. Here there is nothing to clip: it is one job on one
    sheet, only not where it was drawn.
    """

    def __init__(self, pose: Alignment, units_per_mm: float):
        self.pose = pose
        self.units_per_mm = units_per_mm

    def matrix(self):
        return pose_matrix(self.pose, self.units_per_mm)

    def __call__(self, steps):
        matrix = self.matrix()
        for step in steps:
            children = getattr(step, "children", None)
            if children is None:
                continue
            self._move(step, matrix)
        return list(steps)

    def _move(self, operation, matrix) -> None:
        from meerk40t.core.node.elem_path import PathNode
        from meerk40t.svgelements import Matrix

        replacements = []
        for child in list(operation.children):
            geometry = self._geometry(child)
            if geometry is None:
                # An image: it has no geometry, but it does carry its own matrix.
                replacements.append(self._moved_image(child, matrix))
                continue
            geometry.transform(matrix)
            replacements.append(
                PathNode(
                    geometry,
                    matrix=Matrix(),
                    stroke=getattr(child, "stroke", None),
                    fill=getattr(child, "fill", None),
                    stroke_width=getattr(child, "stroke_width", 1000.0),
                )
            )
        for child in list(operation.children):
            child.remove_node()
        for node in [node for node in replacements if node is not None]:
            operation.add_node(node)

    @staticmethod
    def _geometry(node):
        maker = getattr(node, "as_geometry", None)
        if maker is None:
            return None
        try:
            return maker()
        except Exception:  # pragma: no cover - a node type that will not co-operate
            return None

    @staticmethod
    def _moved_image(node, matrix):
        own = getattr(node, "matrix", None)
        if own is None:
            return node
        node.matrix.post_cat(matrix)
        marker = getattr(node, "set_dirty_bounds", None)
        if marker is not None:
            # A raw matrix assignment tells the node nothing; without this it keeps the
            # bounding box of where it used to be (the same trap as in `edits.py`).
            marker()
        return node


class PrintCut:
    """The two marks you point out, the two you drive to, and the pose between them."""

    def __init__(self, kernel, drawing, motion):
        self.kernel = kernel
        self.drawing = drawing
        self.motion = motion
        #: The shapes in the drawing that are also on the material, by id.
        self._marks: list[str] = []
        #: Where the head was when each of them was pointed at, in mm; None until it was.
        self._measured: list[dict | None] = [None, None]
        self._pose: Alignment | None = None
        #: Which machine the pose was measured on. A pose is a pair of machine
        #: coordinates, so on another machine it means nothing.
        self._machine: str | None = None
        #: Why an alignment that was there is gone, until a new one replaces it. Sticky
        #: on purpose: the panel is read after the fact, not at the moment it happened.
        self._lapsed: str | None = None

    # ------------------------------------------------------------------ reading

    def _centre(self, element_id: str) -> Point:
        """
        A mark's place in the drawing: the middle of its bounding box.

        The middle and not a corner, because a registration mark is a cross or a circle
        and its middle is the thing you can aim at. It also makes the choice independent
        of which way round the shape was drawn.
        """
        node = self.drawing._nodes([element_id])[0]
        bounds = getattr(node, "bounds", None)
        if not bounds:
            raise DesignError(
                "This shape has no size, so there is no point to aim at.",
                code="printcut.noBounds",
            )
        per_mm = self.drawing._units_per_mm()
        x0, y0, x1, y1 = bounds
        return Point((x0 + x1) / 2 / per_mm, (y0 + y1) / 2 / per_mm)

    def _machine_now(self) -> str | None:
        device = getattr(self.kernel, "device", None)
        return getattr(device, "label", None) or getattr(device, "path", None)

    def _lapse_if_gone(self) -> str | None:
        """
        Let the pose lapse when it can no longer be about this drawing or this machine.

        Two ways that happens, both of them quiet. The marks can be deleted — then the
        pose is about shapes that no longer exist, and the numbers stay on the screen
        looking valid. And the machine can be switched — the pose is a pair of *machine*
        coordinates, so on another bed it is a shift into nowhere. Returns why, so the
        panel can say it.
        """
        for element_id in self._marks:
            try:
                self._centre(element_id)
            except DesignError:
                if self._pose is not None:
                    self._lapsed = "gone"
                self._pose = None
                return self._lapsed
        if self._pose is not None and self._machine != self._machine_now():
            self._pose = None
            self._lapsed = "machine"
        return self._lapsed

    def state(self) -> dict:
        """Everything the panel needs, including what is still missing."""
        lapsed = self._lapse_if_gone()
        marks = []
        for index, element_id in enumerate(self._marks):
            try:
                centre = self._centre(element_id)
            except DesignError:
                centre = None
            marks.append(
                {
                    "id": element_id,
                    "drawn": (
                        None
                        if centre is None
                        else {"x_mm": round(centre.x_mm, 3), "y_mm": round(centre.y_mm, 3)}
                    ),
                    "measured": self._measured[index] if index < 2 else None,
                }
            )
        # What a person can check with a ruler: how far the *first* mark moved. The
        # pose's own dx/dy is the translation after turning about the origin, and with
        # any real angle that is a much bigger number than anything on the bed — true,
        # but unreadable, and a number nobody can check is a number nobody trusts.
        offset = None
        first = marks[0] if marks else None
        if first and first["drawn"] and first["measured"]:
            offset = {
                "x_mm": round(first["measured"]["x_mm"] - first["drawn"]["x_mm"], 2),
                "y_mm": round(first["measured"]["y_mm"] - first["drawn"]["y_mm"], 2),
            }
        return {
            "marks": marks,
            "offset_mm": offset,
            "aligned": self._pose is not None,
            "angle_deg": round(self._pose.angle_deg, 3) if self._pose else None,
            "dx_mm": round(self._pose.dx_mm, 2) if self._pose else None,
            "dy_mm": round(self._pose.dy_mm, 2) if self._pose else None,
            "distance_error_mm": (
                round(self._pose.distance_error_mm, 2) if self._pose else None
            ),
            "tolerance_mm": TOLERANCE_MM,
            "max_angle_deg": MAX_ANGLE_DEG,
            # Why an alignment that was there is gone. The panel says it; silently
            # dropping it would look like the app forgot.
            "lapsed": lapsed,
        }

    # ------------------------------------------------------------------ setting

    def set_marks(self, element_ids) -> dict:
        """
        Which two shapes in the drawing are the ones on the material.

        Exactly two: one point gives a shift and no angle, and a shift alone is what the
        zero point already does. Three would let us fit a scale, and scale is precisely
        what we refuse to adopt.
        """
        ids = [str(i) for i in (element_ids or []) if str(i)]
        if len(ids) != 2:
            raise DesignError(
                "Point out exactly two shapes: the two marks that are on the material "
                "as well. With one there is no angle, and with three there is no "
                "agreement.",
                code="printcut.needsTwoMarks",
            )
        if ids[0] == ids[1]:
            raise DesignError(
                "Those are the same shape twice. Two different marks are needed to see "
                "which way the sheet lies.",
                code="printcut.sameMark",
            )
        first, second = self._centre(ids[0]), self._centre(ids[1])
        gap = ((second.x_mm - first.x_mm) ** 2 + (second.y_mm - first.y_mm) ** 2) ** 0.5
        if gap < 10.0:
            raise DesignError(
                f"These two marks lie {gap:.1f} mm apart. That is too close together to "
                "read an angle from: a millimetre of aiming error over 10 mm is already "
                "several degrees. Pick two marks as far apart as the sheet allows.",
                code="printcut.marksTooClose",
            )
        self._marks = ids
        self._measured = [None, None]
        self._pose = None
        self._lapsed = None
        return self.state()

    def measure(self, index: int, x_mm=None, y_mm=None) -> dict:
        """
        Where the head is standing now — over mark 1 or mark 2.

        Without coordinates it reads the machine, which is the ordinary way: you jog the
        head over the mark and press. Coordinates may be given, for a camera or for a
        test.
        """
        if not self._marks:
            raise DesignError(
                "Point out the two marks in your drawing first.",
                code="printcut.noMarks",
            )
        if index not in (0, 1):
            raise DesignError("There are two marks: 1 and 2.", code="printcut.badIndex")
        if x_mm is None or y_mm is None:
            where = self.motion._current_mm()
            if where is None:
                raise DesignError(
                    "The machine does not say where its head is, so it cannot be "
                    "captured. Connect it, or type the coordinates.",
                    code="printcut.noPosition",
                )
            x_mm, y_mm = where
        self._measured[index] = {"x_mm": round(float(x_mm), 3), "y_mm": round(float(y_mm), 3)}
        # A fresh point makes the previous answer stale, and a stale pose is the one
        # thing that must never be quietly kept: it would burn on yesterday's sheet.
        self._pose = None
        if all(self._measured):
            return self._solve()
        return self.state()

    def _solve(self) -> dict:
        """
        The pose from the two pairs, with our own two refusals.

        The maths is the tile run's and stays there. The *checks* are done here instead
        of being handed to `alignment()`, because its sentences talk about marks it
        burned and points you tapped on a photo — and here you drove a head over a
        printed sheet. Same rule, different room, so the wording is ours and the numbers
        are in it.
        """
        drawn = [self._centre(i) for i in self._marks]
        measured = [Point(p["x_mm"], p["y_mm"]) for p in self._measured]
        try:
            pose = alignment(
                drawn[0],
                drawn[1],
                measured[0],
                measured[1],
                # Wide open: the two bounds below are ours, and they have to be able to
                # say what they measured.
                max_angle_deg=360.0,
                tolerance_mm=float("inf"),
            )
        except TilingError as e:
            # What is left is the one case that is not a matter of degree: the two
            # points coincide.
            self._pose = None
            raise DesignError(str(e), code="printcut.samePoint") from e

        off_by = pose.distance_error_mm
        if abs(off_by) > TOLERANCE_MM:
            self._pose = None
            raise DesignError(
                f"The two points you drove to lie {abs(off_by):.1f} mm "
                f"{'further' if off_by > 0 else 'closer'} apart than the same two marks "
                f"in your drawing. That is more than a sheet stretches, so one of the "
                "two is not the mark it was taken for. Drive to them again.",
                code="printcut.distance",
                values={"off_by": round(off_by, 2), "tolerance": TOLERANCE_MM},
            )
        if abs(pose.angle_deg) > MAX_ANGLE_DEG:
            self._pose = None
            raise DesignError(
                f"The sheet would be lying {abs(pose.angle_deg):.1f}° out. A sheet does "
                "not lie that far askew without you seeing it, so the marks were "
                "probably swapped. Lay it straight and drive to them again.",
                code="printcut.askew",
                values={"angle": round(pose.angle_deg, 2), "max": MAX_ANGLE_DEG},
            )
        self._pose = pose
        self._machine = self._machine_now()
        self._lapsed = None
        return self.state()

    def clear(self) -> dict:
        self._marks = []
        self._measured = [None, None]
        self._pose = None
        self._lapsed = None
        return self.state()

    # ------------------------------------------------------------------ burning

    def mutators(self) -> list:
        """
        What the job has to be put through, or nothing at all.

        Nothing at all is the normal case and it matters: every job goes past here, and a
        job without an alignment must take exactly the route it always took.
        """
        self._lapse_if_gone()
        if self._pose is None:
            return []
        return [PoseMutator(self._pose, self.drawing._units_per_mm())]
