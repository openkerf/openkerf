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
# De fijnste stappen zijn er voor het interval: dat loopt van 0,05 tot 0,3 mm,
# en op een korrel van 0,1 zouden drie van de vier rijen hetzelfde getal krijgen.
_NETTE_STAPPEN = (
    0.01, 0.02, 0.025, 0.05,
    0.1, 0.2, 0.25, 0.5, 1, 2, 2.5, 5, 10, 20, 25, 50, 100, 200, 250, 500,
)


# ---------------------------------------------------------------- de drie assen
#
# Besluit B12: het interval (de lijnafstand) is de derde grootheid die je kunt
# aftasten. Je kiest zelf welke twee op de assen staan; de derde blijft vast.
# Passes staat er bewust níét bij: dat vermenigvuldigt de brandtijd van het hele
# bord, en dan test je je geduld in plaats van je materiaal.

AXES = {
    "speed": {
        "cell_key": "speed_mm_s",
        "fixed_key": "speed_mm_s",
        "unit": "mm/s",
        "label": "snelheid",
    },
    "power": {
        "cell_key": "power_percent",
        "fixed_key": "power_percent",
        "unit": "%",
        "label": "vermogen",
    },
    "interval": {
        "cell_key": "interval_mm",
        "fixed_key": "interval_mm",
        "unit": "mm",
        "label": "interval",
    },
}

# Waar het interval iets betekent. Bij snijden legt de kop één lijn en is er
# geen lijnafstand; hem daar aanbieden zou een knop zijn die niets doet.
INTERVAL_OPERATIONS = ("graveren-raster",)

# Waar het interval op uitkomt als je er niets over zegt: 0,1 mm ≈ 254 dpi, het
# werkpunt waar de meeste CO2-graveringen op staan.
DEFAULT_INTERVAL_MM = 0.1


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


def _bereik(naam: str, lo, hi, aantal) -> list[float]:
    """De waarden op één as, gecontroleerd en afgerond op nette getallen."""
    laag = _positive(lo, f"{naam}_min")
    hoog = _positive(hi, f"{naam}_max")
    if hoog < laag:
        raise DesignError(f"{naam}_max moet minstens {naam}_min zijn.")
    if naam == "power" and hoog > 100:
        raise DesignError("power_max kan niet boven 100 procent.")
    if naam == "interval" and hoog > 5:
        raise DesignError("interval_max boven 5 mm is geen gravering meer.")
    return _spread(laag, hoog, _steps(aantal, f"{naam}_steps"))


def _vast(naam: str, waarde, terugval) -> float:
    """De waarde van de grootheid die níét op een as staat."""
    if waarde in (None, ""):
        waarde = terugval
    if waarde in (None, ""):
        raise DesignError(
            f"Zet een vaste waarde voor {AXES[naam]['label']}; die staat niet op een as."
        )
    getal = _positive(waarde, AXES[naam]["fixed_key"])
    if naam == "power" and getal > 100:
        raise DesignError("Vermogen kan niet boven 100 procent.")
    return getal


