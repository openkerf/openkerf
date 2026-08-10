"""
Editing elements: move, resize, undo, redo.

Element transforms in MeerK40t act on the *emphasized* selection, not on an
argument. Each edit therefore sets emphasis to the one node it targets and then
runs the console command, so the engine's own selection ends up matching what
the user picked in the browser.

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


class DesignEditor:
    def __init__(self, kernel, runner: CommandRunner | None = None):
        self.kernel = kernel
        self.runner = runner or CommandRunner(kernel)

    @property
    def elements(self):
        return self.kernel.elements

    def _target(self, element_id: str):
        node = self.elements.find_node(element_id)
        if node is None:
            raise DesignError(
                f"Element {element_id} bestaat niet (meer). Vernieuw het ontwerp."
            )
        self.elements.set_emphasis([node])
        return node

    def move(self, element_id: str, dx_mm, dy_mm) -> dict:
        dx = _finite(dx_mm, "dx_mm")
        dy = _finite(dy_mm, "dy_mm")
        self._target(element_id)
        self.runner.run(f"translate {_mm(dx)} {_mm(dy)}")
        return {"id": element_id, "moved": [dx, dy]}

    def resize(self, element_id: str, x_mm, y_mm, width_mm, height_mm) -> dict:
        x = _finite(x_mm, "x_mm")
        y = _finite(y_mm, "y_mm")
        width = _positive(width_mm, "width_mm")
        height = _positive(height_mm, "height_mm")
        self._target(element_id)
        self.runner.run(f"resize {_mm(x)} {_mm(y)} {_mm(width)} {_mm(height)}")
        return {"id": element_id, "bounds": [x, y, width, height]}

    def undo(self) -> dict:
        output = self.runner.run("undo")
        return self._history("undo", output)

    def redo(self) -> dict:
        output = self.runner.run("redo")
        return self._history("redo", output)

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
