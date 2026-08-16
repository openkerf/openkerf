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


def _axis(plate: float, bed: float, settings: TilingSettings) -> list[tuple[float, float]]:
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
                        x_splits[column], y_splits[row], x_splits[column + 1], y_splits[row + 1]
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
