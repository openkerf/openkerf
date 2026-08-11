"""
Drawing elements and managing layers.

The basics a laser app cannot do without: put a shape or a line of text on the
bed, remove it again, duplicate it, and create the operations that decide how it
is burned.

Everything goes through console commands so the engine stays the single source
of truth — including its automatic classification, which is wanted here: a new
red shape should land in the cut layer by itself.
"""

from .commands import CommandRunner
from .design import _xy, operation_label
from .edits import DesignError, _finite, _positive

# What a shape needs, and the console command that draws it. Millimetres in,
# because that is what the user sees.
SHAPES = {
    "rect": ("x_mm", "y_mm", "width_mm", "height_mm"),
    "ellipse": ("cx_mm", "cy_mm", "rx_mm", "ry_mm"),
    "circle": ("cx_mm", "cy_mm", "r_mm"),
    "line": ("x1_mm", "y1_mm", "x2_mm", "y2_mm"),
    "text": ("x_mm", "y_mm"),
}

# Extra's voor tekst, allemaal optioneel.
TEXT_OPTIONS = {
    "font": str,
    "font_size_mm": float,
    "spacing": float,
}

# Library operation names map onto MeerK40t's own console commands.
OPERATIONS = {
    "cut": "cut",
    "engrave": "engrave",
    "raster": "raster",
    "image": "imageop",
    "dots": "dots",
}


def _mm(value: float) -> str:
    return f"{value:.4f}mm"


