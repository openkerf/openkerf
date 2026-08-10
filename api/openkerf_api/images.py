"""
Afbeeldingen: plaatsen, bewerken en zichtbaar maken.

Een `elem image` heeft geen `as_geometry`, dus hij valt buiten de padgebaseerde
snapshot en was daardoor onzichtbaar op ons canvas. Hier komen de gegevens
vandaan die de frontend nodig heeft om hem te tekenen: het kader in millimeters
plus een PNG-weergave van de huidige pixels.

De bewerkingen zijn MeerK40t's eigen `image ...`-commando's. Ze bepalen of een
gravure iets wordt: een foto zonder dithering wordt een grijze vlek.
"""

from .commands import CommandRunner
from .edits import DesignError

# Bewerkingen die zonder argumenten werken; geverifieerd tegen de engine.
ADJUSTMENTS = (
    "grayscale",
    "invert",
    "contrast",
    "sharpen",
    "dither",
    "halftone",
    "edge_enhance",
    "equalize",
    "autocontrast",
    "contour",
    "resample",
)

# Vectoriseren zit in aparte plugins die kunnen ontbreken (potrace heeft een
# externe library nodig), dus we vragen de kernel wat er echt geregistreerd is.
VECTORISERS = ("vectrace", "potrace")

# Bewerkingen met een sterkte. 1.0 laat de afbeelding zoals hij is; lager is
# zwakker, hoger sterker. Dit zijn de schuifjes die xTool Studio ook heeft.
# `brightness` staat er bewust NIET bij: dat commando leest zijn factor uit de
# ruwe argumentenlijst op de verkeerde plek en faalt daardoor altijd. Upstream-
# bevinding, genoteerd in CLAUDE.md; wij bieden geen knop aan die gegarandeerd
# niets doet.
FACTORS = ("contrast", "sharpness", "color")


