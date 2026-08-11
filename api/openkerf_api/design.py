"""
The design as the browser needs it: element outlines and the operations
(layers) they belong to.

Geometry leaves the engine in its native unit — the Tat, 65535 per inch — as
SVG path data. Converting the numbers here would mean rewriting path strings;
instead the snapshot carries `units_per_mm` and the frontend applies a single
scale transform. One multiplication, no parsing.
"""

import re
from meerk40t.core.units import UNITS_PER_MM

# Operation types that carry a laser setting and therefore read as a layer.
OPERATION_PREFIX = ("op ", "effect ")


def _plain(value):
    """numpy scalars and Color objects must survive JSON."""
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, (int, float)):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return str(value)


# Lagen die de engine zelf aanmaakt heten "Engrave 20.0mm/s @1000 #0000ff":
# de instellingen in de naam gepropt. Die staan er al netjes naast, dus we
# tonen waar de laag over gaat.
LAYER_NAMES = {
    "op cut": "Snijden",
    "op engrave": "Graveren",
    "op raster": "Rasteren",
    "op image": "Afbeelding",
    "op dots": "Punten",
}


def operation_label(op) -> str:
    """
    De naam van een laag: die van de gebruiker, of het soort bewerking.

    Het kenmerk van een engine-naam is de kleurcode erin ("Engrave 20.0mm/s
    @1000 #0000ff"). Een testrastercel heet bewust "5.0mm/s @40.0%" — dat is
    juist informatie, en die laten we staan.
    """
    # Eerst laten renderen: de ruwe naam is een sjabloon met plaatshouders als
    # "{percent}", en die horen niet in de lagenlijst.
    rendered = _label(op, str(op.type).replace("op ", ""))
    if rendered and not re.search(r"#[0-9a-fA-F]{6}", rendered):
        return rendered
    return LAYER_NAMES.get(str(op.type), str(op.type).replace("op ", "").title())


def _label(node, fallback: str) -> str:
    """
    A readable name.

    A plain `label` is the user's own name and wins. Templated labels like
    "Engrave ({percent}, {speed}mm/s)" are not: `display_label()` blanks keys
    it cannot resolve, which leaves "Engrave (, 12.0mm/s)". `str(node)` renders
    the node's formatter against the full default map and produces what the
    wxPython tree shows, so templates go through there instead.
    """
    label = _attr_or_none(node, "label")
    if label and "{" not in label:
        return label
    try:
        rendered = str(node)
        if rendered and "{" not in rendered:
            return rendered
    except Exception:
        pass
    if label:
        try:
            resolved = node.display_label()
            if resolved:
                return resolved
        except Exception:
            pass
    return fallback


def _attr_or_none(node, name):
    try:
        return getattr(node, name, None)
    except Exception:
        return None


def _xy(point):
    """
    Punt uit een matrixtransformatie naar (x, y).

    `point_in_matrix_space` geeft een Point terug; die is indexeerbaar maar
    niet te slicen, dus uitpakken moet expliciet.
    """
    try:
        return float(point[0]), float(point[1])
    except (TypeError, IndexError):
        return float(point.x), float(point.y)


def _line_of(node) -> dict | None:
    """
    De twee eindpunten van een lijn.

    Uit de bounds alleen kun je niet zien welke kant een lijn op loopt, dus
    zonder deze velden kan de UI geen eindpunt aanbieden om te verslepen.
    """
    if getattr(node, "type", None) != "elem line":
        return None
    from meerk40t.core.units import UNITS_PER_MM

    try:
        # Draaien zet een matrix op de node en laat x1..y2 ongemoeid. Wie de
        # ruwe punten tekent, zet de grepen dus op de plek van vóór de rotatie.
        matrix = getattr(node, "matrix", None)
        points = [(float(node.x1), float(node.y1)), (float(node.x2), float(node.y2))]
        if matrix is not None:
            points = [_xy(matrix.point_in_matrix_space(p)) for p in points]
        (x1, y1), (x2, y2) = points
        return {
            "x1_mm": x1 / UNITS_PER_MM,
            "y1_mm": y1 / UNITS_PER_MM,
            "x2_mm": x2 / UNITS_PER_MM,
            "y2_mm": y2 / UNITS_PER_MM,
        }
    except (AttributeError, TypeError, ValueError):
        return None


