"""
De lopende tegelreeks: het plan per tegel, en waar je in de reeks bent.

Het klippen en verplaatsen gebeurt op de **kopie** die `plan copy` maakt.
`copy_children_as_real` (meerk40t/core/node/node.py:805) dereferentieert de
ReferenceNodes en kopieert de vormen zelf, dus alles wat hier gebeurt laat de
elementenboom van de gebruiker ongemoeid. Dat is geen bijzaak maar de reden dat
dit ontwerp zo weinig hoeft aan te raken.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from .edits import DesignError
from .tiling import (
    Alignment,
    Point,
    Rect,
    TilingError,
    TilingSettings,
    alignment,
    alignment_from_corner,
    best_split,
    clip_geometry,
    marker_spots,
    tile_layout,
)

#: Snelheid en vermogen van een uitlijnmerk. Een merk hoeft niet diep, het moet
#: zichtbaar zijn: hard erin branden maakt de rand juist waziger om op te
#: richten, en op dun materiaal snijd je er zo doorheen.
MARKER_SPEED_MM_S = 60.0
MARKER_POWER = 300.0  # 30 %


#: De twee cijfers die we ooit nodig hebben, als polylijn in een eenheidsvak:
#: x en y van 0 tot 1, y naar beneden zoals de scène zelf. Zelf getekend, want
#: voor twee glyphs een font-engine binnenhalen is buiten verhouding — en
#: `linetext` overschrijft bovendien bij elke aanroep `last_font` (CLAUDE.md).
#: Eén doorlopende streek per cijfer: dat brandt een laser in één beweging.
CIJFERS = {
    1: [(0.15, 0.22), (0.5, 0.0), (0.5, 1.0)],
    2: [
        (0.08, 0.22),
        (0.26, 0.0),
        (0.62, 0.0),
        (0.8, 0.22),
        (0.8, 0.42),
        (0.1, 1.0),
        (0.86, 1.0),
    ],
}


def digit_geometry(cijfer: int, x: float, y: float, hoogte: float):
    """
    Eén cijfer als geometrie, met zijn linkerbovenhoek op (x, y).

    `hoogte` is de volle hoogte; de breedte volgt uit de vorm van het cijfer.
    """
    from meerk40t.core.geomstr import Geomstr

    punten = CIJFERS.get(cijfer)
    if punten is None:
        raise ValueError(f"No digit drawn for {cijfer}.")
    geom = Geomstr()
    vorig = None
    for px, py in punten:
        nu = complex(x + px * hoogte, y + py * hoogte)
        if vorig is not None:
            geom.line(vorig, nu)
        vorig = nu
    return geom


def marker_geometry(points, size_mm: float, units_per_mm: float, along_y: bool = True):
    """
    De uitlijnmerken als geometrie: een cirkel met een kruis erin, én zijn nummer.

    De cirkel geeft een rand om de kop op te richten die een los kruis niet
    heeft; het snijpunt van het kruis is het punt dat je aantikt.

    **Het nummer wordt meegebrand, en dat is de hele reden dat het bestaat.** Op
    het scherm "merk 1" zeggen is niets waard als er op de plaat twee identieke
    rondjes liggen — dan is een positiewoord ("the left") nog altijd beter, en
    dat woord was juist het probleem: het hangt af van `flip_x`, `swap_xy` en de
    thuishoek, en kan dus omgekeerd zijn. Een gebrand cijfer hangt van niets af.

    `along_y` zegt of de zone hoog-en-smal is (cijfer onder het rondje) of
    breed-en-laag (cijfer ernaast). Alleen dát heeft de tekening nodig van de
    zone, dus dat geven we mee in plaats van de rechthoek — om dezelfde reden als
    in `mark_footprint`: de breedte van de overlap is de krappe maat, dus daar
    komt nooit iets bij.
    """
    from meerk40t.core.geomstr import Geomstr

    from .tiling import CIJFER_FRACTIE, CIJFER_GAT_MM

    straal = size_mm / 2 * units_per_mm
    hoogte = size_mm * CIJFER_FRACTIE * units_per_mm
    gat = CIJFER_GAT_MM * units_per_mm
    geom = Geomstr()
    for nummer, punt in enumerate(points, 1):
        cx = punt.x_mm * units_per_mm
        cy = punt.y_mm * units_per_mm
        geom.append(Geomstr.circle(straal, cx, cy))
        geom.line(complex(cx - straal, cy), complex(cx + straal, cy))
        geom.end()
        geom.line(complex(cx, cy - straal), complex(cx, cy + straal))
        geom.end()
        if along_y:
            hoek_x, hoek_y = cx - hoogte / 2, cy + straal + gat
        else:
            hoek_x, hoek_y = cx + straal + gat, cy - hoogte / 2
        geom.append(digit_geometry(nummer, hoek_x, hoek_y, hoogte))
        geom.end()
    return geom


class TileMutator:
    """
    Eén tegel: klip het plan op het brandgebied en zet het waar de plaat ligt.

    Scènecoördinaten zijn plaatcoördinaten — het ontwerp is op de plaat
    getekend en de engine leest de scène als het bed. De uitlijnmatrix mag
    daarom rechtstreeks in de scène toegepast worden, net zoals
    `Drawing.verschoven` het nulpunt toepast.
    """

    def __init__(
        self,
        burn_mm: Rect,
        alignment: Alignment,
        units_per_mm: float,
        marker_geometry=None,
    ):
        self.burn_mm = burn_mm
        self.alignment = alignment
        self.units_per_mm = units_per_mm
        self.marker_geometry = marker_geometry
        #: hoeveel geklipte geometrie deze tegel brandt, in engine-eenheden.
        #: Hier geteld en niet achteraf uit het plan gelezen: `blob` vervangt de
        #: bewerkingen door één CutCode, en dan is dit niet meer te achterhalen.
        #: De merken tellen niet mee — die horen bij de machine, niet bij het werk.
        self.burned_length_units = 0.0

    # ------------------------------------------------------------- rekenen

    @property
    def burn_units(self) -> Rect:
        u = self.units_per_mm
        return Rect(
            self.burn_mm.x0 * u,
            self.burn_mm.y0 * u,
            self.burn_mm.x1 * u,
            self.burn_mm.y1 * u,
        )

    def matrix(self):
        """The alignment as a matrix in engine units."""
        from meerk40t.svgelements import Matrix

        u = self.units_per_mm
        mx = Matrix()
        mx.post_rotate(math.radians(self.alignment.angle_deg))
        mx.post_translate(self.alignment.dx_mm * u, self.alignment.dy_mm * u)
        return mx

    # ------------------------------------------------------------ bewerken

    def __call__(self, steps):
        blijft = []
        for step in steps:
            children = getattr(step, "children", None)
            if children is None:
                blijft.append(step)
                continue
            if self._reshape(step):
                blijft.append(step)
        if self.marker_geometry is not None and self.marker_geometry.index:
            blijft.append(self._marker_operation())
        return blijft

    def _marker_operation(self):
        """
        De merken als laatste bewerking van de tegel.

        Ze ondergaan dezelfde uitlijning als de rest: ze worden op de plaat
        gebrand, dus ze moeten op de plaat terechtkomen waar de opdeling ze
        heeft berekend.
        """
        from meerk40t.core.node.elem_path import PathNode
        from meerk40t.core.node.op_engrave import EngraveOpNode
        from meerk40t.svgelements import Color, Matrix

        geom = type(self.marker_geometry)(self.marker_geometry)
        geom.transform(self.matrix())
        operation = EngraveOpNode(
            label="Uitlijnmerken",
            speed=MARKER_SPEED_MM_S,
            power=MARKER_POWER,
        )
        operation.add_node(
            PathNode(geom, matrix=Matrix(), stroke=Color("black"), fill=None)
        )
        return operation

    def _reshape(self, operation) -> bool:
        """Clip the children of this operation. Returns whether anything is left."""
        from meerk40t.core.node.elem_path import PathNode
        from meerk40t.svgelements import Matrix

        venster = self.burn_units
        mx = self.matrix()
        vervangers = []
        for child in list(operation.children):
            geom = self._geometry(child)
            if geom is None:
                # Een knoop zonder geometrie — een afbeelding. Zie `_hoort_erbij`:
                # die gaat in zijn geheel mee of helemaal niet.
                if self._hoort_erbij(child):
                    vervangers.append(self._moved_image(child, mx))
                continue
            geklipt = clip_geometry(geom, venster)
            if geklipt.index == 0:
                continue
            self.burned_length_units += sum(
                abs(geklipt.length(i)) for i in range(geklipt.index)
            )
            geklipt.transform(mx)
            vervangers.append(
                PathNode(
                    geklipt,
                    matrix=Matrix(),
                    stroke=getattr(child, "stroke", None),
                    fill=getattr(child, "fill", None),
                    stroke_width=getattr(child, "stroke_width", 1000.0),
                )
            )

        for child in list(operation.children):
            child.remove_node()
        for node in [v for v in vervangers if v is not None]:
            operation.add_node(node)
        return bool(operation.children)

    def _hoort_erbij(self, node) -> bool:
        """
        Hoort deze afbeelding bij deze tegel? Alles of niets.

        Een afbeelding heeft geen `as_geometry`, dus klippen zoals bij een vorm
        kan niet. Een halve foto branden zou het bijsnijden van de bitmap zelf
        vragen, en een gedraaide afbeelding laat zich niet op een rechte naad
        bijsnijden zonder in béide tegels een randje dubbel te branden — precies
        wat we bij vormen met zorg voorkomen.

        Dus: een afbeelding valt in zijn geheel binnen één brandgebied, of hij
        gaat niet mee. Ligt hij over een naad, dan wordt dat bij het opdelen
        geweigerd met een zin (`TileRun.layout`), niet hier stilletjes in twee
        tegels verdubbeld. Zonder deze toets werd een foto in élke tegel
        gebrand, op de verkeerde plek.
        """
        bounds = getattr(node, "bounds", None)
        if not bounds:
            # Geen omhullende betekent: we weten niet waar hij ligt. Meesturen
            # zou hem in elke tegel branden, dus laten we hem staan.
            return False
        venster = self.burn_units
        x0, y0, x1, y1 = bounds
        return (
            venster.x0 <= x0
            and x1 <= venster.x1
            and venster.y0 <= y0
            and y1 <= venster.y1
        )

    @staticmethod
    def _geometry(node):
        maker = getattr(node, "as_geometry", None)
        if maker is None:
            return None
        try:
            return maker()
        except Exception:
            return None

    @staticmethod
    def _moved_image(node, mx):
        """An image moves along; it carries its own matrix."""
        matrix = getattr(node, "matrix", None)
        if matrix is None:
            return node
        node.matrix.post_cat(mx)
        marker = getattr(node, "set_dirty_bounds", None)
        if marker is not None:
            # Een rauwe matrixtoekenning meldt niets aan de knoop; zonder dit
            # draagt hij de omhullende van zijn oude plek.
            marker()
        return node


class TileRun:
    """
    Waar je in een tegelreeks bent, en wat de volgende stap is.

    De reeks staat op schijf naast `vellen.json`: een plaat van 900 mm is werk
    van uren, en dat moet een verversing van de pagina overleven. De uitlijning
    staat er nadrukkelijk níet in — zie `align`.
    """

    def __init__(self, kernel, drawing, sheets, runner, path):
        self.kernel = kernel
        self.drawing = drawing
        self.sheets = sheets
        self.runner = runner
        self.path = Path(path)
        self._alignment = None

    # ------------------------------------------------------------- opslag

    def _read(self) -> dict | None:
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def _write(self, data: dict | None) -> None:
        if data is None:
            self.path.unlink(missing_ok=True)
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=1, ensure_ascii=False))

    # ------------------------------------------------------------ opdeling

    def _sheet(self) -> dict:
        for sheet in self.sheets.state()["sheets"]:
            if sheet.get("active"):
                return sheet
        raise DesignError("There is no active sheet.")

    def _settings(self, sheet) -> TilingSettings:
        blok = sheet.get("tiling") or {}
        return TilingSettings(
            margin_mm=float(blok.get("margin_mm", 10.0)),
            overlap_mm=float(blok.get("overlap_mm", 25.0)),
            marker_size_mm=float(blok.get("marker_size_mm", 8.0)),
        )

    def layout(self) -> dict:
        """
        De opdeling van het actieve vel. Berekend, nooit opgeslagen.

        Hij is een functie van de maten, de instellingen en het ontwerp, dus
        hij klopt vanzelf zodra daar iets aan verandert.
        """
        sheet = self._sheet()
        bed = self.drawing.bed_mm()
        if bed is None:
            raise DesignError("This machine reports no bed size.")
        settings = self._settings(sheet)
        try:
            tiles = tile_layout(
                sheet["width_mm"], sheet["height_mm"], bed[0], bed[1], settings
            )
        except TilingError as e:
            raise DesignError(str(e)) from e

        spans = self._shape_spans()
        tiles = self._nudge_seams(tiles, spans, settings)
        self._check_images(tiles)
        return {
            "tiles": [
                self._tile_json(t, tiles[i - 1] if i else None)
                for i, t in enumerate(tiles)
            ],
            "marks": self._marks(tiles, settings),
            "crossings": self._crossings(tiles, spans),
        }

    def _shape_spans(self) -> list:
        """The bounding boxes of every shape, in millimetres."""
        u = self.drawing._units_per_mm()
        vakken = []
        for node in self.kernel.elements.elems():
            bounds = getattr(node, "bounds", None)
            if not bounds:
                continue
            x0, y0, x1, y1 = bounds
            vakken.append(Rect(x0 / u, y0 / u, x1 / u, y1 / u))
        return vakken

    def _nudge_seams(self, tiles, spans, settings):
        """
        De naad binnen de overlapzone naar waar hij de minste vormen kruist.

        Alleen op de as waarop opgedeeld is; op de andere as is er geen naad.
        Beide assen tegelijk bestaat niet — dat weigert `tile_layout`.

        **Lees uit `aangepast`, niet uit `tiles`.** Elke naad raakt twee tegels,
        dus de middelste tegel wordt tweemaal beschreven: eerst zijn begin door
        de naad ervóór, dan zijn eind door de naad erna. Wie voor die tweede
        schrijfactie het origineel als basis neemt, gooit de eerste weg — en dan
        eindigt tegel 0 op de verschoven naad terwijl tegel 1 nog op de oude
        begint. Gemeten op een plaat van 200×500: tegel 0 tot 150,0 en tegel 1
        vanaf 175,0, een gat van 25 mm dat bij geen enkele tegel hoort en dus
        nooit gebrand wordt. Dat bleef verborgen zolang het verschuiven niets
        veranderde, wat het geval is als er niets te ontwijken valt.
        """
        if len(tiles) < 2:
            return tiles
        horizontaal = len({t.column for t in tiles}) > 1
        aangepast = list(tiles)
        for index in range(len(tiles) - 1):
            links, rechts = aangepast[index], aangepast[index + 1]
            if horizontaal:
                # Het venster verschuift niet mee, dus de zone blijft de zone.
                naad = best_split(
                    rechts.window.x0, links.window.x1, [(s.x0, s.x1) for s in spans]
                )
                aangepast[index] = links._replace(burn=links.burn._replace(x1=naad))
                aangepast[index + 1] = rechts._replace(
                    burn=rechts.burn._replace(x0=naad)
                )
            else:
                naad = best_split(
                    rechts.window.y0, links.window.y1, [(s.y0, s.y1) for s in spans]
                )
                aangepast[index] = links._replace(burn=links.burn._replace(y1=naad))
                aangepast[index + 1] = rechts._replace(
                    burn=rechts.burn._replace(y0=naad)
                )
        return aangepast

    def _check_images(self, tiles) -> None:
        """
        Weiger een afbeelding die over een naad ligt.

        Vormen worden op de naad doormidden gesneden; een afbeelding niet — die
        heeft geen geometrie om te splitsen, en een bitmap bijsnijden op een
        naad zou bij een gedraaide afbeelding in beide tegels een randje dubbel
        branden. Dus hoort een afbeelding in zijn geheel in één tegel, en als
        dat niet kan zeggen we dat, in plaats van hem stilletjes weg te laten of
        in elke tegel te herhalen.
        """
        u = self.drawing._units_per_mm()
        for node in self.kernel.elements.elems():
            if str(getattr(node, "type", "")) != "elem image":
                continue
            bounds = getattr(node, "bounds", None)
            if not bounds:
                continue
            x0, y0, x1, y1 = (v / u for v in bounds)
            past = any(
                t.burn.x0 <= x0
                and x1 <= t.burn.x1
                and t.burn.y0 <= y0
                and y1 <= t.burn.y1
                for t in tiles
            )
            if not past:
                naam = getattr(node, "label", None) or "an image"
                raise DesignError(
                    f"{naam} lies across the seam between two tiles. An image "
                    "cannot be cut in half: move it so that it falls within one tile, "
                    "or make the overlap larger."
                )

    def _marks(self, tiles, settings) -> list[dict]:
        """
        Per grens twee merken. Weigert als er ergens geen plek is.

        Bewust hier en niet pas bij die tegel: zonder plek op grens 2 is de hele
        reeks onuitvoerbaar, en dat hoor je te weten vóór de eerste tegel.
        """
        blokkade = self._shape_spans()
        merken = []
        for links, rechts in zip(tiles, tiles[1:]):
            zone = Rect(
                max(links.window.x0, rechts.window.x0),
                max(links.window.y0, rechts.window.y0),
                min(links.window.x1, rechts.window.x1),
                min(links.window.y1, rechts.window.y1),
            )
            try:
                een, twee = marker_spots(zone, blokkade, settings.marker_size_mm)
            except TilingError as e:
                raise DesignError(
                    f"Tussen tegel {links.index + 1} en {rechts.index + 1}: {e}"
                ) from e
            merken.append(
                {
                    "boundary": links.index,
                    # Welke as de lange is: het cijfer van een merk staat daar
                    # langs, en het canvas moet hem aan dezelfde kant zetten.
                    "along_y": zone.height >= zone.width,
                    "points": [
                        {"x_mm": een.x_mm, "y_mm": een.y_mm},
                        {"x_mm": twee.x_mm, "y_mm": twee.y_mm},
                    ],
                }
            )
        return merken

    @staticmethod
    def _crossings(tiles, spans) -> int:
        """
        Hoeveel vormen door een naad gaan.

        Op de as waarop opgedeeld is, en dat is niet altijd x: een plaat die
        alleen te hóóg is wordt in banden opgedeeld en heeft dan geen enkele
        x-naad. Alleen op x tellen gaf daar nul terwijl er wel degelijk vormen
        doormidden gingen — stil verkeerd, en juist dit getal is waarop iemand
        besluit een vorm te verschuiven. Beide assen tegelijk bestaat niet: dat
        weigert `tile_layout`.
        """
        if len(tiles) < 2:
            return 0
        if len({t.column for t in tiles}) > 1:
            naden = sorted({t.burn.x1 for t in tiles[:-1]})
            return sum(1 for x in naden for s in spans if s.x0 < x < s.x1)
        naden = sorted({t.burn.y1 for t in tiles[:-1]})
        return sum(1 for y in naden for s in spans if s.y0 < y < s.y1)

    def _tile_json(self, tile, vorige=None) -> dict:
        """
        Eén tegel voor de buitenwereld, met erbij hoe ver de plaat moet opschuiven.

        Die verschuiving is de stap tussen de **vensters**, niet tussen de
        brandgebieden. Dat verschil is niet academisch: de brandgebieden staan
        een halve overlap verder uit elkaar dan de vensters, en wie de plaat over
        die grotere afstand opschuift, schuift de merken van het bed af. Gemeten
        op een plaat van 500 mm met een bed van 235: met de brandstap (178,75 mm)
        landen de merken op bed-x −31,5 en 28,5 — het eerste is onbereikbaar. Met
        de vensterstap (142,5 mm) landen ze op 5,0 en 65,0.

        Het venster zelf komt niet mee naar buiten: dat is een intern begrip, en
        wat de gebruiker nodig heeft is de afstand, niet de rechthoek.
        """
        return {
            "index": tile.index,
            "row": tile.row,
            "column": tile.column,
            "burn": {
                "x0_mm": tile.burn.x0,
                "y0_mm": tile.burn.y0,
                "x1_mm": tile.burn.x1,
                "y1_mm": tile.burn.y1,
            },
            "shift_mm": (
                None
                if vorige is None
                else {
                    "x": round(tile.window.x0 - vorige.window.x0, 2),
                    "y": round(tile.window.y0 - vorige.window.y0, 2),
                }
            ),
        }

    # ------------------------------------------------------------- de reeks

    def _fingerprint(self, sheet) -> str:
        """
        Een goedkope samenvatting van ontwerp en plaat.

        Genoeg om te zien dát er iets veranderd is; niet bedoeld om te zeggen
        wát. Bij twijfel ongeldig verklaren is hier het goedkope antwoord.

        **Met sha1 en nadrukkelijk niet met `hash()`.** Python zout de hash van
        strings per proces, dus een `hash()` die naar schijf gaat, komt na een
        herstart gegarandeerd anders terug — en dan is élke hervatte reeks
        ongeldig, precies het geval waarvoor dit bestand bestaat. Dat is niet
        te zien in een test die twee servers in hetzelfde proces maakt; alleen
        een echte herstart laat het zien. Gemeten: dezelfde tuple gaf
        1444352915328149249 en 5992177919278113137 in twee processen.
        """
        import hashlib

        stukken = [
            f"{sheet['width_mm']}x{sheet['height_mm']}",
            json.dumps(sheet.get("tiling"), sort_keys=True),
        ]
        for node in self.kernel.elements.elems():
            bounds = getattr(node, "bounds", None)
            stukken.append(
                f"{node.type}:"
                + ("-".join(f"{v:.1f}" for v in bounds) if bounds else "?")
            )
        return hashlib.sha1("|".join(stukken).encode()).hexdigest()

    def state(self) -> dict | None:
        data = self._read()
        if data is None:
            return None
        try:
            sheet = self._sheet()
        except DesignError:
            # Vangnet, geen pad: `Sheets` houdt er altijd precies één actief
            # (`remove` activeert eerst een ander, `_ensure` herstelt een kapotte
            # verwijzing), dus langs de gewone weg komt hier niemand. Het staat
            # er omdat `state()` uit de statuspayload gelezen wordt: als dit ooit
            # tóch gooit, valt niet deze reeks om maar het hele statusverzoek.
            # Een vel weggooien tijdens een reeks komt hieronder terecht, bij de
            # gewone vergelijking op sheet_id.
            return {
                **data,
                "aligned": False,
                "stale": True,
                "message": (
                    "The sheet this tile run belongs to is gone or is no longer "
                    "active. Choose that sheet again, or stop the run."
                ),
            }
        stale = data.get("sheet_id") != sheet["id"] or data.get(
            "fingerprint"
        ) != self._fingerprint(sheet)
        return {
            **data,
            "aligned": self._alignment is not None,
            # De gemeten stand hoort bij de uitlijning en dus bij de staat, niet
            # alleen bij het antwoord van `align`. Zonder dit verdween "1,2°
            # scheef · 0,3 mm afwijking" van het scherm bij de eerstvolgende
            # statusmelding, een paar seconden nadat de gebruiker het had
            # afgelezen — en dat getal is nu juist zijn bevestiging dat de plaat
            # goed ligt.
            "angle_deg": (
                round(self._alignment.angle_deg, 3) if self._alignment else None
            ),
            "distance_error_mm": (
                round(self._alignment.distance_error_mm, 2) if self._alignment else None
            ),
            "stale": stale,
            "message": (
                "The design or the plate has changed since this run began. The "
                "tiles already burned belong to the old design; carrying on "
                "would give you half old and half new."
                if stale
                else ""
            ),
        }

    def start(self) -> dict:
        sheet = self._sheet()
        if not (sheet.get("tiling") or {}).get("enabled"):
            raise DesignError(
                "Tiles are switched off for this sheet. Switch them on at the plate size."
            )
        opdeling = self.layout()  # weigert hier al als er geen merken passen
        self._alignment = None
        self._write(
            {
                "sheet_id": sheet["id"],
                "tiles": len(opdeling["tiles"]),
                "done": [],
                "current": 0,
                "fingerprint": self._fingerprint(sheet),
            }
        )
        return self.state()

    def align(self, points, reference: str = "markers") -> dict:
        """
        De aangetikte punten omzetten in een stand van de plaat.

        De uitkomst blijft in het geheugen van deze draai. Zodra je de app
        verlaat of een tegel afrondt, vervalt hij en moet je opnieuw aantikken:
        een bewaarde uitlijning is een aanname over waar de plaat ligt, en dat
        is precies wat je na een pauze niet moet vertrouwen.
        """
        # Dezelfde poort als bij `burn`: is de reeks verlopen — vel weg, ontwerp
        # gewijzigd — dan hoort de gebruiker dát te lezen, en niet een melding
        # over vellen die uit de diepte omhoog komt terwijl hij een merk aantikt.
        stand = self.state()
        if stand is None:
            raise DesignError("There is no tile run going.")
        if stand["stale"]:
            raise DesignError(stand["message"])
        data = self._read()
        gemeten = [Point(float(p["x_mm"]), float(p["y_mm"])) for p in points]
        try:
            if reference == "plate_corner":
                if not gemeten:
                    raise DesignError("Tap the corner of the plate first.")
                self._alignment = alignment_from_corner(Point(0.0, 0.0), gemeten[0])
            else:
                if len(gemeten) != 2:
                    raise DesignError("Uitlijnen vraagt twee aangetikte merken.")
                merken = self._marks_for(data["current"] - 1)
                self._alignment = alignment(
                    merken[0], merken[1], gemeten[0], gemeten[1]
                )
        except TilingError as e:
            self._alignment = None
            raise DesignError(str(e)) from e
        # `state()` draagt `angle_deg`/`distance_error_mm` nu zelf al, dus dit
        # is niet langer het enige antwoord dat ze meegeeft.
        return self.state()

    def _marks_for(self, boundary: int) -> tuple:
        for merk in self.layout()["marks"]:
            if merk["boundary"] == boundary:
                return tuple(Point(p["x_mm"], p["y_mm"]) for p in merk["points"])
        raise DesignError("No marks have been calculated for this tile.")

    def burn(self, confirm_reburn: bool = False) -> dict:
        # Eerst of de reeks nog geldig is, dán pas of hij uitgelijnd is. In de
        # omgekeerde volgorde krijgt iemand met een verlopen reeks te horen dat
        # hij "nog moet uitlijnen" — een uitnodiging om merken aan te tikken op
        # een opdeling die niet meer klopt. Dezelfde poort als bij `align`.
        stand = self.state()
        if stand is None:
            raise DesignError("There is no tile run going.")
        if stand["stale"]:
            raise DesignError(stand["message"])
        if self._alignment is None:
            raise DesignError(
                "This tile has not been aligned yet. Tap the two marks first, "
                "otherwise the machine does not know where the plate is."
            )
        data = self._read()
        index = data["current"]
        if index in data.get("burned", []) and not confirm_reburn:
            raise DesignError(
                "This tile has already been burned. Burning it again means the "
                "laser goes over work that is already there — only do that when the "
                "previous attempt was aborted. Confirm to carry on."
            )

        opdeling = self.layout()
        tegel = opdeling["tiles"][index]
        burn = self._brandgebied(tegel, opdeling["tiles"])
        u = self.drawing._units_per_mm()
        merken = [m for m in opdeling["marks"] if m["boundary"] == index]
        geom = (
            marker_geometry(
                [Point(p["x_mm"], p["y_mm"]) for p in merken[0]["points"]],
                self._settings(self._sheet()).marker_size_mm,
                u,
                merken[0].get("along_y", True),
            )
            if merken
            else None
        )
        mutator = TileMutator(burn, self._alignment, u, marker_geometry=geom)
        merkpunten = [Point(p["x_mm"], p["y_mm"]) for m in merken for p in m["points"]]
        self._check_bed(burn, mutator, merkpunten)
        # Twee verschuivingen over elkaar is een fout die je pas op materiaal
        # ziet: de tegelmatrix doet al wat het nulpunt zou doen, en hij is
        # gemeten in plaats van ingesteld.
        with self.drawing.verschoven(None):
            self.runner.start_job(f"Tegel {index + 1}", mutators=[mutator])
        data["burned"] = sorted(set(data.get("burned", [])) | {index})
        self._write(data)
        return {
            **self.state(),
            # Wat deze tegel werkelijk brandt. Tijdens het klippen geteld, want
            # daarna bestaat het plan uit cutcode en is het niet meer te zien.
            "burned_length_mm": round(mutator.burned_length_units / u, 2),
        }

    #: Waarmee de buitenrand van de plaat opgerekt wordt. `clip_geometry` houdt
    #: zijn bovenrand open zodat geometrie pal op een naad in precies één tegel
    #: valt; op de buitenrand van de plaat is er geen tegel erna om hem op te
    #: vangen, dus daar zou een lijn die pal op de rand ligt wegvallen. Een haar
    #: is genoeg: dit is een tie-break, geen maat.
    PLAATRAND_MARGE_MM = 1e-6

    def _brandgebied(self, tegel, alle) -> Rect:
        """
        Het brandgebied van deze tegel, met de buitenrand van de plaat opgerekt.

        Zie `PLAATRAND_MARGE_MM`: de bovenrand van een brandgebied hoort bij de
        tegel erna, maar de laatste tegel heeft er geen, dus daar moet de rand
        wél meedoen.
        """
        x1 = tegel["burn"]["x1_mm"]
        y1 = tegel["burn"]["y1_mm"]
        if x1 >= max(t["burn"]["x1_mm"] for t in alle) - 1e-9:
            x1 += self.PLAATRAND_MARGE_MM
        if y1 >= max(t["burn"]["y1_mm"] for t in alle) - 1e-9:
            y1 += self.PLAATRAND_MARGE_MM
        return Rect(tegel["burn"]["x0_mm"], tegel["burn"]["y0_mm"], x1, y1)

    def _check_bed(self, burn, mutator, marks=()) -> None:
        """
        Past deze tegel na de correctie nog in het bed?

        Een halve graad scheefstand duwt een tegel van 480 mm er zomaar 4 mm
        overheen, en dan loopt de kop tegen zijn eindaanslag terwijl er al werk
        in de plaat zit.

        De merken tellen mee, en dat is niet vanzelfsprekend: ze liggen in de
        overlapzone en dus *buiten* het brandgebied. Een controle op alleen het
        brandgebied liet een tegel door waarvan de merken negen millimeter naast
        het bed gebrand werden — gemeten, met de kop tegen zijn eindaanslag en
        materiaal in de machine.
        """
        bed = self.drawing.bed_mm()
        if bed is None:
            return
        straal = self._settings(self._sheet()).marker_size_mm / 2
        hoeken = [
            (burn.x0, burn.y0),
            (burn.x1, burn.y0),
            (burn.x0, burn.y1),
            (burn.x1, burn.y1),
        ]
        for merk in marks:
            # Een merk is een rondje: zijn rand ligt een halve maat verder dan
            # zijn middelpunt, en die rand wordt gebrand.
            hoeken.extend(
                [
                    (merk.x_mm - straal, merk.y_mm - straal),
                    (merk.x_mm + straal, merk.y_mm - straal),
                    (merk.x_mm - straal, merk.y_mm + straal),
                    (merk.x_mm + straal, merk.y_mm + straal),
                ]
            )
        hoek = math.radians(mutator.alignment.angle_deg)
        draai = complex(math.cos(hoek), math.sin(hoek))
        # Hoe ver hij eroverheen steekt, aan wélke kant dan ook. Alleen naar de
        # onderkant kijken gaf "0 mm buiten het bed" zodra de tegel er rechts of
        # onderlangs uitliep — een melding die de gebruiker niets vertelt over
        # het enige wat hij moet weten: hoeveel het scheelt.
        buiten = 0.0
        for x, y in hoeken:
            punt = complex(x, y) * draai
            mx = punt.real + mutator.alignment.dx_mm
            my = punt.imag + mutator.alignment.dy_mm
            buiten = max(buiten, -mx, -my, mx - bed[0], my - bed[1])
        if buiten > 0:
            raise DesignError(
                f"After the correction this tile falls {buiten:.1f} mm outside the bed. "
                "Lay the plate straighter or a little further in and tap again."
            )

    def advance(self) -> dict:
        data = self._read()
        if data is None:
            raise DesignError("There is no tile run going.")
        done = sorted(set(data["done"]) | {data["current"]})
        volgende = data["current"] + 1
        self._alignment = None  # de plaat gaat verschuiven; de oude stand vervalt
        if volgende >= data["tiles"]:
            self._write(None)
            return {"finished": True, "tiles": data["tiles"], "done": done}
        data.update({"done": done, "current": volgende})
        self._write(data)
        return self.state()

    def cancel(self) -> dict:
        self._alignment = None
        self._write(None)
        return {"finished": False, "cancelled": True}
