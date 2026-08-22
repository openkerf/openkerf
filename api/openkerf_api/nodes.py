"""
Editing nodes: dragging a shape's own points.

Until now you could move, scale and rotate a shape as a whole, but not move one corner. That
is exactly what you need to make a scanned or imported path fit. Since P1 a node can also be
added, removed and turned from a corner into a curve, and a curve's handle can be dragged —
without that, a curve could be imported into OpenKerf but never drawn or repaired.

Three things to know:

- The engine keeps an `elem path` as a **Geomstr**: segments with complex numbers as
  points. Moving a point means adjusting every segment that point occurs in — start *and*
  end point, otherwise the path falls open.
- Shapes (`elem rect`, `elem ellipse`, …) have no separate points; they are parameters.
  Anybody dragging a corner of one means "make it a path". So that is what we do, keeping
  the colour, the layer assignment and the label — otherwise the shape disappears from its
  operation and would no longer burn.
- A **segment** is what carries the curve, not the node: the engine keeps its control points
  per segment (a quad and an arc store the same one twice, in both control columns). So a
  kind and a handle are addressed by segment index and an anchor by node index. Two
  numberings, and confusing them is the one sure way to bend the wrong piece.
"""

from __future__ import annotations

from .edits import DesignError

# Points within this distance (in Tats) are the same point. 65535 Tats is an inch, so this
# is roughly a hundredth of a millimetre.
SAME_POINT = 30.0

SHAPES = ("elem rect", "elem ellipse", "elem line", "elem polyline", "elem path")

#: Segment type → the word we call it by. Filled on first use: importing geomstr at module
#: level would pull numpy into every import of this API.
_KIND_NAMES: dict[int, str] = {}


def _kinds() -> dict[int, str]:
    if not _KIND_NAMES:
        from meerk40t.core.geomstr import TYPE_ARC, TYPE_CUBIC, TYPE_LINE, TYPE_QUAD

        _KIND_NAMES.update(
            {TYPE_LINE: "line", TYPE_QUAD: "quad", TYPE_CUBIC: "cubic", TYPE_ARC: "arc"}
        )
    return _KIND_NAMES


