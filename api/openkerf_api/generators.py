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
        _bend_in_place(geometry, bounds, cx, cy, radius * UNITS_PER_MM, inside)

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

        Het rekenwerk zit in `_plan_barcode`, zodat het voorbeeld dezelfde
        streepjes en dezelfde foutmeldingen krijgt als het echte werk.
        """
        content, bars = self._plan_barcode(text, kind, x_mm, y_mm, width_mm, height_mm)

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

        Het rekenwerk zit in `_plan_box`, zodat het voorbeeld dezelfde panelen,
        dezelfde indeling en dezelfde foutmeldingen krijgt als het echte werk.
        """
        panels, pages, (bed_width, bed_height) = self._plan_box(
            width_mm, depth_mm, height_mm, thickness_mm, finger_mm, kerf_mm,
            gap_mm, lid,
        )

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

        Het rekenwerk zit in `_plan_qrcode`, zodat het voorbeeld dezelfde
        modules en dezelfde foutmeldingen krijgt als het echte werk.
        """
        content, squares, modules = self._plan_qrcode(
            text, x_mm, y_mm, size_mm, border
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

    # ------------------------------------------------------------ voorbeeld

    # Hoeveel kopieën we uittekenen voordat we het bij een omtrek per kopie
    # houden. Vijfhonderd sleutelhangers zijn 500 paden en dat blijft snel,
    # omdat elke kopie hetzelfde pad hergebruikt (zie `parts` hieronder).
    PREVIEW_LIMIT = 500

    def preview(self, what: str, body: dict) -> dict:
        """
        Wat er zou komen te staan, zonder het te maken.

        Geeft vormen terug als SVG-paddata **in millimeters**, plus waar elke
        kopie komt. Twee lagen, omdat een QR-code van 15.000 vlakjes en een
        raster van 500 kopieën allebei door dit gaatje moeten:

        - `shapes` — de unieke omtrekken, elk één d-string (met subpaden).
        - `parts`  — waar ze komen: `{shape, x, y, rot}` in mm en graden.

        De vorm wordt niet aan de tekening toegevoegd en er verandert niets aan
        het document; dit mag dus bij elke toetsaanslag lopen.
        """
        maker = {
            "grid": self._preview_grid,
            "radial": self._preview_radial,
            "polygon": self._preview_polygon,
            "box": self._preview_box,
            "qrcode": self._preview_qrcode,
            "barcode": self._preview_barcode,
            "arctext": self._preview_arctext,
        }.get(str(what))
        if maker is None:
            raise DesignError(f"Van '{what}' is geen voorbeeld te maken.")

        result = maker(body or {})
        sheet_width, sheet_height = self._surface()
        result.setdefault("notes", [])
        result.setdefault("sheets", 1)
        result["what"] = what
        result["sheet"] = {"width_mm": sheet_width, "height_mm": sheet_height}
        # De dozen per vorm dienen alleen om uit te rekenen hoe ver het
        # voorbeeld moet uitzoomen; de browser heeft er niets aan.
        result["bounds"] = _extent(result.pop("boxes"), result["parts"])
        return result

    # De losse voorbeelden. Elk hergebruikt de som van het echte werk; wat er
    # niet in staat, staat er bewust niet in (zie `_preview_arctext`).

    def _preview_grid(self, body: dict) -> dict:
        columns = self._count(body.get("columns"), "kolommen")
        rows = self._count(body.get("rows"), "rijen")
        if columns * rows <= 1:
            raise DesignError("Een raster van één vak is geen raster.")
        gap_x = _finite(body.get("gap_x_mm", 5.0), "gap_x_mm")
        gap_y = _finite(body.get("gap_y_mm", 5.0), "gap_y_mm")
        if gap_x < 0 or gap_y < 0:
            raise DesignError("Een negatieve tussenruimte laat de vormen overlappen.")

        shape, box, (left, top, width, height) = self._selection_outline(
            body.get("ids")
        )
        # Dezelfde steek als `grid --relative`: de opgegeven ruimte is het gat,
        # dus de afstand van kopie tot kopie is die ruimte plús de vorm zelf
        # (core/elements/grid.py:210).
        pitch_x, pitch_y = width + gap_x, height + gap_y
        parts, notes = [], []
        if columns * rows > self.PREVIEW_LIMIT:
            notes.append(
                f"{columns * rows} kopieën is meer dan het voorbeeld tekent; "
                f"hieronder staan de eerste {self.PREVIEW_LIMIT}."
            )
        for row in range(rows):
            for column in range(columns):
                if len(parts) >= self.PREVIEW_LIMIT:
                    break
                parts.append(
                    {
                        "shape": 0,
                        "x": left + column * pitch_x,
                        "y": top + row * pitch_y,
                        "rot": 0.0,
                    }
                )
        return {"shapes": [shape], "boxes": [box], "parts": parts, "notes": notes}

    def _preview_radial(self, body: dict) -> dict:
        count = self._count(body.get("repeats"), "herhalingen")
        if count < 2:
            raise DesignError("Minder dan twee kopieën is geen cirkel.")
        radius = _positive(body.get("radius_mm"), "radius_mm")
        start = _finite(body.get("start_deg", 0.0), "start_deg")
        end = _finite(body.get("end_deg", 360.0), "end_deg")
        if abs(end - start) < 1:
            raise DesignError("De boog moet meer dan één graad beslaan.")
        rotate = body.get("rotate", True) is not False

        shape, box, (left, top, width, height) = self._selection_outline(
            body.get("ids")
        )
        # Het middelpunt ligt `straal` naar **links** van het midden van de
        # selectie, niet erboven, zodat het origineel zelf op de cirkel ligt
        # (core/elements/grid.py:337). De hoek loopt in stappen van
        # (eind − begin) / aantal, en de startangle bepaalt alleen de
        # staplengte — de eerste kopie is het origineel op nul graden.
        cx, cy = left + width / 2 - radius, top + height / 2
        step = (end - start) / count
        parts = []
        for index in range(min(count, self.PREVIEW_LIMIT)):
            angle = index * step
            if rotate:
                # Om het middelpunt draaien, met de vorm op zijn eigen plek.
                # Het minteken is niet cosmetisch: de kopieën lopen linksom
                # over het scherm ("perceived angle travel is CCW",
                # core/elements/grid.py:335). Een volle cirkel is symmetrisch
                # en verbergt dat; pas een boog van 180° liet zien dat het
                # voorbeeld ze gespiegeld neerzette.
                parts.append(
                    {
                        "shape": 0,
                        "x": left,
                        "y": top,
                        "rot": -angle,
                        "rx": cx - left,
                        "ry": cy - top,
                    }
                )
            else:
                # Zonder meedraaien schuift de engine de kopie langs dezelfde
                # cirkel, en dus ook linksom.
                radians = math.radians(angle)
                parts.append(
                    {
                        "shape": 0,
                        "x": left - radius + radius * math.cos(radians),
                        "y": top - radius * math.sin(radians),
                        "rot": 0.0,
                    }
                )
        return {"shapes": [shape], "boxes": [box], "parts": parts, "notes": []}

    def _preview_polygon(self, body: dict) -> dict:
        points = self._plan_polygon(
            body.get("corners"),
            body.get("cx_mm"),
            body.get("cy_mm"),
            body.get("radius_mm"),
            body.get("inner_radius_mm"),
            body.get("start_deg", 0.0),
        )
        shape, box = _as_d([points])
        return {
            "shapes": [shape],
            "boxes": [box],
            "parts": [{"shape": 0, "x": 0.0, "y": 0.0, "rot": 0.0}],
            "notes": [],
        }

    def _preview_box(self, body: dict) -> dict:
        panels, pages, (bed_width, bed_height) = self._plan_box(
            body.get("width_mm"),
            body.get("depth_mm"),
            body.get("height_mm"),
            body.get("thickness_mm"),
            body.get("finger_mm", 10.0),
            body.get("kerf_mm", 0.0),
            body.get("gap_mm", 5.0),
            body.get("lid", True) is not False,
        )
        shapes, boxes, parts, labels = [], [], [], []
        for name, points, at_x, at_y in pages[0]:
            parts.append({"shape": len(shapes), "x": at_x, "y": at_y, "rot": 0.0})
            labels.append(name)
            shape, box = _as_d([points])
            shapes.append(shape)
            boxes.append(box)

        notes = []
        if len(pages) > 1:
            spread = body.get("spread", True) is not False
            notes.append(
                f"Past niet op één vel; er zijn er {len(pages)} nodig. "
                + (
                    "Hieronder staat het eerste."
                    if spread and self.sheets
                    else "Zet 'verdelen over vellen' aan, of kies kleinere maten."
                )
            )
        return {
            "shapes": shapes,
            "boxes": boxes,
            "parts": parts,
            "labels": labels,
            "sheets": len(pages),
            "notes": notes,
        }

    def _preview_qrcode(self, body: dict) -> dict:
        _, squares, modules = self._plan_qrcode(
            body.get("text"),
            body.get("x_mm", 0.0),
            body.get("y_mm", 0.0),
            body.get("size_mm", 30.0),
            body.get("border", 2),
        )
        # Alle vlakjes in één pad: een QR-code van versie 40 heeft er ruim
        # vijftienduizend, en dat zijn geen vijftienduizend losse berichten waard.
        shape, box = _as_d(squares)
        return {
            "shapes": [shape],
            "boxes": [box],
            "parts": [{"shape": 0, "x": 0.0, "y": 0.0, "rot": 0.0}],
            "modules": modules,
            "notes": [],
        }

    def _preview_barcode(self, body: dict) -> dict:
        _, bars = self._plan_barcode(
            body.get("text"),
            body.get("kind") or "code128",
            body.get("x_mm", 0.0),
            body.get("y_mm", 0.0),
            body.get("width_mm", 60.0),
            body.get("height_mm", 20.0),
        )
        shape, box = _as_d(bars)
        return {
            "shapes": [shape],
            "boxes": [box],
            "parts": [{"shape": 0, "x": 0.0, "y": 0.0, "rot": 0.0}],
            "bars": len(bars),
            "notes": [],
        }

    def _preview_arctext(self, body: dict) -> dict:
        """
        De boogtekst in de letter waarin hij straks gebrand wordt.

        De engine rendert tekst normaal gesproken in een node, en die zou hier
        in het document belanden. Dat kan anders: `cfont.render()` schrijft in
        een losse `FontPath` (extra/hershey.py:352), dus we halen dezelfde
        geometrie op zonder iets aan te maken. Wat we níet doen is
        `context.last_font` zetten — `create_linetext_node` doet dat wél
        (hershey.py:492), en een voorbeeld dat stilletjes je lettertypekeuze
        verandert, is een voorbeeld met bijwerkingen.
        """
        from meerk40t.core.units import UNITS_PER_MM

        radius = _positive(body.get("radius_mm"), "radius_mm")
        cx = _finite(body.get("cx_mm", 0.0), "cx_mm") * UNITS_PER_MM
        cy = _finite(body.get("cy_mm", 0.0), "cy_mm") * UNITS_PER_MM
        size = _positive(body.get("font_size_mm", 10.0), "font_size_mm")
        text = str(body.get("text") or "").strip()
        if not text:
            raise DesignError("Tekst mag niet leeg zijn.")

        geometry = self._text_geometry(
            text, size * UNITS_PER_MM, body.get("font"), body.get("spacing")
        )
        bounds = geometry.bbox()
        if bounds is None:
            raise DesignError("De tekst leverde geen vorm op.")
        _bend_in_place(
            geometry, bounds, cx, cy, radius * UNITS_PER_MM,
            bool(body.get("inside")),
        )
        geometry.uscale(1 / UNITS_PER_MM)
        x0, y0, x1, y1 = geometry.bbox()
        return {
            "shapes": [geometry.as_path().d()],
            "boxes": [(x0, y0, x1, y1)],
            "parts": [{"shape": 0, "x": 0.0, "y": 0.0, "rot": 0.0}],
            "notes": [],
        }

    def _text_geometry(self, text, font_size, font, spacing):
        """Rechte tekst als losse geometrie, zonder node en zonder bijwerking."""
        from meerk40t.extra.hershey import FontPath

        registry = getattr(self.kernel.root, "fonts", None)
        if registry is None:
            raise DesignError("Geen lettertype-ondersteuning beschikbaar.")
        registry.context.setting(str, "last_font", "")
        name, path = registry.retrieve_font(font or None)
        if not name:
            raise DesignError("Er staat geen enkel bruikbaar lettertype op deze computer.")
        rendered = FontPath(False)
        try:
            registry.cached_fontclass(path).render(
                rendered,
                self.elements.wordlist_translate(text),
                horizontal=True,
                font_size=float(font_size),
                h_spacing=float(spacing) if spacing else 1.0,
                align="start",
            )
        except Exception as e:
            raise DesignError(f"Dit lettertype is niet te tekenen: {e}") from e
        return rendered.geometry

    def _selection_outline(self, ids):
        """
        De omtrek van de selectie als één pad in mm, plus waar hij ligt.

        Eén pad voor de hele selectie, zodat een raster van 500 kopieën 500
        verwijzingen naar hetzelfde pad is en niet 500 keer de geometrie.
        """
        from meerk40t.core.node.node import Node
        from meerk40t.core.units import UNITS_PER_MM

        nodes = []
        for element_id in ids or []:
            node = self.elements.find_node(element_id)
            if node is None:
                raise DesignError(f"Element {element_id} bestaat niet (meer).")
            nodes.append(node)
        if not nodes:
            raise DesignError("Kies eerst wat er herhaald moet worden.")

        bounds = Node.union_bounds(nodes)
        if not bounds:
            raise DesignError("De selectie heeft geen afmeting.")
        x0, y0, x1, y1 = bounds

        from meerk40t.core.geomstr import Geomstr

        together = Geomstr()
        for node in nodes:
            if not hasattr(node, "as_geometry"):
                continue
            try:
                together.append(node.as_geometry())
            except Exception:
                continue
        if together.index == 0:
            # Een afbeelding heeft geen omtrek; dan is de omhullende het
            # eerlijkste dat we kunnen laten zien.
            together.line(complex(x0, y0), complex(x1, y0))
            together.line(complex(x1, y0), complex(x1, y1))
            together.line(complex(x1, y1), complex(x0, y1))
            together.line(complex(x0, y1), complex(x0, y0))
        together.translate(-x0, -y0)
        together.uscale(1 / UNITS_PER_MM)
        width, height = (x1 - x0) / UNITS_PER_MM, (y1 - y0) / UNITS_PER_MM
        return (
            together.as_path().d(),
            (0.0, 0.0, width, height),
            (x0 / UNITS_PER_MM, y0 / UNITS_PER_MM, width, height),
        )

    # ------------------------------------------------------- het rekenwerk
    #
    # Alles hieronder rekent en raakt de tekening niet aan. Het echte werk én
    # het voorbeeld lopen er allebei doorheen, en dat is de hele reden dat ze
    # bestaan: een voorbeeld dat zijn eigen som doet, gaat op een dag iets
    # anders zeggen dan wat er uit de machine komt, en dan is het erger dan
    # geen voorbeeld. Zelfde regel voor de foutmeldingen — wie in het voorbeeld
    # leest waarom het niet kan, krijgt straks niet ineens een ander verhaal.

    def _plan_barcode(self, text, kind, x_mm, y_mm, width_mm, height_mm):
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
        return content, bars

    def _plan_qrcode(self, text, x_mm, y_mm, size_mm, border):
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
        return content, squares, modules

    def _plan_box(
        self, width_mm, depth_mm, height_mm, thickness_mm, finger_mm, kerf_mm,
        gap_mm, lid,
    ):
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
        return panels, pages, (bed_width, bed_height)

    def _plan_polygon(self, corners, cx_mm, cy_mm, radius_mm, inner_radius_mm, start_deg):
        """
        De hoekpunten van de veelhoek, in mm.

        De echte veelhoek komt uit de `shape`-opdracht van de engine; dit is de
        som ernaast. `test_polygon_preview_matches_the_real_thing` legt beide
        naast elkaar, want een tweede som is pas te vertrouwen als er iets
        omvalt zodra ze uit elkaar lopen.
        """
        count = self._count(corners, "hoeken")
        if count < 3:
            raise DesignError("Een veelhoek heeft minstens drie hoeken.")
        radius = _positive(radius_mm, "radius_mm")
        cx = _finite(cx_mm, "cx_mm")
        cy = _finite(cy_mm, "cy_mm")
        start = _finite(start_deg, "start_deg")
        inner = None
        if inner_radius_mm is not None:
            inner = _positive(inner_radius_mm, "inner_radius_mm")
            if inner >= radius:
                raise DesignError("De binnenstraal moet kleiner zijn dan de straal.")

        # `corners` telt de hoekpunten, niet de punten van de ster: een ster van
        # vijf heeft er vijf, om en om buiten en binnen op stappen van 360°/5
        # (extra/param_functions.py:868). Dat is de val waar het voorbeeld eerst
        # in trapte — die tekende er tien en werd daarmee te hoog.
        points = []
        for index in range(count):
            r = inner if (inner is not None and index % 2) else radius
            angle = math.radians(start) + index / count * math.tau
            points.append((cx + math.cos(angle) * r, cy + math.sin(angle) * r))
        return points

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
        self._recalculate_bounds()
        self.elements.signal("rebuild_tree", "all")
        self.elements.signal("refresh_scene", "Scene")
        return {"generator": generator, "expected": expected}

    def _recalculate_bounds(self):
        """
        De omhullende opnieuw laten uitrekenen na een herhaling.

        `grid` en `radial` maken hun kopieën met `copy(node)` en schuiven ze
        daarna met een rauwe `e.matrix *= ...` (core/elements/grid.py:240,360).
        Die toekenning meldt niets aan de node, dus de kopie houdt de
        omhullende die hij van het origineel meekreeg — `bounds` wijst naar de
        oude plek terwijl `as_geometry()` de nieuwe geeft. Op het canvas is dat
        precies wat je ziet: de aangeklikte kopie krijgt zijn dikke rand, maar
        de handvatten staan om het origineel.

        Wij kunnen dat hier niet in de engine repareren (kernprincipe 1), dus
        vragen we de nodes hun omhullende te vergeten. Zie de upstream-lijst.
        """
        for node in self.elements.elems():
            marker = getattr(node, "set_dirty_bounds", None)
            if marker is not None:
                marker()


def _as_d(groups) -> tuple[str, tuple[float, float, float, float]]:
    """Gesloten veelhoeken als één d-string, met de doos eromheen."""
    parts, xs, ys = [], [], []
    for points in groups:
        if not points:
            continue
        parts.append(
            "M" + " L".join(f"{x:.4g},{y:.4g}" for x, y in points) + " Z"
        )
        xs += [x for x, _ in points]
        ys += [y for _, y in points]
    if not parts:
        raise DesignError("Hier komt geen vorm uit.")
    return " ".join(parts), (min(xs), min(ys), max(xs), max(ys))


def _extent(boxes, parts):
    """
    De doos om alles heen, in mm.

    Bij een gedraaide kopie draaien we de vier hoeken van zijn doos mee. Dat is
    iets ruimer dan de vorm zelf, en dat mag: dit bepaalt alleen hoe ver het
    voorbeeld uitzoomt.
    """
    xs, ys = [], []
    for part in parts:
        x0, y0, x1, y1 = boxes[part["shape"]]
        corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        angle = math.radians(part.get("rot") or 0.0)
        px, py = part.get("rx", 0.0), part.get("ry", 0.0)
        for cx, cy in corners:
            dx, dy = cx - px, cy - py
            rx = px + dx * math.cos(angle) - dy * math.sin(angle)
            ry = py + dx * math.sin(angle) + dy * math.cos(angle)
            xs.append(part["x"] + rx)
            ys.append(part["y"] + ry)
    if not xs:
        return [0.0, 0.0, 0.0, 0.0]
    return [min(xs), min(ys), max(xs), max(ys)]


def _bend_in_place(geometry, bounds, cx, cy, scale, inside):
    """
    Rechte tekst om een cirkel buigen. Alles in Tats.

    Elk punt schuift naar de cirkel: de afstand tot de basislijn wordt de
    afstand tot het middelpunt, de plek langs de regel wordt de hoek. Zo blijft
    de letterhoogte kloppen en rekt niets uit.

    Staat apart omdat het voorbeeld precies dezelfde bocht moet maken als het
    echte werk — inclusief de grens waarboven de tekst over zichzelf heen
    loopt, want dat is de melding die het formulier laat zien.
    """
    x0, _, x1, y1 = bounds
    if x1 - x0 >= 2 * math.pi * scale * 0.98:
        raise DesignError(
            "Deze tekst is te lang voor deze straal; hij zou over zichzelf "
            "heen lopen. Kies een grotere straal of een kleinere letter."
        )
    middle = (x0 + x1) / 2
    baseline = y1  # onderkant van de tekst

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

    for row in geometry.segments[: geometry.index]:
        # Kolom 2 draagt het segmenttype, geen punt; die blijft met rust.
        for column in (0, 1, 3, 4):
            row[column] = bend(complex(row[column]))


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
