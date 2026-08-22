"""
Editing elements: move, resize, rotate, layer assignment, undo, redo.

Element transforms in MeerK40t act on the *emphasized* selection, not on an
argument. Each edit therefore sets emphasis to exactly the nodes it targets and
then runs the console command, so the engine's own selection ends up matching
what the user picked in the browser. Emphasis is a set, so the same code path
handles one element or twenty.

Undo caveat, re-verified against the engine: ids normally *do* survive an undo.
What undo restores is a whole-tree snapshot, so it can land on a state from
before ids were assigned at all — then `validate_ids()` renumbers and hands out
different ids than the client holds. Undo can also step back further than the
last edit (observed: three moves, one undo, two of them gone), so the tree after
an undo is not reliably the tree the client was looking at.

Both are reasons not to trust a held id afterwards, which is why undo/redo
report `ids_invalidated` and the frontend drops its selection instead of
risking a stale id pointing at another element.
"""

import math

from .commands import CommandRunner
from .design import _visual_angle


class DesignError(RuntimeError):
    """
    A refusal the user can act on, in the user's own terms.

    `code` is optional and exists for one reason: the interface can then say it in
    the reader's language. The message is English — the source language of this
    layer — and is what a client without a catalogue shows: curl, a script, a log.
    A raise without a code is one whose message only a developer reads.

    `values` carries the numbers the sentence needs, for the refusal whose only
    variable is a constant of ours: the interface then has the number and can put it
    in its own sentence. Measured before this: "More than 200 bridges in one contour
    is not a cut any more." came out in English in an otherwise Dutch panel, because
    a code alone could not carry the 200. A refusal whose numbers are *measured* per
    call still keeps its English sentence — see the note in `en.ts`.
    """

    def __init__(
        self, message: str, code: str | None = None, values: dict | None = None
    ):
        super().__init__(message)
        self.code = code
        self.values = values


def _finite(value, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as e:
        raise DesignError(f"{name} has to be a number.") from e
    if not math.isfinite(number):
        raise DesignError(f"{name} has to be a finite number.")
    return number


def _positive(value, name: str) -> float:
    number = _finite(value, name)
    if number <= 0:
        raise DesignError(f"{name} has to be greater than zero.")
    return number


def _mm(value: float) -> str:
    """Console commands take unit strings; millimetres keep it readable."""
    return f"{value:.4f}mm"


def _ids(value) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)) or not value:
        raise DesignError("Name at least one element.", code="edit.needsElement")
    return [str(v) for v in value]


def _subpath_count(node) -> int:
    """How many loose pieces a shape has; 0 when there is no geometry."""
    try:
        geometry = (
            node.final_geometry() if hasattr(node, "final_geometry") else node.as_geometry()
        )
        geometry.ensure_proper_subpaths()
        return len(list(geometry.as_subpaths()))
    except AttributeError:
        return 0


