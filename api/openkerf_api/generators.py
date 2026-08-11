"""
Generatoren: dingen die je anders met de hand zou natekenen.

Vergelijkbaar met de "Applications"-tab van xTool Studio, zie
XTOOL-VERGELIJKING.md. Wat hier staat is gekozen op wat een laser echt scheelt:

- **Raster- en cirkelherhaling** — twintig sleutelhangers uitleggen doe je niet
  met kopiëren en plakken.
- **Veelhoek en ster** — de engine kan het al (`shape`), er was alleen geen weg
  naartoe.
- **Doos met vingerlassen** — de enige generator die echt rekenwerk uitspaart:
  vinger­breedte, materiaaldikte en snijbreedte moeten kloppen of de doos past niet.
- **QR-code** — een adres of serienummer graveren zonder een plaatje te zoeken.

Niet gebouwd: sieraden-, sleutelhanger- en kaartgeneratoren. Die maken één
specifiek product; de doos maakt een categorie.
"""

from __future__ import annotations

import math

from .edits import DesignError, _finite, _positive


class Generators:
    def __init__(self, kernel, runner, drawing=None, sheets=None):
        self.kernel = kernel
        self.runner = runner
        self.drawing = drawing
        # Voor een doos die niet op één vel past; zie box().
        self.sheets = sheets

    @property
    def elements(self):
        return self.kernel.elements

    # ------------------------------------------------------------ herhalen

    def grid(self, ids, columns, rows, gap_x_mm=5.0, gap_y_mm=5.0) -> dict:
        """
        De selectie in rijen en kolommen herhalen.

        De afstand is een **gat** tussen de vormen, niet hart-op-hart: dat is wat
        je op materiaal wilt kunnen kiezen, want daar gaat de zaagsnede doorheen.
        """
        columns, rows = self._count(columns, "kolommen"), self._count(rows, "rijen")
        if columns * rows <= 1:
            raise DesignError("Een raster van één vak is geen raster.")
        gap_x = _finite(gap_x_mm, "gap_x_mm")
        gap_y = _finite(gap_y_mm, "gap_y_mm")
        if gap_x < 0 or gap_y < 0:
            raise DesignError("Een negatieve tussenruimte laat de vormen overlappen.")

        with self._selection(ids), self.elements.undoscope("Raster herhalen"):
            self.runner.run(
                f"grid {columns} {rows} {gap_x:.4f}mm {gap_y:.4f}mm --relative"
            )
        return self._added("grid", columns * rows)

    def radial(self, ids, repeats, radius_mm, start_deg=0.0, end_deg=360.0, rotate=True) -> dict:
        """De selectie rond een middelpunt herhalen."""
        count = self._count(repeats, "herhalingen")
        if count < 2:
            raise DesignError("Minder dan twee kopieën is geen cirkel.")
        radius = _positive(radius_mm, "radius_mm")
        start = _finite(start_deg, "start_deg")
        end = _finite(end_deg, "end_deg")
        if abs(end - start) < 1:
            raise DesignError("De boog moet meer dan één graad beslaan.")

        command = f"radial {count} {radius:.4f}mm {start}deg {end}deg"
        if not rotate:
            command += " --unrotated"
        with self._selection(ids), self.elements.undoscope("Cirkelherhaling"):
            self.runner.run(command)
        return self._added("radial", count)

    # -------------------------------------------------------------- vormen

    def polygon(
        self,
        corners,
        cx_mm,
        cy_mm,
        radius_mm,
        inner_radius_mm=None,
        start_deg=0.0,
    ) -> dict:
        """
        Een regelmatige veelhoek, of een ster als er een binnenstraal bij staat.

        De engine maakt een ster door de straal om en om te wisselen
        (`--radius_inner` met `--alternate_seq 1`); zonder die tweede optie krijg
        je een veelhoek met dubbele punten in plaats van een ster.
        """
        count = self._count(corners, "hoeken")
        if count < 3:
            raise DesignError("Een veelhoek heeft minstens drie hoeken.")
        radius = _positive(radius_mm, "radius_mm")
        cx = _finite(cx_mm, "cx_mm")
        cy = _finite(cy_mm, "cy_mm")

        command = (
            f"shape {count} {cx:.4f}mm {cy:.4f}mm {radius:.4f}mm "
            f"--startangle {_finite(start_deg, 'start_deg')}deg"
        )
        if inner_radius_mm is not None:
            inner = _positive(inner_radius_mm, "inner_radius_mm")
            if inner >= radius:
                raise DesignError("De binnenstraal moet kleiner zijn dan de straal.")
            command += f" --radius_inner {inner:.4f}mm --alternate_seq 1"

        with self.elements.undoscope("Veelhoek"):
            self.runner.run(command)
        return self._added("polygon", 1)

    # ----------------------------------------------------------- boogtekst

    def arc_text(
        self,
        text,
        cx_mm,
        cy_mm,
        radius_mm,
        font_size_mm=10.0,
        font=None,
        spacing=None,
        inside=False,
    ) -> dict:
        """
        Tekst langs een boog, bijvoorbeeld voor een rond bordje of een deksel.

        De engine kent geen boogtekst. We laten hem de tekst gewoon recht
        zetten en buigen daarna de geometrie: elk punt schuift naar de cirkel,
        waarbij de afstand tot de basislijn de afstand tot het middelpunt
        wordt. Zo blijft de letterhoogte kloppen en rekt niets uit.

        Na het buigen is het **geen tekst meer maar een pad**: de bron wordt
        losgelaten, want de engine zou de tekst bij de eerstvolgende wijziging
        opnieuw recht renderen en de boog stilletjes wegpoetsen.
        """
        from meerk40t.core.units import UNITS_PER_MM

        radius = _positive(radius_mm, "radius_mm")
        cx = _finite(cx_mm, "cx_mm") * UNITS_PER_MM
        cy = _finite(cy_mm, "cy_mm") * UNITS_PER_MM
        size = _positive(font_size_mm, "font_size_mm")

        drawn = self.drawing.create(
            "text",
            x_mm=0,
            y_mm=0,
            text=text,
            font_size_mm=size,
            font=font,
            spacing=spacing,
        )
        node = self.elements.find_node(drawn["ids"][0])
        geometry = node.as_geometry()
        bounds = node.bounds
        if not bounds:
            raise DesignError("De tekst leverde geen vorm op.")
        x0, _, x1, y1 = bounds
        span = x1 - x0
        if span >= 2 * math.pi * radius * UNITS_PER_MM * 0.98:
            raise DesignError(
                "Deze tekst is te lang voor deze straal; hij zou over zichzelf "
                "heen lopen. Kies een grotere straal of een kleinere letter."
            )

        middle = (x0 + x1) / 2
        baseline = y1  # onderkant van de tekst
        scale = radius * UNITS_PER_MM

        def bend(point):
            if point != point:  # NaN: geen punt maar een markering
                return point
            angle = (point.real - middle) / scale
            above = baseline - point.imag
            if inside:
                distance = scale - above
                return complex(
                    cx + distance * math.sin(-angle), cy + distance * math.cos(-angle)
                )
            distance = scale + above
            return complex(
                cx + distance * math.sin(angle), cy - distance * math.cos(angle)
            )

        segments = geometry.segments[: geometry.index]
        for row in segments:
            # Kolom 2 draagt het segmenttype, geen punt; die blijft met rust.
            for column in (0, 1, 3, 4):
                row[column] = bend(complex(row[column]))

        with self.elements.undoscope("Boogtekst"):
            node.geometry = geometry
            node.matrix.reset()
            # De bron loslaten: anders rendert de engine de tekst bij de
            # volgende wijziging weer recht.
            for attribute in ("mktext", "mkfont", "mkfontsize"):
                if hasattr(node, attribute):
                    setattr(node, attribute, None)
            node.altered()
            self.elements.validate_ids()
        self._refresh()
        return {"generator": "arc_text", "ids": [node.id] if node.id else []}

    # --------------------------------------------------------------- barcode

    def barcode(
        self, text, kind="code128", x_mm=0.0, y_mm=0.0, width_mm=60.0, height_mm=20.0
    ) -> dict:
        """
        Een streepjescode als vlakken.

        De codering komt uit `python-barcode`; de streepjes tekenen we zelf, net
        als bij de QR-code. Een gegraveerde bitmap wordt op hout vaag, en een
        streepjescode die niet scant is nutteloos.
        """
        content = str(text or "").strip()
        if not content:
            raise DesignError("Een streepjescode zonder inhoud bestaat niet.")
        width = _positive(width_mm, "width_mm")
        height = _positive(height_mm, "height_mm")
        x0 = _finite(x_mm, "x_mm")
        y0 = _finite(y_mm, "y_mm")

        try:
            import barcode as barcodes
        except ImportError as e:  # pragma: no cover - alleen bij kale installatie
            raise DesignError(
                "Streepjescodes vragen het pakket 'python-barcode'."
            ) from e

        if kind not in barcodes.PROVIDED_BARCODES:
            raise DesignError(
                f"Onbekend type: {kind}. Kies uit {', '.join(barcodes.PROVIDED_BARCODES)}."
            )
        try:
            bits = "".join(barcodes.get_barcode_class(kind)(content).build())
        except Exception as e:
            # EAN en vrienden stellen eisen aan lengte en controlecijfer; die
            # melding is voor de gebruiker nuttiger dan een 500.
            raise DesignError(f"'{content}' past niet in een {kind}: {e}") from e
        if "1" not in bits:
            raise DesignError("De codering leverde geen streepjes op.")

        step = width / len(bits)
        bars, index = [], 0
        while index < len(bits):
            if bits[index] == "0":
                index += 1
                continue
            run = index
            while run < len(bits) and bits[run] == "1":
                run += 1
            left = x0 + index * step
            right = x0 + run * step
            bars.append(
                [(left, y0), (right, y0), (right, y0 + height), (left, y0 + height)]
            )
            index = run

        with self.elements.undoscope("Streepjescode"):
            node = self._add_polygon(
                bars, f"{kind} — {content[:24]}", subpaths=True, intent="engrave"
            )
            self.elements.validate_ids()
        self._refresh()
        return {
            "generator": "barcode",
            "kind": kind,
            "ids": [node.id] if node.id else [],
            "bars": len(bars),
        }

    # ---------------------------------------------------------------- doos

    def box(
        self,
        width_mm,
        depth_mm,
        height_mm,
        thickness_mm,
        finger_mm=10.0,
        kerf_mm=0.0,
        gap_mm=5.0,
        lid=True,
        spread=True,
    ) -> dict:
        """
        Panelen met vingerlassen, naast elkaar gelegd om te snijden.

        Waarom dit rekenwerk niet met de hand moet: twee panelen die aan elkaar
        vastzitten, moeten **complementaire** tanden hebben — waar de een een
        tand heeft, heeft de ander een gat. Eén paneel verkeerd om en de doos
        past niet. `PHASE` legt per rand vast wie de tand heeft; er is een test
        die controleert dat elk paar tegengesteld is.

        De snijbreedte (kerf) wordt bij de tanden opgeteld en niet van de gaten
        afgetrokken: de laser haalt aan beide kanten van elke snede materiaal
        weg, dus een tand die op papier precies past, is in hout te klein.
        """
        width = _positive(width_mm, "width_mm")
        depth = _positive(depth_mm, "depth_mm")
        height = _positive(height_mm, "height_mm")
        thickness = _positive(thickness_mm, "thickness_mm")
        finger = _positive(finger_mm, "finger_mm")
        kerf = _finite(kerf_mm, "kerf_mm")
        gap = _finite(gap_mm, "gap_mm")
        if not 0 <= kerf <= 2:
            raise DesignError("Een kerf buiten 0–2 mm klopt niet.")
        if gap < 0:
            raise DesignError("De tussenruimte tussen de panelen kan niet negatief zijn.")
        if thickness * 3 >= min(width, depth, height):
            raise DesignError(
                "Het materiaal is te dik voor deze buitenmaten; de wanden zouden "
                "elkaar raken."
            )
        if finger < thickness:
            raise DesignError(
                "Een vinger smaller dan het materiaal dik is, breekt af. "
                f"Kies minstens {thickness} mm."
            )
        if finger * 3 > min(width, depth, height):
            raise DesignError("De vinger is te breed: er passen er geen drie op een rand.")

        panels = box_panels(
            width, depth, height, thickness, finger, kerf, lid=lid
        )

        # Op het bed leggen in rijen, niet op één lange rij: zes panelen naast
        # elkaar zijn zo een meter breed, en wat buiten het bed valt kun je niet
        # meer aanwijzen om het terug te halen.
        bed_width, bed_height = self._surface()
        widest = max(
            max(px for px, _ in points) - min(px for px, _ in points)
            for _, points in panels
        )
        if widest > bed_width:
            raise DesignError(
                f"Het breedste paneel is {widest:.0f} mm en past niet op een vel "
                f"van {bed_width:.0f} mm. Kies kleinere buitenmaten."
            )

        # Eerst uitrekenen waar alles komt, dan pas tekenen. Anders staat er een
        # halve doos buiten het vel voordat je weet dat hij niet past.
        pages = _lay_out(panels, bed_width, bed_height, gap)

        if len(pages) > 1 and not (spread and self.sheets):
            raise DesignError(
                f"Deze doos past niet op één vel van {bed_width:.0f} x "
                f"{bed_height:.0f} mm; er zijn er {len(pages)} nodig. Zet "
                "'verdelen over vellen' aan, of kies kleinere maten."
            )

        started_on = self.sheets.state()["active"] if self.sheets else None
        ids = []
        for index, page in enumerate(pages):
            if index:
                # Volgend vel, even groot als dit: dan klopt de indeling met wat
                # er berekend is.
                self.sheets.add(
                    name=f"Doos {index + 1}",
                    width_mm=bed_width,
                    height_mm=bed_height,
                )
                self.sheets.activate(self.sheets.state()["sheets"][-1]["id"])
            with self.elements.undoscope("Doos"):
                for name, points, at_x, at_y in page:
                    node = self._add_polygon(
                        [(px + at_x, py + at_y) for px, py in points],
                        f"Doos — {name}",
                    )
                    if index == 0:
                        ids.append(node)
                self.elements.validate_ids()
            self._refresh()

        if len(pages) > 1 and self.sheets:
            # Terug naar waar de gebruiker was: het canvas onder je vandaan
            # laten schuiven is verwarrender dan zelf doorklikken.
            self.sheets.activate(started_on)
            self._refresh()

        return {
            "generator": "box",
            "ids": [n.id for n in ids if n.id],
            "panels": [name for name, _ in panels],
            "sheets": len(pages),
        }

    # ------------------------------------------------------------- qr-code

    def qrcode(self, text: str, x_mm=0.0, y_mm=0.0, size_mm=30.0, border=2) -> dict:
        """
        Een QR-code als vierkantjes, klaar om te graveren.

        Geen plaatje maar echte vlakken: een gegraveerde bitmap wordt op hout
        vaak vaag, gevulde vierkanten niet. Wel één pad per module, want dat
        laat de gebruiker zelf kiezen of hij vult of omtrekt.
        """
        content = str(text or "").strip()
        if not content:
            raise DesignError("Een QR-code zonder inhoud bestaat niet.")
        if len(content) > 1000:
            raise DesignError("Deze tekst is te lang voor een leesbare QR-code.")
        size = _positive(size_mm, "size_mm")
        quiet = int(_finite(border, "border"))
        if not 0 <= quiet <= 8:
            raise DesignError("De rand moet tussen 0 en 8 modules liggen.")

        try:
            import segno
        except ImportError as e:  # pragma: no cover - alleen bij kale installatie
            raise DesignError(
                "QR-codes vragen het pakket 'segno'; installeer het naast de API."
            ) from e

        from meerk40t.core.units import UNITS_PER_MM

        code = segno.make(content, error="m")
        matrix = [list(row) for row in code.matrix]
        modules = len(matrix) + 2 * quiet
        step = size / modules
        x0 = _finite(x_mm, "x_mm")
        y0 = _finite(y_mm, "y_mm")

        squares = []
        for row, cells in enumerate(matrix):
            for column, dark in enumerate(cells):
                if not dark:
                    continue
                left = x0 + (column + quiet) * step
                top = y0 + (row + quiet) * step
                squares.append(
                    [
                        (left, top),
                        (left + step, top),
                        (left + step, top + step),
                        (left, top + step),
                    ]
                )

        with self.elements.undoscope("QR-code"):
            node = self._add_polygon(
                squares, f"QR — {content[:24]}", subpaths=True, intent="engrave"
            )
            self.elements.validate_ids()
        self._refresh()
        return {
            "generator": "qrcode",
            "ids": [node.id] if node.id else [],
            "modules": modules,
        }

    # --------------------------------------------------------------- intern

    def _surface(self) -> tuple[float, float]:
        """Waar het op moet passen: het actieve vel, of het bed als die er niet zijn."""
        if self.sheets is not None:
            for sheet in self.sheets.state()["sheets"]:
                if sheet["active"]:
                    return float(sheet["width_mm"]), float(sheet["height_mm"])
        return self._bed()

    def _bed(self) -> tuple[float, float]:
        from meerk40t.core.units import Length

        device = getattr(self.kernel, "device", None)

        def side(name, fallback):
            try:
                return float(Length(getattr(device, name)).mm)
            except Exception:
                return fallback

        return side("bedwidth", 500.0), side("bedheight", 300.0)

    def _add_polygon(
        self, points, label: str, subpaths: bool = False, intent: str = "cut"
    ):
        """
        Een gesloten vorm rechtstreeks als geometrie toevoegen.

        Níet via de `path`-opdracht: die leest zijn d-string als SVG-gebruikers-
        eenheden en schaalt hem daarna nog eens, waardoor een doos van 100 mm er
        als 72 meter uitkwam. Geomstr rekent in Tats en laat geen ruimte voor
        die verwarring.
        """
        from meerk40t.core.geomstr import Geomstr
        from meerk40t.core.units import UNITS_PER_MM

        geometry = Geomstr()
        groups = points if subpaths else [points]
        for group in groups:
            corners = [complex(px * UNITS_PER_MM, py * UNITS_PER_MM) for px, py in group]
            for start, end in zip(corners, corners[1:] + corners[:1]):
                geometry.line(start, end)
        node = self.elements.elem_branch.add(
            geometry=geometry,
            type="elem path",
            stroke=self.elements.default_stroke,
            stroke_width=self.elements.default_strokewidth,
            label=label,
        )
        # Expliciet in één laag zetten, niet via kleurclassificatie: die zet een
        # doospaneel in een gráveerlaag én meteen in een tweede laag die dezelfde
        # kleur claimt. Dan brandt hetzelfde paneel twee keer, en dat merk je pas
        # op materiaal.
        if intent:
            self._file_under(node, intent)
        return node

    def _file_under(self, node, intent: str):
        """De vorm in één laag van het gevraagde soort, en nergens anders in."""
        label = {"cut": "Snijden", "engrave": "Graveren"}.get(intent, "Snijden")
        for operation in self.elements.ops():
            if operation.type == f"op {intent}" and getattr(operation, "label", "") == label:
                target = operation
                break
        else:
            made = self.drawing.create_operation(kind=intent, label=label)
            target = self.elements.find_node(made["id"])
        if target is not None:
            target.add_reference(node)

    def _refresh(self):
        self.elements.signal("rebuild_tree", "all")
        self.elements.signal("refresh_scene", "Scene")

    def _count(self, value, what: str) -> int:
        try:
            count = int(value)
        except (TypeError, ValueError) as e:
            raise DesignError(f"Het aantal {what} moet een geheel getal zijn.") from e
        if not 1 <= count <= 500:
            raise DesignError(f"Het aantal {what} moet tussen 1 en 500 liggen.")
        return count

    def _selection(self, ids):
        from contextlib import contextmanager

        @contextmanager
        def scope():
            nodes = []
            for element_id in ids or []:
                node = self.elements.find_node(element_id)
                if node is None:
                    raise DesignError(f"Element {element_id} bestaat niet (meer).")
                nodes.append(node)
            if not nodes:
                raise DesignError("Kies eerst wat er herhaald moet worden.")
            self.elements.set_emphasis(nodes)
            yield nodes

        return scope()

    def _added(self, generator: str, expected: int) -> dict:
        self.elements.validate_ids()
        self.elements.signal("rebuild_tree", "all")
        self.elements.signal("refresh_scene", "Scene")
        return {"generator": generator, "expected": expected}


