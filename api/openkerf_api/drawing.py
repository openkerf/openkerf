"""
Drawing elements and managing layers.

The basics a laser app cannot do without: put a shape or a line of text on the
bed, remove it again, duplicate it, and create the operations that decide how it
is burned.

Everything goes through console commands so the engine stays the single source
of truth — including its automatic classification, which is wanted here: a new
red shape should land in the cut layer by itself.
"""

import re

from .commands import CommandRunner
from .design import _xy, operation_label
from .edits import DesignError, _finite, _positive
from .palette import normalise

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


def _is_filled(node) -> bool:
    """Heeft deze vorm een vlak om te rasteren? Een afbeelding is er zelf een."""
    if str(getattr(node, "type", "")) == "elem image":
        return True
    fill = getattr(node, "fill", None)
    if fill is None or getattr(fill, "value", None) is None:
        return False
    return getattr(fill, "alpha", 255) != 0


def _number(value):
    """Een getal, of niets. De engine levert hier soms een string of numpy."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class Drawing:
    def __init__(self, kernel, runner: CommandRunner | None = None):
        self.kernel = kernel
        self.runner = runner or CommandRunner(kernel)
        # Zelfgemaakte lagen, zodat ze zichtbaar blijven zolang ze leeg zijn.
        self.user_operations: set[str] = set()
        # Callable die de operaties van testrasters teruggeeft; die staan op
        # slot omdat hun waarden de sweep zijn.
        self.grid_operations = lambda: {}
        # Wat een paletkleur op deze machine eerder deed (besluit B2). De
        # server hangt hier het echte geheugen in; los getest is er niets.
        self.color_memory = lambda color: None

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
        before_ops = {id(o) for o in self.elements.ops()}
        with self.elements.undoscope(f"{kind} tekenen"):
            self.runner.run(self._command(kind, values, fields))
        created = [n for n in self.elements.elems() if id(n) not in before]
        if not created:
            raise DesignError("De engine heeft niets getekend.")

        self.elements.validate_ids()
        for node in created:
            self._single_layer(node)
        self._seed_from_memory(before_ops)
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
            self._ensure_colors()
            self.runner.run(" ".join(parts))
        created = [o for o in self.elements.ops() if id(o) not in before]
        if not created:
            raise DesignError("De engine heeft geen laag aangemaakt.")
        operation = created[0]
        # Een naam die je herkent, in plaats van "Cut defaultmm/s @default".
        operation.label = str(label) if label else self.LAYER_NAMES.get(kind, kind)
        # Een eigen kleur vanaf het begin. De engine geeft rasterlagen zwart en
        # puntlagen doorzichtig mee; als laagkleur zijn dat allebei niets — je
        # ziet op het canvas én in de lijst niet welke laag je voor je hebt.
        self._set_color(operation, self._next_color())
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

    def move_operation(self, operation_id: str, direction=None, index=None) -> dict:
        """
        Verschuif een laag in de brandvolgorde.

        De volgorde van de kinderen onder `branch ops` ís de volgorde waarin de
        machine brandt — graveren vóór snijden, anders val je het werkstuk uit
        het vel voordat het opschrift erop staat. Rastercellen slaan we over:
        die horen bij één testbord en hebben onderling geen eigen volgorde.

        Twee manieren, één weg: `direction` is één stap (de knoppen ↑/↓),
        `index` is een bestemming (slepen, gat L1). Bij slepen weet de lijst
        precies waar de laag heen moet en niet hoeveel stappen dat zijn — dat
        omrekenen naar stapjes zou bij elke tussenliggende rastercel misgaan.
        """
        if (direction is None) == (index is None):
            raise DesignError("Geef één van beide: 'direction' of 'index'.")
        if direction is not None and direction not in ("up", "down"):
            raise DesignError("richting moet 'up' of 'down' zijn.")
        operation = self._operation(operation_id)
        parent = operation.parent
        if parent is None:
            raise DesignError("Deze laag zit niet in de bewerkingenboom.")

        siblings = list(parent.children)
        try:
            here = siblings.index(operation)
        except ValueError:  # pragma: no cover - de boom is dan al inconsistent
            raise DesignError("Deze laag staat niet in zijn eigen tak.")

        if direction is not None:
            step = -1 if direction == "up" else 1
            target = here + step
            below = direction == "down"
        else:
            # De lijst telt in lagen, wij tellen in kinderen van `branch ops`.
            # Voor de gebruiker is "plek 3" de derde láág, niet de derde knoop;
            # met een testraster ertussen is dat niet hetzelfde getal.
            plain = [node for node in siblings if self._plain_layer(node)]
            try:
                wanted = int(index)
            except (TypeError, ValueError):
                raise DesignError("index moet een geheel getal zijn.")
            if not 0 <= wanted < len(plain):
                raise DesignError(
                    f"index moet tussen 0 en {len(plain) - 1} liggen."
                )
            anchor = plain[wanted]
            if anchor is operation:
                return {"id": operation_id, "moved": False, "index": here}
            target = siblings.index(anchor)
            # Naar beneden schuiven betekent: ónder de laag komen die daar nu
            # staat. Naar boven: erboven. Anders landt de laag er steeds één
            # naast en loopt de lijst bij het slepen een plek achter.
            below = target > here
        if not 0 <= target < len(siblings):
            return {"id": operation_id, "moved": False, "index": here}

        with self.elements.undoscope("Laagvolgorde wijzigen"):
            # `swap_node` lijkt hier de juiste zet maar wisselt óók de kinderen
            # van beide knopen om, dus de referenties naar de vormen verhuizen
            # mee en er verandert per saldo niets. `insert_sibling` verplaatst
            # alleen de knoop zelf — dat is wat "een laag opschuiven" betekent.
            siblings[target].insert_sibling(operation, below=below)
        self._refresh()
        return {"id": operation_id, "moved": True, "index": target}

    # Hoe de machine hoort te werken: eerst wat het oppervlak raakt, dan wat
    # erdoorheen gaat. Snijden als laatste, want een uitgesneden werkstuk ligt
    # los in het bed en verschuift onder de volgende bewerking — of valt eruit.
    BURN_ORDER = {
        "op image": 0,
        "op raster": 1,
        "op engrave": 2,
        "op dots": 3,
        "op cut": 4,
    }

    def _plain_layer(self, node) -> bool:
        """Een gewone laag: een bewerking die geen cel van een testraster is."""
        if not str(getattr(node, "type", "")).startswith("op "):
            return False
        return not self._is_grid_cell(node, getattr(node, "id", "") or "")

    def sort_operations(self) -> dict:
        """
        Graveren vóór snijden, in één handeling (gat L2).

        LightBurn heeft hier `Sort Cuts Last` voor, en dat is één klik voor de
        duurste fout die er is: het werkstuk valt uit het vel voordat het
        opschrift erop staat. Stabiel sorteren, zodat twee snijlagen hun
        onderlinge volgorde houden — die heeft de gebruiker zelf gekozen.

        Rastercellen blijven staan waar ze staan: hun volgorde is de sweep.
        """
        parent = self.elements.op_branch
        children = list(parent.children)
        layers = [node for node in children if self._plain_layer(node)]
        if len(layers) < 2:
            return {"sorted": False, "order": [node.id for node in layers]}

        wanted = sorted(
            layers, key=lambda node: self.BURN_ORDER.get(str(node.type), 99)
        )
        if wanted == layers:
            return {"sorted": False, "order": [node.id for node in wanted]}

        with self.elements.undoscope("Graveren vóór snijden"):
            # De eerste laag blijft liggen waar de eerste laag lag; de rest
            # schuift er in volgorde achteraan. Zo blijft een testraster dat
            # ertussen staat op zijn eigen plek en verhuist alleen wat wij
            # sorteren.
            vorige = wanted[0]
            for node in wanted[1:]:
                vorige.insert_sibling(node, below=True)
                vorige = node
        self._refresh()
        return {"sorted": True, "order": [node.id for node in wanted]}

    # Instellingen die een laag houdt als hij van soort verandert. Bewust niet
    # `dpi`/`overscan`: die horen bij rasteren en zijn op een snijlaag zinloos —
    # de engine geeft de nieuwe laag daar zijn eigen standaard voor.
    TYPE_KEEP = ("label", "speed", "power", "passes", "output", "coolant")

    def change_operation_type(self, operation_id: str, kind: str) -> dict:
        """
        Een snijlaag graveerlaag maken, met de vormen erin (gat L3).

        De engine kent geen "verander het type van deze bewerking": het type
        zit in de klasse van de knoop. Wat er wél kan is een nieuwe bewerking
        maken, de referenties verhuizen en de oude weghalen — precies wat je
        met de hand zou doen, maar dan zonder de toewijzingen kwijt te raken.
        Alles binnen één undoscope, dus één keer ongedaan maken zet het terug.
        """
        if kind not in OPERATIONS:
            raise DesignError(
                f"Onbekend laagtype: {kind}. Kies uit {', '.join(sorted(OPERATIONS))}."
            )
        old = self._operation(operation_id)
        if self._is_grid_cell(old, operation_id):
            raise DesignError(
                "Dit is een cel van een testraster; het soort bewerking is de test."
            )
        if str(old.type) == f"op {kind}" or (
            kind == "image" and str(old.type) == "op image"
        ):
            return {"id": operation_id, "type": old.type, "changed": False}

        parent = old.parent
        siblings = list(parent.children)
        here = siblings.index(old)
        kleur = self._usable_color(old)
        bewaard = {
            name: getattr(old, name, None)
            for name in self.TYPE_KEEP
            if getattr(old, name, None) is not None
        }
        # Een laag die nog "Snijden" heet omdat hij zo geboren is, moet na het
        # omzetten "Graveren" heten — anders staat er een snijlaag in de lijst
        # die graveert. Een naam die de gebruiker zélf gaf, blijft staan: die
        # zegt waar de laag voor is en niet wat hij doet.
        standaard = {f"op {k}": v for k, v in self.LAYER_NAMES.items()}
        if bewaard.get("label") == standaard.get(str(old.type)):
            bewaard["label"] = self.LAYER_NAMES.get(kind, kind)
        vormen = [
            reference.node
            for reference in list(old.children)
            if getattr(reference, "node", None) is not None
        ]

        with self.elements.undoscope("Laagsoort wijzigen"):
            before = {id(o) for o in self.elements.ops()}
            self.runner.run(OPERATIONS[kind])
            gemaakt = [o for o in self.elements.ops() if id(o) not in before]
            if not gemaakt:
                raise DesignError("De engine heeft geen laag aangemaakt.")
            nieuw = gemaakt[0]
            for name, value in bewaard.items():
                setattr(nieuw, name, value)
            if kleur:
                self._set_color(nieuw, kleur)
            for node in vormen:
                nieuw.add_reference(node)
            # Op de plek van de oude: de brandvolgorde is de reden dat de lijst
            # een volgorde heeft, en die mag niet verspringen omdat je het soort
            # bijstelt.
            old.insert_sibling(nieuw, below=False)
            old.remove_node()

        self.elements.validate_ids()
        self.user_operations.discard(operation_id)
        self.user_operations.add(nieuw.id)
        self._refresh()
        return {
            "id": nieuw.id,
            "type": nieuw.type,
            "changed": True,
            "replaced": operation_id,
            "index": here,
            "elements": len(vormen),
        }

    # ------------------------------------------------------- air assist (B11)
    #
    # De engine zet air assist per bewerking in `coolant`: 0 is "laat staan",
    # 1 is aan, 2 is uit. `cutplan` vertaalt dat naar `coolant_on`/`coolant_off`
    # — maar alléén als het apparaat een methode geclaimd heeft. Heeft het die
    # niet, dan schrijft de engine een klacht op het consolekanaal en gebeurt er
    # verder niets. Een schakelaar die stilzwijgend niets doet is erger dan geen
    # schakelaar, dus tonen we hem alleen als de driver hem kent (besluit B11).
    COOLANT_ON = 1
    COOLANT_OFF = 2

    def air_assist_supported(self) -> bool:
        """Kent de actieve machine een commando voor air assist?"""
        coolant = getattr(getattr(self.kernel, "root", None), "coolant", None)
        device = getattr(self.kernel, "device", None)
        if coolant is None or device is None:
            return False
        try:
            return coolant.get_device_function(device) is not None
        except Exception:  # pragma: no cover - een driver die niet meewerkt
            return False

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
            if fields.get("color") is not None:
                # Laagkleur is identificatie, geen instelling: hij bepaalt hoe
                # de vormen op het canvas getekend worden en waar de gebruiker
                # zijn laag aan herkent. De engine wil een Color, geen string.
                applied["color"] = self._set_color(operation, fields["color"])
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
            if fields.get("air_assist") is not None:
                # Uit is expliciet uit (2), niet "laat staan" (0): een laag die
                # ná een laag met air assist brandt, moet de blazer ook echt
                # dichtzetten. Met 0 blijft hij aan en denkt de gebruiker dat
                # hij uitstaat omdat de schakelaar dat zegt.
                if not self.air_assist_supported():
                    raise DesignError(
                        "Deze machine kent geen commando voor air assist, dus "
                        "een schakelaar hier zou niets doen. Stel eerst bij de "
                        "machine in welke methode de blazer aanstuurt."
                    )
                aan = bool(fields["air_assist"])
                operation.coolant = self.COOLANT_ON if aan else self.COOLANT_OFF
                applied["air_assist"] = aan
        self._refresh()
        return {"id": operation_id, "applied": applied}

    # ---------------------------------------------------------------- palet

    def layer_for_color(self, color: str, memory: dict | None = None) -> dict:
        """
        De laag met deze paletkleur, desnoods vers aangemaakt (besluit B2).

        Kleur is bij ons de identiteit van een laag, dus "de laag van rood" is
        een eenduidige vraag: er is er hoogstens één. Testrastercellen tellen
        niet mee — die horen bij een testbord en hun waarden liggen vast.

        Een verse laag begint op wat die kleur op deze machine eerder deed. Dat
        is het hele punt van het geheugen: een laag die blanco begint, dwingt je
        elke keer opnieuw twee getallen te bedenken.
        """
        wanted = self._valid_color(color)
        self.elements.validate_ids()
        for op in self.elements.ops():
            # Alleen echte bewerkingen: een effect draagt ook een kleur, maar
            # het is een container in de elementenboom en geen laag.
            if not str(op.type).startswith("op "):
                continue
            if self._is_grid_cell(op, getattr(op, "id", "") or ""):
                continue
            if self._usable_color(op) == wanted:
                return {"id": op.id, "type": op.type, "created": False}

        memory = memory or {}
        kind = str(memory.get("type") or "cut")
        if kind not in OPERATIONS:
            kind = "cut"
        made = self.create_operation(
            kind,
            speed=memory.get("speed_mm_s"),
            power_percent=memory.get("power_percent"),
        )
        operation = self._operation(made["id"])
        # create_operation deelt de eerstvolgende vrije paletkleur uit; hier is
        # de kleur juist de reden dat de laag bestaat.
        self._set_color(operation, wanted)
        self._refresh()
        return {"id": operation.id, "type": operation.type, "created": True}

    def _seed_from_memory(self, before_ops: set) -> None:
        """
        Een laag die de classificatie zelf aanmaakt, op het geheugen zetten.

        Wie een paletkleur kiest en dan tekent, laat de engine een laag maken —
        niet wij. Zonder dit begint die op de fabrieksinstelling, terwijl de
        gebruiker net een kleur koos waarvan hij wéét wat hij ermee deed. B2
        belooft dat een verse laag niet blanco begint; dit is de andere helft
        van die belofte.
        """
        for op in self.elements.ops():
            if id(op) in before_ops or not str(op.type).startswith("op "):
                continue
            kleur = self._usable_color(op)
            if kleur is None:
                # De classificatie geeft zo'n verse laag de tekenkleur mét
                # alfa nul mee ("#0090ff00"). Dat is dezelfde kleur en toch
                # geen kleur: op het canvas viel de laag terug op de eerste
                # paletkleur, dus je tekende in blauw en kreeg rood. De alfa
                # eraf halen is hier de hele reparatie.
                kleur = normalise(str(getattr(op, "color", ""))[:7])
                if kleur is None:
                    continue
                self._set_color(op, kleur)
            try:
                onthouden = self.color_memory(kleur) or {}
            except Exception:
                continue
            if onthouden.get("speed_mm_s"):
                op.speed = float(onthouden["speed_mm_s"])
            if onthouden.get("power_percent"):
                op.power = float(onthouden["power_percent"]) * 10

    def paint(self, element_ids, color: str, memory: dict | None = None) -> dict:
        """
        Zet de selectie in de laag van deze kleur — verplaatsen, niet toevoegen.

        Eén klik op een paletvakje, waar het via het lagenpaneel drie
        handelingen kostte (tabblad, laag zoeken, "hierin"). Verplaatsen en niet
        toevoegen, want dat is wat een gebruiker bedoelt met "maak dit rood":
        een vorm die daarna in twee lagen zit, brandt twee keer.

        De lijnkleur van de vorm gaat mee. In MeerK40t ís de lijnkleur waar de
        classificatie op werkt, dus zonder dat springt de vorm bij het opnieuw
        laden van een SVG terug naar zijn oude laag.
        """
        from meerk40t.svgelements import Color

        wanted = self._valid_color(color)
        nodes = self._nodes(element_ids)
        layer = self.layer_for_color(wanted, memory)
        operation = self._operation(layer["id"])

        with self.elements.undoscope("Naar laag verplaatsen"):
            for node in nodes:
                for reference in list(getattr(node, "_references", [])):
                    if reference.parent is not None:
                        reference.remove_node()
                operation.add_reference(node)
                if hasattr(node, "stroke"):
                    node.stroke = Color(wanted)
                    # Zoals de engine het zelf doet in `element_stroke`: geen
                    # altered(), want dat gooit de gecachete geometrie weg.
                    node.translated(0, 0)
        self.elements.signal("element_property_reload", nodes)
        self._refresh()
        return {
            "operation_id": operation.id,
            "created": layer["created"],
            "ids": [n.id for n in nodes],
        }

    def set_default_color(self, color: str) -> dict:
        """
        De kleur waarin nieuw werk getekend wordt.

        `default_stroke` is de kleur die de engine aan elke nieuwe vorm geeft,
        dus dit is precies LightBurns "klikken zonder selectie zet de kleur voor
        nieuw werk" — geen eigen boekhouding ernaast.
        """
        from meerk40t.svgelements import Color

        wanted = self._valid_color(color)
        self.elements.default_stroke = Color(wanted)
        return {"color": wanted}

    def default_color(self) -> str | None:
        try:
            return normalise(str(self.elements.default_stroke.hexrgb))
        except (AttributeError, TypeError, ValueError):
            return None

    @staticmethod
    def _valid_color(color) -> str:
        wanted = normalise(color)
        if wanted is None:
            raise DesignError("color moet een #rrggbb-waarde zijn.")
        return wanted

    def delete_operation(self, operation_id: str) -> dict:
        operation = self._operation(operation_id)
        with self.elements.undoscope("Laag verwijderen"):
            # Alleen de operatie verdwijnt; de elementen zelf blijven staan,
            # want die kunnen in meerdere lagen zitten.
            operation.remove_node()
        self.user_operations.discard(operation_id)
        self._refresh()
        return {"removed": operation_id}

    # Dezelfde tien als `--layer-1..10` in tokens.css en LAYER_COLORS in de
    # frontend. Ze staan hier nog een keer omdat een nieuwe laag zijn kleur van
    # de engine moet krijgen, niet pas van het paneel dat hem toevallig toont.
    # Laag 4 ging in design-system v3.3 van #46A758 naar #0F9B32: de oude groen
    # was bij rood-groenblindheid niet te scheiden van laag 9 en 10.
    PALETTE = (
        "#E5484D", "#F76B15", "#FFC53D", "#0F9B32", "#12A594",
        "#0090FF", "#8E4EC6", "#E93D82", "#8D6E63", "#607D8B",
    )

    @staticmethod
    def _usable_color(op) -> str | None:
        """
        De kleur van een laag, of niets als de engine er geen gaf.

        Een snijlaag krijgt rood mee, maar een rasterlaag zwart en een puntlaag
        volledig doorzichtig. Als laagkleur zijn die twee laatste geen kleur:
        onzichtbaar op het canvas en niet te onderscheiden in de lijst.
        """
        color = getattr(op, "color", None)
        if color is None:
            return None
        if getattr(color, "alpha", 255) == 0 or getattr(color, "value", None) is None:
            return None
        text = str(getattr(color, "hexrgb", "") or "").lower()
        return None if text in ("", "#000000") else text

    def _next_color(self) -> str:
        """De eerste palet-kleur die nog niet in gebruik is, anders op volgorde."""
        ops = list(self.elements.ops())
        used = {c for c in (self._usable_color(op) for op in ops) if c}
        for candidate in self.PALETTE:
            if candidate.lower() not in used:
                return candidate
        return self.PALETTE[len(ops) % len(self.PALETTE)]

    def _ensure_colors(self) -> None:
        """
        Geef elke laag zonder bruikbare kleur er alsnog een.

        Zonder dit botst een nieuwe laag met de standaardlaag die de engine zelf
        aanmaakte: die is doorzichtig, dus de frontend valt voor hem terug op de
        eerste paletkleur — precies degene die wij net uitdeelden.
        """
        for op in list(self.elements.ops()):
            if self._usable_color(op) is None:
                self._set_color(op, self._next_color())

    @staticmethod
    def _set_color(operation, value) -> str:
        """Zet een `#rrggbb` op de laag; alfa laten we er niet in, want een
        doorzichtige laagkleur is op het canvas geen kleur meer."""
        from meerk40t.svgelements import Color

        text = str(value).strip()
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", text):
            raise DesignError("color moet een #rrggbb-waarde zijn.")
        operation.color = Color(text)
        return text

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

    def estimate(self, library=None, provenance=None, sheet=None, exact=False) -> dict:
        """
        Hoe lang gaat deze job duren, vóór je hem start.

        Standaard gerekend op de geometrie en de laaginstellingen, niet op het
        gebouwde snijplan. Dat plan bouwen was de reden dat deze route op een
        zwaar ontwerp minuten kostte (gat J1): `plan copy` kopieert de cutcode
        één keer per pass, en de optimalisatie erna schaalt kwadratisch in het
        aantal stukken. Zestig passes over tweehonderd vormen zijn twaalfduizend
        objecten waarvan we uiteindelijk alleen de totale lengte gebruiken.

        Lengte per vorm keer het aantal passes, gedeeld door de snelheid van de
        laag, plus de sprongen ertussen — dat is precies wat `duration_cut` en
        `duration_travel` optellen, alleen zonder eerst het plan te maken. De
        volgorde die de optimalisatie kiest zit er niet in, dus de reistijd is
        een bovengrens; de brandtijd is exact dezelfde som.

        `exact=True` bouwt alsnog het volledige plan. Alleen bedoeld om de
        snelle route tegen de oude te kunnen ijken — niet voor de UI.
        """
        seconds, pieces = (
            self._plan_estimate() if exact else self._geometry_estimate()
        )
        return {
            "seconds": round(seconds, 1),
            # Hoeveel vormen er gebrand worden. Nul betekent dat de machine
            # niets zou doen, en dáár hangt de pre-flight zijn "er is niets om
            # te branden" aan.
            "parts": pieces,
            "method": "plan" if exact else "geometry",
            # Waarin gebrand wordt hoort bij wat er gebrand wordt: zonder het
            # materiaal van het vel is "instelling van 3 mm berken" een
            # mededeling zonder tegenpartij.
            "sheet": sheet,
            "layers": self.job_layers(library, provenance, sheet),
            # Wat er buiten het bed of buiten het vel hangt (gat C2). Hier en
            # niet alleen op het canvas: op tablet en telefoon staat het canvas
            # er niet naast, en dit is het laatste scherm vóór het branden.
            "bounds": self.bounds_report(sheet),
        }

    # Een halve millimeter speling. Precies op de rand liggen is geen fout —
    # dat is een vorm die het vel vult — en meetruis in de omhullende mag geen
    # rode rand opleveren op werk dat gewoon past.
    RAND_SPELING = 0.5

    def bed_mm(self) -> tuple[float, float] | None:
        """De bedmaat van de actieve machine in millimeters."""
        device = getattr(self.kernel, "device", None)
        view = getattr(device, "view", None)
        try:
            from meerk40t.core.units import Length

            return (
                float(Length(view.width).mm),
                float(Length(view.height).mm),
            )
        except Exception:
            return None

    def bounds_report(self, sheet=None) -> dict:
        """
        Wat er buiten het bed of buiten het vel valt (gat C2).

        Twee verschillende fouten, en het verschil telt: buiten het bed kán de
        machine niet komen — daar loopt de kop tegen zijn eindaanslag of slaat
        de driver de beweging over. Buiten het vel kán de machine wel komen,
        maar daar ligt geen materiaal; dan brandt hij in de rooster of in je
        werkblad. Allebei kosten ze materiaal en tijd, en allebei zijn ze nu
        alleen te zien door goed te kijken.
        """
        units = self._units_per_mm()
        bed = self.bed_mm()
        vel = None
        if sheet and sheet.get("width_mm") and sheet.get("height_mm"):
            vel = (float(sheet["width_mm"]), float(sheet["height_mm"]))

        buiten_bed: list[str] = []
        buiten_vel: list[str] = []
        x0 = y0 = float("inf")
        x1 = y1 = float("-inf")
        for node in self.elements.elems():
            box = getattr(node, "bounds", None)
            if not box:
                continue
            a, b, c, d = (float(v) / units for v in box)
            x0, y0 = min(x0, a), min(y0, b)
            x1, y1 = max(x1, c), max(y1, d)
            naam = getattr(node, "id", None) or ""
            if bed and self._buiten(a, b, c, d, bed):
                buiten_bed.append(naam)
            if vel and self._buiten(a, b, c, d, vel):
                buiten_vel.append(naam)

        werk = None
        if x1 > x0:
            werk = {
                "x_mm": round(x0, 2),
                "y_mm": round(y0, 2),
                "width_mm": round(x1 - x0, 2),
                "height_mm": round(y1 - y0, 2),
            }
        return {
            "bed": None if not bed else {"width_mm": round(bed[0], 2), "height_mm": round(bed[1], 2)},
            "sheet": None if not vel else {"width_mm": vel[0], "height_mm": vel[1]},
            "work": werk,
            "outside_bed": len(buiten_bed),
            "outside_sheet": len(buiten_vel),
            "outside_bed_ids": buiten_bed,
            "outside_sheet_ids": buiten_vel,
        }

    @classmethod
    def _buiten(cls, x0, y0, x1, y1, kader) -> bool:
        speling = cls.RAND_SPELING
        return (
            x0 < -speling
            or y0 < -speling
            or x1 > kader[0] + speling
            or y1 > kader[1] + speling
        )

    def _units_per_mm(self) -> float:
        from meerk40t.core.units import UNITS_PER_MM

        return float(UNITS_PER_MM)

    def _plan_estimate(self) -> tuple[float, int]:
        """De oude weg: het hele plan bouwen en de duur eruit optellen."""
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
        return seconds, pieces

    # Verplaatsen zonder branden. De engine rekent met 100 mm/s zodra een
    # apparaat niets anders opgeeft (core/parameters.py:314).
    RAPID_MM_S = 100.0

    def _geometry_estimate(self) -> tuple[float, int]:
        """Brandtijd en reistijd uit de elementenboom, zonder plan."""
        seconds = 0.0
        pieces = 0
        rapid = self._rapid_mm_s()
        for operation in self.elements.ops():
            kind = str(operation.type)
            if not kind.startswith("op ") or not getattr(operation, "output", True):
                continue
            shapes = self._burnable(operation)
            pieces += len(shapes)
            if not shapes:
                continue
            passes = int(getattr(operation, "passes", None) or 1)
            if kind == "op dots":
                # Een punt kost zijn verblijftijd, niet zijn lengte.
                dwell = _number(getattr(operation, "dwell_time", None)) or 0.0
                seconds += passes * len(shapes) * dwell / 1000
                continue
            speed = _number(getattr(operation, "speed", None))
            if not speed or speed <= 0:
                continue
            if kind in ("op raster", "op image"):
                burn_mm = self._scan_mm(operation, shapes)
                travel_mm = 0.0
            else:
                burn_mm = sum(self._length_mm(node) for node in shapes)
                travel_mm = self._travel_mm(shapes)
            seconds += passes * (burn_mm / speed + travel_mm / rapid)
        return seconds, pieces

    def _rapid_mm_s(self) -> float:
        device = getattr(self.kernel, "device", None)
        value = _number(getattr(device, "rapid_speed", None))
        return value if value and value > 0 else self.RAPID_MM_S

    def _burnable(self, operation) -> list:
        """
        De vormen onder een laag, verwijzingen opgelost.

        Een laag bevat `ReferenceNode`s die naar het element wijzen, en een
        effect (hatch, wobble) is zelf een container met eigen geometrie. Wat
        verborgen is, wordt niet gebrand en telt hier dus niet mee.
        """
        found = []
        stack = list(operation.children)
        depth = 0
        while stack and depth < 5000:
            depth += 1
            node = stack.pop()
            target = getattr(node, "node", None) or node
            if getattr(target, "hidden", False):
                continue
            if hasattr(target, "as_geometry") or getattr(target, "type", "") == (
                "elem image"
            ):
                found.append(target)
            else:
                stack.extend(getattr(target, "children", []) or [])
        return found

    @staticmethod
    def _length_mm(node) -> float:
        from meerk40t.core.units import UNITS_PER_MM

        try:
            return float(node.as_geometry().length()) / UNITS_PER_MM
        except Exception:
            # Een afbeelding heeft geen pad; die valt onder de rasterrekensom.
            return 0.0

    @staticmethod
    def _center_mm(node) -> tuple[float, float] | None:
        from meerk40t.core.units import UNITS_PER_MM

        bounds = getattr(node, "bounds", None)
        if not bounds:
            return None
        x0, y0, x1, y1 = bounds
        return (x0 + x1) / 2 / UNITS_PER_MM, (y0 + y1) / 2 / UNITS_PER_MM

    def _travel_mm(self, nodes) -> float:
        """
        De sprongen tussen de vormen, in de volgorde die het dichtst bij ligt.

        De optimalisatie van de engine doet hetzelfde (nearest-neighbour) maar
        dan op snijstukken in plaats van op hele vormen, dus dit is een ruwe
        bovengrens. Bij veel vormen wordt het te duur om exact te doen, en het
        is de kleinste term in de som.
        """
        points = [p for p in (self._center_mm(n) for n in nodes) if p]
        if len(points) < 2:
            return 0.0
        import numpy as np

        # Als complexe getallen, net als de geometrie van de engine: dan is de
        # afstand tot álle overgebleven punten één numpy-bewerking. In Python
        # per punt zou dit bij duizend vormen seconden kosten, en dan zijn we
        # terug bij het probleem dat we oplossen.
        rest = np.array([complex(x, y) for x, y in points])
        here = rest[0]
        rest = np.delete(rest, 0)
        travel = 0.0
        while rest.size:
            afstanden = np.abs(rest - here)
            index = int(afstanden.argmin())
            travel += float(afstanden[index])
            here = rest[index]
            rest = np.delete(rest, index)
        return travel

    @staticmethod
    def _scan_mm(operation, nodes) -> float:
        """
        Hoeveel millimeter de kop aflegt om deze laag te rasteren.

        Regel voor regel over elke vorm heen, met de regelafstand uit de dpi en
        de overscan aan weerszijden. Eenrichtingsverkeer verdubbelt het: dan
        rijdt de kop elke regel leeg terug.

        Per vorm, niet over de omhullende van de hele laag: twee vlakken in
        tegenoverliggende hoeken rasteren het lege midden ertussen niet.

        Een rasterlaag brandt het **vlak**, en een vorm zonder vulling heeft dat
        niet. Zo'n vorm levert in het echte plan nul cutcode op (gemeten: een
        omlijnde rechthoek in een rasterlaag geeft 0,0 s), dus hij telt hier ook
        niet mee — anders staat er 8 minuten voor werk dat niet gebeurt.
        """
        from meerk40t.core.units import UNITS_PER_MM

        dpi = _number(getattr(operation, "dpi", None)) or 500.0
        step_mm = 25.4 / max(dpi, 1.0)
        vlak = str(operation.type) == "op raster"
        overscan_mm = 0.0
        raw = getattr(operation, "overscan", None)
        if raw is not None:
            try:
                from meerk40t.core.units import Length

                overscan_mm = float(Length(raw).mm)
            except Exception:
                overscan_mm = 0.0

        scan = 0.0
        for node in nodes:
            bounds = getattr(node, "bounds", None)
            if not bounds:
                continue
            if vlak and not _is_filled(node):
                continue
            width = (bounds[2] - bounds[0]) / UNITS_PER_MM
            height = (bounds[3] - bounds[1]) / UNITS_PER_MM
            lines = max(1.0, height / step_mm)
            scan += lines * (width + 2 * overscan_mm)
        if not getattr(operation, "bidirectional", True):
            scan *= 2
        return scan

    def job_layers(self, library=None, provenance=None, sheet=None) -> list[dict]:
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

        sheet_id = (sheet or {}).get("id")

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
            percent = None if power is None else round(float(power) / 10, 1)
            operation_id = getattr(operation, "id", None)
            # Het briefje van deze laag gaat vóór op raden aan de getallen: het
            # weet ook wélk materiaal er bij die getallen hoorde.
            entry = (
                provenance.lookup(sheet_id, operation_id, speed, percent)
                if provenance is not None
                else None
            )
            layers.append(
                {
                    # Zonder id kan de pre-flight de laagkleur niet opzoeken, en
                    # twee operaties van hetzelfde type heten allebei "Graveren".
                    "id": operation_id,
                    "label": operation_label(operation),
                    "type": operation.type,
                    "speed_mm_s": None if speed is None else float(speed),
                    "power_percent": percent,
                    "passes": int(passes),
                    "elements": children,
                    "source": (entry or {}).get("source") or herkomst(speed, power),
                    "preset_id": (entry or {}).get("preset_id"),
                    "material_id": (entry or {}).get("material_id"),
                    "material_name": (entry or {}).get("material_name"),
                    "thickness_mm": (entry or {}).get("thickness_mm"),
                    "warnings": _layer_warnings(entry, sheet),
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


# Verschil in dikte waarbij een instelling nog "van dezelfde plaat" is. Een
# halve millimeter dekt de spreiding van plaatmateriaal; daarboven is het een
# andere dikte en dus een andere snede.
DIKTE_SPELING = 0.51


def _mm_tekst(waarde) -> str:
    """3 in plaats van 3.0, en 0,8 in plaats van 0.8 — het is een Nederlandse maat."""
    getal = float(waarde)
    heel = f"{getal:g}"
    return heel.replace(".", ",")


# Hoe zwaar een bezwaar weegt. Niet alle waarschuwingen zijn even erg, en wie ze
# even zwaar toont laat de gebruiker zelf uitzoeken wat er eerst moet — precies
# op het moment dat hij daar geen zin in heeft.
#
# Een gemeten instelling van het verkeerde materiaal is het ergst: die getallen
# zijn wél waar, maar over iets anders, en niets in beeld spreekt ze tegen. Een
# andere dikte van hetzelfde materiaal is een gradatie daarvan. Een uitgerekende
# waarde op het juiste materiaal is de mildste: hij kán kloppen, hij is alleen
# nooit bewezen.
ERNST = {"ander-materiaal": 3, "andere-dikte": 2, "nooit-gebrand": 1}


def _layer_warnings(entry: dict | None, sheet: dict | None) -> list[dict]:
    """
    Waarom je vóór het starten nog even naar deze laag moet kijken.

    Drie dingen, in volgorde van hoe hard ze kunnen aankomen: de instelling
    komt van een ánder materiaal, van een andere dikte, of van niemand — hij is
    uitgerekend of overgenomen en nooit werkelijk gebrand.
    """
    if not entry:
        return []

    waarschuwingen = []
    sheet = sheet or {}
    vel_materiaal = sheet.get("material_id")
    vel_naam = sheet.get("material_name") or "dit vel"
    vel_dikte = sheet.get("thickness_mm")

    van = entry.get("material_name") or "een ander materiaal"
    if (
        vel_materiaal is not None
        and entry.get("material_id") is not None
        and entry["material_id"] != vel_materiaal
    ):
        waarschuwingen.append(
            {
                "code": "ander-materiaal",
                "text": f"Deze instelling is voor {van}; dit vel is {vel_naam}.",
            }
        )
    elif (
        vel_dikte is not None
        and entry.get("thickness_mm") is not None
        and abs(float(entry["thickness_mm"]) - float(vel_dikte)) >= DIKTE_SPELING
    ):
        waarschuwingen.append(
            {
                "code": "andere-dikte",
                "text": (
                    f"Deze instelling is voor {_mm_tekst(entry['thickness_mm'])} mm; "
                    f"dit vel is {_mm_tekst(vel_dikte)} mm."
                ),
            }
        )

    if entry.get("source") == "geextrapoleerd":
        waarschuwingen.append(
            {
                "code": "nooit-gebrand",
                "text": "Uitgerekend vanaf een andere dikte — nooit gebrand.",
            }
        )
    elif entry.get("source") == "geimporteerd":
        waarschuwingen.append(
            {
                "code": "nooit-gebrand",
                "text": "Van een andere machine overgenomen — hier nooit gebrand.",
            }
        )

    # Het zwaarste bezwaar bovenaan, zodat de lezer niet zelf hoeft te wegen.
    for waarschuwing in waarschuwingen:
        waarschuwing["ernst"] = ERNST.get(waarschuwing["code"], 1)
    waarschuwingen.sort(key=lambda w: -w["ernst"])
    return waarschuwingen