def plan_grid(
    operation: str,
    speed_min=None,
    speed_max=None,
    speed_steps=None,
    power_min=None,
    power_max=None,
    power_steps=None,
    interval_min=None,
    interval_max=None,
    interval_steps=None,
    speed_mm_s=None,
    power_percent=None,
    interval_mm=None,
    row_axis="speed",
    column_axis="power",
    cell_mm=8.0,
    gap_mm=2.0,
    origin_x_mm=10.0,
    origin_y_mm=10.0,
    material_id=None,
    machine_id=None,
    thickness_mm=None,
) -> tuple[dict, list[dict]]:
    """
    Work out the cells without touching the engine, so it can be previewed.

    Twee van de drie grootheden staan op een as (`row_axis` naar beneden,
    `column_axis` naar rechts), de derde blijft vast. Standaard is dat wat het
    altijd was: snelheid omlaag, vermogen naar rechts.
    """
    if row_axis not in AXES or column_axis not in AXES:
        raise DesignError(
            f"Onbekende as: kies uit {', '.join(AXES)}."
        )
    if row_axis == column_axis:
        raise DesignError(
            "De twee assen moeten verschillende grootheden zijn — anders varieer "
            "je één ding in twee richtingen."
        )
    assen = (row_axis, column_axis)
    interval_telt = operation in INTERVAL_OPERATIONS
    if "interval" in assen and not interval_telt:
        raise DesignError(
            "Interval is alleen een as bij rasteren: bij snijden en vectorgraveren "
            "legt de kop één lijn en is er geen lijnafstand."
        )

    reeksen = {
        "speed": (speed_min, speed_max, speed_steps),
        "power": (power_min, power_max, power_steps),
        "interval": (interval_min, interval_max, interval_steps),
    }
    waarden = {
        naam: _bereik(naam, *reeksen[naam]) if naam in assen else None
        for naam in AXES
    }
    vaste = {
        "speed": None if "speed" in assen else _vast("speed", speed_mm_s, speed_min),
        "power": None if "power" in assen else _vast("power", power_percent, power_min),
        "interval": (
            None
            if "interval" in assen or not interval_telt
            else _vast(
                "interval",
                interval_mm,
                interval_min if interval_min else DEFAULT_INTERVAL_MM,
            )
        ),
    }

    rows = len(waarden[row_axis])
    columns = len(waarden[column_axis])
    if rows * columns > MAX_CELLS:
        raise DesignError(
            f"{rows}×{columns} cellen is te veel; hou het onder {MAX_CELLS}."
        )

    cell = _positive(cell_mm, "cell_mm")
    gap = float(gap_mm)
    if gap < 0:
        raise DesignError("gap_mm kan niet negatief zijn.")
    pitch = cell + gap

    cells = []
    for row in range(rows):
        for column in range(columns):
            entry = {
                "row": row,
                "column": column,
                "x_mm": round(origin_x_mm + column * pitch, 3),
                "y_mm": round(origin_y_mm + row * pitch, 3),
                "width_mm": cell,
                "height_mm": cell,
            }
            for naam, as_ in AXES.items():
                if naam == row_axis:
                    getal = waarden[naam][row]
                elif naam == column_axis:
                    getal = waarden[naam][column]
                else:
                    getal = vaste[naam]
                entry[as_["cell_key"]] = None if getal is None else round(getal, 4)
            cells.append(entry)

    plan = {
        "material_id": material_id,
        "machine_id": machine_id,
        "thickness_mm": thickness_mm,
        "operation": operation,
        "row_axis": row_axis,
        "column_axis": column_axis,
        "rows": rows,
        "columns": columns,
        "cell_mm": cell,
        "gap_mm": gap,
        "origin_x_mm": float(origin_x_mm),
        "origin_y_mm": float(origin_y_mm),
        "width_mm": round(columns * pitch - gap, 3),
        "height_mm": round(rows * pitch - gap, 3),
    }
    # Hoeveel ruimte de rijlabels links van het raster nodig hebben. Ze worden
    # daar gegraveerd, en bij Start X 10 met driecijferige snelheden staan ze
    # buiten het bed — dan brandt de machine ze niet en is het bord onleesbaar.
    # Het vectorfont is ongeveer 0,62 × de teksthoogte per teken breed; dit is
    # dus een schatting, en hij wordt als schatting gemeld.
    tekst_hoogte = max(2.0, cell * 0.35)
    langste = max(
        (len(toon(row_axis, waarde)) for waarde in waarden[row_axis]), default=0
    )
    marge = round(2 + 0.62 * tekst_hoogte * langste, 1)
    plan["label_margin_mm"] = marge
    plan["label_room"] = float(origin_x_mm) >= marge

    # Elke grootheid krijgt zijn min/max/steps, ook de vaste: dan blijft één
    # rij in de database genoeg om het raster te herbouwen, en blijven de
    # kolommen die er al waren betekenen wat ze betekenden.
    for naam in AXES:
        reeks = waarden[naam]
        if reeks is None:
            vast = vaste[naam]
            plan[f"{naam}_min"] = vast
            plan[f"{naam}_max"] = vast
            plan[f"{naam}_steps"] = 1 if vast is not None else None
        else:
            plan[f"{naam}_min"] = reeks[0]
            plan[f"{naam}_max"] = reeks[-1]
            plan[f"{naam}_steps"] = len(reeks)
    return plan, cells