# Wie heeft de tand en wie het gat. Twee panelen die aan elkaar zitten, moeten
# hier tegengesteld staan; `test_generators.py` controleert dat voor elk paar.
# Sleutel: (paneel, rand) → True als dit paneel op die rand de tand heeft.
PHASE = {
    ("voor", "links"): True,
    ("voor", "rechts"): True,
    ("voor", "onder"): True,
    ("achter", "links"): True,
    ("achter", "rechts"): True,
    ("achter", "onder"): True,
    ("links", "voor"): False,
    ("links", "achter"): False,
    ("links", "onder"): True,
    ("rechts", "voor"): False,
    ("rechts", "achter"): False,
    ("rechts", "onder"): True,
    ("bodem", "voor"): False,
    ("bodem", "achter"): False,
    ("bodem", "links"): False,
    ("bodem", "rechts"): False,
    ("deksel", "voor"): False,
    ("deksel", "achter"): False,
    ("deksel", "links"): False,
    ("deksel", "rechts"): False,
}

# Welke rand van welk paneel op welke rand van welk ander paneel past.
JOINTS = [
    (("voor", "links"), ("links", "voor")),
    (("voor", "rechts"), ("rechts", "voor")),
    (("achter", "links"), ("links", "achter")),
    (("achter", "rechts"), ("rechts", "achter")),
    (("voor", "onder"), ("bodem", "voor")),
    (("achter", "onder"), ("bodem", "achter")),
    (("links", "onder"), ("bodem", "links")),
    (("rechts", "onder"), ("bodem", "rechts")),
]


