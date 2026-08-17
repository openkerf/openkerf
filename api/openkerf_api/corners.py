"""
Hoeken afronden of afschuinen.

Puur rekenwerk op geometrie: geen kernel, geen bestanden, geen HTTP. De
omrekening naar engine-eenheden en het vervangen van knopen gebeurt in
`edits.py`.

**Waarom dit bestaat, terwijl de engine afgeronde rechthoeken al kan.** Een
`elem rect` draagt `rx`/`ry` en de engine tekent hem afgerond; dat pad laten we
met rust, want daar hoort het. Maar de engine bepaalt óók dat een rechthoek
altijd rónd afloopt — een afschuining kan hij niet, en er is nergens in de
engine een fillet- of chamfer-gereedschap (de `bevel` die je er vindt is een
lijnverbinding voor het tekenen van een streekbreedte, en een laser volgt het
pad, niet de streek). Dus doen we het hier, en dan meteen voor elke vorm met
rechte zijden: veelhoeken, sterren, ingelezen contouren.

De maat is de **terugsnijafstand langs de zijde**, niet de radius. Bij een rechte
hoek zijn die gelijk — daarom ziet een afgeronde veelhoek er precies zo uit als
een afgeronde rechthoek met dezelfde `rx`. Bij een scherpere of stompere hoek
lopen ze uiteen, en dan is "hoeveel er van mijn zijde af gaat" het getal waar
iemand aan een machine iets aan heeft.
"""

from __future__ import annotations

import math

STYLES = ("round", "chamfer")

#: Verder terugsnijden dan de helft van een zijde laat twee hoeken elkaar
#: overlappen. De grens per hoek is dus de helft van de kortste aanliggende
#: zijde: dan passen twee hoeken op één zijde nog precies naast elkaar.
FRACTIE_PER_ZIJDE = 0.5


class CornerError(Exception):
    """Wat de gebruiker moet weten voordat er iets verandert."""


def _eenheid(z: complex) -> complex:
    lengte = abs(z)
    return z / lengte if lengte else 0j


def corner_geometry(geom, size_units: float, style: str):
    """
    De geometrie met afgeronde of afgeschuinde hoeken.

    Geeft `(nieuwe_geomstr, gewijzigd, overgeslagen)` terug: hoeveel hoeken zijn
    aangepakt en hoeveel er zijn overgeslagen. Dat tweede getal is niet
    cosmetisch — het is het verschil tussen "klaar" en "de helft van je hoeken
    is niets gebeurd", en dat hoort de gebruiker te lezen.

    Het origineel blijft ongemoeid.

    Een hoek doet mee als er twee **rechte** zijden op uitkomen en de maat op
    beide zijden past. Een hoek waar een boog op uitkomt blijft staan: langs een
    kromme terugsnijden is een ander probleem, en er half iets van maken is
    slechter dan het laten.
    """
    from meerk40t.core.geomstr import TYPE_LINE, Geomstr

    if style not in STYLES:
        raise CornerError(
            f"Onbekende hoekstijl: {style}. Kies 'round' om af te ronden of "
            "'chamfer' om af te schuinen."
        )
    if size_units <= 0:
        raise CornerError("De maat van een hoek moet groter zijn dan nul.")

    uit = Geomstr()
    gewijzigd = 0
    overgeslagen = 0

    for subpad in geom.as_subpaths():
        rijen = [subpad.segments[i] for i in range(subpad.index)]
        rijen = [r for r in rijen if int(r[2].real) != 0x80]  # einde-markeringen weg
        if not rijen:
            continue
        gesloten = abs(rijen[0][0] - rijen[-1][4]) < 1e-9 and len(rijen) > 2

        # Per segment: hoeveel er aan begin en eind af gaat.
        trim_begin = [0.0] * len(rijen)
        trim_eind = [0.0] * len(rijen)
        hoeken = []  # (index van de eerste zijde, index van de tweede)
        paren = list(zip(range(len(rijen) - 1), range(1, len(rijen))))
        if gesloten:
            paren.append((len(rijen) - 1, 0))

        for eerste, tweede in paren:
            a, b = rijen[eerste], rijen[tweede]
            if int(a[2].real) != TYPE_LINE or int(b[2].real) != TYPE_LINE:
                overgeslagen += 1
                continue
            if abs(a[4] - b[0]) > 1e-9:
                # Geen aansluitende hoek maar twee losse stukken.
                continue
            len_a, len_b = abs(a[4] - a[0]), abs(b[4] - b[0])
            grens = FRACTIE_PER_ZIJDE * min(len_a, len_b)
            if size_units > grens + 1e-9:
                overgeslagen += 1
                continue
            trim_eind[eerste] = size_units
            trim_begin[tweede] = size_units
            hoeken.append((eerste, tweede))
            gewijzigd += 1

        if not hoeken:
            for rij in rijen:
                uit.append_segment(*rij)
            continue

        ingekort = _inkorten(rijen, trim_begin, trim_eind)
        verbinding = {eerste: tweede for eerste, tweede in hoeken}
        for index, rij in enumerate(ingekort):
            uit.append_segment(*rij)
            tweede = verbinding.get(index)
            if tweede is None:
                continue
            _verbind(uit, rij[4], rijen[index][4], ingekort[tweede][0], style)

    if not gewijzigd:
        raise CornerError(
            "Geen enkele hoek is af te ronden of af te schuinen: er komen geen "
            "twee rechte zijden op uit, of de maat is te groot voor de zijden. "
            "Kies een kleinere maat."
        )
    return uit, gewijzigd, overgeslagen


def _inkorten(rijen, trim_begin, trim_eind):
    """Elke lijn aan beide kanten inkorten met wat de hoeken vragen."""
    ingekort = []
    for index, rij in enumerate(rijen):
        start, control, info, control2, eind = rij
        richting = _eenheid(eind - start)
        nieuw_start = start + richting * trim_begin[index]
        nieuw_eind = eind - richting * trim_eind[index]
        ingekort.append((nieuw_start, control, info, control2, nieuw_eind))
    return ingekort


def _verbind(uit, van: complex, hoekpunt: complex, naar: complex, style: str) -> None:
    """
    Het stukje dat de twee ingekorte zijden verbindt.

    Bij afschuinen is dat een rechte lijn. Bij afronden een échte boog: hij komt
    tangent uit beide zijden, dus het middelpunt ligt op de deellijn van de hoek.
    De boog wordt met drie punten opgegeven, dus we rekenen het middenpunt uit —
    `Geomstr.arc` wil een punt óp de boog, geen radius.
    """
    if style == "chamfer":
        uit.line(van, naar)
        return

    naar_a = _eenheid(van - hoekpunt)
    naar_b = _eenheid(naar - hoekpunt)
    deellijn = _eenheid(naar_a + naar_b)
    if deellijn == 0:
        # De zijden liggen in één lijn: er is geen hoek om te ronden.
        uit.line(van, naar)
        return

    cos_hoek = max(
        -1.0, min(1.0, (naar_a.real * naar_b.real + naar_a.imag * naar_b.imag))
    )
    halve = math.acos(cos_hoek) / 2
    terug = abs(van - hoekpunt)
    radius = terug * math.tan(halve)
    naar_middelpunt = terug / math.cos(halve)
    midden = hoekpunt + deellijn * (naar_middelpunt - radius)
    uit.arc(van, midden, naar)