# ------------------------------------------------------- het vakje aanwijzen
#
# M4: de herkomst zegt "rij 2, kolom 3", maar op de foto is niets gemarkeerd —
# het bewijs is er, de aanwijzing niet. Met de uitlijning uit T4 in de database
# kan dezelfde afbeelding hier gebruikt worden om het vakje op de foto zelf aan
# te wijzen, zodat de markering meekomt in elk <img> dat de foto toont.

# De hoeken waar de overlay op begint als er nog niets uitgelijnd is: dezelfde
# 10%-marge die de frontend voorstelt.
STANDAARD_HOEKEN = [
    {"x": 0.1, "y": 0.1},
    {"x": 0.9, "y": 0.1},
    {"x": 0.9, "y": 0.9},
    {"x": 0.1, "y": 0.9},
]


def _homografie(hoeken: list[dict]):
    """
    Projectieve afbeelding van het eenheidsvierkant naar de vier hoeken.

    Dezelfde standaardhomografie als in TestGridResult.svelte: wie schuin boven
    het bord staat fotografeert een trapezium, en een affiene transformatie
    vangt dat niet.
    """
    p0, p1, p2, p3 = hoeken
    dx1, dx2 = p1["x"] - p2["x"], p3["x"] - p2["x"]
    dx3 = p0["x"] - p1["x"] + p2["x"] - p3["x"]
    dy1, dy2 = p1["y"] - p2["y"], p3["y"] - p2["y"]
    dy3 = p0["y"] - p1["y"] + p2["y"] - p3["y"]
    noemer = dx1 * dy2 - dy1 * dx2
    g = h = 0.0
    if abs(noemer) > 1e-9 and (dx3 or dy3):
        g = (dx3 * dy2 - dy3 * dx2) / noemer
        h = (dx1 * dy3 - dy1 * dx3) / noemer
    return (
        p1["x"] - p0["x"] + g * p1["x"],
        p3["x"] - p0["x"] + h * p3["x"],
        p0["x"],
        p1["y"] - p0["y"] + g * p1["y"],
        p3["y"] - p0["y"] + h * p3["y"],
        p0["y"],
        g,
        h,
    )


def cel_veelhoek(grid: dict, cell: dict) -> list[tuple[float, float]]:
    """De vier hoeken van één vakje in fotocoördinaten (0–1)."""
    pitch = grid["cell_mm"] + grid["gap_mm"]
    kolommen = grid.get("columns") or grid["power_steps"]
    rijen = grid.get("rows") or grid["speed_steps"]
    breedte = kolommen * pitch - grid["gap_mm"]
    hoogte = rijen * pitch - grid["gap_mm"]
    a, b, c, d, e, f, g, h = _homografie(grid.get("alignment") or STANDAARD_HOEKEN)

    def naar_foto(u, v):
        w = g * u + h * v + 1 or 1e-9
        return ((a * u + b * v + c) / w, (d * u + e * v + f) / w)

    u0 = (cell["x_mm"] - grid["origin_x_mm"]) / breedte
    v0 = (cell["y_mm"] - grid["origin_y_mm"]) / hoogte
    u1 = u0 + cell["width_mm"] / breedte
    v1 = v0 + cell["height_mm"] / hoogte
    return [naar_foto(u0, v0), naar_foto(u1, v0), naar_foto(u1, v1), naar_foto(u0, v1)]


def markeer_foto(grid: dict, path, row: int, column: int) -> bytes:
    """
    De rasterfoto met één vakje omcirkeld, als JPEG-bytes.

    Server-side en niet in de browser, zodat de markering meekomt overal waar de
    foto als plaatje getoond wordt — ook op de herkomstkaart in de bibliotheek.
    """
    from io import BytesIO

    from PIL import Image, ImageDraw

    cell = next(
        (c for c in grid["cells"] if c["row"] == row and c["column"] == column), None
    )
    if cell is None:
        raise DesignError(f"Cel rij {row}, kolom {column} hoort niet bij dit raster.")

    foto = Image.open(path).convert("RGB")
    breedte, hoogte = foto.size
    punten = [(x * breedte, y * hoogte) for x, y in cel_veelhoek(grid, cell)]
    dik = max(3, round(min(breedte, hoogte) / 160))
    teken = ImageDraw.Draw(foto)
    # Wit eronder, accent erop: op donker verbrand hout verdwijnt één lijn.
    teken.polygon(punten, outline=(255, 255, 255), width=dik * 2)
    teken.polygon(punten, outline=(42, 166, 177), width=dik)

    buffer = BytesIO()
    foto.save(buffer, format="JPEG", quality=88)
    return buffer.getvalue()