def teeth_count(length: float, finger: float) -> int:
    """
    Altijd oneven, zodat een rand met materiaal begint én eindigt.

    Twee panelen die aan elkaar zitten, rekenen dit met dezelfde lengte uit en
    komen dus op hetzelfde aantal — dat is waarom de tanden op elkaar passen.
    """
    count = max(3, int(length // finger))
    return count if count % 2 else count - 1


def edge_points(start, end, thickness, finger, kerf, tab_first: bool):
    """
    Eén rand, van start naar end, met tanden die naar buiten steken.

    De kerf wordt bij de tand opgeteld (halve kerf aan elke kant): de laser
    haalt aan beide zijden van de snede materiaal weg, dus een tand die op
    papier precies past, is in hout te smal.
    """
    (x0, y0), (x1, y1) = start, end
    length = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
    if length <= 0:
        return []
    count = teeth_count(length, finger)
    step = length / count
    dx, dy = (x1 - x0) / length, (y1 - y0) / length
    # Loodrecht, naar buiten (de rand loopt met de klok mee rond het paneel).
    nx, ny = dy, -dx
    depth = thickness

    points = []
    for index in range(count):
        tab = (index % 2 == 0) == tab_first
        a = index * step
        b = (index + 1) * step
        if tab:
            a -= kerf / 2
            b += kerf / 2
        else:
            a += kerf / 2
            b -= kerf / 2
        out = depth + kerf / 2 if tab else 0.0
        for value in (a, b):
            points.append(
                (x0 + dx * value + nx * out, y0 + dy * value + ny * out)
            )
    return points


def panel_outline(name, w, h, thickness, finger, kerf, edges):
    """
    Eén paneel als gesloten omtrek, met de klok mee: onder, rechts, boven, links.

    `edges` zegt welke doos-rand elke zijde is; randen die nergens op aansluiten
    (bijvoorbeeld de bovenkant van een wand bij een open doos) worden recht.
    """
    corners = [((0.0, 0.0), (w, 0.0)), ((w, 0.0), (w, h)), ((w, h), (0.0, h)), ((0.0, h), (0.0, 0.0))]
    points = []
    for (start, end), edge in zip(corners, edges):
        if edge is None:
            points.append(start)
            points.append(end)
            continue
        points += edge_points(
            start, end, thickness, finger, kerf, PHASE[(name, edge)]
        )
    return points


def box_panels(width, depth, height, thickness, finger, kerf, lid=True):
    """
    De panelen van de doos, elk als gesloten omtrek beginnend op (0, 0).

    De randen staan met de klok mee: onder, rechts, boven, links. Welke doos-rand
    dat is, verschilt per paneel — een wand raakt de bodem aan zijn onderkant,
    de bodem raakt die wand aan zijn eigen voorrand.
    """
    panels = [
        ("bodem", width, depth, ("voor", "rechts", "achter", "links")),
        ("voor", width, height, ("onder", "rechts", None, "links")),
        ("achter", width, height, ("onder", "rechts", None, "links")),
        ("links", depth, height, ("onder", "voor", None, "achter")),
        ("rechts", depth, height, ("onder", "achter", None, "voor")),
    ]
    if lid:
        panels.append(("deksel", width, depth, ("voor", "rechts", "achter", "links")))
    return [
        (name, panel_outline(name, w, h, thickness, finger, kerf, edges))
        for name, w, h, edges in panels
    ]


def _lay_out(panels, width, height, gap):
    """
    De panelen in rijen leggen, en aan een nieuw vel beginnen zodra het vol is.

    Geeft een lijst van vellen terug, elk met (naam, punten, x, y). Puur
    rekenwerk: pas als vaststaat hoeveel vellen het worden, wordt er getekend.
    """
    pages, page = [], []
    x, y, shelf = gap, gap, 0.0
    for name, points in panels:
        span = max(px for px, _ in points) - min(px for px, _ in points)
        high = max(py for _, py in points) - min(py for _, py in points)
        if x > gap and x + span > width - gap:
            x = gap
            y += shelf + gap
            shelf = 0.0
        if y + high + gap > height:
            pages.append(page)
            page, x, y, shelf = [], gap, gap, 0.0
        page.append((name, points, x, y))
        x += span + gap
        shelf = max(shelf, high)
    if page:
        pages.append(page)
    return pages
