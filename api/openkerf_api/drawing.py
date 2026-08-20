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
from contextlib import contextmanager

from .commands import CommandRunner
from .design import _xy, operation_label
from .edits import DesignError, _finite, _positive
from .palette import normalise
from .testgrid import LABEL_LAYER

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

# Het knooptype dat bij elk laagtype hoort — nodig om een bestaande laag van
# het gevraagde soort terug te vinden in plaats van er nog een aan te maken.
_OPERATION_TYPES = {
    "cut": "op cut",
    "engrave": "op engrave",
    "raster": "op raster",
    "image": "op image",
    "dots": "op dots",
}


def _mm(value: float) -> str:
    return f"{value:.4f}mm"


def _passes_of(node) -> int:
    """
    Hoe vaak de machine deze laag werkelijk gaat doen.

    Niet het veld `passes`, maar `implicit_passes`: de engine negeert het veld
    zolang `passes_custom` uit staat (`core/parameters.py:401`), dus een laag
    met `passes = 3` en die vlag uit brandt één keer. Gemeten op een testbord
    dat "2 passes" op zijn opschrift had en er één deed — en de pre-flight en
    het paneel meldden allebei 2, want die lazen het veld.
    """
    getal = getattr(node, "implicit_passes", None)
    if getal is None:
        getal = getattr(node, "passes", None)
    try:
        return max(int(getal), 1)
    except (TypeError, ValueError):
        return 1


def _is_filled(node) -> bool:
    """Does this shape have an area to raster? An image is one itself."""
    if str(getattr(node, "type", "")) == "elem image":
        return True
    fill = getattr(node, "fill", None)
    if fill is None or getattr(fill, "value", None) is None:
        return False
    return getattr(fill, "alpha", 255) != 0