class DesignEditor:
    def __init__(self, kernel, runner: CommandRunner | None = None):
        self.kernel = kernel
        self.runner = runner or CommandRunner(kernel)

    @property
    def elements(self):
        return self.kernel.elements

    def _node(self, node_id: str):
        node = self.elements.find_node(node_id)
        if node is None:
            raise DesignError(
                f"Element {node_id} does not exist (any more). Refresh the design.",
            code="edit.staleElement",
            )
        return node

    def _target(self, element_ids, verb: str = "changed") -> list:
        """
        The nodes an edit acts on, emphasised for the engine — and never a locked one.

        Every transform in this class comes through here, which is why the lock is
        checked here and not three times over: a guard you have to remember is a guard
        that gets forgotten on the fourth transform somebody adds.
        """
        # Imported here and not at the top: locking.py takes DesignError from this
        # module, and a module-level import back would be a circle.
        from .locking import refuse_locked

        nodes = [self._node(node_id) for node_id in _ids(element_ids)]
        refuse_locked(nodes, verb)
        self.elements.set_emphasis(nodes)
        return nodes

    # ------------------------------------------------------------ transforms

    def move(self, element_ids, dx_mm, dy_mm) -> dict:
        dx = _finite(dx_mm, "dx_mm")
        dy = _finite(dy_mm, "dy_mm")
        ids = _ids(element_ids)
        self._target(ids, "moved")
        self.runner.run(f"translate {_mm(dx)} {_mm(dy)}")
        return {"ids": ids, "moved": [dx, dy]}

    def resize(self, element_ids, x_mm, y_mm, width_mm, height_mm) -> dict:
        x = _finite(x_mm, "x_mm")
        y = _finite(y_mm, "y_mm")
        width = _positive(width_mm, "width_mm")
        height = _positive(height_mm, "height_mm")
        ids = _ids(element_ids)
        # With several elements the engine resizes their combined bounding box
        # and keeps their relative positions, like dragging a group.
        self._target(ids, "resized")
        self.runner.run(f"resize {_mm(x)} {_mm(y)} {_mm(width)} {_mm(height)}")
        return {"ids": ids, "bounds": [x, y, width, height]}

    def rotate(self, element_ids, angle_deg, absolute: bool = False) -> dict:
        """
        Rotate around the centre of the selection.

        With ``absolute`` the angle is a destination rather than a step, so the
        panel can offer an angle field whose value is a fact instead of a
        running total. The engine has its own ``rotate -a`` for this, but it is
        broken: it applies ``start - target`` where it means ``target - start``,
        so every call doubles the current angle (measured, noted for upstream).
        The delta is therefore computed here, which also keeps the selection
        rigid: one rotation around the shared centre rather than one per node.
        """
        angle = _finite(angle_deg, "angle_deg")
        ids = _ids(element_ids)
        nodes = self._target(ids, "rotated")
        if absolute:
            angles = [_visual_angle(node) for node in nodes]
            known = [value for value in angles if value is not None]
            if not known:
                raise DesignError(
                    "The angle of this selection cannot be read off; "
                    "use the 1° or 90° steps.",
                    code="edit.mixedAngle",
                )
            spread = max(known) - min(known)
            if spread > 0.01:
                raise DesignError(
                    "These shapes sit at different angles. "
                    "Turn them with the steps, or make them equal first."
                )
            angle -= known[0]
        angle %= 360.0
        if abs(angle) < 1e-6 or abs(angle - 360.0) < 1e-6:
            return {"ids": ids, "rotated": 0.0, "absolute": bool(absolute)}
        self.runner.run(f"rotate {angle:.4f}deg")
        return {"ids": ids, "rotated": angle, "absolute": bool(absolute)}

    # --------------------------------------------------------------- layers

    def assign(self, element_ids, operation_id: str) -> dict:
        """
        Put elements into an existing operation — a layer in the UI.

        Operations hold ReferenceNodes rather than the elements themselves, so
        this adds a reference; an element can legitimately sit in several
        operations at once.
        """
        operation = self._operation(operation_id)
        nodes = [self._node(node_id) for node_id in _ids(element_ids)]

        added = 0
        with self.elements.undoscope("Assign to operation"):
            for node in nodes:
                if not self._referenced(operation, node):
                    operation.add_reference(node)
                    added += 1
        self._refresh()
        return {"operation_id": operation_id, "added": added}

    def unassign(self, element_ids, operation_id: str) -> dict:
        operation = self._operation(operation_id)
        targets = {id(self._node(node_id)) for node_id in _ids(element_ids)}

        removed = 0
        with self.elements.undoscope("Remove from operation"):
            for reference in list(operation.children):
                node = getattr(reference, "node", None)
                if node is not None and id(node) in targets:
                    reference.remove_node()
                    removed += 1
        self._refresh()
        return {"operation_id": operation_id, "removed": removed}

    # --------------------------------------------------------------- splitting

    def split(self, element_ids) -> dict:
        """
        Break paths into their subpaths — one shape per piece.

        A CAD export often holds a whole model in a single ``<path>``: 46
        panels, nothing selectable on its own. The engine has ``subpath`` for
        that. What it leaves behind is the problem: the original node is
        replaced by a group, but every operation that referenced it keeps its
        reference, now pointing at a node that is no longer in the tree.
        Measured in a bare kernel — an engrave layer with one child had three
        after splitting: the two new pieces plus the original. That layer would
        burn the whole path *and* its pieces, so the dead references go here.
        """
        ids = _ids(element_ids)
        nodes = [self._node(node_id) for node_id in ids]
        splitsbaar = [node for node in nodes if _subpath_count(node) > 1]
        skipped = len(nodes) - len(splitsbaar)
        if not splitsbaar:
            self.elements.set_emphasis(nodes)
            return {"ids": [], "count": 0, "skipped": skipped}

        before = {id(node) for node in self.elements.elems()}
        self.elements.set_emphasis(splitsbaar)
        self.runner.run("element subpath")
        self._drop_dead_references()
        self.elements.validate_ids()
        created = [node for node in self.elements.elems() if id(node) not in before]
        self.elements.set_emphasis(created)
        self._refresh()
        return {
            "ids": [node.id for node in created],
            "count": len(created),
            "skipped": skipped,
        }

    def _drop_dead_references(self) -> int:
        """
        Removing references to elements that are no longer in the tree.

        Only `reference` children: an operation can also have a real child (`effect hatch`),
        and that is not a reference and may stay.
        """
        levend = {id(node) for node in self.elements.elems()}
        dropped = 0
        for operation in list(self.elements.ops()):
            for child in list(operation.children):
                if str(getattr(child, "type", "")) != "reference":
                    continue
                node = getattr(child, "node", None)
                if node is None or id(node) not in levend:
                    child.remove_node()
                    dropped += 1
        return dropped

    def apply_settings(
        self,
        operation_id: str,
        speed=None,
        power_percent=None,
        passes=None,
        dpi=None,
        overscan_mm=None,
        bidirectional=None,
    ) -> dict:
        """
        Write laser settings onto an operation — how a preset lands in the job.

        MeerK40t stores power on a 0–1000 scale, not as a percentage, so a
        preset of 65% becomes 650. Getting that wrong would be a factor of ten
        on a machine that burns.
        """
        operation = self._operation(operation_id)
        applied = {}
        with self.elements.undoscope("Apply preset"):
            if speed is not None:
                operation.speed = _positive(speed, "speed")
                applied["speed"] = operation.speed
            if power_percent is not None:
                percent = _finite(power_percent, "power_percent")
                if not 0 < percent <= 100:
                    raise DesignError("power_percent has to be between 0 and 100.")
                operation.power = percent * 10
                applied["power"] = operation.power
            if passes is not None:
                count = int(_positive(passes, "passes"))
                operation.passes_custom = True
                operation.passes = count
                applied["passes"] = count
            if dpi is not None:
                # DPI decides the line spacing of a raster engraving: too high costs hours,
                # too low gives stripes.
                value = _positive(dpi, "dpi")
                if not 10 <= value <= 2000:
                    raise DesignError("dpi has to be between 10 and 2000.")
                operation.dpi = value
                applied["dpi"] = value
            if overscan_mm is not None:
                distance = _finite(overscan_mm, "overscan_mm")
                if not 0 <= distance <= 50:
                    raise DesignError("overscan_mm has to be between 0 and 50.")
                # In the engine overscan is a length-with-unit, not a number.
                operation.overscan = f"{distance}mm"
                applied["overscan"] = operation.overscan
            if bidirectional is not None:
                operation.bidirectional = bool(bidirectional)
                applied["bidirectional"] = operation.bidirectional
        self._refresh()
        return {"operation_id": operation_id, "applied": applied}

    def _operation(self, operation_id: str):
        operation = self._node(operation_id)
        if not str(operation.type).startswith(("op ", "effect ")):
            raise DesignError(f"{operation_id} is not an operation.")
        return operation

    @staticmethod
    def _referenced(operation, node) -> bool:
        return any(getattr(c, "node", None) is node for c in operation.children)

    def _refresh(self):
        """Tell the rest of the engine the tree changed, as the GUI does."""
        if getattr(self.runner, "document", None) is not None:
            self.runner.document.touch()
        self.elements.signal("rebuild_tree", "all")
        self.elements.signal("refresh_scene", "Scene")

    # -------------------------------------------------------------- history

    def undo(self) -> dict:
        self._adjust_the_stack()
        return self._history("undo", self.runner.run("undo"))

    def redo(self) -> dict:
        return self._history("redo", self.runner.run("redo"))

    def _adjust_the_stack(self) -> None:
        """
        One undo has to reverse one change (upstream #3258).

        The stack keeps, per change, the state **before** that change: `undoscope` calls
        `mark()` before anything happens. `Undo.undo()` computes its target as
        `_undo_index - 1` — and does that **before** it calls `validate()`. That is the
        fault, because `validate()` moves `_undo_index` in precisely the case where it goes
        wrong:

        1. It puts a "Last status" safety net on top of the stack and *raises* `_undo_index`
           when it was already at the top. That is exactly the state after a change, so on the
           first step back `undo()` computes with an index from before that rise: one step too
           far.
        2. If the stack thereby exceeds the twenty states it holds (`Undo.levels`), it throws
           the oldest out and **all** the indexes shift by one. The already computed target
           does not shift along, so it then points at the state *after* the one you meant —
           and undoing does nothing at all. Measured: after 25 changes, remove a shape and
           undo, and the shape stayed gone.

        Point 2 was the hole in our own detour. That computed an index itself and passed it as
        `undo <index>`, but ran into exactly the same shift: on a full stack that index pointed
        wrongly as well.

        The solution is one step earlier: call `validate()` ourselves *before* the command goes
        out. After that the safety net is already there, `validate()` inside `undo()` moves
        nothing any more, and `_undo_index - 1` *is* the state from before the last change — on
        a full stack just as much as on an empty one. So we no longer compute anything
        ourselves; we only make sure the engine computes with a stack that no longer shifts out
        from under its hands.
        """
        try:
            self.elements.undo.validate()
        except AttributeError:
            # If the engine changes its stack, we go back to doing it the way it does
            # itself: better one step too far than no undo.
            pass

    def _history(self, action: str, output: list[str]) -> dict:
        # The console reports exhaustion as text rather than an error.
        exhausted = any("No undo available" in line or "No redo" in line for line in output)
        return {
            "action": action,
            "applied": not exhausted,
            # After an undo the tree may predate id assignment, or have jumped
            # back further than one edit; treat held ids as stale either way.
            "ids_invalidated": not exhausted,
            "output": output,
        }
