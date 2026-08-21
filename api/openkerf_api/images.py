"""
Images: placing, editing and making them visible.

An `elem image` has no `as_geometry`, so it falls outside the path-based snapshot and was
therefore invisible on our canvas. This is where the data the frontend needs to draw it
comes from: the frame in millimetres plus a PNG rendering of the current pixels.

Edits are **not destructive**. An `elem image` keeps the original and a list of operations
(`node.operations`); on every change that whole recipe goes over the original again. That is
the reason you can press the same button twice without burning the image away, and that the
panel can show *what* is switched on.

This used to go through the `image ...` console commands. Those write the result back into
the image itself, so raising the contrast twice really did it twice, and after a few clicks
there was nothing left. The engine already had the right model; we were using the wrong
one.
"""

from .commands import CommandRunner
from .edits import DesignError

# Edits that work without arguments; verified against the engine.
ADJUSTMENTS = {
    "contrast": {
        "label": "Contrast and brightness",
        # The engine converts -128..127 into a factor around 1.
        "defaults": {"contrast": 25, "brightness": 0},
        "ranges": {"contrast": (-127, 127), "brightness": (-127, 127)},
    },
    "gamma": {
        "label": "Gamma",
        "defaults": {"factor": 1.5},
        "ranges": {"factor": (0.0, 5.0)},
    },
    "auto_contrast": {
        "label": "Automatisch contrast",
        "defaults": {"cutoff": 3},
        "ranges": {"cutoff": (0, 45)},
    },
    "unsharp_mask": {
        "label": "Verscherpen",
        "defaults": {"percent": 150, "radius": 2, "threshold": 3},
        "ranges": {"percent": (0, 500), "radius": (0, 20), "threshold": (0, 255)},
    },
    "edge_enhance": {"label": "Randen versterken", "defaults": {}, "ranges": {}},
    "halftone": {
        "label": "Halftoon",
        "defaults": {"black": True, "sample": 10, "angle": 22, "oversample": 2},
        "ranges": {"sample": (2, 50), "angle": (0, 90), "oversample": (1, 4)},
    },
    "dither": {
        "label": "Dithering",
        "defaults": {"type": "Floyd-Steinberg"},
        "ranges": {},
    },
    "tone": {
        "label": "Invert",
        # Inverting does not exist as an operation of its own, but a tone curve from (0,255)
        # to (255,0) does exactly that — and it *is* in the recipe, so it stays
        # reversible.
        "defaults": {"type": "line", "values": [(0, 255), (255, 0)]},
        "ranges": {},
    },
    "crop": {
        "label": "Bijsnijden",
        "defaults": {"bounds": None},
        "ranges": {},
    },
}

DITHER_TYPES = (
    "Floyd-Steinberg",
    "Atkinson",
    "Jarvis-Judice-Ninke",
    "Stucki",
    "Burkes",
    "Sierra3",
    "Sierra2",
    "Sierra-2-4a",
)

# Vectorising sits in separate plugins that may be absent (potrace needs an external
# library), so we ask the kernel what is really registered.
VECTORISERS = ("vectrace", "potrace")