def _number(value):
    """A number, or nothing. The engine sometimes hands a string or numpy here."""
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
        # Het nulpunt van de gebruiker (gat J12). De server hangt hier
        # `MachineControl.origin` in; zonder dat is er geen nulpunt en
        # verandert er niets aan de plek van het werk.
        self.origin = lambda: None
        # Lag er een hele groep op het klembord? Zie `clipboard_paste`.
        self._klembord_groep = False

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

        with self.elements.undoscope("Draw path"):
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
                f"Unknown shape: {kind}. Choose from {', '.join(sorted(SHAPES))}."
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
        # Tekenen én in een laag zetten binnen dezelfde handeling: een vorm
        # neerzetten is één stap, dus één keer ongedaan maken. Zou het opzoeken
        # van de laag erbuiten vallen, dan haalde de eerste `undo` alleen die
        # laag weg en bleef de vorm staan.
        with self.elements.undoscope(f"Draw {kind}"):
            self.runner.run(self._command(kind, values, fields))
            created = [n for n in self.elements.elems() if id(n) not in before]
            if created:
                self.elements.validate_ids()
                for node in created:
                    self._single_layer(node)
                self._seed_from_memory(before_ops)
        if not created:
            raise DesignError("De engine heeft niets getekend.")

        self.elements.set_emphasis(created)
        self._refresh()
        return {"ids": [n.id for n in created], "type": created[0].type}

    def _single_layer(self, node) -> None:
        """
        Een verse vorm hoort in één laag te vallen, niet in twee — en nooit in
        een laag van een testbord.

        De classificatie van de engine kijkt naar de lijnkleur, en meerdere
        operaties kunnen dezelfde kleur claimen. Dan zit dezelfde rechthoek in
        een snij- én een graveerlaag, en brandt hij twee keer — de tweede keer
        vaak op 100%. Precies de val die eerder bij het testraster toesloeg.
        Een element in meerdere lagen zetten blijft kunnen, maar dan omdat
        iemand daarvoor kiest.

        De lagen van een testbord tellen niet mee als kandidaat. De labellaag
        draagt de standaardkleur van de engine (#0000ff) en staat níét in de
        paletstrook onder het canvas, dus een vorm die daarin belandt is werk
        dat verdwijnt: onzichtbaar in de balk, en gebrand op 80 mm/s @ 30 %
        omdat dat de instelling van een opschrift is. Gemeten: in een document
        waar de gebruiker zijn eigen lagen had weggegooid, viel élke nieuwe
        vorm in "Raster-labels".
        """
        references = [
            reference
            for reference in list(getattr(node, "_references", []))
            if reference.parent is not None
        ]
        eigen = [r for r in references if not self._is_board_layer(r.parent)]
        # Alleen bordlagen? Dan hoort deze vorm daar sowieso niet, en is er ook
        # geen alternatief onder de referenties: alles eraf, en de vorm krijgt
        # via zijn eigen lijnkleur een echte laag.
        houden = eigen[:1]
        for extra in references:
            if extra not in houden:
                extra.remove_node()
        if not houden:
            self._own_layer(node)

    def _own_layer(self, node) -> None:
        """Give a shape without a layer one, on its own stroke colour."""
        kleur = normalise(str(getattr(node, "stroke", "") or "")[:7])
        if kleur is None:
            return
        try:
            # Hetzelfde geheugen als bij het paletvakje (besluit B2): een verse
            # laag begint op wat deze kleur op deze machine eerder deed.
            onthouden = None
            try:
                onthouden = self.color_memory(kleur)
            except Exception:
                pass
            layer = self.layer_for_color(kleur, onthouden)
        except DesignError:
            return
        self._operation(layer["id"]).add_reference(node)

    def _is_board_layer(self, operation) -> bool:
        """
        Een laag die bij een testbord hoort in plaats van bij de gebruiker.

        Twee soorten: de cellen (elk hun eigen sweep-instelling) en de gedeelde
        labellaag waar de opschriften van alle borden in gaan.
        """
        if operation is None:
            return False
        if getattr(operation, "label", None) == LABEL_LAYER:
            return True
        return self._is_grid_cell(operation, getattr(operation, "id", "") or "")

    def _command(self, kind: str, v: dict, fields: dict) -> str:
        if kind == "rect":
            regel = (
                f"rect {_mm(v['x_mm'])} {_mm(v['y_mm'])} "
                f"{_mm(v['width_mm'])} {_mm(v['height_mm'])}"
            )
            # Afgeronde hoeken meteen bij het tekenen: het commando heeft er
            # `-x`/`-y` voor, en de engine doet de rest. Eén getal, want een
            # hoek met twee verschillende radii is een vormgeversding waar aan
            # een machine niemand om vraagt.
            radius = fields.get("corner_radius_mm")
            if radius not in (None, ""):
                maat = _positive(radius, "corner_radius_mm")
                halve = min(v["width_mm"], v["height_mm"]) / 2
                if maat > halve:
                    raise DesignError(
                        f"A corner radius of {maat:g} mm does not fit in a rectangle "
                        f"of {v['width_mm']:g}×{v['height_mm']:g} mm. At most "
                        f"{halve:g} mm.",
                        code="draw.radiusTooBig",
                    )
                regel += f" -x {_mm(maat)} -y {_mm(maat)}"
            return regel
        if kind == "circle":
            return f"circle {_mm(v['cx_mm'])} {_mm(v['cy_mm'])} {_mm(v['r_mm'])}"
        if kind == "ellipse":
            return f"ellipse {_mm(v['cx_mm'])} {_mm(v['cy_mm'])} {_mm(v['rx_mm'])} {_mm(v['ry_mm'])}"
        if kind == "line":
            return f"line {_mm(v['x1_mm'])} {_mm(v['y1_mm'])} {_mm(v['x2_mm'])} {_mm(v['y2_mm'])}"
        text = str(fields.get("text") or "").strip()
        if not text:
            raise DesignError("Text cannot be empty.", code="draw.emptyText")
        if '"' in text:
            raise DesignError(
                "Quotation marks in text are not supported yet.",
                code="draw.quotesInText",
            )
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
            raise DesignError(
                "This element is not editable text.", code="draw.notText"
            )
        registry = getattr(self.kernel.root, "fonts", None)
        if registry is None:
            raise DesignError("No font support available.", code="draw.noFonts")

        text = node.mktext
        with self.elements.undoscope("Change text"):
            if fields.get("text") is not None:
                new = str(fields["text"]).strip()
                if not new:
                    raise DesignError("Text cannot be empty.", code="draw.emptyText")
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
                        f"Alignment has to be one of {', '.join(self.ALIGNMENTS)}."
                    )
                node.mkalign = align
            registry.update_linetext(node, text)
        self.elements.validate_ids()
        self._refresh()
        return {"id": node.id, "text": node.mktext}

    def update_line(self, element_id: str, **fields) -> dict:
        """Move one end of a line, without drawing it again."""
        from meerk40t.core.units import UNITS_PER_MM

        node = self._nodes([element_id])[0]
        if node.type != "elem line":
            raise DesignError("This element is not a line.", code="draw.notALine")

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

        with self.elements.undoscope("Adjust line"):
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
                f"Unknown alignment: {mode}. Choose from {', '.join(self.ALIGNMENTS_2D)}."
            )
        nodes = self._nodes(element_ids)
        if len(nodes) < 2:
            raise DesignError("Uitlijnen heeft minstens twee elementen nodig.")
        self.elements.set_emphasis(nodes)
        with self.elements.undoscope("Align"):
            self.runner.run(f"align {mode}")
        self._refresh()
        return {"aligned": [n.id for n in nodes], "mode": mode}

    def group(self, element_ids) -> dict:
        nodes = self._nodes(element_ids)
        if len(nodes) < 2:
            raise DesignError("Groeperen heeft minstens twee elementen nodig.")
        self.elements.set_emphasis(nodes)
        with self.elements.undoscope("Group"):
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
            raise DesignError(
                "This selection is not in a group.", code="draw.notInGroup"
            )
        self.elements.set_emphasis(groups)
        with self.elements.undoscope("Ungroup"):
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
            raise DesignError("The mirror axis has to be 'horizontal' or 'vertical'.")
        nodes = self._nodes(element_ids)
        self.elements.set_emphasis(nodes)
        factors = "-1 1" if axis == "horizontal" else "1 -1"
        with self.elements.undoscope("Mirror"):
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
                f"Unknown operation: {operation}. Choose from {', '.join(self.BOOLEAN)}."
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
                f"{operation} yielded nothing — do the shapes actually overlap?",
                code="draw.booleanEmpty",
            )
        self.elements.validate_ids()
        self.elements.set_emphasis(created)
        self._refresh()
        return {"ids": [n.id for n in created], "operation": operation}

    EFFECTS = {"hatch": "effect-hatch", "wobble": "effect-wobble"}

    def offset(self, element_ids, distance_mm) -> dict:
        """A parallel contour at a distance — for kerf compensation or a border."""
        distance = _finite(distance_mm, "distance_mm")
        if distance == 0:
            raise DesignError("An offset of zero yields nothing.")
        nodes = self._nodes(element_ids)
        before = {id(n) for n in self.elements.elems()}
        self.elements.set_emphasis(nodes)
        with self.elements.undoscope("Offset"):
            self.runner.run(f"offset {distance:.4f}mm")
        created = [n for n in self.elements.elems() if id(n) not in before]
        if not created:
            raise DesignError("The engine made no offset.", code="draw.noOffset")
        self.elements.validate_ids()
        self.elements.set_emphasis(created)
        self._refresh()
        return {"ids": [n.id for n in created], "distance_mm": distance}

    def corners(self, element_ids, style: str, size_mm) -> dict:
        """
        Hoeken afronden of afschuinen.

        Twee wegen, en welke het is bepaalt de engine, niet wij:

        - **Afronden van een rechthoek** zet `rx`/`ry` op de knoop. Hij blíjft
          een rechthoek: breedte en hoogte blijven werken, de radius is later te
          wijzigen, en de SVG-rondgang klopt. De engine tekent dat al.
        - **Afschuinen, of afronden van iets anders**, wordt geometrie die wij
          maken, en het resultaat is een pad. Dat is eenrichting: een pad heeft
          geen breedte- en hoogteveld meer. De engine bepaalt dat een `elem rect`
          altijd rónd afloopt, dus een afgeschuinde rechthoek kán daar niet
          blijven — zie de kop van `corners.py`.
        """
        from meerk40t.core.geomstr import Geomstr
        from meerk40t.svgelements import Matrix

        from .corners import STYLES, CornerError, corner_geometry

        if style not in STYLES:
            raise DesignError(
                f"Onbekende hoekstijl: {style}. Kies 'round' of 'chamfer'."
            )
        maat = _positive(size_mm, "size_mm")
        nodes = self._nodes(element_ids)
        units = self._units_per_mm()

        afgerond, paden, overgeslagen = [], [], 0
        with self.elements.undoscope("Corners"):
            for node in nodes:
                if style == "round" and str(getattr(node, "type", "")) == "elem rect":
                    node.rx = node.ry = maat * units
                    # Een rauwe toekenning meldt niets aan de knoop, dus hij
                    # draagt anders zijn oude omhullende — dezelfde valkuil als
                    # bij `grid`/`radial` (zie CLAUDE.md).
                    vergeet = getattr(node, "set_dirty_bounds", None)
                    if vergeet is not None:
                        vergeet()
                    node.altered()
                    afgerond.append(node.id)
                    continue
                geom = node.as_geometry()
                try:
                    nieuw, _gewijzigd, gemist = corner_geometry(
                        geom, maat * units, style
                    )
                except CornerError as e:
                    raise DesignError(str(e), code=getattr(e, "code", None)) from e
                overgeslagen += gemist
                # `replace_node` geeft de níeuwe knoop terug; de oude is daarna
                # losgekoppeld en zijn id zegt niets meer.
                paden.append(
                    node.replace_node(
                        type="elem path",
                        geometry=nieuw,
                        matrix=Matrix(),
                        stroke=getattr(node, "stroke", None),
                        fill=getattr(node, "fill", None),
                    )
                )

        self.elements.validate_ids()
        self._refresh()
        return {
            "rounded": afgerond,
            "paths": [n.id for n in paden],
            "skipped": overgeslagen,
            "style": style,
            "size_mm": maat,
        }

    def simplify(self, element_ids) -> dict:
        """Fewer nodes, same shape — saves time on complicated paths."""
        nodes = self._nodes(element_ids)
        self.elements.set_emphasis(nodes)
        with self.elements.undoscope("Simplify"):
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
                f"Unknown effect: {effect}. Choose from {', '.join(sorted(self.EFFECTS))}."
            )
        nodes = self._nodes(element_ids)
        self.elements.set_emphasis(nodes)
        with self.elements.undoscope(f"Add {effect}"):
            self.runner.run(command)
        self.elements.validate_ids()
        self._refresh()
        return {"effect": effect, "ids": [n.id for n in nodes]}

    def delete(self, element_ids) -> dict:
        nodes = self._nodes(element_ids)
        self.elements.set_emphasis(nodes)
        with self.elements.undoscope("Delete"):
            # `delete` alleen bestaat niet op de basiscontext; `element delete`
            # werkt op de nadruk-selectie.
            self.runner.run("element delete")
        self._refresh()
        return {"removed": [n.id for n in nodes]}

    def duplicate(self, element_ids) -> dict:
        nodes = self._nodes(element_ids)
        before = {id(n) for n in self.elements.elems()}
        self.elements.set_emphasis(nodes)
        with self.elements.undoscope("Duplicate"):
            self.runner.run("copy")
        created = [n for n in self.elements.elems() if id(n) not in before]
        if not created:
            raise DesignError("De engine heeft niets gedupliceerd.")
        self.elements.validate_ids()
        self.elements.set_emphasis(created)
        self._refresh()
        return {"ids": [n.id for n in created]}

    # ----------------------------------------------------------------- klembord
    #
    # De engine heeft een compleet klembord (`core/elements/clipboard.py`:
    # `clipboard copy | cut | paste | clear`). Wij zetten alleen de nadruk en
    # lezen de stand terug, zodat het klembord van de engine de enige waarheid
    # blijft — ook als iemand er tegelijk via de console aan zit.
    #
    # Eén ding vangen we wél af: `clipboard paste` stopt méér dan één vorm in
    # een nieuwe groep ("Group", id "Copy"). Plakken dat stilzwijgend groepeert
    # is een verrassing die je pas merkt als je één vorm wil verslepen en er
    # drie meekomen. Hebben we zelf om die groep gevraagd, dan halen we hem er
    # weer af. Wie een échte groep kopieerde, plakt één knoop en houdt zijn
    # groep — de engine wikkelt alleen bij meer dan één.

    def _clipboard_nodes(self) -> list:
        buffer = getattr(self.elements, "_clipboard", None) or {}
        sleutel = getattr(self.elements, "_clipboard_default", "0")
        return list(buffer.get(sleutel) or [])

    def _clipboard_bounds(self):
        from meerk40t.core.units import UNITS_PER_MM

        vakken = [n.bounds for n in self._clipboard_nodes() if getattr(n, "bounds", None)]
        if not vakken:
            return None
        x0 = min(v[0] for v in vakken) / UNITS_PER_MM
        y0 = min(v[1] for v in vakken) / UNITS_PER_MM
        x1 = max(v[2] for v in vakken) / UNITS_PER_MM
        y1 = max(v[3] for v in vakken) / UNITS_PER_MM
        return {
            "x_mm": x0,
            "y_mm": y0,
            "width_mm": max(0.0, x1 - x0),
            "height_mm": max(0.0, y1 - y0),
        }

    def clipboard_state(self) -> dict:
        return {"count": len(self._clipboard_nodes()), "bounds": self._clipboard_bounds()}

    def _hele_groep(self, nodes) -> bool:
        """
        Is dit precies één volledige groep?

        Dat bepaalt of het omhulsel dat de engine bij het plakken maakt mag
        blijven staan. Wie een groep kopieert, verwacht een groep terug; wie
        drie losse vormen kopieert, verwacht drie losse vormen.
        """
        ouders = {getattr(n, "parent", None) for n in nodes}
        if len(ouders) != 1:
            return False
        ouder = ouders.pop()
        if ouder is None or getattr(ouder, "type", None) != "group":
            return False
        return len(list(ouder.children)) == len(nodes)

    def clipboard_copy(self, element_ids) -> dict:
        nodes = self._nodes(element_ids)
        self._klembord_groep = self._hele_groep(nodes)
        self.elements.set_emphasis(nodes)
        self.runner.run("clipboard copy")
        return self.clipboard_state()

    def clipboard_cut(self, element_ids) -> dict:
        nodes = self._nodes(element_ids)
        self._klembord_groep = self._hele_groep(nodes)
        self.elements.set_emphasis(nodes)
        # De engine zet zelf een undoscope om het verwijderen.
        self.runner.run("clipboard cut")
        self._refresh()
        return self.clipboard_state()

    def clipboard_paste(self, x_mm=None, y_mm=None, offset_mm: float = 5.0) -> dict:
        """
        Plakken, met of zonder doelplek.

        Zonder `x_mm`/`y_mm` komt het werk `offset_mm` naast het origineel te
        liggen: precies op elkaar plakken ziet eruit als "nothing happened", en
        dan sleep je per ongeluk het origineel weg. Mét een doelplek is dat de
        linkerbovenhoek van wat er geplakt wordt — dat is wat "plakken hier" in
        een rechterklikmenu belooft.
        """
        aantal = len(self._clipboard_nodes())
        if not aantal:
            raise DesignError("Het klembord is leeg.")
        doos = self._clipboard_bounds()
        if x_mm is not None and y_mm is not None and doos is not None:
            dx = _finite(x_mm, "x_mm") - doos["x_mm"]
            dy = _finite(y_mm, "y_mm") - doos["y_mm"]
        else:
            dx = dy = float(offset_mm)

        before = {id(n) for n in self.elements.elems()}
        groepen_voor = {id(n) for n in self._alle_groepen()}
        self.runner.run(f"clipboard paste -x {_mm(dx)} -y {_mm(dy)}")
        geplakt = [n for n in self.elements.elems() if id(n) not in before]
        if not geplakt:
            raise DesignError("De engine heeft niets geplakt.")

        # Dezelfde valstrik als bij `grid`/`radial`: `clipboard paste` schuift
        # zijn kopieën met een rauwe `node.matrix *= matrix`, en die toekenning
        # meldt niets aan de node. De omhullende bleef dus op de plek van het
        # origineel staan terwijl de vorm elders getekend werd — je klikt de
        # kopie aan en de handvatten verschijnen om het origineel. Zie de
        # upstream-lijst in CLAUDE.md.
        for node in geplakt:
            marker = getattr(node, "set_dirty_bounds", None)
            if marker is not None:
                marker()

        # De omhullende groep die de engine er zelf om zette, weer weghalen —
        # met de eigen `ungroup` van de engine, zodat de boom op dezelfde manier
        # herbouwd wordt als wanneer de gebruiker het zelf doet. Tenzij er een
        # hele groep gekopieerd werd: dan is dat omhulsel precies wat je terug
        # wilde hebben.
        if aantal > 1 and not getattr(self, "_klembord_groep", False):
            wikkels = [
                n
                for n in self._alle_groepen()
                if id(n) not in groepen_voor and getattr(n, "id", None) == "Copy"
            ]
            if wikkels:
                self.elements.set_emphasis(wikkels)
                self.runner.run("ungroup")

        self.elements.validate_ids()
        self.elements.set_emphasis(geplakt)
        self._refresh()
        return {"ids": [n.id for n in geplakt], "count": len(geplakt)}

    def _alle_groepen(self) -> list:
        return [n for n in self.elements.elem_branch.flat() if n.type == "group"]

    def _nodes(self, element_ids):
        from .edits import _ids

        nodes = []
        for node_id in _ids(element_ids):
            node = self.elements.find_node(node_id)
            if node is None:
                raise DesignError(f"Element {node_id} does not exist (any more).")
            nodes.append(node)
        return nodes

    # ------------------------------------------------------------- operations

    # Een laag zonder naam kreeg van de engine een label als
    # "Cut defaultmm/s @default #ff0000" — machinetaal op de plek waar je je
    # eigen werk moet herkennen.
    LAYER_NAMES = {
        "cut": "Cut",
        "engrave": "Engrave",
        "raster": "Raster",
        "image": "Image",
        "dots": "Dots",
    }

    def create_operation(self, kind: str, label=None, speed=None, power_percent=None) -> dict:
        command = OPERATIONS.get(kind)
        if command is None:
            raise DesignError(
                f"Unknown layer type: {kind}. Choose from {', '.join(sorted(OPERATIONS))}."
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
        with self.elements.undoscope("Add layer"):
            self._ensure_colors()
            self.runner.run(" ".join(parts))
        created = [o for o in self.elements.ops() if id(o) not in before]
        if not created:
            raise DesignError("The engine created no layer.", code="draw.noLayer")
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
            raise DesignError("Give one of the two: 'direction' or 'index'.")
        if direction is not None and direction not in ("up", "down"):
            raise DesignError("direction has to be 'up' or 'down'.")
        operation = self._operation(operation_id)
        parent = operation.parent
        if parent is None:
            raise DesignError("This layer is not in the operations tree.")

        siblings = list(parent.children)
        try:
            here = siblings.index(operation)
        except ValueError:  # pragma: no cover - de boom is dan al inconsistent
            raise DesignError("This layer is not in its own branch.")

        # De lijst telt in lagen, wij tellen in kinderen van `branch ops`. Voor
        # de gebruiker is "plek 3" de derde láág, niet de derde knoop; met een
        # testraster of een lege standaardlaag ertussen is dat niet hetzelfde
        # getal. Beide manieren rekenen daarom in deze lijst.
        plain = [node for node in siblings if self._plain_layer(node)]

        if direction is not None:
            step = -1 if direction == "up" else 1
            # Eén stap is één zichtbare laag verder, niet één knoop. Stapte dit
            # over knopen, dan schoof de laag langs een onzichtbare buur en
            # bleef het scherm hetzelfde — de fout die deze reparatie oplost.
            try:
                spot = plain.index(operation)
            except ValueError:
                # Geen zichtbare laag (een rastercel): dan telt de oude weg.
                spot = None
            if spot is None:
                target = here + step
            else:
                buur = spot + step
                if not 0 <= buur < len(plain):
                    return {"id": operation_id, "moved": False, "index": here}
                target = siblings.index(plain[buur])
            below = direction == "down"
        else:
            try:
                wanted = int(index)
            except (TypeError, ValueError):
                raise DesignError("index has to be a whole number.")
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

        with self.elements.undoscope("Reorder layers"):
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
        """
        Een laag zoals de gebruiker hem ziet staan.

        Drie eisen, en de derde is degene die ontbrak. Het moet een bewerking
        zijn, het mag geen cel van een testraster zijn, én hij moet in beeld
        staan: **een verse boom bevat ruim tweehonderd lege standaardlagen** die
        de engine achter de hand houdt, en `DesignReader` laat die weg — een
        bewerking zonder vormen is geen laag, tenzij de gebruiker hem net zelf
        aanmaakte (`user_operations`).

        Zonder die derde eis rekende het verschuiven in een lijst van
        tweehonderd terwijl het paneel er twee toonde. Wat je dan ziet: op
        "later branden" drukken verplaatst de laag netjes één plek — langs een
        onzichtbare standaardlaag. De API meldt `moved: true`, de volgorde op
        het scherm verandert niet, en slepen landt op een plek die niet bestaat
        in de lijst waaruit je sleepte. Gemeten met twee lagen: tien lege
        `op cut`-lagen ertussen, elke druk op de knop een schijnbeweging.
        """
        if not str(getattr(node, "type", "")).startswith("op "):
            return False
        if self._is_grid_cell(node, getattr(node, "id", "") or ""):
            return False
        # Dezelfde regel als in `DesignReader.snapshot`: vormen erin, of door
        # de gebruiker net aangemaakt. Blijven die twee uit elkaar lopen, dan
        # loopt het verschuiven weer mis op lagen die niemand ziet.
        if getattr(node, "children", None):
            return True
        return (getattr(node, "id", "") or "") in self.user_operations

    def sort_operations(self) -> dict:
        """
        Graveren vóór snijden, in één handeling (gat L2).

        LightBurn heeft hier `Sort Cuts Last` voor, en dat is één klik voor de
        duurste fout die er is: het werkstuk valt uit het vel voordat het
        opschrift erop staat. Stabiel sorteren, zodat twee snijlagen hun
        onderlinge volgorde houden — die heeft de gebruiker zelf gekozen.

        Binnen dezelfde soort telt de sterkte mee (gat L7). Twee snijlagen zijn
        niet uitwisselbaar: een lichte scoreerlijn op 5 % en een doorsnede op
        80 % horen in die volgorde, want zodra het werkstuk los is, ligt het
        niet meer stil voor de rest. LightBurn sorteert daar ook op, alleen
        andersom om — hun sterkste gaat vooraan en daarna de Line-lagen naar
        achteren; wij houden één regel aan die op elke soort hetzelfde doet.

        Rastercellen blijven staan waar ze staan: hun volgorde is de sweep.
        """
        parent = self.elements.op_branch
        children = list(parent.children)
        layers = [node for node in children if self._plain_layer(node)]
        if len(layers) < 2:
            return {"sorted": False, "order": [node.id for node in layers]}

        wanted = sorted(
            layers,
            key=lambda node: (
                self.BURN_ORDER.get(str(node.type), 99),
                self._sterkte(node),
            ),
        )
        if wanted == layers:
            return {"sorted": False, "order": [node.id for node in wanted]}

        with self.elements.undoscope("Engrave before cut"):
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

    def _sterkte(self, node) -> float:
        """
        Hoe diep deze laag gaat, als één getal (gat L7).

        Vermogen gedeeld door snelheid maal het aantal passes: dat is de
        energie per millimeter, en het is precies de grootheid waar een
        laseraar op afgaat als hij "zwaarder" zegt. Het is een rangschikking,
        geen natuurkunde — hij hoeft alleen twee lagen van dezelfde soort uit
        elkaar te houden.

        Een laag zonder snelheid of vermogen krijgt 0 en blijft daarmee vooraan
        staan; sorted() is stabiel, dus onderling houden die hun volgorde.
        """
        power = _number(getattr(node, "power", None)) or 0.0
        speed = _number(getattr(node, "speed", None)) or 0.0
        passes = float(_passes_of(node))
        if speed <= 0 or power <= 0:
            return 0.0
        return (power / speed) * max(passes, 1.0)

    # Instellingen die een laag houdt als hij van soort verandert. Bewust niet
    # `dpi`/`overscan`: die horen bij rasteren en zijn op een snijlaag zinloos —
    # de engine geeft de nieuwe laag daar zijn eigen standaard voor.
    TYPE_KEEP = ("label", "speed", "power", "passes", "output", "coolant")

    def change_operation_type(self, operation_id: str, kind: str) -> dict:
        """
        Een snijlaag graveerlaag maken, met de vormen erin (gat L3).

        De engine kent geen "change the type of this operation": het type
        zit in de klasse van de knoop. Wat er wél kan is een nieuwe bewerking
        maken, de referenties verhuizen en de oude weghalen — precies wat je
        met de hand zou doen, maar dan zonder de toewijzingen kwijt te raken.
        Alles binnen één undoscope, dus één keer ongedaan maken zet het terug.
        """
        if kind not in OPERATIONS:
            raise DesignError(
                f"Unknown layer type: {kind}. Choose from {', '.join(sorted(OPERATIONS))}."
            )
        old = self._operation(operation_id)
        if self._is_grid_cell(old, operation_id):
            raise DesignError(
                "This is a cell of a test grid; the kind of operation is the test.",
                code="layer.gridCell",
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

        with self.elements.undoscope("Change layer type"):
            before = {id(o) for o in self.elements.ops()}
            self.runner.run(OPERATIONS[kind])
            gemaakt = [o for o in self.elements.ops() if id(o) not in before]
            if not gemaakt:
                raise DesignError("The engine created no layer.", code="draw.noLayer")
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

    # Methoden die wel geclaimd kunnen worden maar niets aan de machine doen.
    #
    # Gat L8. De engine kent er drie: `gcode_m7` en `gcode_m8` (grbl-only, die
    # schakelen echt iets) en `popup` — "Warnmessage". Die derde stuurt geen
    # enkel signaal naar de laser; hij roept `kernel.yesno`, en dat is buiten de
    # wxPython-GUI een `input()` op stdin (kernel.py:4217). Wij draaien
    # headless, dus dan staat de spoolerthread te wachten op een toets die
    # niemand indrukt — er kijkt niemand naar die terminal, de UI is een
    # browser — of hij valt om met EOFError zodra stdin dicht is.
    #
    # Een schakelaar aanbieden die de job laat hangen is erger dan geen
    # schakelaar. Op een Ruida is `popup` de enige claimbare methode (de andere
    # twee hebben `constraints="grbl"`), en dus is air assist daar niet iets wat
    # wij kunnen beloven. Zie de bevinding bij L8.
    LOZE_COOLANTS = {"popup"}

    def air_assist_supported(self) -> bool:
        """Does the active machine have a command that really switches the blower?"""
        coolant = getattr(getattr(self.kernel, "root", None), "coolant", None)
        device = getattr(self.kernel, "device", None)
        if coolant is None or device is None:
            return False
        try:
            if coolant.get_device_function(device) is None:
                return False
            gekozen = coolant.get_device_coolant(device) or {}
            return str(gekozen.get("id", "")) not in self.LOZE_COOLANTS
        except Exception:  # pragma: no cover - een driver die niet meewerkt
            return False

    # Meer dan 20 mm zakken tussen twee passes is geen snijgang meer maar een
    # verkeerd ingetikt getal, en een Z-as die zo ver wegloopt tikt tegen de kop.
    Z_STEP_LIMIT_MM = 20.0

    def z_step_supported(self) -> bool:
        """
        Kan deze machine de Z-as bewegen tussen twee passes door?

        Twee eisen, en allebei nodig. De driver moet een Z-as **hebben**
        (`supports_z_axis`, een instelling die alleen het GRBL-apparaat kent) en
        er moet een `z_move`-commando geregistreerd staan dat hem beweegt. Op
        een Ruida is er geen van beide: die driver kent het woord niet, dus daar
        hoort dit veld ook niet op het scherm te staan (besluit B11).
        """
        device = getattr(self.kernel, "device", None)
        if device is None or not getattr(device, "supports_z_axis", False):
            return False
        # Dezelfde vraag die de consoleparser stelt, dus hetzelfde antwoord.
        return bool(self.kernel.find("command", "None", "z_move$"))

    def update_operation(self, operation_id: str, **fields) -> dict:
        operation = self._operation(operation_id)
        if self._is_grid_cell(operation, operation_id):
            blocked = sorted(
                k for k, v in fields.items() if v is not None and k not in self.GRID_EDITABLE
            )
            if blocked:
                raise DesignError(
                    "This is a cell of a test grid; speed and power are fixed "
                    f"because they are the test. Only burn-along can be changed "
                    f"({', '.join(blocked)} refused).",
                    code="layer.gridCellValues",
                )
        applied = {}
        with self.elements.undoscope("Change layer"):
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
            if fields.get("z_step_mm") is not None:
                # Zakken per pass: bij dik materiaal snijd je in lagen en gaat de
                # focus elke pass mee naar beneden. De engine kent dit niet — een
                # pass is bij haar een teller op één cutcode-object, en alle
                # passes delen dus letterlijk één settings-dict. Wij bouwen het
                # daarom in het plan op (zie CommandRunner.start_job), en slaan
                # hier alleen op wat de gebruiker koos.
                stap = _finite(fields["z_step_mm"], "z_step_mm")
                if stap and not self.z_step_supported():
                    raise DesignError(
                        "This machine has no Z axis the driver can move, so a step "
                        "per pass would do nothing. Switch the Z axis on at the "
                        "machine, or leave this field empty.",
                        code="layer.noZAxis",
                    )
                if abs(stap) > self.Z_STEP_LIMIT_MM:
                    raise DesignError(
                        f"z_step_mm moet tussen -{self.Z_STEP_LIMIT_MM:g} en "
                        f"{self.Z_STEP_LIMIT_MM:g} mm liggen."
                    )
                # 0 is "uit", niet "nul millimeter zakken": zonder dat verschil
                # zou een uitgezette stap alsnog het gesplitste plan opleveren.
                operation.z_step_mm = stap or None
                applied["z_step_mm"] = operation.z_step_mm
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
                        "This machine has no command for air assist, so a switch "
                        "here would do nothing. Set up at the machine first which "
                        "method drives the blower.",
                        code="layer.noAirAssist",
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

        Kleur is bij ons de identiteit van een laag, dus "the layer of red" is
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
            # Lagen van een testbord tellen niet mee: de cellen omdat hun
            # waarden de proef zíjn, de labellaag omdat hij de blauwe
            # standaardkleur van de engine draagt en dus zomaar de laag "van
            # blauw" zou blijken te zijn.
            if self._is_board_layer(op):
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

        with self.elements.undoscope("Move to layer"):
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
        """
        De kleur waarin nieuw werk getekend wordt, altijd een kleur uit het palet.

        De engine begint op `#0000ff`, en die kleur staat in geen van de tien
        vakjes onder het canvas. Dat leverde een strook op waarin geen enkel
        vakje aan stond terwijl er wél een kleur actief was, en — erger — de
        laag die "of blue" bleek te zijn, was de labellaag van het testraster:
        `Raster-labels`, op 80 mm/s @ 30 %. De onderrand meldde dan doodleuk
        "laag 1 · Raster-labels" als de laag van je volgende vorm.

        We schuiven daarom één keer op naar de eerste paletkleur. Alleen als de
        engine op een kleur staat die het palet niet kent: heeft de gebruiker
        zelf een vakje gekozen, dan blijft die keuze staan.
        """
        try:
            kleur = normalise(str(self.elements.default_stroke.hexrgb))
        except (AttributeError, TypeError, ValueError):
            kleur = None
        palet = {normalise(c) for c in self.PALETTE}
        if kleur is not None and kleur not in palet:
            try:
                return self.set_default_color(self.PALETTE[0])["color"]
            except (AttributeError, DesignError, TypeError, ValueError):
                return kleur
        return kleur

    @staticmethod
    def _valid_color(color) -> str:
        wanted = normalise(color)
        if wanted is None:
            raise DesignError("color has to be a #rrggbb value.")
        return wanted

    def delete_operation(self, operation_id: str) -> dict:
        operation = self._operation(operation_id)
        with self.elements.undoscope("Remove layer"):
            # Alleen de operatie verdwijnt; de elementen zelf blijven staan,
            # want die kunnen in meerdere lagen zitten.
            operation.remove_node()
        self.user_operations.discard(operation_id)
        self._refresh()
        return {"removed": operation_id}

    # Vormen die een binnenkant hebben. Een lijn en een punt hebben er geen, en
    # de engine zou de vulling dan wel zetten maar er nooit iets mee doen — een
    # knop die aangaat en niets doet.
    FILLABLE = ("elem rect", "elem ellipse", "elem path", "elem polyline")

    def fill(self, element_ids, filled: bool = True, color=None) -> dict:
        """
        Een vorm een vlak geven, of het weer weghalen.

        Waarom dit nodig is: onze rasteraar vult wat een `fill` heeft en trekt
        alleen een lijn om wat er geen heeft (`rasterizer.py`). Een vierkant dat
        je in OpenKerf tekent heeft er geen, dus in een rasterlaag brandde het
        zijn omtrek. Gemeten op een beeld van 100×100 pixels: 8 % zwart vóór,
        boven 90 % erna.

        Let op bij het lezen van een schatting: de **tijd** verandert hier niet
        van. Een rasterlaag scant de omtrekbox regel voor regel, gevuld of niet
        — gemeten op een vierkant van 30 mm: 123,7 s in beide gevallen. Alleen
        de uitkomst verschilt, en dat is precies waarom een lege rasterlaag zo
        makkelijk over het hoofd te zien is.

        De kleur volgt standaard de lijn van de vorm zelf. In MeerK40t ís de
        kleur waar de classificatie op werkt; een vulling in een andere kleur kan
        de vorm bij een volgende classificatie in een andere laag laten belanden
        dan zijn eigen lijn.
        """
        nodes = self._nodes(element_ids)
        wanted = self._valid_color(color) if color is not None else None

        kan = [n for n in nodes if str(getattr(n, "type", "")) in self.FILLABLE]
        skipped = len(nodes) - len(kan)
        filled_count = 0
        cleared = 0
        with self.elements.undoscope("Fill" if filled else "Remove fill"):
            for node in kan:
                self.elements.set_emphasis([node])
                if not filled:
                    self.runner.run("fill none")
                    cleared += 1
                    continue
                kleur = wanted or self._shape_color(node)
                self.runner.run(f"fill {kleur}")
                filled_count += 1
        self.elements.set_emphasis(nodes)
        self._refresh()
        return {
            "ids": [n.id for n in nodes],
            "filled": filled_count,
            "cleared": cleared,
            "skipped": skipped,
        }

    def _shape_color(self, node) -> str:
        """The stroke colour of the shape, or else the colour for new work."""
        stroke = getattr(node, "stroke", None)
        hex_value = getattr(stroke, "hexrgb", None) or getattr(stroke, "hex", None)
        if hex_value:
            return str(hex_value)[:7]
        return self.default_color() or "#000000"

    def single_layer(self, element_ids, kind: str = "cut", operation_id=None) -> dict:
        """
        Alles uit de selectie in één laag, en in geen enkele andere.

        Wat een import kost zonder deze handeling: een tekening komt binnen in
        de laag die de engine erbij vindt — bij een zwarte lijn is dat een
        rasterlaag, want `classify_black_as_raster` staat aan — en wie het wil
        snijden, gooit eerst de lagen weg die hij niet wil, maakt een snijlaag
        en wijst alles opnieuw toe.

        Het losmaken is de kern, niet het toewijzen. Een element mag in meerdere
        lagen zitten (operaties houden verwijzingen, geen elementen), dus alleen
        toewijzen laat de vorm in zijn oude laag staan en brandt hem twee keer.

        Dit is hetzelfde verplaatsen als `paint`, met een ander adres: `paint`
        vraagt om een **kleur** (de strook onder het canvas), dit om een
        **soort**. Dat verschil is het hele punt — "dit moet gesneden worden" is
        wat iemand bedoelt, en welk vakje in de strook de snijlaag is, weet hij
        niet. De lijnkleur gaat om dezelfde reden als daar mee: in MeerK40t is
        de lijnkleur waar de classificatie op werkt, dus zonder dat springt de
        vorm bij een volgende classificatie terug naar zijn oude laag.
        """
        from meerk40t.svgelements import Color
        nodes = self._nodes(element_ids)

        if operation_id is not None:
            doel = self._operation(operation_id)
            created = False
        else:
            wanted = _OPERATION_TYPES.get(kind)
            if wanted is None:
                raise DesignError(
                    f"Unknown layer type: {kind}. Choose from {', '.join(sorted(OPERATIONS))}."
                )
            bestaand = [
                op
                for op in self.elements.ops()
                if str(op.type) == wanted and not self._is_board_layer(op)
            ]
            created = not bestaand
            doel = (
                bestaand[0]
                if bestaand
                else self._operation(self.create_operation(kind)["id"])
            )

        kleur = getattr(doel, "color", None)
        assigned = 0
        removed = 0
        with self.elements.undoscope("Into one layer"):
            for node in nodes:
                # De knoop weet zelf in welke lagen hij hangt; dat is korter dan
                # alle lagen aflopen, en het is hoe `paint` het ook doet.
                for reference in list(getattr(node, "_references", [])):
                    if reference.parent is None:
                        continue
                    if reference.parent is doel:
                        continue
                    reference.remove_node()
                    removed += 1
                if not any(getattr(c, "node", None) is node for c in doel.children):
                    doel.add_reference(node)
                    assigned += 1
                if kleur is not None and hasattr(node, "stroke"):
                    node.stroke = Color(kleur)
                    # Zoals de engine het in `element_stroke` doet: geen
                    # altered(), want dat gooit de gecachete geometrie weg.
                    node.translated(0, 0)
        self.elements.signal("element_property_reload", nodes)
        self.elements.set_emphasis(nodes)
        self._refresh()
        return {
            "operation_id": doel.id,
            "type": str(doel.type),
            "assigned": assigned,
            "removed": removed,
            "created": created,
        }

    def prune_operations(self) -> dict:
        """
        Lege lagen weg.

        Een leeg project heeft er twaalf voor je iets gedaan hebt — de engine
        maakt bij het opstarten een rasterlaag, twee graveerlagen en negen
        snijlagen aan, één per palettekleur. Wie een tekening indeelt, houdt
        daar de helft van over als lege regels in de lijst.

        Een laag met alleen dode verwijzingen telt als leeg: na het splitsen van
        een pad houdt een laag een verwijzing naar het verdwenen origineel, en
        die laag stelt niets meer voor. Lagen van een testbord blijven staan,
        ook leeg: die horen bij een bord en gaan er als geheel uit.
        """
        levend = {id(node) for node in self.elements.elems()}

        def heeft_werk(operation) -> bool:
            return any(
                id(getattr(child, "node", None)) in levend
                for child in operation.children
                if str(getattr(child, "type", "")) == "reference"
            ) or any(
                str(getattr(child, "type", "")) != "reference"
                for child in operation.children
            )

        doomed = [
            op
            for op in self.elements.ops()
            if str(op.type).startswith("op ")
            and not self._is_board_layer(op)
            and not heeft_werk(op)
        ]
        if not doomed:
            return {"removed": 0, "ids": []}

        ids = [op.id for op in doomed]
        with self.elements.undoscope("Clear out empty layers"):
            for op in doomed:
                op.remove_node()
        for operation_id in ids:
            self.user_operations.discard(operation_id)
        self._refresh()
        return {"removed": len(ids), "ids": ids}

    def delete_all_operations(self) -> dict:
        """
        Alle gewone lagen in één handeling weg.

        Per laag kost dat drie klikken (uitklappen, verwijderen, bevestigen), en
        wie een geïmporteerde SVG met tien kleuren opnieuw wil indelen, klikt
        dus dertig keer. Hier is het één keer, met dezelfde belofte als bij één
        laag: **de vormen blijven staan.** Ze zitten daarna in geen enkele laag
        en het canvas tekent ze gestippeld — zichtbaar werk zonder bestemming,
        precies wat je wil zien voordat je opnieuw indeelt.

        Lagen van een testraster tellen niet mee: die horen bij één bord en
        gaan er als geheel uit ("Remove the grid from the design"). Ze los
        weggooien zou een half testresultaat achterlaten — en dat gold ook voor
        de labellaag, die hier wél sneuvelde: de opschriften en het randkader
        van elk bord bleven achter zonder laag en brandden dus niet meer, aan
        een bord waar je verder niets aan zag.
        """
        doomed = [
            op
            for op in self.elements.ops()
            if str(op.type).startswith("op ") and not self._is_board_layer(op)
        ]
        if not doomed:
            raise DesignError("There is no layer to throw away.")
        ids = [op.id for op in doomed]
        with self.elements.undoscope("Remove all layers"):
            for op in doomed:
                op.remove_node()
        for operation_id in ids:
            self.user_operations.discard(operation_id)
        self._refresh()
        # Het aantal vormen erbij, want dat is de belofte: die staan er nog.
        return {"removed": ids, "kept_elements": sum(1 for _ in self.elements.elems())}

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
        """The first palette colour not in use yet, otherwise in order."""
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
            raise DesignError("color has to be a #rrggbb value.")
        operation.color = Color(text)
        return text

    def _is_grid_cell(self, operation, operation_id: str) -> bool:
        """The same verification as the snapshot: id and settings both have to match."""
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
            raise DesignError(f"Layer {operation_id} does not exist (any more).")
        if not str(node.type).startswith(("op ", "effect ")):
            raise DesignError(f"{operation_id} is not a layer.")
        return node

    def fonts(self) -> list[dict]:
        """
        Beschikbare vectorfonts.

        De Hershey-plugin registreert zowel zijn eigen fonts als de systeem-TTF's;
        namen die met een punt beginnen zijn verborgen systeemfonts.

        Bestanden die er niet meer zijn vallen af. De engine houdt zijn lijst in
        een cache die een verwijderd bestand niet opmerkt, en zo'n regel kan
        alleen maar mislukken: de kiezer toont hem, haalt het bestand op voor
        het voorbeeld en krijgt een 409 terug. Gemeten met twee weggegooide
        fonts — twee rijen in de lijst, twee mislukte verzoeken, en geen woord
        op het scherm over wat er aan de hand was.
        """
        from pathlib import Path

        registry = getattr(self.kernel.root, "fonts", None)
        if registry is None:
            return []
        found = []
        for entry in registry.available_fonts() or []:
            path = entry[0] if len(entry) > 0 else None
            display = entry[1] if len(entry) > 1 else None
            if not path or not display or str(display).startswith("."):
                continue
            # Alleen absolute paden toetsen. De engine zet zijn eigen
            # Hershey-fonts als kale naam in de lijst (`meerk40t.jhf`) en die
            # zijn wel degelijk bruikbaar — dat is zelfs het font waarmee wij
            # de opschriften op een testbord zetten.
            plek = Path(str(path))
            if plek.is_absolute() and not plek.is_file():
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
            "engine": self.engine_report(),
        }

    def engine_report(self) -> dict:
        """
        Wat déze engine met een soort laag kan.

        Nu één ding: rasteren. Zonder de rasteraar komt een rasterlaag blanco
        uit de machine (zie `raster_supported`), en dat mag geen verrassing zijn
        die je pas ná het branden ontdekt.
        """
        from .testgrid import raster_supported

        return {"raster": raster_supported(self.kernel)}

    # Een halve millimeter speling. Precies op de rand liggen is geen fout —
    # dat is een vorm die het vel vult — en meetruis in de omhullende mag geen
    # rode rand opleveren op werk dat gewoon past.
    RAND_SPELING = 0.5

    def bed_mm(self) -> tuple[float, float] | None:
        """The bed size of the active machine in millimetres."""
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

    # ------------------------------------------- gebruikersoorsprong (J12)

    @contextmanager
    def verschoven(self, oorsprong):
        """
        Het hele ontwerp even opzij zetten, zolang het de machine in gaat.

        Dit is de hele werking van het nulpunt (gat J12): wat je op 0,0 tekent
        brandt op het nulpunt, en alles wat je eromheen tekende schuift mee.
        De tekening zelf verandert niet — na afloop staat elke vorm weer op de
        coördinaten die in het paneel stonden, want anders zou één druk op
        starten je ontwerp verplaatsen.

        Bewust niet via het console-commando `translate`: dat werkt in een
        eigen undoscope, en dan levert elke start twee stappen in de
        ongedaan-geschiedenis op die de gebruiker nooit heeft gemaakt. De
        matrix rechtstreeks verzetten is precies wat dat commando doet, zonder
        die bijwerking.

        De verschuiving wordt in een `finally` teruggedraaid: gaat het plannen
        stuk, dan mag het ontwerp niet verschoven achterblijven.
        """
        dx = float((oorsprong or {}).get("x_mm") or 0.0)
        dy = float((oorsprong or {}).get("y_mm") or 0.0)
        if not dx and not dy:
            yield False
            return
        units = self._units_per_mm()
        verzet = self._verzet(dx * units, dy * units)
        try:
            yield True
        finally:
            self._verzet(-dx * units, -dy * units, verzet)

    def _verzet(self, dx: float, dy: float, nodes=None) -> list:
        """Move every shape along by a fixed amount, in engine units."""
        from meerk40t.svgelements import Matrix

        matrix = Matrix.translate(dx, dy)
        verzet = []
        for node in list(nodes if nodes is not None else self.elements.elems()):
            try:
                node.matrix *= matrix
                node.translated(dx, dy)
            except AttributeError:
                # Een knoop zonder matrix (die bestaan) laten we met rust; hij
                # staat dan op zijn eigen plek en dat melden we niet als fout.
                continue
            verzet.append(node)
        return verzet

    def bounds_report(self, sheet=None) -> dict:
        """
        Wat er buiten het bed of buiten het vel valt (gat C2).

        Twee verschillende fouten, en het verschil telt: buiten het bed kán de
        machine niet komen — daar loopt de kop tegen zijn eindaanslag of slaat
        de driver de beweging over. Buiten het vel kán de machine wel komen,
        maar daar ligt geen materiaal; dan brandt hij in de rooster of in je
        werkblad. Allebei kosten ze materiaal en tijd, en allebei zijn ze nu
        alleen te zien door goed te kijken.

        De id's die hieruit komen moeten dezelfde zijn als die in `/api/design`,
        anders kan de weergave in de pre-flight er niets mee — en dan doet die
        de meting alsnog over. `validate_ids()` deelt ze uit; wie het overslaat
        krijgt lege strings terug voor alles wat uit een SVG kwam (gemeten).
        """
        self.elements.validate_ids()
        units = self._units_per_mm()
        bed = self.bed_mm()
        vel = None
        if sheet and sheet.get("width_mm") and sheet.get("height_mm"):
            vel = (float(sheet["width_mm"]), float(sheet["height_mm"]))

        # Het nulpunt telt wél mee voor het bed en níet voor het vel (gat J12).
        #
        # Dat is geen slordigheid maar wat het nulpunt betekent: je legt hem op
        # de hoek van het materiaal dat op het bed ligt. Het vel schuift dus mee
        # — het werk blijft er net zo op liggen als je het tekende — terwijl het
        # bed blijft waar het is, want dat is de machine. Zonder dit onderscheid
        # zou elk gezet nulpunt een "buiten het vel"-waarschuwing opleveren, en
        # alarmbellen die altijd afgaan leert iedereen negeren (zie C2).
        # Het canvas tekent daarom ook het vel op zijn nieuwe plek.
        nulpunt = self.origin() or None
        ox = float((nulpunt or {}).get("x_mm") or 0.0)
        oy = float((nulpunt or {}).get("y_mm") or 0.0)

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
            if bed and self._buiten(a + ox, b + oy, c + ox, d + oy, bed):
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
        # Waar het werk terechtkomt zodra er een nulpunt staat. Zonder dit getal
        # zou de pre-flight een kader tonen op de plek waar je tekende, terwijl
        # de machine ergens anders brandt — en dat is precies de fout die het
        # nulpunt moet voorkomen.
        gebrand = werk
        if werk and (ox or oy):
            gebrand = {
                **werk,
                "x_mm": round(werk["x_mm"] + ox, 2),
                "y_mm": round(werk["y_mm"] + oy, 2),
            }

        return {
            "bed": None if not bed else {"width_mm": round(bed[0], 2), "height_mm": round(bed[1], 2)},
            "sheet": None if not vel else {"width_mm": vel[0], "height_mm": vel[1]},
            "work": werk,
            "origin": nulpunt,
            "burns_at": gebrand,
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
        """The old route: build the whole plan and add up the duration from it."""
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
        """Burn time and travel time from the element tree, without a plan."""
        seconds = 0.0
        pieces = 0
        rapid = self._rapid_mm_s()
        rastert = self.engine_report()["raster"]
        for operation in self.elements.ops():
            kind = str(operation.type)
            if not kind.startswith("op ") or not getattr(operation, "output", True):
                continue
            # Geen tijd rekenen voor werk dat deze engine niet uitvoert. Zonder
            # rasteraar gooit `OpRasterNode.preprocess` de kinderen van de laag
            # weg en levert hij nul cutcode; wij rekenden er wél seconden voor.
            # Gemeten op één gevuld vlak van 60×40 mm: onze som 385,5 s tegen
            # 70,0 s in het echte plan — 315 s beloofd voor een blanco plaat.
            # De laag telt nog wél als onderdeel: hij ligt op het bed, en de
            # melding erover hoort in de pre-flight en niet in een nul.
            if kind == "op raster" and not rastert:
                pieces += len(self._burnable(operation))
                continue
            shapes = self._burnable(operation)
            pieces += len(shapes)
            if not shapes:
                continue
            passes = _passes_of(operation)
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
        """
        De lengte van het pad in mm.

        Twee wegen, want de eerste kan omvallen op geldige geometrie. Gevonden
        in een echt project: tekst in Chalkduster, 474 contouren en 10 026
        segmenten, waarop `Geomstr.length()` van de engine afgaat met
        "expected a positive input, got -inf" (een ontaard segment in het log).
        Wij vingen dat op met een 0 — de `except` stond er voor afbeeldingen,
        die geen pad hebben — en daarmee rekende de schatting nul seconden voor
        juist de vorm die het langst duurde. Nu meten we hem dan zelf na langs
        de punten: gemeten 0,68 m, waar het 0,0 was.
        """
        from math import hypot

        from meerk40t.core.units import UNITS_PER_MM

        try:
            geometry = node.as_geometry()
        except Exception:
            # Een afbeelding heeft geen pad; die valt onder de rasterrekensom.
            return 0.0
        try:
            return float(geometry.length()) / UNITS_PER_MM
        except Exception:
            pass
        try:
            totaal, vorige = 0.0, None
            for punt in geometry.as_interpolated_points(interpolate=20):
                if punt is None:
                    vorige = None
                    continue
                if vorige is not None:
                    totaal += hypot(punt.real - vorige.real, punt.imag - vorige.imag)
                vorige = punt
            return totaal / UNITS_PER_MM
        except Exception:
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
        rastert = self.engine_report()["raster"]

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
            passes = _passes_of(operation)
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
                    # Brandt deze laag daadwerkelijk? Een rasterlaag doet dat op
                    # een engine zonder rasteraar niet, en dan mag de tabel geen
                    # snelheid en vermogen tonen alsof er iets gaat gebeuren.
                    "burns": not (str(operation.type) == "op raster" and not rastert),
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
            raise DesignError("The engine wrote no file.")
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
            raise DesignError("This is not an OpenKerf project.", code="project.notOurs")
        with zipfile.ZipFile(source) as bundle:
            names = set(bundle.namelist())
            if "design.svg" not in names:
                raise DesignError("The project holds no design.", code="project.noDesign")
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
    """
    3 rather than 3.0.

    The decimal separator stays a point here: this is the source language of the
    API, and the interface writes the number again in the reader's own notation.
    """
    return f"{float(waarde):g}"


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
    vel_naam = sheet.get("material_name") or "this sheet"
    vel_dikte = sheet.get("thickness_mm")

    van = entry.get("material_name") or "another material"
    if (
        vel_materiaal is not None
        and entry.get("material_id") is not None
        and entry["material_id"] != vel_materiaal
    ):
        waarschuwingen.append(
            {
                "code": "ander-materiaal",
                "text": f"This setting is for {van}; this sheet is {vel_naam}.",
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
                    f"This setting is for {_mm_tekst(entry['thickness_mm'])} mm; "
                    f"this sheet is {_mm_tekst(vel_dikte)} mm."
                ),
            }
        )

    if entry.get("source") == "geextrapoleerd":
        waarschuwingen.append(
            {
                "code": "nooit-gebrand",
                "text": "Calculated from another thickness — never burned.",
            }
        )
    elif entry.get("source") == "geimporteerd":
        waarschuwingen.append(
            {
                "code": "nooit-gebrand",
                "text": "Taken from another machine — never burned here.",
            }
        )

    # Het zwaarste bezwaar bovenaan, zodat de lezer niet zelf hoeft te wegen.
    for waarschuwing in waarschuwingen:
        waarschuwing["ernst"] = ERNST.get(waarschuwing["code"], 1)
    waarschuwingen.sort(key=lambda w: -w["ernst"])
    return waarschuwingen
