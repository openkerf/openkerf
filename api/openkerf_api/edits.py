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
    pass


def _finite(value, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as e:
        raise DesignError(f"{name} moet een getal zijn.") from e
    if not math.isfinite(number):
        raise DesignError(f"{name} moet een eindig getal zijn.")
    return number


def _positive(value, name: str) -> float:
    number = _finite(value, name)
    if number <= 0:
        raise DesignError(f"{name} moet groter dan nul zijn.")
    return number


def _mm(value: float) -> str:
    """Console commands take unit strings; millimetres keep it readable."""
    return f"{value:.4f}mm"


def _ids(value) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)) or not value:
        raise DesignError("Geef minstens één element op.")
    return [str(v) for v in value]


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
                f"Element {node_id} bestaat niet (meer). Vernieuw het ontwerp."
            )
        return node

    def _target(self, element_ids) -> list:
        nodes = [self._node(node_id) for node_id in _ids(element_ids)]
        self.elements.set_emphasis(nodes)
        return nodes

    # ------------------------------------------------------------ transforms

    def move(self, element_ids, dx_mm, dy_mm) -> dict:
        dx = _finite(dx_mm, "dx_mm")
        dy = _finite(dy_mm, "dy_mm")
        ids = _ids(element_ids)
        self._target(ids)
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
        self._target(ids)
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
        nodes = self._target(ids)
        if absolute:
            angles = [_visual_angle(node) for node in nodes]
            known = [value for value in angles if value is not None]
            if not known:
                raise DesignError(
                    "Van deze selectie is de hoek niet af te lezen; "
                    "gebruik de stapjes van 1° of 90°."
                )
            spread = max(known) - min(known)
            if spread > 0.01:
                raise DesignError(
                    "Deze vormen staan onder verschillende hoeken. "
                    "Draai ze met de stapjes, of zet ze eerst gelijk."
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
        with self.elements.undoscope("Toewijzen aan bewerking"):
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
        with self.elements.undoscope("Verwijderen uit bewerking"):
            for reference in list(operation.children):
                node = getattr(reference, "node", None)
                if node is not None and id(node) in targets:
                    reference.remove_node()
                    removed += 1
        self._refresh()
        return {"operation_id": operation_id, "removed": removed}

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
        with self.elements.undoscope("Preset toepassen"):
            if speed is not None:
                operation.speed = _positive(speed, "speed")
                applied["speed"] = operation.speed
            if power_percent is not None:
                percent = _finite(power_percent, "power_percent")
                if not 0 < percent <= 100:
                    raise DesignError("power_percent moet tussen 0 en 100 liggen.")
                operation.power = percent * 10
                applied["power"] = operation.power
            if passes is not None:
                count = int(_positive(passes, "passes"))
                operation.passes_custom = True
                operation.passes = count
                applied["passes"] = count
            if dpi is not None:
                # DPI bepaalt de lijnafstand van een rastergravure: te hoog kost
                # uren, te laag geeft strepen.
                value = _positive(dpi, "dpi")
                if not 10 <= value <= 2000:
                    raise DesignError("dpi moet tussen 10 en 2000 liggen.")
                operation.dpi = value
                applied["dpi"] = value
            if overscan_mm is not None:
                distance = _finite(overscan_mm, "overscan_mm")
                if not 0 <= distance <= 50:
                    raise DesignError("overscan_mm moet tussen 0 en 50 liggen.")
                # Overscan is een lengte-met-eenheid in de engine, geen getal.
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
            raise DesignError(f"{operation_id} is geen bewerking.")
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
        return self._history("undo", self.runner.run("undo"))

    def redo(self) -> dict:
        return self._history("redo", self.runner.run("redo"))

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