class Nodes:
    def __init__(self, kernel, runner=None):
        self.kernel = kernel
        self.runner = runner

    @property
    def elements(self):
        return self.kernel.elements

    def points(self, element_id: str) -> dict:
        """
        The nodes of an element, in millimetres — and the segments between them.

        `points` is the anchors, and it is exactly what it always was: the editor and the
        canvas both key on that numbering. `segments` is beside it, because a curve does
        not live in a point but between two of them. Without it the node tool could not
        draw a handle, let alone drag one: measured on a path `M 10,10 Q 60,10 35,60 …`
        the answer named the three anchors and the control point (35, 60) appeared
        nowhere.
        """
        node = self._node(element_id)
        geometry = self._geometry(node)
        anchors = self._unique(geometry)
        return {
            "id": element_id,
            "type": node.type,
            "editable": node.type in SHAPES,
            "closed": self._closed(geometry),
            "points": [
                {"index": index, **self._mm(point)}
                for index, point in enumerate(anchors)
            ],
            "segments": self._segments(geometry, anchors),
        }

    def move_point(self, element_id: str, index, x_mm, y_mm) -> dict:
        from meerk40t.core.units import UNITS_PER_MM

        node = self._node(element_id)
        self._must_be_editable(node)
        position = self._whole(index, "index")
        target = complex(
            self._number(x_mm, "x") * UNITS_PER_MM, self._number(y_mm, "y") * UNITS_PER_MM
        )

        geometry = self._geometry(node)
        points = self._unique(geometry)
        if not 0 <= position < len(points):
            raise DesignError(
                f"Node {position} does not exist; there are {len(points)}.",
                code="nodes.noSuchNode",
            )

        moved = self._with_point_moved(geometry, points[position], target)
        with self.elements.undoscope("Move node"):
            new_id = self._replace(node, moved, element_id)
        self.elements.signal("refresh_scene", "Scene")
        return {"id": new_id, "was": element_id, "index": position}

    # ------------------------------------------------------------ adding and removing

    def insert_point(
        self, element_id: str, segment_index=None, t=None, x_mm=None, y_mm=None
    ) -> dict:
        """
        A new node on a segment.

        Two ways in, because the two callers know different things. The canvas knows
        where the double-click landed and nothing else, so it sends a point in
        millimetres and we look for the nearest place on the shape. The menu knows the
        segment (the one after the selected node) and asks for its middle.

        The parameter is kept away from the very ends: a double-click two per cent from
        a corner would otherwise leave a segment of almost no length behind, which is a
        node you can never grab again.
        """
        node = self._node(element_id)
        self._must_be_editable(node)
        geometry = self._geometry(node)
        rows = self._rows(geometry)
        carrying = self._carrying(geometry)

        if segment_index is None:
            index, parameter = self._nearest(geometry, self._units(x_mm, y_mm, "point"))
        else:
            index = self._whole(segment_index, "segment_index")
            if index not in carrying:
                raise DesignError(
                    f"Segment {index} does not exist; this shape has "
                    f"{len(carrying)} of them.",
                    code="nodes.noSuchSegment",
                )
            parameter = 0.5 if t is None else self._number(t, "t")
        parameter = min(0.98, max(0.02, parameter))

        landing = complex(geometry.position(index, parameter))
        rows[index : index + 1] = self._pieces(geometry, index, [parameter])
        fresh = self._from_rows(rows)
        with self.elements.undoscope("Add node"):
            new_id = self._replace(node, fresh, element_id)
        self.elements.signal("refresh_scene", "Scene")
        return {
            "id": new_id,
            "was": element_id,
            "index": self._index_of(self._unique(fresh), landing),
        }

    def remove_point(self, element_id: str, index) -> dict:
        """
        Taking a node away, and joining what met there.

        The two segments that met at the node become one, and it keeps the shape as far
        as it can: two straight pieces become a straight piece, two arcs become the arc
        through the three remaining points (a circle stays a circle), and anything with
        a curve in it becomes a cubic that leaves and arrives along the old tangents.
        An end node of an open path has only one segment, and then removing the node is
        removing that segment.

        What is refused is what would leave no shape behind: an open path needs two
        points to be a line, a closed one needs three to have an inside.
        """
        node = self._node(element_id)
        self._must_be_editable(node)
        geometry = self._geometry(node)
        anchors = self._unique(geometry)
        position = self._whole(index, "index")
        if not 0 <= position < len(anchors):
            raise DesignError(
                f"Node {position} does not exist; there are {len(anchors)}.",
                code="nodes.noSuchNode",
            )
        closed = self._closed(geometry)
        if closed and len(anchors) <= 3:
            raise DesignError(
                "A closed shape needs three points; this one has three.",
                code="nodes.closedNeedsThree",
            )
        if not closed and len(anchors) <= 2:
            raise DesignError(
                "A line needs two points; there are two left.",
                code="nodes.openNeedsTwo",
            )

        point = anchors[position]
        rows = self._rows(geometry)
        incoming = [i for i in self._carrying(geometry) if self._same(rows[i][4], point)]
        outgoing = [i for i in self._carrying(geometry) if self._same(rows[i][0], point)]
        if not incoming and not outgoing:  # pragma: no cover - _unique found it
            raise DesignError(
                f"Node {position} does not exist; there are {len(anchors)}.",
                code="nodes.noSuchNode",
            )
        if not incoming:
            del rows[outgoing[0]]
        elif not outgoing:
            del rows[incoming[-1]]
        else:
            before, after = incoming[-1], outgoing[0]
            merged = self._merged(geometry, before, after, point)
            # A closed path meets at its first node with the *last* segment, so the two
            # are not neighbours in the array. Then the merged piece takes the place of
            # the outgoing one and the incoming one simply goes.
            if before < after:
                rows[before : after + 1] = [merged]
            else:
                rows[after] = merged
                del rows[before]

        fresh = self._from_rows(rows)
        with self.elements.undoscope("Remove node"):
            new_id = self._replace(node, fresh, element_id)
        self.elements.signal("refresh_scene", "Scene")
        return {"id": new_id, "was": element_id, "index": position}

    # ------------------------------------------------------------ curve or corner

    #: What a segment can be turned into. An arc is not among them: an arc is defined by
    #: three points on one circle, and "make this an arc" has no such circle to name.
    KINDS = ("line", "quad", "cubic")

    def set_kind(self, element_id: str, segment_index, kind) -> dict:
        """
        A corner into a curve and back.

        Turning it into a curve does not move a millimetre: the handles land on the
        chord (a quad's in the middle, a cubic's at a third and two thirds), so the
        picture is the same and there is now something to drag. Measured on a rectangle:
        `L 100,0` becomes `Q 50,0 100,0` and back to `L 100,0`.
        """
        wanted = str(kind or "").strip().lower()
        if wanted not in self.KINDS:
            raise DesignError(
                f"A segment can be a {', '.join(self.KINDS)}, not a '{wanted}'.",
                code="nodes.unknownKind",
            )
        node = self._node(element_id)
        self._must_be_editable(node)
        geometry = self._geometry(node)
        index = self._segment(geometry, segment_index)
        rows = self._rows(geometry)
        rows[index] = self._as_kind(geometry, index, wanted)

        fresh = self._from_rows(rows)
        with self.elements.undoscope("Change segment"):
            new_id = self._replace(node, fresh, element_id)
        self.elements.signal("refresh_scene", "Scene")
        return {"id": new_id, "was": element_id, "segment": index, "kind": wanted}

    def move_control(self, element_id: str, segment_index, which, x_mm, y_mm) -> dict:
        """
        Dragging a handle.

        A quad and an arc keep the same control point in both control columns of the
        segment, so one handle writes both; a cubic has a handle of its own on each
        side. A straight segment has no handle at all — it has to become a curve first,
        and saying that is more use than silently bending it.
        """
        from meerk40t.core.geomstr import TYPE_CUBIC, TYPE_LINE

        node = self._node(element_id)
        self._must_be_editable(node)
        geometry = self._geometry(node)
        index = self._segment(geometry, segment_index)
        rows = self._rows(geometry)
        row = rows[index]
        info = int(complex(row[2]).real)
        if info == TYPE_LINE:
            raise DesignError(
                "A straight segment has no handle; make it a curve first.",
                code="nodes.noHandle",
            )
        target = self._units(x_mm, y_mm, "handle")
        side = self._whole(which, "which") if which is not None else 1
        if side not in (1, 2):
            raise DesignError(
                "A handle is the first or the second one.", code="nodes.noSuchHandle"
            )
        columns = (1,) if side == 1 else (3,)
        if info != TYPE_CUBIC:
            columns = (1, 3)
        row = list(row)
        for column in columns:
            row[column] = target
        rows[index] = row

        fresh = self._from_rows(rows)
        with self.elements.undoscope("Move handle"):
            new_id = self._replace(node, fresh, element_id)
        self.elements.signal("refresh_scene", "Scene")
        return {"id": new_id, "was": element_id, "segment": index, "which": side}

    # --------------------------------------------------------------- intern

    def _node(self, element_id: str):
        node = self.elements.find_node(element_id)
        if node is None:
            raise DesignError(f"Element {element_id} does not exist (any more).")
        return node

    def _must_be_editable(self, node) -> None:
        if node.type not in SHAPES:
            raise DesignError(
                f"The nodes of a {node.type} cannot be edited.",
                code="nodes.notEditable",
            )

    # ---- reading the array ------------------------------------------------------

    def _rows(self, geometry) -> list:
        """The segments as a plain list, so a piece can be cut in or out of it.

        Not `Geomstr.replace`: that one works out its own space with
        `allocate_at_position`, and deleting a segment there is off by one (`replace(i, i,
        [])` drops segment *i-1*). A list plus one fresh Geomstr is a hundred segments of
        work and no arithmetic to get wrong.
        """
        return [list(geometry.segments[i]) for i in range(geometry.index)]

    def _from_rows(self, rows):
        from meerk40t.core.geomstr import Geomstr

        fresh = Geomstr()
        for row in rows:
            fresh.append_segment(
                complex(row[0]),
                complex(row[1]),
                complex(row[2]),
                complex(row[3]),
                complex(row[4]),
            )
        return fresh

    def _carrying(self, geometry) -> list[int]:
        """The indices of the segments that carry geometry.

        The rest — an end marker, a nop, a bare point — has no length and no handles, and
        a shape of several subpaths has those in between.
        """
        return [
            i
            for i in range(geometry.index)
            if int(complex(geometry.segments[i][2]).real) in _kinds()
        ]

    def _kind_of(self, geometry, index: int) -> str:
        return _kinds()[int(complex(geometry.segments[index][2]).real)]

    def _segments(self, geometry, anchors: list[complex]) -> list[dict]:
        """Every carrying segment with its kind, its two anchors and its handles."""
        from meerk40t.core.geomstr import TYPE_CUBIC, TYPE_LINE

        found = []
        for index in self._carrying(geometry):
            row = geometry.segments[index]
            info = int(complex(row[2]).real)
            controls = []
            if info != TYPE_LINE:
                controls.append({"which": 1, **self._mm(complex(row[1]))})
                if info == TYPE_CUBIC:
                    controls.append({"which": 2, **self._mm(complex(row[3]))})
            found.append(
                {
                    "index": index,
                    "kind": self._kind_of(geometry, index),
                    "start": self._index_of(anchors, complex(row[0])),
                    "end": self._index_of(anchors, complex(row[4])),
                    "controls": controls,
                }
            )
        return found

    def _subpaths(self, geometry) -> list[list[int]]:
        """
        The carrying segments grouped per subpath, in the order the path runs.

        A new subpath begins wherever a segment does not start where the previous one
        ended — that is the only marker there is, and it works whether the engine wrote an
        end marker in between or not.
        """
        groups: list[list[int]] = []
        previous = None
        for index in self._carrying(geometry):
            row = geometry.segments[index]
            if previous is None or not self._same(row[0], previous):
                groups.append([])
            groups[-1].append(index)
            previous = complex(row[4])
        return groups

    def _closed(self, geometry) -> bool:
        """
        Does the shape come back to where it started?

        There is no marker for it: a rectangle is four lines and nothing says "closed".
        So the only honest reading is the one the path itself gives — the last segment of
        every subpath ends where that subpath's first one begins.

        Per subpath, because a shape of several loops closes only if all of them do.
        Measured on `text "Hi"` (three subpaths, each a closed loop): reading only the
        first and the last row of the whole shape said `false`, and on that answer removing
        a node was allowed down to two points on a shape that has an inside.
        """
        groups = self._subpaths(geometry)
        if not groups:
            return False
        return all(
            len(group) >= 2
            and self._same(
                geometry.segments[group[-1]][4], geometry.segments[group[0]][0]
            )
            for group in groups
        )

    def _same(self, one, other) -> bool:
        return abs(complex(one) - complex(other)) <= SAME_POINT

    def _index_of(self, anchors: list[complex], point: complex) -> int:
        for index, anchor in enumerate(anchors):
            if self._same(anchor, point):
                return index
        return -1

    def _segment(self, geometry, segment_index) -> int:
        carrying = self._carrying(geometry)
        index = self._whole(segment_index, "segment_index")
        if index not in carrying:
            raise DesignError(
                f"Segment {index} does not exist; this shape has {len(carrying)} of them.",
                code="nodes.noSuchSegment",
            )
        return index

    def _nearest(self, geometry, point: complex) -> tuple[int, float]:
        """
        The place on the shape closest to a point, as a segment and a parameter.

        Sampled and not solved: a cubic's nearest point is a fifth-degree root, and this
        is a double-click on a screen. Thirty-two samples per segment is a fifth of a
        millimetre on a segment of 50 mm, and the parameter is refined once around the
        best sample, which brings it under a hundredth.
        """
        best = (None, 0.0, float("inf"))
        for index in self._carrying(geometry):
            for step in range(33):
                t = step / 32
                gap = abs(complex(geometry.position(index, t)) - point)
                if gap < best[2]:
                    best = (index, t, gap)
        if best[0] is None:
            raise DesignError(
                "This shape has no segment to put a node on.",
                code="nodes.noSegments",
            )
        index, coarse = best[0], best[1]
        fine = (index, coarse, best[2])
        for step in range(-16, 17):
            t = min(1.0, max(0.0, coarse + step / 512))
            gap = abs(complex(geometry.position(index, t)) - point)
            if gap < fine[2]:
                fine = (index, t, gap)
        return fine[0], fine[1]

    def _pieces(self, geometry, index: int, ts):
        """
        Splitting one segment, arcs included.

        `Geomstr.split` has no branch for an arc and hands back zero pieces for one
        (upstream #3263), so a node added to a circle would make the quarter it landed on
        vanish. `tiling._pieces` already had to solve exactly that, and an arc through
        three points of a circle *is* that circle — so we use it rather than write it
        twice.
        """
        from .tiling import _pieces

        return [list(piece) for piece in _pieces(geometry, index, list(ts))]

    # ---- units -----------------------------------------------------------------

    def _mm(self, point: complex) -> dict:
        from meerk40t.core.units import UNITS_PER_MM

        return {"x_mm": point.real / UNITS_PER_MM, "y_mm": point.imag / UNITS_PER_MM}

    def _units(self, x_mm, y_mm, what: str) -> complex:
        from meerk40t.core.units import UNITS_PER_MM

        return complex(
            self._number(x_mm, f"{what} x") * UNITS_PER_MM,
            self._number(y_mm, f"{what} y") * UNITS_PER_MM,
        )

    def _number(self, value, what: str) -> float:
        import math

        try:
            number = float(value)
        except (TypeError, ValueError) as e:
            raise DesignError(
                f"{what.capitalize()} needs a number.", code="nodes.needsNumber"
            ) from e
        if not math.isfinite(number):
            raise DesignError(
                f"{what.capitalize()} needs a number.", code="nodes.needsNumber"
            )
        return number

    def _whole(self, value, what: str) -> int:
        try:
            return int(value)
        except (TypeError, ValueError) as e:
            raise DesignError(
                f"{what.capitalize()} needs a whole number.", code="nodes.needsNumber"
            ) from e

    # ---- rebuilding one segment -------------------------------------------------

    def _as_kind(self, geometry, index: int, wanted: str) -> list:
        """One segment as another kind, moving the shape as little as it can."""
        from meerk40t.core.geomstr import Geomstr

        row = geometry.segments[index]
        start, end = complex(row[0]), complex(row[4])
        # The settings level rides along; it is the layer the engine put this piece in and
        # dropping it would silently move the segment to level 0.
        settings = int(complex(row[2]).imag)
        fresh = Geomstr()
        if wanted == "line":
            fresh.line(start, end, settings=settings)
        elif wanted == "quad":
            fresh.quad(start, self._quad_control(geometry, index), end, settings=settings)
        else:
            first, second = self._cubic_controls(geometry, index)
            fresh.cubic(start, first, second, end, settings=settings)
        return list(fresh.segments[0])

    def _quad_control(self, geometry, index: int) -> complex:
        """The one control point a quad would have here."""
        from meerk40t.core.geomstr import TYPE_CUBIC, TYPE_LINE, TYPE_QUAD

        row = geometry.segments[index]
        start, end = complex(row[0]), complex(row[4])
        info = int(complex(row[2]).real)
        if info == TYPE_QUAD:
            return complex(row[1])
        if info == TYPE_LINE:
            # On the chord: the curve looks exactly like the line it came from, and there
            # is now a handle to pull it away with.
            return (start + end) / 2
        if info == TYPE_CUBIC:
            # Degree reduction; exact for a cubic that was a quad to begin with, and the
            # nearest quad otherwise.
            return (3 * (complex(row[1]) + complex(row[3])) - start - end) / 4
        # An arc: the quad through its middle. A quad at t=0.5 sits halfway between the
        # chord's middle and its control, so the control is twice the distance out.
        return 2 * complex(geometry.position(index, 0.5)) - (start + end) / 2

    def _cubic_controls(self, geometry, index: int) -> tuple[complex, complex]:
        """
        The two controls a cubic would have here.

        One upstream trap to know about: a cubic whose two controls have the same y (or x)
        reads as **flat** from `Geomstr._bbox_segment`. The test for a vanishing
        denominator there compares an absolute 1e-12 against numbers of the order 1e5, so
        the cancellation at Tat scale does not register and the local extreme is never
        computed. Measured on the quad `Q 35,60` over (10,10)-(60,10): as a quad the bounds
        say 10→35 mm in y, and the identical cubic says 10→10. That is what the selection
        frame and the "outside the bed" warning read, so it is visible.
        A symmetric quad turns into exactly such a cubic — which is why the *menu* offers a
        quad ("make this a curve") and a cubic only comes in through the pen and through
        `set_kind` on purpose.
        """
        from meerk40t.core.geomstr import TYPE_CUBIC, TYPE_LINE

        row = geometry.segments[index]
        start, end = complex(row[0]), complex(row[4])
        info = int(complex(row[2]).real)
        if info == TYPE_CUBIC:
            return complex(row[1]), complex(row[3])
        if info == TYPE_LINE:
            return start + (end - start) / 3, start + 2 * (end - start) / 3
        # A quad (or an arc through its quad) is exactly a cubic with its control two
        # thirds of the way from each end towards the quad's control.
        control = self._quad_control(geometry, index)
        return start + 2 * (control - start) / 3, end + 2 * (control - end) / 3

    def _merged(self, geometry, before: int, after: int, point: complex) -> list:
        """
        The one segment that replaces two when the node between them goes.

        Two arcs become the arc through the three remaining points, because that is the
        only merge that keeps a circle a circle. Two straight pieces become a straight
        piece. Everything else becomes a cubic that leaves along the first tangent and
        arrives along the second — the shape a drawing program leaves behind, and the
        removed point is no longer on it.
        """
        from meerk40t.core.geomstr import Geomstr

        first, second = geometry.segments[before], geometry.segments[after]
        start, end = complex(first[0]), complex(second[4])
        kinds = (self._kind_of(geometry, before), self._kind_of(geometry, after))
        fresh = Geomstr()
        if kinds == ("line", "line"):
            fresh.line(start, end)
        elif kinds == ("arc", "arc"):
            fresh.arc(start, point, end)
        else:
            departure = self._cubic_controls(geometry, before)[0]
            arrival = self._cubic_controls(geometry, after)[1]
            fresh.cubic(start, departure, arrival, end)
        return list(fresh.segments[0])

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

        Only the carrying rows, which is the whole point of `_carrying`: a shape of several
        subpaths has end markers in between, and those rows hold `nan` in every column.
        Measured on the `elem path` that `text "Hi"` leaves behind (three subpaths, 24
        rows): this walked all 24 and reported 28 anchors of which 8 were `nan`, the honest
        ones starting at index 2 — and `nan` is not JSON, so the route answered HTTP 500 and
        the node tool showed nothing at all. The `segments[].start/end` numbering is against
        this same list, so it was wrong by the same shift.
        """
        found: list[complex] = []
        for index in self._carrying(geometry):
            segment = geometry.segments[index]
            for point in (segment[0], segment[4]):
                value = complex(point)
                if not any(abs(value - seen) <= SAME_POINT for seen in found):
                    found.append(value)
        return found

    def _with_point_moved(self, geometry, source: complex, target: complex):
        """
        A copy of the shape with that one point moved — handles and all.

        A curve's handles move with the anchor they belong to. Before P1 they did not,
        unless a handle happened to lie *on* the anchor, and then dragging one end of a
        curve deformed it instead of carrying it: the far half stayed where it was and
        the curve bulged. Every drawing program carries the handles.

        How far each handle goes is not a guess. Shift a quad's control by half the
        movement, or a cubic's controls by two thirds and one third, and every point of
        the curve moves by `shift · (1 − t)`: the whole thing at the anchor you are
        dragging, nothing at all at the other end, and a straight taper in between. That
        is what "the curve follows this end" means, and it drops out of the Bernstein
        basis exactly.

        A straight segment keeps its control columns: the engine does not read them for a
        line (`Geomstr.line` writes plain zeros there) and moving them would be inventing
        data.
        """
        import copy

        from meerk40t.core.geomstr import TYPE_CUBIC, TYPE_LINE

        moved = copy.deepcopy(geometry)
        shift = target - source
        for segment in moved.segments[: moved.index]:
            at_start = self._same(segment[0], source)
            at_end = self._same(segment[4], source)
            if at_start:
                segment[0] = target
            if at_end:
                segment[4] = target
            if not (at_start or at_end):
                continue
            info = int(complex(segment[2]).real)
            if info == TYPE_LINE or info not in _kinds():
                continue
            if info == TYPE_CUBIC:
                shares = (
                    (2 / 3 if at_start else 0) + (1 / 3 if at_end else 0),
                    (1 / 3 if at_start else 0) + (2 / 3 if at_end else 0),
                )
            else:
                # A quad and an arc keep one control point in both columns, so both get
                # the same share of the movement.
                share = 1.0 if at_start and at_end else 0.5
                shares = (share, share)
            segment[1] = complex(segment[1]) + shift * shares[0]
            segment[3] = complex(segment[3]) + shift * shares[1]
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
            # And the bounding box has to be forgotten, or it keeps the one from before.
            # Measured: turning a quad into a cubic left `bounds` reporting a flat
            # 10→10 mm in y while the curve itself still bulged to 35 mm — so the
            # selection frame, the "outside the bed" warning and nesting all read the
            # old shape. Same family as the upstream traps in CLAUDE.md where a raw
            # matrix assignment tells the node nothing.
            node.set_dirty_bounds()
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