class Images:
    def __init__(self, kernel, runner: CommandRunner | None = None):
        self.kernel = kernel
        self.runner = runner or CommandRunner(kernel)
        self._cache = None

    @property
    def elements(self):
        return self.kernel.elements

    def _node(self, element_id: str):
        node = self.elements.find_node(element_id)
        if node is None:
            raise DesignError(f"Element {element_id} bestaat niet (meer).")
        if node.type != "elem image":
            raise DesignError("Dit element is geen afbeelding.")
        return node

    def adjust(self, element_id: str, adjustment: str) -> dict:
        if adjustment not in ADJUSTMENTS:
            raise DesignError(
                f"Onbekende bewerking: {adjustment}. Kies uit {', '.join(ADJUSTMENTS)}."
            )
        node = self._node(element_id)
        self.elements.set_emphasis([node])
        with self.elements.undoscope(f"Afbeelding {adjustment}"):
            self.runner.run(f"image {adjustment}")
        self.elements.signal("rebuild_tree", "all")
        self.elements.signal("refresh_scene", "Scene")
        return {"id": element_id, "adjustment": adjustment}

    def enhance(self, element_id: str, adjustment: str, factor) -> dict:
        """
        Helderheid, contrast, scherpte of verzadiging met een sterkte.

        Anders dan de vaste bewerkingen is dit een schuifje: 1,0 verandert
        niets, en dat maakt het bruikbaar om naar een resultaat toe te werken
        in plaats van er één keer overheen te gaan.
        """
        if adjustment not in FACTORS:
            raise DesignError(
                f"Onbekende bewerking: {adjustment}. Kies uit {', '.join(FACTORS)}."
            )
        try:
            strength = float(factor)
        except (TypeError, ValueError) as e:
            raise DesignError("De sterkte moet een getal zijn.") from e
        if not 0 <= strength <= 5:
            raise DesignError("De sterkte moet tussen 0 en 5 liggen.")

        node = self._node(element_id)
        self.elements.set_emphasis([node])
        with self.elements.undoscope(f"Afbeelding {adjustment}"):
            self.runner.run(f"image {adjustment} {strength}")
        self.elements.signal("rebuild_tree", "all")
        self.elements.signal("refresh_scene", "Scene")
        return {"id": element_id, "adjustment": adjustment, "factor": strength}

    def set_dpi(self, element_id: str, dpi) -> dict:
        """
        DPI bepaalt hoe fijn de raster-gravure wordt afgetast — en daarmee de
        brandtijd.
        """
        node = self._node(element_id)
        try:
            value = float(dpi)
        except (TypeError, ValueError) as e:
            raise DesignError("dpi moet een getal zijn.") from e
        if not 10 <= value <= 2000:
            raise DesignError("dpi moet tussen 10 en 2000 liggen.")
        with self.elements.undoscope("Afbeelding-DPI"):
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
        Van pixels naar paden, zodat een gescande tekening gesneden kan worden in
        plaats van gegraveerd.
        """
        available = self.vectorisers()
        if method not in available:
            raise DesignError(
                "Vectoriseren met "
                f"{method} kan niet; beschikbaar: {', '.join(available) or 'geen'}."
            )
        node = self._node(element_id)
        before = {id(n) for n in self.elements.elems()}
        self.elements.set_emphasis([node])
        with self.elements.undoscope(f"Vectoriseren ({method})"):
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

        De engine snijdt op pixels, dus we rekenen om via het kader van de
        afbeelding. Dat is een evenredige afbeelding zonder rotatie — precies
        hoe het canvas de afbeelding ook tekent.
        """
        from meerk40t.core.units import UNITS_PER_MM

        node = self._node(element_id)
        image = getattr(node, "active_image", None) or getattr(node, "image", None)
        bounds = getattr(node, "bounds", None)
        if image is None or not bounds:
            raise DesignError("Deze afbeelding heeft geen pixels om te snijden.")
        try:
            rect = [float(v) for v in (x_mm, y_mm, width_mm, height_mm)]
        except (TypeError, ValueError) as e:
            raise DesignError("Het snijkader moet uit getallen bestaan.") from e
        if rect[2] <= 0 or rect[3] <= 0:
            raise DesignError("Het snijkader moet breedte en hoogte hebben.")

        x0, y0, x1, y1 = (v / UNITS_PER_MM for v in bounds)
        width, height = image.size
        if x1 - x0 <= 0 or y1 - y0 <= 0:
            raise DesignError("Deze afbeelding heeft geen kader.")

        def to_pixels(value, low, high, count):
            return int(round((value - low) / (high - low) * count))

        left = to_pixels(rect[0], x0, x1, width)
        upper = to_pixels(rect[1], y0, y1, height)
        right = to_pixels(rect[0] + rect[2], x0, x1, width)
        lower = to_pixels(rect[1] + rect[3], y0, y1, height)
        left, right = max(0, min(left, width)), max(0, min(right, width))
        upper, lower = max(0, min(upper, height)), max(0, min(lower, height))
        if right - left < 1 or lower - upper < 1:
            raise DesignError("Het snijkader valt buiten de afbeelding.")

        self.elements.set_emphasis([node])
        with self.elements.undoscope("Afbeelding bijsnijden"):
            self.runner.run(f"image crop {left} {upper} {right} {lower}")
        self.elements.signal("rebuild_tree", "all")
        self.elements.signal("refresh_scene", "Scene")
        return {"id": element_id, "pixels": [left, upper, right, lower]}

    def render_png(self, element_id: str):
        """
        De huidige pixels als PNG, zodat het canvas de afbeelding kan tonen.

        Eén map voor alle weergaves: het canvas vraagt hier bij elke verversing
        om, en per keer een nieuwe tijdelijke map maken laat er honderden staan.
        """
        node = self._node(element_id)
        image = getattr(node, "active_image", None) or getattr(node, "image", None)
        if image is None:
            raise DesignError("Deze afbeelding heeft geen pixels.")
        target = self._cache_dir() / f"{element_id.replace(':', '_')}.png"
        image.convert("RGBA").save(target, "PNG")
        return target

    def _cache_dir(self):
        import tempfile
        from pathlib import Path

        if self._cache is None:
            self._cache = Path(tempfile.mkdtemp(prefix="openkerf-images-"))
        return self._cache