def _text_of(node) -> dict | None:
    """
    Bewerkbare vector-tekst.

    `linetext` maakt een pad, maar de engine bewaart de bron op de node
    (`mktext`, `mkfont`, `mkfontsize`, ...) en kan hem opnieuw renderen. Zonder
    deze velden zou tekst na plaatsen bevroren zijn.
    """
    text = _attr_or_none(node, "mktext")
    if text is None:
        return None
    from meerk40t.core.units import UNITS_PER_MM

    size = _attr_or_none(node, "mkfontsize")
    try:
        size_mm = round(float(size) / UNITS_PER_MM, 2) if size is not None else None
    except (TypeError, ValueError):
        size_mm = None
    return {
        "text": str(text),
        "font": str(_attr_or_none(node, "mkfont") or ""),
        "font_size_mm": size_mm,
        "spacing": _plain(_attr_or_none(node, "mkfontspacing")) or 1,
        "align": str(_attr_or_none(node, "mkalign") or "start"),
    }


def _image_of(node) -> dict | None:
    """Kader en resolutie van een afbeelding, in millimeters."""
    if getattr(node, "type", None) != "elem image":
        return None
    from meerk40t.core.units import UNITS_PER_MM

    bounds = getattr(node, "bounds", None)
    if not bounds:
        return None
    x0, y0, x1, y1 = (v / UNITS_PER_MM for v in bounds)
    image = _attr_or_none(node, "active_image") or _attr_or_none(node, "image")
    size = getattr(image, "size", None) if image is not None else None
    return {
        "x_mm": x0,
        "y_mm": y0,
        "width_mm": x1 - x0,
        "height_mm": y1 - y0,
        "pixels": list(size) if size else None,
        "dpi": _plain(_attr_or_none(node, "dpi")),
    }


def _effect_of(node) -> dict | None:
    """
    Een hatch- of wobble-effect waar dit element in zit.

    Effects zijn geen operaties maar containers in de elementenboom: het
    commando hangt de node aan `first_node.parent` en neemt de vormen als
    kinderen op. Wie ze in de operatieboom zoekt, vindt ze niet.
    """
    parent = _attr_or_none(node, "parent")
    depth = 0
    while parent is not None and depth < 20:
        kind = getattr(parent, "type", "") or ""
        if kind.startswith("effect "):
            return {
                "id": getattr(parent, "id", None),
                "type": kind.replace("effect ", ""),
                "label": _label(parent, kind),
            }
        parent = _attr_or_none(parent, "parent")
        depth += 1
    return None


def _group_of(node) -> str | None:
    """
    De dichtstbijzijnde groep waar dit element in zit.

    Het canvas tekent elementen plat, dus zonder deze verwijzing zou je de
    losse vierkanten van een testraster elk apart kunnen verslepen — terwijl
    het raster juist één ding is.
    """
    parent = _attr_or_none(node, "parent")
    depth = 0
    while parent is not None and depth < 20:
        if getattr(parent, "type", None) == "group":
            return getattr(parent, "id", None)
        parent = _attr_or_none(parent, "parent")
        depth += 1
    return None


def _color(value) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text.startswith("#") else None


