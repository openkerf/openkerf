"""
Tegels: een plaat branden die groter is dan het bed.

Dit bestand is met opzet kernelloos. Alles wat hier staat is rekenwerk op
getallen in millimeters — de opdeling, waar de naad valt, waar de merken
passen, en wat twee aangetikte punten over de stand van de plaat zeggen. Dat
is precies het deel dat je op materiaal betaalt als het fout is, en dus het
deel dat volledig te testen moet zijn zonder machine erbij.

De omrekening naar engine-eenheden (Tats) gebeurt in `tilerun.py`, op de grens.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import NamedTuple


class TilingError(Exception):
    """Wat de gebruiker moet weten voordat er materiaal in gaat."""


class Rect(NamedTuple):
    """Een rechthoek in plaatcoördinaten, in millimeters."""

    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0


@dataclass(frozen=True)
class TilingSettings:
    margin_mm: float = 10.0
    overlap_mm: float = 25.0
    marker_size_mm: float = 8.0


class Tile(NamedTuple):
    """
    Eén tegel: wat hij brandt, en wat de kop kan halen als de plaat zo ligt.

    Een NamedTuple en geen dataclass, omdat de naadverschuiving later
    `tile._replace(burn=...)` gebruikt — dat is een NamedTuple-methode.
    """

    index: int
    row: int
    column: int
    #: wat deze tegel brandt
    burn: Rect
    #: wat de kop kan halen als de plaat op deze stand ligt
    window: Rect


def _axis(
    plate: float, bed: float, settings: TilingSettings
) -> list[tuple[float, float]]:
    """
    De vensters op één as: paren (begin, eind) in plaatcoördinaten.

    Het aantal volgt uit de eis dat opeenvolgende vensters minstens `overlap_mm`
    delen. Daarna worden ze **gelijk verdeeld** in plaats van vol-vol-restje,
    zodat de overlap ruimer wordt dan het minimum en er nooit een laatste
    strookje overblijft waar geen merk in past.
    """
    usable = bed - 2 * settings.margin_mm
    if usable <= 0:
        raise TilingError(
            "Het bed is kleiner dan tweemaal de marge, dus er blijft niets over "
            "om in te branden. Zet de marge lager."
        )
    if usable >= plate:
        return [(0.0, plate)]
    if usable <= settings.overlap_mm:
        raise TilingError(
            f"Het bruikbare bed is {usable:.0f} mm en de overlap {settings.overlap_mm:.0f} mm. "
            "Twee tegels zouden elkaar dan volledig overlappen. Zet de overlap "
            "lager of de marge kleiner."
        )
    count = math.ceil((plate - settings.overlap_mm) / (usable - settings.overlap_mm))
    step = (plate - usable) / (count - 1)
    return [(i * step, i * step + usable) for i in range(count)]


def tile_layout(
    plate_w_mm: float,
    plate_h_mm: float,
    bed_w_mm: float,
    bed_h_mm: float,
    settings: TilingSettings,
) -> list[Tile]:
    """
    De opdeling van deze plaat op deze machine.

    Wordt nooit opgeslagen: hij is een functie van de maten en de instellingen,
    dus hij klopt vanzelf zodra er iets verandert.
    """
    columns = _axis(plate_w_mm, bed_w_mm, settings)
    rows = _axis(plate_h_mm, bed_h_mm, settings)

    if len(columns) > 1 and len(rows) > 1:
        # Opdelen in twee richtingen is een eigen ontwerp: elke naad krijgt
        # eigen merken, de volgorde van de tegels gaat ertoe doen en het
        # uitlijnen wordt een keten in plaats van een stap. Half werkend
        # opleveren is hier erger dan weigeren — gemeten: `_marks` legt de
        # merken van de rijgrens en de kolomgrens dan op hetzelfde punt, zodat
        # één rondje twee keer gebrand wordt.
        raise TilingError(
            "Deze plaat is in beide richtingen groter dan het bed. In twee "
            "richtingen opdelen kan nog niet: elke naad heeft dan eigen merken "
            "en een eigen volgorde. Snijd de plaat eerst op bedhoogte, of neem "
            "een smallere plaat."
        )

    x_splits = _splits([c[0] for c in columns], [c[1] for c in columns], plate_w_mm)
    y_splits = _splits([r[0] for r in rows], [r[1] for r in rows], plate_h_mm)

    tiles: list[Tile] = []
    for row, (wy0, wy1) in enumerate(rows):
        for column, (wx0, wx1) in enumerate(columns):
            tiles.append(
                Tile(
                    index=len(tiles),
                    row=row,
                    column=column,
                    burn=Rect(
                        x_splits[column],
                        y_splits[row],
                        x_splits[column + 1],
                        y_splits[row + 1],
                    ),
                    window=Rect(wx0, wy0, wx1, wy1),
                )
            )
    return tiles


def _splits(starts: list[float], ends: list[float], plate: float) -> list[float]:
    """
    De grenzen van de brandgebieden: 0, de naden, en de plaatmaat.

    De naad valt in het midden van de overlapzone. Taak 2 mag hem daarna binnen
    die zone verschuiven naar waar hij de minste vormen kruist.
    """
    bounds = [0.0]
    for left, right in zip(range(len(starts) - 1), range(1, len(starts))):
        bounds.append((starts[right] + ends[left]) / 2)
    bounds.append(plate)
    return bounds


def best_split(low_mm: float, high_mm: float, spans) -> float:
    """
    Waar de naad tussen twee tegels het beste valt.

    `spans` zijn de uitgestrektheden van de vormen langs de deelas. Een vorm
    telt als doorsneden zodra de naad er strikt binnen valt. Kandidaten zijn de
    randen van de overlapzone, het midden, en net naast elke vormgrens die in
    de zone ligt — meer standen dan dat maken het antwoord niet beter.

    Gelijkspel gaat naar de stand die het dichtst bij het midden ligt: dat houdt
    de tegels zo gelijk mogelijk van grootte.
    """
    middle = (low_mm + high_mm) / 2
    if not spans:
        return middle

    nudge = 0.01
    candidates = {low_mm, high_mm, middle}
    for a, b in spans:
        for edge in (a - nudge, b + nudge):
            if low_mm <= edge <= high_mm:
                candidates.add(edge)

    def crossings(x: float) -> int:
        return sum(1 for a, b in spans if a < x < b)

    return min(sorted(candidates), key=lambda x: (crossings(x), abs(x - middle)))


class Point(NamedTuple):
    x_mm: float
    y_mm: float


def _overlaps(a: Rect, b: Rect) -> bool:
    return not (a.x1 <= b.x0 or b.x1 <= a.x0 or a.y1 <= b.y0 or b.y1 <= a.y0)


#: Breedte van het gebrande cijfer naast een merk, als fractie van de
#: markergrootte. Een cijfer hoeft niet groot: het staat naast een rondje dat je
#: al gevonden hebt, en moet alleen 1 van 2 onderscheiden.
CIJFER_FRACTIE = 0.7

#: Ruimte tussen het rondje en zijn cijfer.
CIJFER_GAT_MM = 1.5


def mark_footprint(punt: Point, size_mm: float, zone: Rect) -> Rect:
    """
    Wat een merk in beslag neemt: het rondje én zijn cijfer.

    Het cijfer staat langs de **lange as** van de overlapzone, niet er dwars op.
    Dat is geen smaak: de breedte van de overlap is de krappe maat — bij het
    instellen wordt al geëist dat een merk erin past (`Sheets._tiling`) — en zou
    het cijfer die kant op staan, dan werden bestaande instellingen ineens te
    smal. In de lengte is er ruimte over: gemeten zijn die zones 150 tot 200 mm
    lang tegen 50 tot 72 mm breed.
    """
    half = size_mm / 2
    extra = size_mm * CIJFER_FRACTIE + CIJFER_GAT_MM
    if zone.height >= zone.width:
        return Rect(
            punt.x_mm - half,
            punt.y_mm - half,
            punt.x_mm + half,
            punt.y_mm + half + extra,
        )
    return Rect(
        punt.x_mm - half, punt.y_mm - half, punt.x_mm + half + extra, punt.y_mm + half
    )


def marker_spots(
    zone: Rect, blocked: list[Rect], size_mm: float, clearance_mm: float = 2.0
) -> tuple[Point, Point]:
    """
    Twee vrije plekken in de overlapzone, zo ver mogelijk uit elkaar.

    De zone wordt in vakjes ter grootte van een merk plus speling verdeeld; een
    vakje valt af zodra het de omhullende van een vorm raakt. Van wat overblijft
    nemen we de twee uiterste langs de lange as van de zone — verder uit elkaar
    betekent een nauwkeuriger hoek, en de uitersten zijn deterministisch waar
    'het verste paar' bij gelijkspel dat niet is.
    """
    half = size_mm / 2 + clearance_mm / 2
    extra = size_mm * CIJFER_FRACTIE + CIJFER_GAT_MM
    langs_y = zone.height >= zone.width
    # De stap is in de lengterichting groter, want daar staat het cijfer.
    stap_x = size_mm + clearance_mm + (0.0 if langs_y else extra)
    stap_y = size_mm + clearance_mm + (extra if langs_y else 0.0)

    vrij: list[Point] = []
    y = zone.y0 + half
    while y <= zone.y1 - half + 1e-9:
        x = zone.x0 + half
        while x <= zone.x1 - half + 1e-9:
            punt = Point(x, y)
            vak = mark_footprint(punt, size_mm, zone)
            binnen = (
                zone.x0 <= vak.x0
                and vak.x1 <= zone.x1
                and zone.y0 <= vak.y0
                and vak.y1 <= zone.y1
            )
            if binnen and not any(_overlaps(vak, b) for b in blocked):
                vrij.append(punt)
            x += stap_x
        y += stap_y

    if len(vrij) < 2:
        raise TilingError(
            "Er is in de overlapstrook geen plek voor twee uitlijnmerken die "
            "vrij van het werk ligt. Maak de overlap groter, of schuif een vorm "
            "bij de naad weg."
        )

    langs_y = zone.height >= zone.width
    sleutel = (lambda p: p.y_mm) if langs_y else (lambda p: p.x_mm)
    geordend = sorted(vrij, key=sleutel)
    return geordend[0], geordend[-1]


@dataclass(frozen=True)
class Alignment:
    """Hoe de plaat er nu bij ligt, ten opzichte van hoe hij getekend is."""

    angle_deg: float
    dx_mm: float
    dy_mm: float
    #: hoeveel de gemeten afstand afwijkt van de gebrande — een controle, geen correctie
    distance_error_mm: float


def alignment(
    p1: Point,
    p2: Point,
    m1: Point,
    m2: Point,
    max_angle_deg: float = 3.0,
    tolerance_mm: float = 1.0,
) -> Alignment:
    """
    De stand van de plaat, uit twee gebrande merken en twee aangetikte punten.

    Schaal wordt **niet** overgenomen en wél gecontroleerd. De afstand tussen
    twee gebrande merken verandert niet; wijkt de gemeten afstand af, dan is er
    verkeerd aangetikt. Zou je de schaal wel overnemen, dan rekent één tikfout
    van 2 mm de hele tegel uit elkaar.
    """
    plaat = complex(p2.x_mm - p1.x_mm, p2.y_mm - p1.y_mm)
    gemeten = complex(m2.x_mm - m1.x_mm, m2.y_mm - m1.y_mm)
    if abs(plaat) < 1e-6 or abs(gemeten) < 1e-6:
        raise TilingError("De twee aangetikte punten liggen op elkaar.")

    afwijking = abs(gemeten) - abs(plaat)
    if abs(afwijking) > tolerance_mm:
        raise TilingError(
            f"Deze twee punten liggen {abs(afwijking):.1f} mm "
            f"{'verder' if afwijking > 0 else 'dichter'} "
            "uit elkaar dan de merken die ik gebrand heb. Heb je het juiste "
            "merk aangetikt?"
        )

    hoek = math.atan2(gemeten.imag, gemeten.real) - math.atan2(plaat.imag, plaat.real)
    hoek = math.atan2(math.sin(hoek), math.cos(hoek))
    graden = math.degrees(hoek)
    if abs(graden) > max_angle_deg:
        raise TilingError(
            f"De plaat zou {abs(graden):.1f}° scheef liggen. Dat is meer dan een "
            "plaat scheef kán liggen zonder dat je het ziet — waarschijnlijk is "
            "het verkeerde merk aangetikt. Leg hem recht en tik opnieuw aan."
        )

    gedraaid = complex(p1.x_mm, p1.y_mm) * complex(math.cos(hoek), math.sin(hoek))
    return Alignment(
        angle_deg=graden,
        dx_mm=m1.x_mm - gedraaid.real,
        dy_mm=m1.y_mm - gedraaid.imag,
        distance_error_mm=afwijking,
    )


def alignment_from_corner(plate_corner: Point, measured: Point) -> Alignment:
    """
    Tegel 1: er zijn nog geen merken, dus uitlijnen gebeurt op de plaat zelf.

    Zonder tweede punt is er geen hoek te meten, en dan rekenen we met nul — en
    zeggen dat erbij, want een aanname die je niet ziet is een aanname die je
    op materiaal betaalt.
    """
    return Alignment(
        angle_deg=0.0,
        dx_mm=measured.x_mm - plate_corner.x_mm,
        dy_mm=measured.y_mm - plate_corner.y_mm,
        distance_error_mm=0.0,
    )


#: De segmentsoorten die echte geometrie dragen. De rest (einde, nop, punt)
#: heeft geen lengte en hoort niet in een geklipt resultaat.
def _dragende_soorten():
    from meerk40t.core.geomstr import TYPE_ARC, TYPE_CUBIC, TYPE_LINE, TYPE_QUAD

    return (TYPE_LINE, TYPE_QUAD, TYPE_CUBIC, TYPE_ARC)


def _rand_segmenten(rect_units: Rect):
    """De vier randen van het klipvenster, elk als los lijnsegment."""
    from meerk40t.core.geomstr import Geomstr

    hoeken = (
        (complex(rect_units.x0, rect_units.y0), complex(rect_units.x1, rect_units.y0)),
        (complex(rect_units.x1, rect_units.y0), complex(rect_units.x1, rect_units.y1)),
        (complex(rect_units.x1, rect_units.y1), complex(rect_units.x0, rect_units.y1)),
        (complex(rect_units.x0, rect_units.y1), complex(rect_units.x0, rect_units.y0)),
    )
    randen = Geomstr()
    for begin, eind in hoeken:
        randen.line(begin, eind)
        randen.end()
    return randen


def _stukken(geom, index: int, ts):
    """
    De stukken van één segment, gesplitst op de gegeven parameters.

    Lijnen, quads en cubics laat de engine zelf splitsen; die takken bestaan en
    werken. **Bogen niet:** `Geomstr.split` heeft geen tak voor `TYPE_ARC` en
    geeft er nul stukken voor terug, waardoor een boog die de naad middenin
    kruist uit beide tegels verdwijnt. Gemeten op een cirkel met de naad naast
    de laslijnen: een halve cirkel spoorloos.

    Zelf splitsen kan exact, want een boog door drie punten van een cirkel ís
    die cirkel: elk stuk wordt opgebouwd uit zijn begin, zijn midden en zijn
    eind, alle drie opgevraagd met `position`.
    """
    from meerk40t.core.geomstr import Geomstr, TYPE_ARC

    if not ts:
        return [geom.segments[index]]
    if int(geom.segments[index][2].real) != TYPE_ARC:
        return list(geom.split(index, sorted(ts)))

    grenzen = [0.0] + sorted(ts) + [1.0]
    hulp = Geomstr()
    for begin, eind in zip(grenzen, grenzen[1:]):
        if eind - begin < 1e-12:
            continue
        hulp.arc(
            geom.position(index, begin),
            geom.position(index, (begin + eind) / 2),
            geom.position(index, eind),
        )
    return [hulp.segments[i] for i in range(hulp.index)]


def clip_geometry(geom, rect_units: Rect):
    """
    De geometrie die binnen dit brandgebied valt, als nieuwe Geomstr.

    Elk segment wordt gesplitst op zijn snijpunten met de vier vensterranden,
    en van de stukken houden we wat met zijn midden binnen ligt. Splitsen
    gebeurt op de parameter, dus **een boog blijft een boog** — er wordt niet
    geïnterpoleerd, en dat is te zien aan het werkstuk.

    `rect_units` is in engine-eenheden, niet in millimeters: het klippen gebeurt
    in dezelfde ruimte als de geometrie. Het origineel wordt niet aangeraakt.

    **De onderrand telt mee, de bovenrand niet.** Een lijn die pal op een naad
    ligt wordt door geen van beide tegels doorgesneden — hij kruist niets — dus
    zonder dat verschil zou zijn midden in allebei de rechthoeken vallen en ging
    de laser er tweemaal overheen. Met `x0 <= midden < x1` valt hij altijd in de
    tegel erna, en nooit in geen van beide. De uiterste rand van de plaat is
    daarmee de enige plek waar iets buiten de boot valt; `TileRun.burn` rekt het
    brandgebied van de laatste tegel daarom een haar op.

    **Waarom niet `geomstr.Clip`, die dit lijkt te doen?** Omdat hij op bogen
    stukloopt: `Clip.inside` vraagt zijn middens in één keer op en belandt in de
    oneindige recursie van `Geomstr._arc_position` (`geomstr.py:5784`, `line` in
    plaats van `_line`), en `Clip.polycut` laat een boogsegment vallen dat de
    grens niet eens kruist. Upstream merkt het niet omdat hun eigen `Clip`-test
    alleen lijnen klipt. Wij wijzigen niets in `meerk40t/`; dit is de weg
    eromheen, en voor ons geval ook de eenvoudigere.
    """
    from meerk40t.core.geomstr import Geomstr

    randen = _rand_segmenten(rect_units)
    dragend = _dragende_soorten()

    # Eerst alle stukken verzamelen, dan pas filteren: het midden van een stuk
    # is alleen te vragen aan een Geomstr die het stuk al bevat.
    stukken = Geomstr()
    for index in range(geom.index):
        if int(geom.segments[index][2].real) not in dragend:
            continue
        snijpunten = set()
        for rand in range(randen.index):
            if int(randen.segments[rand][2].real) not in dragend:
                continue
            for t, _ander in geom.intersections(index, randen.segments[rand]):
                # De uiteinden zelf zijn geen splitsing: daar houdt het segment
                # toch al op, en splitsen op 0 of 1 levert een leeg stuk.
                if 1e-9 < float(t) < 1 - 1e-9:
                    snijpunten.add(round(float(t), 9))
        for stuk in _stukken(geom, index, sorted(snijpunten)):
            stukken.append_segment(*stuk)

    binnen = Geomstr()
    for index in range(stukken.index):
        midden = stukken.position(index, 0.5)
        if (
            rect_units.x0 <= midden.real < rect_units.x1
            and rect_units.y0 <= midden.imag < rect_units.y1
        ):
            binnen.append_segment(*stukken.segments[index])
    return binnen