def as_waarde(cell: dict, naam: str):
    """De waarde van één grootheid in een cel, of None als hij niet meedoet."""
    return cell.get(AXES[naam]["cell_key"])


def toon(naam: str, waarde) -> str:
    """Een aswaarde met zijn eenheid, zoals hij op het hout komt te staan."""
    if waarde is None:
        return ""
    eenheid = AXES[naam]["unit"]
    if naam == "interval":
        return f"{waarde:g}{eenheid}"
    return f"{waarde:g}{'' if eenheid == '%' else ' '}{eenheid}"


def _cel_label(plan: dict, cell: dict) -> str:
    """
    Het laaglabel van één vakje: precies de grootheden die variëren.

    De vaste grootheid staat in het opschrift op het bord; hem in zestien
    laagnamen herhalen maakt het lagenpaneel onleesbaar.
    """
    return " · ".join(
        toon(naam, as_waarde(cell, naam))
        for naam in (plan.get("row_axis", "speed"), plan.get("column_axis", "power"))
    )


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
                instelling = {
                    "type": op_type,
                    "speed": cell["speed_mm_s"],
                    # MeerK40t's power runs 0-1000, not 0-100.
                    "power": cell["power_percent"] * 10,
                    "label": _cel_label(plan, cell),
                }
                # De lijnafstand heet bij de engine dpi. Alleen een rasterop
                # kent hem; op de andere zou het een genegeerde sleutel zijn.
                if op_type == "op raster" and cell.get("interval_mm"):
                    instelling["dpi"] = int(round(25.4 / cell["interval_mm"]))
                operation = self.elements.op_branch.add(**instelling)
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
        Engrave the axis labels: the row quantity left, the column one on top.

        Without them the grid is unreadable once it is off the machine — every
        square looks the same and you cannot tell which settings made it. The
        labels go in their own engrave operation, so they are not part of the
        sweep.
        """
        rij_as = plan.get("row_axis", "speed")
        kolom_as = plan.get("column_axis", "power")
        speeds = {c["row"]: as_waarde(c, rij_as) for c in cells}
        powers = {c["column"]: as_waarde(c, kolom_as) for c in cells}
        pitch = plan["cell_mm"] + plan["gap_mm"]
        # Schaal mee met het vakje. Op ware grootte is "25 mm/s" bijna 20 mm
        # breed en steekt hij links van het bed uit.
        text_height = max(2.0, plan["cell_mm"] * 0.35)

        # Pas aanmaken als er echt tekst getekend wordt: zonder vectorfont zou
        # er anders een lege laag achterblijven.
        labels = None

        for row, speed in sorted(speeds.items()):
            node = self._text(toon(rij_as, speed), text_height)
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
            node = self._text(toon(kolom_as, power), text_height)
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
        # Welke as welke grootheid draagt. Zonder dit is een bord met vrij
        # gekozen assen niet te lezen: "0,05" links kan snelheid of interval
        # zijn. LightBurn zet de asnamen naast de waarden; wij hebben ze harder
        # nodig, want bij ons staat niet vast wát er op de as staat.
        assen = (plan.get("row_axis", "speed"), plan.get("column_axis", "power"))
        delen.append(
            f"{AXES[assen[0]]['label']} v / {AXES[assen[1]]['label']} >"
        )
        # De grootheid die níét op een as staat, hoort er ook op: zonder haar
        # is het bord over twee weken niet terug te rekenen naar een instelling.
        for naam in AXES:
            if naam in assen or plan.get(f"{naam}_min") is None:
                continue
            delen.append(f"{AXES[naam]['label']} {toon(naam, plan[f'{naam}_min'])}")
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