class DesignReader:
    """Builds a render-ready snapshot of the element tree."""

    def __init__(self, kernel, keep_operations=None, grid_operations=None):
        self.kernel = kernel
        # Operaties die de gebruiker zelf aanmaakte. Een verse boom bevat 201
        # lege standaardoperaties, dus lege lagen tonen we normaal niet — maar
        # een laag die je net zelf maakte moet niet meteen onzichtbaar zijn.
        self.keep_operations = keep_operations if keep_operations is not None else set()
        # Callable die {operatie-id: {grid_id, row, column, ...}} teruggeeft.
        # Rasteroperaties worden in de UI tot één regel samengevouwen.
        self.grid_operations = grid_operations or (lambda: {})

    @property
    def elements(self):
        return self.kernel.elements

    def snapshot(self) -> dict:
        # Give every node a stable identifier. The engine's own mechanism:
        # existing ids are kept, missing ones get "meerk40t:N", duplicates are
        # reassigned. SVG loading calls this too, so it is the identity the
        # rest of MeerK40t already uses — and `elements.find_node(id)` resolves
        # it back. Index-based ids would shift the moment the tree changes,
        # which would make a selection point at the wrong element.
        self.elements.validate_ids()

        grids = self.grid_operations()
        element_ids = {}
        elements = []
        for index, node in enumerate(self.elements.elems()):
            entry = self._element(node, node.id or f"e{index}")
            if entry is not None:
                element_ids[id(node)] = entry["id"]
                elements.append(entry)

        operations = []
        for index, op in enumerate(self.elements.ops()):
            entry = self._operation(op, op.id or f"o{index}", element_ids)
            if entry is not None:
                entry["grid"] = self._grid_for(op, grids.get(entry["id"]))
            # An operation with no elements is not a layer the user sees; the
            # engine keeps a stack of unused defaults around.
            if entry is not None and (
                entry["element_ids"] or entry["id"] in self.keep_operations
            ):
                operations.append(entry)

        # Which operations claim each element. This is genuinely many-to-many:
        # MeerK40t classifies elements into every operation whose colour
        # matches, so an element commonly sits in several at once. Rendering
        # therefore uses the element's own stroke, not a "layer colour".
        claims: dict[str, list[str]] = {}
        for op in operations:
            for element_id in op["element_ids"]:
                claims.setdefault(element_id, []).append(op["id"])
        for element in elements:
            operation_ids = claims.get(element["id"], [])
            element["operation_ids"] = operation_ids
            element["operation_id"] = operation_ids[0] if operation_ids else None

        return {
            "units_per_mm": UNITS_PER_MM,
            "elements": elements,
            "operations": operations,
        }

    @staticmethod
    def _grid_for(op, cell):
        """
        Alleen markeren als de operatie ook echt die cel is.

        De koppeling komt uit de database en overleeft een herstart, terwijl
        element-id's per document worden uitgedeeld. Een id uit een oud raster
        kan dus toevallig op een nieuwe operatie passen; dan zou die ten
        onrechte op slot gaan. De instellingen moeten daarom kloppen.
        """
        if not cell:
            return None
        speed = _attr_or_none(op, "speed")
        power = _attr_or_none(op, "power")
        if speed is None or power is None:
            return None
        if abs(float(speed) - float(cell["speed_mm_s"])) > 0.01:
            return None
        if abs(float(power) - float(cell["power_percent"]) * 10) > 0.1:
            return None
        return cell

    def _element(self, node, element_id) -> dict | None:
        path = self._path(node)
        image = _image_of(node)
        # Afbeeldingen hebben geen pad; zonder deze uitzondering vielen ze uit
        # de snapshot en waren ze onzichtbaar op het canvas.
        if path is None and image is None:
            return None
        return {
            "image": image,
            "id": element_id,
            "type": node.type,
            "label": _label(node, node.type.replace("elem ", "")),
            "hidden": bool(getattr(node, "hidden", False)),
            "group_id": _group_of(node),
            "text": _text_of(node),
            "line": _line_of(node),
            "effect": _effect_of(node),
            "stroke": _color(getattr(node, "stroke", None)),
            "fill": _color(getattr(node, "fill", None)),
            "bounds": [_plain(v) for v in (node.bounds or [])] or None,
            "path": path or "",
        }

    def _path(self, node) -> str | None:
        """SVG path data in native units, or None for nodes without outlines."""
        if not hasattr(node, "as_geometry"):
            return None
        try:
            geometry = node.as_geometry()
            data = geometry.as_path().d()
        except Exception:
            # Images and text may have no vector form; they are skipped rather
            # than breaking the whole snapshot.
            return None
        return data or None

    def _operation(self, op, operation_id, element_ids) -> dict | None:
        if not str(op.type).startswith(OPERATION_PREFIX):
            return None
        referenced = []
        for child in op.children:
            target = getattr(child, "node", None)
            if target is not None and id(target) in element_ids:
                referenced.append(element_ids[id(target)])
        return {
            "id": operation_id,
            "type": op.type,
            "label": operation_label(op),
            "color": _color(getattr(op, "color", None)),
            "speed": _plain(getattr(op, "speed", None)),
            "power": _plain(getattr(op, "power", None)),
            # 0 betekent bij de engine "niet ingesteld", niet "nul keer".
            "passes": _plain(getattr(op, "passes", None)) or 1,
            # Alleen zinvol voor raster/afbeelding, maar elke operatie draagt de
            # velden; de frontend toont ze op type.
            "dpi": _plain(getattr(op, "dpi", None)),
            "overscan": _plain(getattr(op, "overscan", None)),
            "bidirectional": bool(getattr(op, "bidirectional", True)),
            "output": bool(getattr(op, "output", True)),
            "element_ids": referenced,
        }