class Drawing:
    def __init__(self, kernel, runner: CommandRunner | None = None):
        self.kernel = kernel
        self.runner = runner or CommandRunner(kernel)
        # Zelfgemaakte lagen, zodat ze zichtbaar blijven zolang ze leeg zijn.
        self.user_operations: set[str] = set()
        # Callable die de operaties van testrasters teruggeeft; die staan op
        # slot omdat hun waarden de sweep zijn.
        self.grid_operations = lambda: {}

    @property
    def elements(self):
        return self.kernel.elements

    # --------------------------------------------------------------- elements

    def create_path(self, points, closed: bool = False, label=None) -> dict:
        """
        Een vrij pad uit losse punten — de pen.

        Elk punt mag een bocht dragen: `[x, y]` is een rechte hoek, en
        `[x, y, cx, cy]` trekt de lijn ernaartoe krom via dat controlepunt. Zo
        kan de pen met één klik een hoek zetten en met slepen een bocht, zoals
        elk tekenprogramma dat doet.

        De geometrie gaat rechtstreeks naar de elementenboom. De `path`-opdracht
        van de engine schaalt zijn d-string, en dan tekent een pad van 10 cm
        zichzelf tientallen meters groot.
        """
        from meerk40t.core.geomstr import Geomstr
        from meerk40t.core.units import UNITS_PER_MM

        cleaned = []
        for point in points or []:
            if not isinstance(point, (list, tuple)) or len(point) not in (2, 4):
                raise DesignError("Een punt is [x, y] of [x, y, cx, cy].")
            cleaned.append([_finite(value, "punt") for value in point])
        if len(cleaned) < 2:
            raise DesignError("Een pad heeft minstens twee punten.")

        def at(values, index=0):
            return complex(
                values[index] * UNITS_PER_MM, values[index + 1] * UNITS_PER_MM
            )

        geometry = Geomstr()
        pairs = list(zip(cleaned, cleaned[1:]))
        if closed:
            pairs.append((cleaned[-1], cleaned[0]))
        for start, end in pairs:
            if len(end) == 4:
                geometry.quad(at(start), at(end, 2), at(end))
            else:
                geometry.line(at(start), at(end))

        with self.elements.undoscope("Pad tekenen"):
            node = self.elements.elem_branch.add(
                geometry=geometry,
                type="elem path",
                stroke=self.elements.default_stroke,
                stroke_width=self.elements.default_strokewidth,
                label=label,
            )
            self.elements.validate_ids()
        self.user_operations  # noqa: B018 - documenteert dat lagen ongemoeid blijven
        self.elements.set_emphasis([node])
        self._refresh()
        return {"ids": [node.id], "type": node.type}

    def create(self, kind: str, **fields) -> dict:
        if kind not in SHAPES:
            raise DesignError(
                f"Onbekende vorm: {kind}. Kies uit {', '.join(sorted(SHAPES))}."
            )
        values = {}
        for name in SHAPES[kind]:
            positive = name.startswith(("width", "height", "r", "rx", "ry"))
            values[name] = (
                _positive(fields.get(name), name)
                if positive
                else _finite(fields.get(name), name)
            )

        before = {id(n) for n in self.elements.elems()}
        with self.elements.undoscope(f"{kind} tekenen"):
            self.runner.run(self._command(kind, values, fields))
        created = [n for n in self.elements.elems() if id(n) not in before]
        if not created:
            raise DesignError("De engine heeft niets getekend.")

        self.elements.validate_ids()
        for node in created:
            self._single_layer(node)
        self.elements.set_emphasis(created)
        self._refresh()
        return {"ids": [n.id for n in created], "type": created[0].type}

    def _single_layer(self, node) -> None:
        """
        Een verse vorm hoort in één laag te vallen, niet in twee.

        De classificatie van de engine kijkt naar de lijnkleur, en meerdere
        operaties kunnen dezelfde kleur claimen. Dan zit dezelfde rechthoek in
        een snij- én een graveerlaag, en brandt hij twee keer — de tweede keer
        vaak op 100%. Precies de val die eerder bij het testraster toesloeg.
        Een element in meerdere lagen zetten blijft kunnen, maar dan omdat
        iemand daarvoor kiest.
        """
        references = [
            reference
            for reference in list(getattr(node, "_references", []))
            if reference.parent is not None
        ]
        for extra in references[1:]:
            extra.remove_node()

    def _command(self, kind: str, v: dict, fields: dict) -> str:
        if kind == "rect":
            return f"rect {_mm(v['x_mm'])} {_mm(v['y_mm'])} {_mm(v['width_mm'])} {_mm(v['height_mm'])}"
        if kind == "circle":
            return f"circle {_mm(v['cx_mm'])} {_mm(v['cy_mm'])} {_mm(v['r_mm'])}"
        if kind == "ellipse":
            return f"ellipse {_mm(v['cx_mm'])} {_mm(v['cy_mm'])} {_mm(v['rx_mm'])} {_mm(v['ry_mm'])}"
        if kind == "line":
            return f"line {_mm(v['x1_mm'])} {_mm(v['y1_mm'])} {_mm(v['x2_mm'])} {_mm(v['y2_mm'])}"
        text = str(fields.get("text") or "").strip()
        if not text:
            raise DesignError("Tekst mag niet leeg zijn.")
        if '"' in text:
            raise DesignError("Aanhalingstekens in tekst worden nog niet ondersteund.")
        # linetext, niet text: bitmaptekst heeft geen geometrie en is dus
        # onzichtbaar op het canvas en niet te positioneren.
        parts = ["linetext", _mm(v["x_mm"]), _mm(v["y_mm"])]
        font = str(fields.get("font") or "").strip()
        if font:
            if '"' in font:
                raise DesignError("Ongeldige fontnaam.")
            parts += ["-f", f'"{font}"']
        size = fields.get("font_size_mm")
        if size is not None:
            parts += ["-s", _mm(_positive(size, "font_size_mm"))]
        spacing = fields.get("spacing")
        if spacing is not None:
            parts += ["-g", f"{_positive(spacing, 'spacing'):g}"]
        parts.append(f'"{text}"')
        return " ".join(parts)

    ALIGNMENTS = ("start", "middle", "end")

    def update_text(self, element_id: str, **fields) -> dict:
        """
        Bestaande vector-tekst bijwerken: inhoud, lettertype, hoogte,
        spatiëring of uitlijning.

        De engine bewaart de bron op de node en rendert opnieuw, dus tekst
        hoeft niet verwijderd en opnieuw geplaatst te worden.
        """
        from meerk40t.core.units import UNITS_PER_MM

        node = self._nodes([element_id])[0]
        if getattr(node, "mktext", None) is None:
            raise DesignError("Dit element is geen bewerkbare tekst.")
        registry = getattr(self.kernel.root, "fonts", None)
        if registry is None:
            raise DesignError("Geen lettertype-ondersteuning beschikbaar.")

        text = node.mktext
        with self.elements.undoscope("Tekst wijzigen"):
            if fields.get("text") is not None:
                new = str(fields["text"]).strip()
                if not new:
                    raise DesignError("Tekst mag niet leeg zijn.")
                text = new
            if fields.get("font"):
                node.mkfont = str(fields["font"])
            if fields.get("font_size_mm") is not None:
                node.mkfontsize = _positive(fields["font_size_mm"], "font_size_mm") * UNITS_PER_MM
            if fields.get("spacing") is not None:
                node.mkfontspacing = _positive(fields["spacing"], "spacing")
            if fields.get("align") is not None:
                align = str(fields["align"])
                if align not in self.ALIGNMENTS:
                    raise DesignError(
                        f"Uitlijning moet een van {', '.join(self.ALIGNMENTS)} zijn."
                    )
                node.mkalign = align
            registry.update_linetext(node, text)
        self.elements.validate_ids()
        self._refresh()
        return {"id": node.id, "text": node.mktext}

    def update_line(self, element_id: str, **fields) -> dict:
        """Een eindpunt van een lijn verzetten, zonder hem opnieuw te tekenen."""
        from meerk40t.core.units import UNITS_PER_MM

        node = self._nodes([element_id])[0]
        if node.type != "elem line":
            raise DesignError("Dit element is geen lijn.")

        # De client geeft punten zoals ze op het bed liggen; de node bewaart ze
        # vóór zijn matrix. Zonder terugrekenen zou een gedraaide lijn
        # verspringen zodra je een eindpunt verzet.
        matrix = getattr(node, "matrix", None)
        inverse = ~matrix if matrix is not None else None

        def to_raw(x_mm, y_mm):
            point = (x_mm * UNITS_PER_MM, y_mm * UNITS_PER_MM)
            if inverse is None:
                return point
            return _xy(inverse.point_in_matrix_space(point))

        current = {
            "x1_mm": float(node.x1) / UNITS_PER_MM,
            "y1_mm": float(node.y1) / UNITS_PER_MM,
            "x2_mm": float(node.x2) / UNITS_PER_MM,
            "y2_mm": float(node.y2) / UNITS_PER_MM,
        }
        if matrix is not None:
            for index, prefix in ((0, "1"), (1, "2")):
                px, py = _xy(
                    matrix.point_in_matrix_space(
                        (float(getattr(node, f"x{prefix}")), float(getattr(node, f"y{prefix}")))
                    )
                )
                current[f"x{prefix}_mm"] = px / UNITS_PER_MM
                current[f"y{prefix}_mm"] = py / UNITS_PER_MM

        wanted = dict(current)
        for name in ("x1_mm", "y1_mm", "x2_mm", "y2_mm"):
            if fields.get(name) is not None:
                wanted[name] = _finite(fields[name], name)

        with self.elements.undoscope("Lijn aanpassen"):
            node.x1, node.y1 = to_raw(wanted["x1_mm"], wanted["y1_mm"])
            node.x2, node.y2 = to_raw(wanted["x2_mm"], wanted["y2_mm"])
            node.altered()
        self._refresh()
        return {"id": element_id}

    ALIGNMENTS_2D = (
        "top", "bottom", "left", "right", "center", "centerh", "centerv",
        "spaceh", "spacev",
    )

    def align(self, element_ids, mode: str) -> dict:
        if mode not in self.ALIGNMENTS_2D:
            raise DesignError(
                f"Onbekende uitlijning: {mode}. Kies uit {', '.join(self.ALIGNMENTS_2D)}."
            )
        nodes = self._nodes(element_ids)
        if len(nodes) < 2:
            raise DesignError("Uitlijnen heeft minstens twee elementen nodig.")
        self.elements.set_emphasis(nodes)
        with self.elements.undoscope("Uitlijnen"):
            self.runner.run(f"align {mode}")
        self._refresh()
        return {"aligned": [n.id for n in nodes], "mode": mode}

    def group(self, element_ids) -> dict:
        nodes = self._nodes(element_ids)
        if len(nodes) < 2:
            raise DesignError("Groeperen heeft minstens twee elementen nodig.")
        self.elements.set_emphasis(nodes)
        with self.elements.undoscope("Groeperen"):
            self.runner.run("group")
        self.elements.validate_ids()
        self._refresh()
        return {"grouped": [n.id for n in nodes]}

    def ungroup(self, element_ids) -> dict:
        """
        Groep opheffen. De elementen blijven; alleen het omhulsel verdwijnt.
        """
        nodes = self._nodes(element_ids)
        groups = []
        for node in nodes:
            parent = getattr(node, "parent", None)
            while parent is not None and getattr(parent, "type", None) != "group":
                parent = getattr(parent, "parent", None)
            if parent is not None and parent not in groups:
                groups.append(parent)
        if not groups:
            raise DesignError("Deze selectie zit niet in een groep.")
        self.elements.set_emphasis(groups)
        with self.elements.undoscope("Groep opheffen"):
            self.runner.run("ungroup")
        self.elements.validate_ids()
        self._refresh()
        return {"ungrouped": len(groups)}

    BOOLEAN = ("union", "difference", "intersection", "xor")

    def mirror(self, element_ids, axis: str) -> dict:
        """
        Spiegelen om het midden van de selectie.

        Er is geen `mirror`-commando; de engine doet dit met een negatieve
        schaalfactor.
        """
        if axis not in ("horizontal", "vertical"):
            raise DesignError("Spiegelas moet 'horizontal' of 'vertical' zijn.")
        nodes = self._nodes(element_ids)
        self.elements.set_emphasis(nodes)
        factors = "-1 1" if axis == "horizontal" else "1 -1"
        with self.elements.undoscope("Spiegelen"):
            self.runner.run(f"scale {factors}")
        self._refresh()
        return {"mirrored": [n.id for n in nodes], "axis": axis}

    def boolean(self, element_ids, operation: str) -> dict:
        """
        Vormen samenvoegen, aftrekken, snijden of uitsluiten.

        De commando's komen uit `extra/cag.py` en werken op een keten, niet los:
        `element union` pakt de nadruk-selectie. Het resultaat is één nieuw pad;
        de oorspronkelijke vormen verdwijnen.
        """
        if operation not in self.BOOLEAN:
            raise DesignError(
                f"Onbekende bewerking: {operation}. Kies uit {', '.join(self.BOOLEAN)}."
            )
        nodes = self._nodes(element_ids)
        if len(nodes) < 2:
            raise DesignError(f"{operation} heeft minstens twee vormen nodig.")
        before = {id(n) for n in self.elements.elems()}
        self.elements.set_emphasis(nodes)
        with self.elements.undoscope(operation):
            self.runner.run(f"element {operation}")
        created = [n for n in self.elements.elems() if id(n) not in before]
        if not created:
            raise DesignError(
                f"{operation} leverde niets op — overlappen de vormen wel?"
            )
        self.elements.validate_ids()
        self.elements.set_emphasis(created)
        self._refresh()
        return {"ids": [n.id for n in created], "operation": operation}

    EFFECTS = {"hatch": "effect-hatch", "wobble": "effect-wobble"}

    def offset(self, element_ids, distance_mm) -> dict:
        """Een parallelle contour op afstand — voor kerfcompensatie of een rand."""
        distance = _finite(distance_mm, "distance_mm")
        if distance == 0:
            raise DesignError("Een offset van nul levert niets op.")
        nodes = self._nodes(element_ids)
        before = {id(n) for n in self.elements.elems()}
        self.elements.set_emphasis(nodes)
        with self.elements.undoscope("Offset"):
            self.runner.run(f"offset {distance:.4f}mm")
        created = [n for n in self.elements.elems() if id(n) not in before]
        if not created:
            raise DesignError("De engine heeft geen offset gemaakt.")
        self.elements.validate_ids()
        self.elements.set_emphasis(created)
        self._refresh()
        return {"ids": [n.id for n in created], "distance_mm": distance}

    def simplify(self, element_ids) -> dict:
        """Minder knooppunten, zelfde vorm — scheelt tijd bij ingewikkelde paden."""
        nodes = self._nodes(element_ids)
        self.elements.set_emphasis(nodes)
        with self.elements.undoscope("Vereenvoudigen"):
            self.runner.run("simplify")
        self._refresh()
        return {"simplified": [n.id for n in nodes]}

    def add_effect(self, element_ids, effect: str) -> dict:
        """
        Vulling (hatch) of wobble op de selectie.

        Een effect is in MeerK40t geen elementeigenschap maar een knoop in de
        operatieboom die naar de elementen verwijst, dus het verschijnt als een
        eigen laag.
        """
        command = self.EFFECTS.get(effect)
        if command is None:
            raise DesignError(
                f"Onbekend effect: {effect}. Kies uit {', '.join(sorted(self.EFFECTS))}."
            )
        nodes = self._nodes(element_ids)
        self.elements.set_emphasis(nodes)
        with self.elements.undoscope(f"{effect} toevoegen"):
            self.runner.run(command)
        self.elements.validate_ids()
        self._refresh()
        return {"effect": effect, "ids": [n.id for n in nodes]}

    def delete(self, element_ids) -> dict:
        nodes = self._nodes(element_ids)
        self.elements.set_emphasis(nodes)
        with self.elements.undoscope("Verwijderen"):
            # `delete` alleen bestaat niet op de basiscontext; `element delete`
            # werkt op de nadruk-selectie.
            self.runner.run("element delete")
        self._refresh()
        return {"removed": [n.id for n in nodes]}

    def duplicate(self, element_ids) -> dict:
        nodes = self._nodes(element_ids)
        before = {id(n) for n in self.elements.elems()}
        self.elements.set_emphasis(nodes)
        with self.elements.undoscope("Dupliceren"):
            self.runner.run("copy")
        created = [n for n in self.elements.elems() if id(n) not in before]
        if not created:
            raise DesignError("De engine heeft niets gedupliceerd.")
        self.elements.validate_ids()
        self.elements.set_emphasis(created)
        self._refresh()
        return {"ids": [n.id for n in created]}

    def _nodes(self, element_ids):
        from .edits import _ids

        nodes = []
        for node_id in _ids(element_ids):
            node = self.elements.find_node(node_id)
            if node is None:
                raise DesignError(f"Element {node_id} bestaat niet (meer).")
            nodes.append(node)
        return nodes

    # ------------------------------------------------------------- operations

    # Een laag zonder naam kreeg van de engine een label als
    # "Cut defaultmm/s @default #ff0000" — machinetaal op de plek waar je je
    # eigen werk moet herkennen.
    LAYER_NAMES = {
        "cut": "Snijden",
        "engrave": "Graveren",
        "raster": "Rasteren",
        "image": "Afbeelding",
        "dots": "Punten",
    }

    def create_operation(self, kind: str, label=None, speed=None, power_percent=None) -> dict:
        command = OPERATIONS.get(kind)
        if command is None:
            raise DesignError(
                f"Onbekend laagtype: {kind}. Kies uit {', '.join(sorted(OPERATIONS))}."
            )
        parts = [command]
        if speed is not None:
            parts += ["-s", f"{_positive(speed, 'speed'):g}"]
        if power_percent is not None:
            percent = _finite(power_percent, "power_percent")
            if not 0 < percent <= 100:
                raise DesignError("power_percent moet tussen 0 en 100 liggen.")
            # De console verwacht de 0-1000 schaal van de engine.
            parts += ["-p", f"{percent * 10:g}"]

        before = {id(o) for o in self.elements.ops()}
        with self.elements.undoscope("Laag toevoegen"):
            self.runner.run(" ".join(parts))
        created = [o for o in self.elements.ops() if id(o) not in before]
        if not created:
            raise DesignError("De engine heeft geen laag aangemaakt.")
        operation = created[0]
        # Een naam die je herkent, in plaats van "Cut defaultmm/s @default".
        operation.label = str(label) if label else self.LAYER_NAMES.get(kind, kind)
        # De engine zet passes op 0 voor "niet ingesteld". Dat leest als "nul
        # keer snijden", en dat is het getal waar een laseraar naar kijkt.
        if not getattr(operation, "passes", 0):
            operation.passes = 1
        self.elements.validate_ids()
        self.user_operations.add(operation.id)
        self._refresh()
        return {"id": operation.id, "type": operation.type}

    # Wat je aan een rasterlaag nog wél mag veranderen.
    GRID_EDITABLE = {"output"}

    def update_operation(self, operation_id: str, **fields) -> dict:
        operation = self._operation(operation_id)
        if self._is_grid_cell(operation, operation_id):
            blocked = sorted(
                k for k, v in fields.items() if v is not None and k not in self.GRID_EDITABLE
            )
            if blocked:
                raise DesignError(
                    "Dit is een cel van een testraster; snelheid en vermogen liggen "
                    f"vast omdat ze de test zijn. Alleen meebranden is te wijzigen "
                    f"({', '.join(blocked)} geweigerd)."
                )
        applied = {}
        with self.elements.undoscope("Laag wijzigen"):
            if "label" in fields and fields["label"] is not None:
                operation.label = str(fields["label"])
                applied["label"] = operation.label
            if fields.get("speed") is not None:
                operation.speed = _positive(fields["speed"], "speed")
                applied["speed"] = operation.speed
            if fields.get("power_percent") is not None:
                percent = _finite(fields["power_percent"], "power_percent")
                if not 0 < percent <= 100:
                    raise DesignError("power_percent moet tussen 0 en 100 liggen.")
                operation.power = percent * 10
                applied["power"] = operation.power
            if fields.get("passes") is not None:
                operation.passes_custom = True
                operation.passes = int(_positive(fields["passes"], "passes"))
                applied["passes"] = operation.passes
            if fields.get("output") is not None:
                operation.output = bool(fields["output"])
                applied["output"] = operation.output
            if fields.get("dpi") is not None:
                # Lijnafstand van een rastergravure; te hoog kost uren.
                dpi = _positive(fields["dpi"], "dpi")
                if not 10 <= dpi <= 2000:
                    raise DesignError("dpi moet tussen 10 en 2000 liggen.")
                operation.dpi = dpi
                applied["dpi"] = dpi
            if fields.get("overscan_mm") is not None:
                distance = _finite(fields["overscan_mm"], "overscan_mm")
                if not 0 <= distance <= 50:
                    raise DesignError("overscan_mm moet tussen 0 en 50 liggen.")
                # De engine wil een lengte mét eenheid, geen kaal getal.
                operation.overscan = f"{distance}mm"
                applied["overscan"] = operation.overscan
            if fields.get("bidirectional") is not None:
                operation.bidirectional = bool(fields["bidirectional"])
                applied["bidirectional"] = operation.bidirectional
        self._refresh()
        return {"id": operation_id, "applied": applied}

    def delete_operation(self, operation_id: str) -> dict:
        operation = self._operation(operation_id)
        with self.elements.undoscope("Laag verwijderen"):
            # Alleen de operatie verdwijnt; de elementen zelf blijven staan,
            # want die kunnen in meerdere lagen zitten.
            operation.remove_node()
        self.user_operations.discard(operation_id)
        self._refresh()
        return {"removed": operation_id}

    def _is_grid_cell(self, operation, operation_id: str) -> bool:
        """Zelfde verificatie als de snapshot: id én instellingen moeten kloppen."""
        cell = self.grid_operations().get(operation_id)
        if not cell:
            return False
        try:
            return (
                abs(float(operation.speed) - float(cell["speed_mm_s"])) <= 0.01
                and abs(float(operation.power) - float(cell["power_percent"]) * 10) <= 0.1
            )
        except (TypeError, ValueError):
            return False

    def _operation(self, operation_id: str):
        node = self.elements.find_node(operation_id)
        if node is None:
            raise DesignError(f"Laag {operation_id} bestaat niet (meer).")
        if not str(node.type).startswith(("op ", "effect ")):
            raise DesignError(f"{operation_id} is geen laag.")
        return node

    def fonts(self) -> list[dict]:
        """
        Beschikbare vectorfonts.

        De Hershey-plugin registreert zowel zijn eigen fonts als de systeem-TTF's;
        namen die met een punt beginnen zijn verborgen systeemfonts.
        """
        registry = getattr(self.kernel.root, "fonts", None)
        if registry is None:
            return []
        found = []
        for entry in registry.available_fonts() or []:
            path = entry[0] if len(entry) > 0 else None
            display = entry[1] if len(entry) > 1 else None
            if not path or not display or str(display).startswith("."):
                continue
            # De engine bewaart alleen de bestandsnaam op de node, dus die
            # geven we mee — anders kan de UI niet zien welk font actief is.
            found.append(
                {
                    "file": str(path),
                    "name": str(display),
                    "basename": str(path).rsplit("/", 1)[-1],
                }
            )
        found.sort(key=lambda f: f["name"].lower())
        return found

    def estimate(self, library=None) -> dict:
        """
        Hoe lang gaat deze job duren, vóór je hem start.

        De pre-flight liet tot nu toe alleen de schatting van een al lopende job
        zien, wat precies te laat is. We draaien de planpijplijn zonder te
        spoolen, tellen snij- en reistijd op, en gooien het plan weer weg.
        """
        self.runner.run("plan copy preprocess validate blob preopt optimize")
        planner = getattr(self.kernel, "planner", None)
        seconds = 0.0
        pieces = 0
        try:
            plan = getattr(planner, "default_plan", None)
            for item in getattr(plan, "plan", []) or []:
                for name in ("duration_cut", "duration_travel"):
                    fn = getattr(item, name, None)
                    if callable(fn):
                        try:
                            seconds += float(fn())
                        except Exception:
                            pass
                pieces += 1
        finally:
            self.runner.run("plan clear")
        return {
            "seconds": round(seconds, 1),
            "parts": pieces,
            "layers": self.job_layers(library),
        }

    def job_layers(self, library=None) -> list[dict]:
        """
        Wat de machine straks gaat dóén, per laag.

        De pre-flight liet alleen de tijd en het aantal onderdelen zien. Wie
        tien jaar met een laser werkt, kijkt vóór het starten naar iets anders:
        welke snelheid, welk vermogen, hoeveel passes — en waar die getallen
        vandaan komen. Een geëxtrapoleerde instelling op acryl is een ander
        gesprek dan een gemeten instelling.
        """
        library = library or getattr(self, "library", None)
        presets = []
        if library is not None:
            try:
                presets = library.presets()
            except Exception:
                presets = []

        def herkomst(speed, power):
            if speed is None or power is None:
                return None
            for preset in presets:
                if abs(float(preset["speed_mm_s"]) - float(speed)) > 0.01:
                    continue
                if abs(float(preset["power_percent"]) * 10 - float(power)) > 0.1:
                    continue
                return preset["source"]
            return None

        layers = []
        for operation in self.elements.ops():
            if not str(operation.type).startswith("op "):
                continue
            if not getattr(operation, "output", True):
                continue
            children = sum(1 for _ in operation.children)
            if not children:
                continue
            speed = getattr(operation, "speed", None)
            power = getattr(operation, "power", None)
            passes = getattr(operation, "passes", None) or 1
            layers.append(
                {
                    "label": operation_label(operation),
                    "type": operation.type,
                    "speed_mm_s": None if speed is None else float(speed),
                    "power_percent": None if power is None else round(float(power) / 10, 1),
                    "passes": int(passes),
                    "elements": children,
                    "source": herkomst(speed, power),
                }
            )
        return layers

    def export_svg(self, filename: str = "ontwerp.svg"):
        """
        Schrijf het ontwerp weg als SVG.

        MeerK40t's eigen schrijver, inclusief zijn namespace, dus operaties en
        instellingen komen bij het terugladen weer mee. Het bestand gaat naar
        een tijdelijke map; de browser haalt het op als download.
        """
        import tempfile
        from pathlib import Path

        safe = Path(filename).name or "ontwerp.svg"
        if not safe.lower().endswith(".svg"):
            safe += ".svg"
        target = Path(tempfile.mkdtemp(prefix="openkerf-export-")) / safe
        self.runner.run(f'save "{target}"')
        if not target.is_file():
            raise DesignError("De engine heeft geen bestand geschreven.")
        return target

    def export_project(self, library, filename: str = "project.openkerf", sheets=None):
        """
        Een projectbestand: het ontwerp plus de bibliotheek-context.

        Een SVG bewaart de vormen en operaties, maar niet welk materiaal of
        welk testraster erbij hoorde — die leven in de lokale database. Een
        project is daarom een zip met de SVG en een JSON ernaast.
        """
        import json
        import tempfile
        import zipfile
        from pathlib import Path

        safe = Path(filename).name or "project.openkerf"
        if not safe.lower().endswith(".openkerf"):
            safe += ".openkerf"
        target = Path(tempfile.mkdtemp(prefix="openkerf-project-")) / safe

        design = self.export_svg("design.svg")
        context = {
            "version": 1,
            "materials": library.materials(),
            "presets": library.presets(),
            "machines": library.machines(),
            "test_grids": library.test_grids(),
        }
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as bundle:
            # design.svg blijft het actieve vel, zodat een ouder OpenKerf het
            # project nog kan openen: dan mis je de andere vellen, maar niet je
            # werk.
            bundle.write(design, "design.svg")
            bundle.writestr("library.json", json.dumps(context, indent=1, default=str))
            if sheets is not None:
                index = sheets.export_into(bundle)
                bundle.writestr(
                    "vellen.json",
                    json.dumps(
                        {"active": sheets.state()["active"], "sheets": index},
                        indent=1,
                        ensure_ascii=False,
                    ),
                )
        return target

    def import_project(self, path, library, sheets=None) -> dict:
        """
        Een project openen: het ontwerp vervangen en ontbrekende
        bibliotheekgegevens aanvullen.

        Bestaande materialen en presets blijven staan; we vullen alleen aan wat
        er niet is, zodat openen van een project andermans werk niet overschrijft.
        """
        import json
        import zipfile
        from pathlib import Path

        source = Path(path)
        if not zipfile.is_zipfile(source):
            raise DesignError("Dit is geen OpenKerf-project.")
        with zipfile.ZipFile(source) as bundle:
            names = set(bundle.namelist())
            if "design.svg" not in names:
                raise DesignError("Het project bevat geen ontwerp.")
            svg = bundle.read("design.svg")
            context = (
                json.loads(bundle.read("library.json")) if "library.json" in names else {}
            )
            if sheets is not None and "vellen.json" in names:
                index = json.loads(bundle.read("vellen.json"))
                sheets.import_from(
                    bundle, index.get("sheets") or [], index.get("active")
                )

        import tempfile

        scratch = Path(tempfile.mkdtemp(prefix="openkerf-open-")) / "design.svg"
        scratch.write_bytes(svg)
        self.elements.clear_all()
        self.user_operations.clear()
        self.runner.run(f'load "{scratch}"')
        self.elements.validate_ids()
        self._refresh()

        added = self._merge_library(context, library)
        return {"imported": True, "library": added}

    @staticmethod
    def _merge_library(context: dict, library) -> dict:
        known = {m["name"] for m in library.materials()}
        materials = 0
        mapping = {m["name"]: m["id"] for m in library.materials()}
        for material in context.get("materials", []):
            if material.get("name") and material["name"] not in known:
                created = library.add_material(material["name"], material.get("synonyms"))
                mapping[created["name"]] = created["id"]
                materials += 1

        existing = {
            (p["material_name"], p["operation"], p["speed_mm_s"], p["power_percent"])
            for p in library.presets()
        }
        presets = 0
        for preset in context.get("presets", []):
            key = (
                preset.get("material_name"),
                preset.get("operation"),
                preset.get("speed_mm_s"),
                preset.get("power_percent"),
            )
            material_id = mapping.get(preset.get("material_name"))
            if key in existing or material_id is None:
                continue
            library.add_preset(
                material_id=material_id,
                thickness_mm=preset.get("thickness_mm"),
                operation=preset.get("operation"),
                speed_mm_s=preset.get("speed_mm_s"),
                power_percent=preset.get("power_percent"),
                passes=preset.get("passes") or 1,
                source=preset.get("source") or "geimporteerd",
                origin_id=preset.get("origin_id"),
                note=preset.get("note") or "",
            )
            presets += 1
        return {"materials": materials, "presets": presets}

    def _refresh(self):
        if getattr(self.runner, "document", None) is not None:
            self.runner.document.touch()
        self.elements.signal("rebuild_tree", "all")
        self.elements.signal("refresh_scene", "Scene")