class Images:
    def __init__(self, kernel, runner: CommandRunner | None = None):
        self.kernel = kernel
        self.runner = runner or CommandRunner(kernel)

    @property
    def elements(self):
        return self.kernel.elements

    def _node(self, element_id: str):
        node = self.elements.find_node(element_id)
        if node is None:
            raise DesignError(f"Element {element_id} does not exist (any more).")
        if node.type != "elem image":
            raise DesignError("This element is not an image.")
        return node

    def adjustments(self, element_id: str) -> dict:
        """
        What is switched on for this image, and with which values.

        Without this the panel could not show what had been chosen — you only saw buttons and
        had to remember what you had pressed.
        """
        node = self._node(element_id)
        recipe = {op.get("name"): op for op in getattr(node, "operations", []) or []}
        return {
            "id": element_id,
            "dpi": float(getattr(node, "dpi", 0) or 0) or None,
            "dither_types": list(DITHER_TYPES),
            "adjustments": [
                {
                    "name": name,
                    "label": spec["label"],
                    "enabled": bool(recipe.get(name, {}).get("enable", False)),
                    "ranges": {k: list(v) for k, v in spec["ranges"].items()},
                    "values": {
                        key: recipe.get(name, {}).get(key, default)
                        for key, default in spec["defaults"].items()
                    },
                }
                for name, spec in ADJUSTMENTS.items()
                # Cropping has a route of its own (a frame on the canvas), so it is not a
                # button among the rest.
                if name != "crop"
            ],
        }

    def set_adjustment(self, element_id: str, name: str, enabled=None, values=None) -> dict:
        """
        Eén operation aan- of uitzetten, of zijn values bijstellen.

        The recipe then goes over the **original** again in its entirety. So the same button
        twice produces the same result, and switching it off really brings the image back —
        that was the fault in the previous version.
        """
        spec = ADJUSTMENTS.get(name)
        if spec is None:
            usable = ", ".join(k for k in ADJUSTMENTS if k != "crop")
            raise DesignError(f"Unknown adjustment: {name}. Choose from {usable}.")
        node = self._node(element_id)

        operation = self._find(node, name)
        if operation is None:
            operation = {"name": name, **spec["defaults"]}
            node.operations = list(getattr(node, "operations", []) or []) + [operation]
        if enabled is not None:
            operation["enable"] = bool(enabled)
        operation.setdefault("enable", True)

        for key, value in (values or {}).items():
            if key not in spec["defaults"]:
                raise DesignError(f"'{key}' does not belong to {name}.")
            operation[key] = self._checked(name, key, value, spec)

        if name == "dither" and operation.get("type") not in DITHER_TYPES:
            raise DesignError(
                f"Unknown dither type. Choose from {', '.join(DITHER_TYPES)}."
            )

        with self.elements.undoscope(f"Image: {spec['label']}"):
            self._reprocess(node)
        return self.adjustments(element_id)

    def clear_adjustments(self, element_id: str) -> dict:
        """Everything off: back to the image as it came in."""
        node = self._node(element_id)
        with self.elements.undoscope("Image: clear the adjustments"):
            node.operations = []
            self._reprocess(node)
        return self.adjustments(element_id)

    def _find(self, node, name):
        for operation in getattr(node, "operations", []) or []:
            if operation.get("name") == name:
                return operation
        return None

    def _checked(self, name, key, value, spec):
        bounds = spec["ranges"].get(key)
        if bounds is None:
            return value
        try:
            number = float(value)
        except (TypeError, ValueError) as e:
            raise DesignError(f"{key} has to be a number.") from e
        low, high = bounds
        if not low <= number <= high:
            raise DesignError(f"{key} has to be between {low} and {high}.")
        return number if isinstance(spec["defaults"][key], float) else int(number)

    def _reprocess(self, node):
        """Run the recipe over the original again."""
        node._processed_image = None
        node.update(self.kernel.root)
        # update() works in a thread of its own; active_image waits for it politely.
        node.active_image  # noqa: B018
        self.elements.signal("element_property_update", [node])
        self.elements.signal("refresh_scene", "Scene")

    def set_dpi(self, element_id: str, dpi) -> dict:
        """
        DPI decides how finely the raster engraving is scanned — and with it the burn time.
        """
        node = self._node(element_id)
        try:
            value = float(dpi)
        except (TypeError, ValueError) as e:
            raise DesignError("dpi has to be a number.") from e
        if not 10 <= value <= 2000:
            raise DesignError("dpi has to be between 10 and 2000.")
        with self.elements.undoscope("Image DPI"):
            node.dpi = value
            node.altered()
        self.elements.signal("rebuild_tree", "all")
        return {"id": element_id, "dpi": value}

    def vectorisers(self) -> list[str]:
        return [
            name
            for name in VECTORISERS
            if any(True for _ in self.kernel.find("command", "image", f"{name}$"))
        ]

    def vectorise(self, element_id: str, method: str = "vectrace") -> dict:
        """
        From pixels to paths, so that a scanned drawing can be cut instead of engraved.
        """
        available = self.vectorisers()
        if method not in available:
            raise DesignError(
                "Tracing with "
                f"{method} is not possible; available: {', '.join(available) or 'none'}."
            )
        node = self._node(element_id)
        before = {id(n) for n in self.elements.elems()}
        self.elements.set_emphasis([node])
        with self.elements.undoscope(f"Vectorise ({method})"):
            self.runner.run(f"image {method}")
        added = [n for n in self.elements.elems() if id(n) not in before]
        self.elements.validate_ids()
        self.elements.signal("rebuild_tree", "all")
        self.elements.signal("refresh_scene", "Scene")
        return {
            "id": element_id,
            "method": method,
            "ids": [n.id for n in added if n.id],
        }

    def crop(self, element_id: str, x_mm, y_mm, width_mm, height_mm) -> dict:
        """
        Bijsnijden op een rechthoek in millimeters.

        This too goes into the recipe rather than into the pixels: that makes cropping
        reversible, and a second crop computes from the original instead of from the
        already-cropped image.
        """
        from meerk40t.core.units import UNITS_PER_MM

        node = self._node(element_id)
        image = getattr(node, "image", None)
        bounds = getattr(node, "bounds", None)
        if image is None or not bounds:
            raise DesignError("This image has no pixels to crop.")
        try:
            rect = [float(v) for v in (x_mm, y_mm, width_mm, height_mm)]
        except (TypeError, ValueError) as e:
            raise DesignError("The crop box has to consist of numbers.") from e
        if rect[2] <= 0 or rect[3] <= 0:
            raise DesignError("The crop box needs a width and a height.")

        x0, y0, x1, y1 = (v / UNITS_PER_MM for v in bounds)
        width, height = image.size
        if x1 - x0 <= 0 or y1 - y0 <= 0:
            raise DesignError("This image has no box.")

        def to_pixels(value, low, high, count):
            return int(round((value - low) / (high - low) * count))

        left = to_pixels(rect[0], x0, x1, width)
        upper = to_pixels(rect[1], y0, y1, height)
        right = to_pixels(rect[0] + rect[2], x0, x1, width)
        lower = to_pixels(rect[1] + rect[3], y0, y1, height)
        left, right = max(0, min(left, width)), max(0, min(right, width))
        upper, lower = max(0, min(upper, height)), max(0, min(lower, height))
        if right - left < 1 or lower - upper < 1:
            raise DesignError("The crop box falls outside the image.")

        operation = self._find(node, "crop")
        if operation is None:
            operation = {"name": "crop"}
            node.operations = list(getattr(node, "operations", []) or []) + [operation]
        operation["enable"] = True
        operation["bounds"] = [left, upper, right, lower]

        with self.elements.undoscope("Crop image"):
            self._reprocess(node)
        return {"id": element_id, "pixels": [left, upper, right, lower]}

    def render_png(self, element_id: str) -> bytes:
        """
        The current pixels as a PNG, so that the canvas can show the image.

        Bytes, not a file. This used to go through one fixed path per element, and that
        broke as soon as the canvas asked for the same image twice at once — which it does,
        because every refresh hangs a new `?v=` number on it while the previous request is
        still running. One request rewrote the file while the other was sending it:
        `Content-Length` from before the overwrite, content from after, and uvicorn fell over
        with `Too little data for declared Content-Length` in the user's log. An answer from
        memory always has the length it reports.
        """
        from io import BytesIO

        node = self._node(element_id)
        image = getattr(node, "active_image", None) or getattr(node, "image", None)
        if image is None:
            raise DesignError("This image has no pixels.")
        buffer = BytesIO()
        image.convert("RGBA").save(buffer, "PNG")
        return buffer.getvalue()
