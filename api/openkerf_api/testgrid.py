"""
Parametric test grids.

The verification loop from ARCHITECTUUR.md: burn a grid of squares that sweeps
power against speed, photograph the result, point at the best cell, and turn
that into a verified preset. This module covers the first half — planning the
grid and drawing it into the element tree.

Each cell needs its own laser settings, so each cell gets its own operation
with one square referenced from it. That is exactly how MeerK40t models a job,
and it means the existing plan → spool route runs the grid without changes.
"""

from .edits import DesignError

MAX_CELLS = 400  # A 20x20 sweep is already more than anyone reads off a photo.


def _positive(value, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as e:
        raise DesignError(f"{name} moet een getal zijn.") from e
    if number <= 0:
        raise DesignError(f"{name} moet groter dan nul zijn.")
    return number


def _steps(value, name: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as e:
        raise DesignError(f"{name} moet een geheel getal zijn.") from e
    if number < 2:
        raise DesignError(f"{name} moet minstens 2 zijn — anders varieer je niets.")
    return number


# De stappen waarop een mens werkt. Een raster dat rijen snijdt op 11,667 mm/s
# is geen naslagwerk: die instelling type je nooit meer over.
_NETTE_STAPPEN = (0.1, 0.2, 0.25, 0.5, 1, 2, 2.5, 5, 10, 20, 25, 50, 100, 200, 250, 500)


def _rond_af(waarde: float, ruwe_stap: float) -> float:
    """
    Een tussenwaarde naar het dichtstbijzijnde nette getal schuiven.

    De korrel volgt de stapgrootte: bij stappen van ~13 rond je op tientallen af,
    bij stappen van ~0,4 op tienden. Zo blijft het raster herkenbaar oplopen in
    plaats van vier keer hetzelfde getal te tonen.
    """
    # De grofste nette stap die hoogstens een halve stap groot is: dan schuift
    # een waarde nooit verder dan een kwart stap op en blijft de reeks netjes
    # oplopen.
    grens = ruwe_stap / 2 if ruwe_stap else 1
    passend = [k for k in _NETTE_STAPPEN if k <= grens]
    korrel = passend[-1] if passend else _NETTE_STAPPEN[0]
    afgerond = round(waarde / korrel) * korrel
    # Drijvende komma laat 3 * 0.1 als 0.30000000000000004 achter.
    return round(afgerond, 3)


def _spread(low: float, high: float, steps: int) -> list[float]:
    """
    De reeks waarden voor één as.

    Begin en eind blijven exact wat er gevraagd is — dat is het bereik dat de
    gebruiker wil aftasten. Alleen de tussenstappen schuiven naar een net getal,
    en als twee daarvan op hetzelfde uitkomen blijft de rauwe waarde staan:
    liever een lelijk getal dan twee identieke rijen.
    """
    if steps == 1:
        return [low]
    span = (high - low) / (steps - 1)
    ruw = [low + span * i for i in range(steps)]
    net = [ruw[0]] + [_rond_af(v, span) for v in ruw[1:-1]] + [ruw[-1]]
    if len(set(net)) < len(net) or any(
        net[i] >= net[i + 1] for i in range(len(net) - 1)
    ):
        return ruw
    return net


def plan_grid(
    operation: str,
    speed_min,
    speed_max,
    speed_steps,
    power_min,
    power_max,
    power_steps,
    cell_mm=8.0,
    gap_mm=2.0,
    origin_x_mm=10.0,
    origin_y_mm=10.0,
    material_id=None,
    machine_id=None,
    thickness_mm=None,
) -> tuple[dict, list[dict]]:
    """Work out the cells without touching the engine, so it can be previewed."""
    speed_lo = _positive(speed_min, "speed_min")
    speed_hi = _positive(speed_max, "speed_max")
    power_lo = _positive(power_min, "power_min")
    power_hi = _positive(power_max, "power_max")
    if speed_hi < speed_lo:
        raise DesignError("speed_max moet minstens speed_min zijn.")
    if power_hi < power_lo:
        raise DesignError("power_max moet minstens power_min zijn.")
    if power_hi > 100:
        raise DesignError("power_max kan niet boven 100 procent.")

    rows = _steps(speed_steps, "speed_steps")
    columns = _steps(power_steps, "power_steps")
    if rows * columns > MAX_CELLS:
        raise DesignError(
            f"{rows}×{columns} cellen is te veel; hou het onder {MAX_CELLS}."
        )

    cell = _positive(cell_mm, "cell_mm")
    gap = float(gap_mm)
    if gap < 0:
        raise DesignError("gap_mm kan niet negatief zijn.")
    pitch = cell + gap

    speeds = _spread(speed_lo, speed_hi, rows)
    powers = _spread(power_lo, power_hi, columns)

    cells = []
    for row, speed in enumerate(speeds):
        for column, power in enumerate(powers):
            cells.append(
                {
                    "row": row,
                    "column": column,
                    "speed_mm_s": round(speed, 3),
                    "power_percent": round(power, 3),
                    "x_mm": round(origin_x_mm + column * pitch, 3),
                    "y_mm": round(origin_y_mm + row * pitch, 3),
                    "width_mm": cell,
                    "height_mm": cell,
                }
            )

    plan = {
        "material_id": material_id,
        "machine_id": machine_id,
        "thickness_mm": thickness_mm,
        "operation": operation,
        "speed_min": speed_lo,
        "speed_max": speed_hi,
        "speed_steps": rows,
        "power_min": power_lo,
        "power_max": power_hi,
        "power_steps": columns,
        "cell_mm": cell,
        "gap_mm": gap,
        "origin_x_mm": float(origin_x_mm),
        "origin_y_mm": float(origin_y_mm),
        "width_mm": round(columns * pitch - gap, 3),
        "height_mm": round(rows * pitch - gap, 3),
    }
    return plan, cells


# Which MeerK40t operation type a library operation maps to.
OPERATION_TYPES = {
    "snijden": "op cut",
    "graveren-vector": "op engrave",
    "graveren-raster": "op raster",
    "markeren": "op engrave",
}


class TestGridGenerator:
    def __init__(self, kernel):
        self.kernel = kernel

    @property
    def elements(self):
        return self.kernel.elements

    def draw(self, plan: dict, cells: list[dict]) -> list[dict]:
        """
        Draw the grid: one square per cell, each in its own operation.

        Returns the cells enriched with the element and operation ids, so a
        photo overlay can later map a tap back to speed and power.
        """
        op_type = OPERATION_TYPES.get(plan["operation"])
        if op_type is None:
            raise DesignError(f"Onbekende bewerking: {plan['operation']}")

        bed = self._bed_mm()
        if bed and (
            plan["origin_x_mm"] + plan["width_mm"] > bed[0]
            or plan["origin_y_mm"] + plan["height_mm"] > bed[1]
        ):
            raise DesignError(
                f"Het raster ({plan['width_mm']:.0f}×{plan['height_mm']:.0f} mm vanaf "
                f"{plan['origin_x_mm']:.0f},{plan['origin_y_mm']:.0f}) valt buiten het bed "
                f"van {bed[0]:.0f}×{bed[1]:.0f} mm."
            )

        drawn = []
        # Zonder dit belandt elke cel óók in elke bestaande operatie waarvan de
        # kleur matcht — de engine classificeert nieuwe elementen automatisch.
        # Het raster zou dan dubbel gebrand worden: één keer op de instelling van
        # de cel en één keer op die van de andere laag. Dat maakt de test
        # waardeloos en verbrandt materiaal.
        classify = getattr(self.elements, "classify_new", None)
        if classify is not None:
            self.elements.classify_new = False
        try:
            drawn = self._draw_cells(plan, cells)
        finally:
            if classify is not None:
                self.elements.classify_new = classify

        self.elements.signal("rebuild_tree", "all")
        self.elements.signal("refresh_scene", "Scene")
        return drawn

    def group_drawn(self, drawn: list[dict]) -> str | None:
        """
        Vouw het hele raster tot één groep.

        Een raster is één ding: half verslepen slaat nergens op, en als losse
        vierkanten vult het de selectie en het canvas met ruis. De cellen
        houden wél elk hun eigen operatie — anders brandt de sweep niet.
        """
        nodes = [
            node
            for node in (
                self.elements.find_node(entry["element_id"]) for entry in drawn
            )
            if node is not None
        ]
        labels = [
            node
            for node in self.elements.elems()
            if node.type == "elem path" and node not in nodes
        ]
        members = nodes + [n for n in labels if self._is_label(n)]
        if len(members) < 2:
            return None
        self.elements.set_emphasis(members)
        self.kernel.console("group\n")
        self.elements.validate_ids()
        for node in self.elements.elem_branch.flat():
            if node.type == "group" and any(c in members for c in node.children):
                return node.id
        return None

    def _is_label(self, node) -> bool:
        for reference in getattr(node, "_references", []) or []:
            parent = getattr(reference, "parent", None)
            if parent is not None and getattr(parent, "label", None) == "Raster-labels":
                return True
        return False

    def _draw_cells(self, plan: dict, cells: list[dict]) -> list[dict]:
        op_type = OPERATION_TYPES[plan["operation"]]
        drawn = []
        with self.elements.undoscope("Testraster genereren"):
            for cell in cells:
                node = self._square(cell)
                operation = self.elements.op_branch.add(
                    type=op_type,
                    speed=cell["speed_mm_s"],
                    # MeerK40t's power runs 0-1000, not 0-100.
                    power=cell["power_percent"] * 10,
                    # Eén decimaal: tussenstappen komen anders uit op 53.333%.
                    label=(
                        f"{cell['speed_mm_s']:.1f}mm/s @{cell['power_percent']:.1f}%"
                    ),
                )
                operation.add_reference(node)
                drawn.append({**cell, "element_id": None, "operation_id": None,
                              "_node": node, "_op": operation})

            self._label_axes(plan, cells)
            self._caption(plan)

        # Ids only exist once the engine has handed them out.
        self.elements.validate_ids()
        for entry in drawn:
            entry["element_id"] = entry.pop("_node").id
            entry["operation_id"] = entry.pop("_op").id
        return drawn

    def _label_axes(self, plan: dict, cells: list[dict]):
        """
        Engrave the axis labels: speed down the left, power across the top.

        Without them the grid is unreadable once it is off the machine — every
        square looks the same and you cannot tell which settings made it. The
        labels go in their own engrave operation, so they are not part of the
        sweep.
        """
        speeds = {c["row"]: c["speed_mm_s"] for c in cells}
        powers = {c["column"]: c["power_percent"] for c in cells}
        pitch = plan["cell_mm"] + plan["gap_mm"]
        # Schaal mee met het vakje. Op ware grootte is "25 mm/s" bijna 20 mm
        # breed en steekt hij links van het bed uit.
        text_height = max(2.0, plan["cell_mm"] * 0.35)

        # Pas aanmaken als er echt tekst getekend wordt: zonder vectorfont zou
        # er anders een lege laag achterblijven.
        labels = None

        for row, speed in sorted(speeds.items()):
            node = self._text(f"{speed:g} mm/s", text_height)
            if node is None:
                return  # Geen vectorfont beschikbaar; het raster blijft bruikbaar.
            labels = labels or self._label_op()
            self._place(
                node,
                right=plan["origin_x_mm"] - 2,
                middle=plan["origin_y_mm"] + row * pitch + plan["cell_mm"] / 2,
            )
            labels.add_reference(node)

        for column, power in sorted(powers.items()):
            node = self._text(f"{power:g}%", text_height)
            if node is None or labels is None:
                return
            self._place(
                node,
                center=plan["origin_x_mm"] + column * pitch + plan["cell_mm"] / 2,
                bottom=plan["origin_y_mm"] - 2,
            )
            labels.add_reference(node)

    def _caption(self, plan: dict):
        """
        Het opschrift op het bord: wat is dit, waarvan, wanneer.

        Een gebrand raster zonder opschrift is over twee weken een raadselachtig
        stuk hout. Het staat in de labellaag, dus met een vaste, veilige
        instelling — het opschrift moet leesbaar zijn ongeacht welke cel het
        beste uitpakt.
        """
        delen = [str(plan.get("caption") or "").strip()]
        if plan.get("material_name"):
            delen.append(str(plan["material_name"]))
        if plan.get("thickness_mm"):
            delen.append(f"{plan['thickness_mm']:g} mm")
        delen.append(str(plan["operation"]))
        if plan.get("stamp"):
            delen.append(str(plan["stamp"]))
        tekst = " · ".join(d for d in delen if d)
        if not tekst:
            return

        hoogte = max(2.5, plan["cell_mm"] * 0.4)
        node = self._text(tekst, hoogte)
        if node is None:
            return
        labels = self._label_op()
        self._place(
            node,
            left=plan["origin_x_mm"],
            # Bóven de kolomlabels, met dezelfde marge als die labels zelf.
            bottom=plan["origin_y_mm"] - 2 - hoogte - 2,
        )
        labels.add_reference(node)

    def _label_op(self):
        """De laag waar alle opschriften in gaan; één per raster."""
        for node in self.elements.op_branch.children:
            if getattr(node, "label", None) == "Raster-labels":
                return node
        return self.elements.op_branch.add(
            type="op engrave", speed=80, power=300, label="Raster-labels"
        )

    def _text(self, text: str, height_mm: float):
        """Vector text via the Hershey fonts; bitmap text has no geometry."""
        before = {id(n) for n in self.elements.elems()}
        try:
            self.kernel.console(f'linetext 0mm 0mm "{text}"\n')
        except Exception:
            return None
        node = next(
            (n for n in self.elements.elems() if id(n) not in before and n.bounds), None
        )
        if node is None:
            return None
        return self._scale_to_height(node, height_mm)

    def _scale_to_height(self, node, height_mm: float):
        from meerk40t.core.units import UNITS_PER_MM

        x0, y0, x1, y1 = (v / UNITS_PER_MM for v in node.bounds)
        current = y1 - y0
        if current <= 0:
            return node
        factor = height_mm / current
        self.elements.set_emphasis([node])
        self.kernel.console(
            f"resize {x0:.4f}mm {y0:.4f}mm "
            f"{max(0.1, (x1 - x0) * factor):.4f}mm {height_mm:.4f}mm\n"
        )
        return node

    def _place(self, node, right=None, center=None, middle=None, bottom=None, left=None):
        """Move a freshly drawn label to where it belongs, measured from its bounds."""
        from meerk40t.core.units import UNITS_PER_MM

        x0, y0, x1, y1 = (v / UNITS_PER_MM for v in node.bounds)
        dx = dy = 0.0
        if right is not None:
            dx = right - x1
        if left is not None:
            dx = left - x0
        if center is not None:
            dx = center - (x0 + x1) / 2
        if bottom is not None:
            dy = bottom - y1
        if middle is not None:
            dy = middle - (y0 + y1) / 2
        self.elements.set_emphasis([node])
        self.kernel.console(f"translate {dx:.4f}mm {dy:.4f}mm\n")

    def _square(self, cell: dict):
        before = set(id(n) for n in self.elements.elems())
        self.kernel.console(
            f"rect {cell['x_mm']}mm {cell['y_mm']}mm "
            f"{cell['width_mm']}mm {cell['height_mm']}mm\n"
        )
        for node in self.elements.elems():
            if id(node) not in before:
                return node
        raise DesignError("De engine heeft geen vierkant aangemaakt.")

    def _bed_mm(self):
        device = getattr(self.kernel, "device", None)
        try:
            from meerk40t.core.units import Length

            return (
                Length(device.bedwidth).mm,
                Length(device.bedheight).mm,
            )
        except Exception:
            return None
