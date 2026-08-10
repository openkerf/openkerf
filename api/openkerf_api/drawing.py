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
        self.elements.set_emphasis(created)
        self._refresh()
        return {"ids": [n.id for n in created], "type": created[0].type}

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
        if label:
            operation.label = str(label)
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
            found.append({"file": str(path), "name": str(display)})
        found.sort(key=lambda f: f["name"].lower())
        return found

    def estimate(self) -> dict:
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
        return {"seconds": round(seconds, 1), "parts": pieces}

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

    def _refresh(self):
        if getattr(self.runner, "document", None) is not None:
            self.runner.document.touch()
        self.elements.signal("rebuild_tree", "all")
        self.elements.signal("refresh_scene", "Scene")
