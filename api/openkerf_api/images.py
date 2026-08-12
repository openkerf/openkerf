"""
Afbeeldingen: plaatsen, bewerken en zichtbaar maken.

Een `elem image` heeft geen `as_geometry`, dus hij valt buiten de padgebaseerde
snapshot en was daardoor onzichtbaar op ons canvas. Hier komen de gegevens
vandaan die de frontend nodig heeft om hem te tekenen: het kader in millimeters
plus een PNG-weergave van de huidige pixels.

Bewerkingen zijn **niet destructief**. Een `elem image` bewaart het origineel
en een receptenlijst (`node.operations`); bij elke wijziging gaat dat hele
recept opnieuw over het origineel heen. Dat is de reden dat je twee keer op
dezelfde knop kunt drukken zonder de afbeelding weg te branden, en dat het
paneel kan laten zien wát er aanstaat.

Eerder liep dit via de `image ...`-console­commando's. Die schrijven het
resultaat terug in de afbeelding zelf, dus contrast twee keer verhogen deed dat
ook echt twee keer, en na een paar klikken was er niets meer over. De engine had
het goede model al; wij gebruikten het verkeerde.
"""

from .commands import CommandRunner
from .edits import DesignError

# Bewerkingen die zonder argumenten werken; geverifieerd tegen de engine.
ADJUSTMENTS = {
    "contrast": {
        "label": "Contrast en helderheid",
        # De engine rekent -128..127 om naar een factor rond 1.
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
        "label": "Omkeren",
        # Omkeren bestaat niet als eigen bewerking, maar een tooncurve van
        # (0,255) naar (255,0) doet precies dat — en zit wél in het recept, dus
        # blijft hij omkeerbaar.
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

# Vectoriseren zit in aparte plugins die kunnen ontbreken (potrace heeft een
# externe library nodig), dus we vragen de kernel wat er echt geregistreerd is.
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
            raise DesignError(f"Element {element_id} bestaat niet (meer).")
        if node.type != "elem image":
            raise DesignError("Dit element is geen afbeelding.")
        return node

    def adjustments(self, element_id: str) -> dict:
        """
        Wat er op deze afbeelding aanstaat, en met welke waarden.

        Zonder dit kon het paneel niet tonen wat er gekozen was — je zag alleen
        knoppen en moest maar onthouden waar je op had gedrukt.
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
                # Bijsnijden heeft een eigen weg (een kader op het canvas), dus
                # het staat niet als knop tussen de rest.
                if name != "crop"
            ],
        }

    def set_adjustment(self, element_id: str, name: str, enabled=None, values=None) -> dict:
        """
        Eén bewerking aan- of uitzetten, of zijn waarden bijstellen.

        Het recept gaat daarna in zijn geheel opnieuw over het **origineel**.
        Twee keer dezelfde knop levert dus hetzelfde resultaat op, en uitzetten
        brengt de afbeelding echt terug — dat was de fout in de vorige versie.
        """
        spec = ADJUSTMENTS.get(name)
        if spec is None:
            usable = ", ".join(k for k in ADJUSTMENTS if k != "crop")
            raise DesignError(f"Onbekende bewerking: {name}. Kies uit {usable}.")
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
                raise DesignError(f"'{key}' hoort niet bij {name}.")
            operation[key] = self._checked(name, key, value, spec)

        if name == "dither" and operation.get("type") not in DITHER_TYPES:
            raise DesignError(
                f"Onbekend dither-type. Kies uit {', '.join(DITHER_TYPES)}."
            )

        with self.elements.undoscope(f"Afbeelding: {spec['label']}"):
            self._reprocess(node)
        return self.adjustments(element_id)

    def clear_adjustments(self, element_id: str) -> dict:
        """Alles eraf: terug naar de afbeelding zoals hij binnenkwam."""
        node = self._node(element_id)
        with self.elements.undoscope("Afbeelding: bewerkingen wissen"):
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
            raise DesignError(f"{key} moet een getal zijn.") from e
        low, high = bounds
        if not low <= number <= high:
            raise DesignError(f"{key} moet tussen {low} en {high} liggen.")
        return number if isinstance(spec["defaults"][key], float) else int(number)

    def _reprocess(self, node):
        """Het recept opnieuw over het origineel halen."""
        node._processed_image = None
        node.update(self.kernel.root)
        # update() rekent in een eigen thread; active_image wacht daar netjes op.
        node.active_image  # noqa: B018
        self.elements.signal("element_property_update", [node])
        self.elements.signal("refresh_scene", "Scene")

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

        Ook dit gaat in het recept in plaats van in de pixels: bijsnijden is
        daarmee terug te draaien, en een tweede keer snijden rekent vanaf het
        origineel in plaats van vanaf de al bijgesneden afbeelding.
        """
        from meerk40t.core.units import UNITS_PER_MM

        node = self._node(element_id)
        image = getattr(node, "image", None)
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

        operation = self._find(node, "crop")
        if operation is None:
            operation = {"name": "crop"}
            node.operations = list(getattr(node, "operations", []) or []) + [operation]
        operation["enable"] = True
        operation["bounds"] = [left, upper, right, lower]

        with self.elements.undoscope("Afbeelding bijsnijden"):
            self._reprocess(node)
        return {"id": element_id, "pixels": [left, upper, right, lower]}

    def render_png(self, element_id: str) -> bytes:
        """
        De huidige pixels als PNG, zodat het canvas de afbeelding kan tonen.

        Bytes, geen bestand. Dit liep eerst via één vast pad per element, en
        dat brak zodra het canvas twee keer tegelijk om hetzelfde plaatje
        vroeg — wat het doet, want elke verversing hangt er een nieuw
        `?v=`-nummer aan terwijl de vorige aanvraag nog loopt. De ene aanvraag
        schreef het bestand opnieuw terwijl de andere het aan het versturen
        was: `Content-Length` van vóór het overschrijven, inhoud van erna, en
        uvicorn viel om met `Too little data for declared Content-Length` in
        het log van de gebruiker. Een antwoord uit het geheugen heeft altijd de
        lengte die het meldt.
        """
        from io import BytesIO

        node = self._node(element_id)
        image = getattr(node, "active_image", None) or getattr(node, "image", None)
        if image is None:
            raise DesignError("Deze afbeelding heeft geen pixels.")
        buffer = BytesIO()
        image.convert("RGBA").save(buffer, "PNG")
        return buffer.getvalue()
