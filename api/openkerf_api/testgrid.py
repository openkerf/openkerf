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

import re
import unicodedata

from .edits import DesignError

MAX_CELLS = 400  # A 20x20 sweep is already more than anyone reads off a photo.

# De laag waar alle opschriften van alle borden in gaan. Eén naam op één plek,
# want zowel de generator als het tekengedeelte moet hem herkennen: hij is een
# láág van het bord en geen laag van de gebruiker, en mag dus nooit vers werk
# opvangen (zie Drawing._single_layer).
LABEL_LAYER = "Raster-labels"

# Hoe de groep heet die één bord bij elkaar houdt.
BOARD_LABEL = "Testraster"


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


def _passes(value) -> int:
    """
    Hoe vaak de kop over elk vakje gaat, voor het hele bord tegelijk.

    Streng op halve passes: `int(2.5)` is 2, en dat is precies het soort stille
    afronding waar iemand op materiaal achter komt. Een leeg veld is wél goed —
    het formulier stuurt "" voor "niet ingevuld".
    """
    if value in (None, ""):
        return 1
    try:
        getal = float(value)
    except (TypeError, ValueError) as e:
        raise DesignError("passes moet een heel getal van 1 of meer zijn.") from e
    if getal != int(getal) or int(getal) < 1:
        raise DesignError("passes moet een heel getal van 1 of meer zijn.")
    return int(getal)


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

# ------------------------------------------------------- de letter op het bord
#
# Een testbord is een bewijsstuk: over twee weken moet je er nog aan kunnen
# aflezen welk vakje 200 mm/s bij 40 % was. Welke letter daar staat, mag dus
# niet afhangen van wat je toevallig het laatst in het tekstvenster koos.
#
# En dat gebeurde wél. `linetext` valt zonder `-f` terug op `context.last_font`
# (meerk40t/extra/hershey.py:895), een instelling die de engine bewaart en die
# élke tekstplaatsing overschrijft — ook een die de gebruiker allang vergeten
# is. Een bord met de opschriften in Apple Chancery is precies wat je niet wilt.
#
# `meerk40t.jhf` is de ingebouwde Hershey-letter van de engine: hij komt niet
# van de schijf, staat er dus altijd, en is enkellijnig — precies wat een
# gegraveerd opschrift wil (een TrueType-omtrek graveert de contour van de
# letter, niet de letter). De rest is terugval voor het geval upstream hem ooit
# hernoemt.
LABEL_FONTS = ("meerk40t.jhf", "rowmans.jhf", "romant.shx", "arial.ttf")

# Waarop we de letter laten renderen. De hoogte wordt daarna alsnog exact
# gezet met `_scale_to_height`, maar een vaste startmaat houdt het resultaat
# reproduceerbaar in plaats van afhankelijk van de console-standaard.
LABEL_FONT_SIZE_PX = 20

# Hoe breed een teken van die letter is, als deel van de teksthoogte. Nagemeten
# op de werkelijk getekende opschriften (0,53–0,66 afhankelijk van welke tekens
# erin staan); we rekenen aan de ruime kant, want dit reserveert ruimte en een
# tekort laat het opschrift buiten het bord steken.
CAPTION_CHAR_RATIO = 0.62

# Waar een gegraveerd opschrift ophoudt leesbaar te zijn. Kleiner dan dit is
# het geen opschrift meer maar een streep, dus krimpt het niet verder — het
# breekt dan af naar een volgende regel.
MIN_CAPTION_MM = 2.0

# Hoeveel hoger de ene opschriftregel boven de andere staat, als deel van de
# teksthoogte. 1,4 is de gebruikelijke regelafstand; krapper gaan de stokken
# en staarten van twee regels door elkaar lopen en is het gegraveerd niet meer
# te lezen.
CAPTION_LINE_PITCH = 1.4

# ------------------------------------------------- waar het bord komt te liggen
#
# Gat T9: Start X/Y sloeg op de linkerbovenhoek van het raster. Een testbord leg
# je op een reststuk, en dan weet je waar het mídden van dat stuk ligt — niet
# waar de hoek van een raster moet komen dat je nog niet gezien hebt. LightBurn
# vraagt X Center/Y Center; wij laten de keuze staan, want vanaf een hoek is bij
# een verse plaat juist handiger.
#
# Het midden slaat op het hele bord inclusief labels en opschrift. Het raster
# centreren terwijl de rijlabels er links buiten steken, legt het bord scheef —
# en juist die labels waren de aanleiding voor T11.
ANCHORS = ("corner", "center")

# Hoe ver het randkader (T10) om het bord heen ligt. Ruim genoeg om niet tegen
# de opschriften aan te lopen, krap genoeg om geen plaat te verspillen.
BORDER_PAD_MM = 2.0

# De labellaag brandt niet mee in de sweep: hij moet leesbaar zijn wat er ook
# uit de proef komt. Deze twee waren hardgecodeerd; sinds T10 zijn ze in te
# stellen, met dezelfde getallen als terugval.
DEFAULT_LABEL_SPEED_MM_S = 80.0
DEFAULT_LABEL_POWER_PERCENT = 30.0


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
    # De reden staat sinds punt 2 náást het voorbeeld in beeld in plaats van
    # onder de vouw, dus hij is nu tekst voor een mens en geen veldnaam uit de
    # API. "speed_max moet minstens speed_min zijn" is geen Nederlands.
    label = AXES[naam]["label"]
    laag = _positive(lo, f"De {label} bij 'van'")
    hoog = _positive(hi, f"De {label} bij 'tot'")
    if hoog < laag:
        raise DesignError(
            f"De {label} bij 'tot' moet minstens de {label} bij 'van' zijn."
        )
    if naam == "power" and hoog > 100:
        raise DesignError("Vermogen kan niet boven 100 procent.")
    if naam == "interval" and hoog > 5:
        raise DesignError("Een interval boven 5 mm is geen gravering meer.")
    return _spread(laag, hoog, _steps(aantal, f"Het aantal stappen {label}"))


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
    # Eén getal voor het hele bord. Als as zou het een bord opleveren dat
    # niemand meer terugleest: passes vermenigvuldigt de brandtijd en verandert
    # de uitkomst van elk vakje, dus twee kolommen met verschillende passes
    # zijn twee proeven op één plank.
    passes=1,
    cell_mm=8.0,
    gap_mm=2.0,
    origin_x_mm=10.0,
    origin_y_mm=10.0,
    anchor="corner",
    text=True,
    border=False,
    label_speed_mm_s=None,
    label_power_percent=None,
    material_id=None,
    machine_id=None,
    thickness_mm=None,
    # Het opschrift hoort bij het bord en niet bij de sweep, maar het bepaalt
    # wél hoe breed het bord wordt — dus moet de planner het kennen. Weglaten
    # mag: dan rekent hij met het opschrift dat hij zelf al kan afleiden.
    caption=None,
    material_name=None,
    stamp=None,
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

    aantal_passes = _passes(passes)
    cell = _positive(cell_mm, "cell_mm")
    gap = float(gap_mm)
    if gap < 0:
        raise DesignError("gap_mm kan niet negatief zijn.")
    pitch = cell + gap

    if anchor not in ANCHORS:
        raise DesignError("Kies 'corner' (vanaf de hoek) of 'center' (vanaf het midden).")
    tekst = bool(text)
    kader = bool(border)
    label_speed = _positive(
        DEFAULT_LABEL_SPEED_MM_S if label_speed_mm_s in (None, "") else label_speed_mm_s,
        "label_speed_mm_s",
    )
    label_power = _positive(
        DEFAULT_LABEL_POWER_PERCENT
        if label_power_percent in (None, "")
        else label_power_percent,
        "label_power_percent",
    )
    if label_power > 100:
        raise DesignError("Het vermogen van de labellaag kan niet boven 100 procent.")

    breedte = round(columns * pitch - gap, 3)
    hoogte = round(rows * pitch - gap, 3)

    # Wat er buiten de vakjes om nog gebrand wordt, en dus meetelt voor "past dit
    # op mijn plaat". Hier vóór de plaatsing berekend, want bij `anchor="center"`
    # bepaalt juist deze maat waar de linkerbovenhoek terechtkomt.
    #
    # Hoeveel ruimte de rijlabels links van het raster nodig hebben. Ze worden
    # daar gegraveerd, en bij Start X 10 met driecijferige snelheden staan ze
    # buiten het bed — dan brandt de machine ze niet en is het bord onleesbaar.
    # Het vectorfont is ongeveer 0,62 × de teksthoogte per teken breed; dit is
    # dus een schatting, en hij wordt als schatting gemeld.
    tekst_hoogte = max(2.0, cell * 0.35)
    opschrift_hoogte = max(2.5, cell * 0.4)
    langste = max(
        (len(toon(row_axis, waarde)) for waarde in waarden[row_axis]), default=0
    )
    marge = round(2 + 0.62 * tekst_hoogte * langste, 1)

    # Het opschrift past zich aan het bord aan, niet andersom.
    #
    # Het stond op één regel en het bord kreeg er rechts ruimte bij tot die
    # regel paste: op een raster van 38 mm werd het bord 134 mm breed. Dat is
    # geen bord meer maar een wapperende banier, en het maakt het testpaneel
    # onbruikbaar breed op het scherm. Nu krimpt het opschrift eerst mee tot
    # het binnen de bordbreedte valt, en breekt het pas af naar een tweede
    # regel als het onder de leesbaarheidsgrens zou zakken. Het bord wordt dus
    # nooit breder dan zijn eigen vakjes plus de rijlabels — alleen iets hoger.
    opschrift_regels = (
        caption_lines(
            {
                "caption": caption,
                "material_name": material_name,
                "stamp": stamp,
                "thickness_mm": thickness_mm,
                "operation": operation,
                "passes": aantal_passes,
                "row_axis": row_axis,
                "column_axis": column_axis,
                # De vaste grootheid hoort erbij: zonder haar is het bord over
                # twee weken niet terug te rekenen naar een instelling. Dit
                # stond in `caption_text` al klaar, maar de sleutels werden
                # nooit meegegeven — de tak vuurde dus nooit.
                **{
                    f"{naam}_min": vaste[naam]
                    for naam in AXES
                    if vaste[naam] is not None
                },
            }
        )
        if tekst
        else []
    )
    if opschrift_regels:
        beschikbaar = marge + breedte
        # Eerst krimpen: de hoogte waarbij de langste regel nog net past.
        krap = beschikbaar / (
            CAPTION_CHAR_RATIO * max(len(r) for r in opschrift_regels)
        )
        if krap < MIN_CAPTION_MM:
            # Zelfs op de ondergrens past het niet — dan een regel erbij.
            per_regel = max(8, int(beschikbaar / (CAPTION_CHAR_RATIO * MIN_CAPTION_MM)))
            opschrift_regels = _breek(opschrift_regels, per_regel)
            krap = beschikbaar / (
                CAPTION_CHAR_RATIO * max(len(r) for r in opschrift_regels)
            )
        opschrift_hoogte = round(max(MIN_CAPTION_MM, min(opschrift_hoogte, krap)), 3)

    # Boven het raster: de kolomlabels 2 mm erboven, en daar weer boven het
    # opschrift. `_caption` zet de ónderkant van de onderste opschriftregel op
    # `origin_y - 4 - hoogte`, dus de bovenkant van de bovenste ligt daar nog
    # een teksthoogte plus de regelafstanden boven. Nagemeten tegen de
    # werkelijk getekende vormen (zie
    # `test_the_reported_size_covers_everything_that_is_drawn`).
    boven = round(
        max(
            2 + tekst_hoogte,
            4
            + 2 * opschrift_hoogte
            + max(0, len(opschrift_regels) - 1) * CAPTION_LINE_PITCH * opschrift_hoogte,
        ),
        1,
    )

    links_pad = (marge if tekst else 0.0) + (BORDER_PAD_MM if kader else 0.0)
    boven_pad = (boven if tekst else 0.0) + (BORDER_PAD_MM if kader else 0.0)
    rechts_pad = onder_pad = BORDER_PAD_MM if kader else 0.0

    buiten_breedte = round(links_pad + breedte + rechts_pad, 3)
    buiten_hoogte = round(boven_pad + hoogte + onder_pad, 3)

    if anchor == "center":
        buiten_x = round(float(origin_x_mm) - buiten_breedte / 2, 3)
        buiten_y = round(float(origin_y_mm) - buiten_hoogte / 2, 3)
        origin_x_mm = round(buiten_x + links_pad, 3)
        origin_y_mm = round(buiten_y + boven_pad, 3)
    else:
        origin_x_mm = float(origin_x_mm)
        origin_y_mm = float(origin_y_mm)
        buiten_x = round(origin_x_mm - links_pad, 3)
        buiten_y = round(origin_y_mm - boven_pad, 3)

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
        "passes": aantal_passes,
        "row_axis": row_axis,
        "column_axis": column_axis,
        "rows": rows,
        "columns": columns,
        "cell_mm": cell,
        "gap_mm": gap,
        "origin_x_mm": origin_x_mm,
        "origin_y_mm": origin_y_mm,
        "width_mm": breedte,
        "height_mm": hoogte,
        # T9/T10: waar het bord ligt en hoe groot het écht is. `origin_*` is en
        # blijft de linkerbovenhoek van de vákjes — daar rekent de foto-overlay
        # mee — en `outer_*` is het hele bord inclusief opschriften en kader.
        "anchor": anchor,
        "text": tekst,
        "border": kader,
        "label_speed_mm_s": label_speed,
        "label_power_percent": label_power,
        "outer_x_mm": buiten_x,
        "outer_y_mm": buiten_y,
        "outer_width_mm": buiten_breedte,
        "outer_height_mm": buiten_hoogte,
        "center_x_mm": round(buiten_x + buiten_breedte / 2, 3),
        "center_y_mm": round(buiten_y + buiten_hoogte / 2, 3),
        # Het opschrift hoort bij de planning omdat het de breedte bepaalt.
        # `caption_text` staat hier al berekend zodat de tekenaar exact dezelfde
        # regel zet als waar hier ruimte voor gereserveerd is.
        "caption": str(caption or "").strip(),
        "material_name": material_name,
        "stamp": stamp,
        "caption_lines": opschrift_regels,
        "caption_text": " · ".join(opschrift_regels),
        # De maat waarop het opschrift past; de tekenaar hoeft hem dan niet
        # opnieuw te raden en zet exact wat hier gemaat is.
        "caption_height_mm": opschrift_hoogte if opschrift_regels else 0.0,
    }
    # Wat dit bord gaat kosten aan tijd, vóórdat er iets getekend is.
    #
    # Nodig omdat interval als as de brandtijd stil kan vermenigvuldigen: een
    # rij op 0,05 mm legt zes keer zoveel regels als een rij op 0,3 mm, en dat
    # zie je aan geen enkel getal in het formulier. Zelfde som als
    # `DrawingService._geometry_estimate`: lengte gedeeld door snelheid, plus de
    # sprong naar het volgende vakje. Het bord is nog niet getekend, dus dit kan
    # niet uit de elementenboom komen.
    RAPID_MM_S = 100.0
    seconden = 0.0
    for entry in cells:
        snelheid = entry["speed_mm_s"] or 0
        if snelheid <= 0:
            continue
        interval = entry.get("interval_mm")
        if interval_telt and interval:
            # Rasteren: regel na regel over het vlak, plus één regelsprong.
            regels = cell / interval
            brand_mm = regels * cell + cell
        else:
            # Snijden of vectorgraveren: de omtrek van het vakje.
            brand_mm = 4 * cell
        # Elke pass brandt de hele weg opnieuw; de sprong naar het volgende
        # vakje is er één keer. Zonder deze factor meldt een bord van twee
        # passes de helft van zijn tijd, en dat getal gebruiken we ook om te
        # zeggen of het binnen een dag past.
        seconden += aantal_passes * brand_mm / snelheid + pitch / RAPID_MM_S
    plan["seconds"] = round(seconden, 1)

    plan["label_margin_mm"] = marge if tekst else 0.0
    # Staan de rijlabels nog op het bed? Zonder opschriften is die vraag weg.
    plan["label_room"] = (not tekst) or origin_x_mm >= marge
    # En het bord als geheel: sinds T9 kan het midden het ankerpunt zijn, en dan
    # is "zet Start X hoger" geen antwoord meer dat de gebruiker kan geven.
    plan["board_room"] = buiten_x >= 0 and buiten_y >= 0

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


# -------------------------------------------------- is dit knooppunt van ons?
#
# De koppeling raster → knooppunt staat in de database en overleeft een
# herstart; id's worden per document uitgedeeld. `meerk40t:3` op vel 2 is dus
# een ánder ding dan `meerk40t:3` op vel 1. Wie een raster van het canvas haalt
# terwijl hij op een ander vel staat, wiste daar het werk — gemeten: dertien
# lagen van een ander raster, zonder een woord. Daarom kijkt het weghalen niet
# alleen naar het id maar ook of het gevonden knooppunt werkelijk deze cel is.
# Dezelfde eis als `DesignReader._grid_for` stelt bij het markeren.

MAAT_SPELING_MM = 0.6  # de lijndikte telt mee in `bounds`


def is_raster_groep(node) -> bool:
    return str(getattr(node, "type", "")).startswith("group")


def is_cel_operatie(node, cell: dict) -> bool:
    speed = getattr(node, "speed", None)
    power = getattr(node, "power", None)
    if speed is None or power is None:
        return False
    try:
        return (
            abs(float(speed) - float(cell["speed_mm_s"])) <= 0.01
            and abs(float(power) - float(cell["power_percent"]) * 10) <= 0.1
        )
    except (TypeError, ValueError):
        return False


def is_cel_element(node, cell: dict) -> bool:
    from meerk40t.core.units import UNITS_PER_MM

    bounds = getattr(node, "bounds", None)
    if not bounds or len(bounds) != 4:
        return False
    x0, y0, x1, y1 = (float(v) / UNITS_PER_MM for v in bounds)
    gemeten = (x0, y0, x1 - x0, y1 - y0)
    verwacht = (cell["x_mm"], cell["y_mm"], cell["width_mm"], cell["height_mm"])
    return all(abs(a - b) <= MAAT_SPELING_MM for a, b in zip(gemeten, verwacht))


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


def _woorden(tekst) -> list[str]:
    """De losse woorden van een stuk tekst, klein en zonder accenten."""
    plat = unicodedata.normalize("NFKD", str(tekst or "").lower())
    plat = "".join(c for c in plat if not unicodedata.combining(c))
    return [w for w in re.split(r"[^0-9a-z]+", plat) if w]


def _al_gezegd(woord: str, gezegd: list[str]) -> bool:
    """
    Staat dit woord al in het opschrift dat de gebruiker zelf typte?

    Op stam en niet op letter: wie "3MM Acryl Graveren" intikt heeft het
    materiaal "Acrylaat (geëxtrudeerd)" al benoemd, ook al staat er een andere
    uitgang achter. Korte woorden doen niet mee — "mm" of "cm" komt overal in
    voor en zou halve opschriften wegvagen.
    """
    if len(woord) < 4:
        return False
    return any(w.startswith(woord) or woord.startswith(w) for w in gezegd if len(w) >= 4)


# Hoe een bewerking op het hout heet. `graveren-raster` is een sleutel uit onze
# database, geen woord dat je op een plankje graveert.
OPERATION_LABELS = {
    "snijden": "snijden",
    "graveren-vector": "graveren vector",
    "graveren-raster": "graveren raster",
    "markeren": "markeren",
}


def caption_lines(plan: dict) -> list[str]:
    """
    Het opschrift zoals het op het hout komt, als losse regels.

    Twee regels en geen banier. De eerste zegt wáár dit over gaat — het woord
    dat de gebruiker zelf koos, of anders het materiaal — en de tweede hoe het
    gebrand is. Ze staan onder elkaar omdat het bord een bord moet blijven: een
    opschrift dat op één regel doorloopt was op een raster van 38 mm ruim
    130 mm breed, en dan is het bord drie keer zo breed als de proef erop.

    Wat de gebruiker zelf al zei, herhalen we niet. "3MM Acryl Graveren" naast
    "Acrylaat (geëxtrudeerd) · 3 mm · graveren-raster" is dezelfde zin drie
    keer; dat maakt het opschrift lang zonder er iets aan toe te voegen.

    Hier en niet in de tekenaar, want `plan_grid` moet er ruimte voor
    reserveren — en wat wij als maat melden moet dekken wat er brandt.
    """
    eigen = str(plan.get("caption") or "").strip()
    gezegd = _woorden(eigen)

    kop = [eigen] if eigen else []
    materiaal = str(plan.get("material_name") or "").strip()
    if materiaal:
        stam = _woorden(materiaal)
        if not (stam and _al_gezegd(stam[0], gezegd)):
            kop.append(materiaal)
    dikte = plan.get("thickness_mm")
    if dikte and not re.search(rf"(?<![0-9]){dikte:g}\s*mm", " ".join(gezegd)):
        kop.append(f"{dikte:g} mm")

    bewerking = plan.get("operation") or ""
    naam = OPERATION_LABELS.get(bewerking, str(bewerking))
    # Alleen het deel dat nog niet gezegd is: wie "Graveren" typte hoeft geen
    # tweede "graveren" op zijn plank, maar "raster" tegenover "vector" is wél
    # het verschil tussen twee heel andere proeven.
    resterend = " ".join(w for w in naam.split() if not _al_gezegd(w, gezegd))
    voet = [resterend] if resterend else []

    # Welke as welke grootheid draagt. Zonder dit is een bord met vrij gekozen
    # assen niet te lezen: "0,05" links kan snelheid of interval zijn.
    # LightBurn zet de asnamen naast de waarden; wij hebben ze harder nodig,
    # want bij ons staat niet vast wát er op de as staat.
    assen = (plan.get("row_axis", "speed"), plan.get("column_axis", "power"))
    voet.append(f"{AXES[assen[0]]['label']} v / {AXES[assen[1]]['label']} >")
    # De grootheid die níét op een as staat, hoort er ook op: zonder haar is
    # een bord over twee weken niet terug te rekenen naar een instelling.
    for as_naam in AXES:
        if as_naam in assen or plan.get(f"{as_naam}_min") is None:
            continue
        voet.append(f"{AXES[as_naam]['label']} {toon(as_naam, plan[f'{as_naam}_min'])}")
    # Het aantal passes hoort bij de uitkomst: hetzelfde vakje op 8 mm/s is een
    # andere proef in één dan in twee passes. Bij één pass staat het er niet —
    # dat is de normale gang van zaken, en het opschrift bepaalt de bordbreedte.
    passes = int(plan.get("passes") or 1)
    if passes > 1:
        voet.append(f"{passes} passes")
    if plan.get("stamp"):
        voet.append(str(plan["stamp"]))

    regels = [" · ".join(kop), " · ".join(voet)]
    return [r for r in regels if r]


def caption_text(plan: dict) -> str:
    """Dezelfde regels achter elkaar — voor waar één string genoeg is."""
    return " · ".join(caption_lines(plan))


def _breek(regels: list[str], tekens: int) -> list[str]:
    """
    Regels die te lang zijn afbreken op de scheidingstekens die er al in staan.

    Alleen als het echt niet past: het opschrift krimpt eerst mee (zie
    `plan_grid`), en pas onder de leesbaarheidsgrens gaat er een regel bij.
    Een deel dat op zichzelf al te lang is blijft heel — afbreken middenin
    "Acrylaat" levert geen leesbaarder bord op.
    """
    uit: list[str] = []
    for regel in regels:
        lopend = ""
        for deel in regel.split(" · "):
            kandidaat = f"{lopend} · {deel}" if lopend else deel
            if lopend and len(kandidaat) > tekens:
                uit.append(lopend)
                lopend = deel
            else:
                lopend = kandidaat
        if lopend:
            uit.append(lopend)
    return uit


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


def raster_supported(kernel) -> bool:
    """
    Kan deze engine een rasterlaag daadwerkelijk branden?

    Nee, als er geen rasteraar geregistreerd is. `op raster` zet zijn vormen
    tijdens het plannen om in een bitmap via `render-op/make_raster`, en die
    dienst wordt **alleen door de wxPython-GUI geregistreerd**
    (`meerk40t/gui/plugin.py:79`, met als commentaar "used to do cut planning").
    Ontbreekt hij, dan neemt `OpRasterNode.preprocess` de `strip_rasters`-tak:
    de laag gooit zijn eigen kinderen weg en levert nul cutcode.

    Gemeten op onze headless server: een ontwerp met alleen rasterlagen geeft
    `/api/job/estimate?exact=1` → 0,0 s over 0 delen. Het bord komt blanco uit
    de machine. Daarom wordt dit gemeld in plaats van gehoopt.
    """
    try:
        return kernel.root.lookup("render-op/make_raster") is not None
    except Exception:
        return False


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

    def draw(self, plan: dict, cells: list[dict]) -> tuple[list[dict], str | None]:
        """
        Draw the grid: one square per cell, each in its own operation.

        Returns the cells enriched with the element and operation ids, so a
        photo overlay can later map a tap back to speed and power — plus het
        id van de groep die het bord bij elkaar houdt.

        Het groeperen gebeurt binnen dezelfde handeling als het tekenen. Een
        bord is één ding, dus het maken ervan is één keer ongedaan maken; stond
        het groeperen erbuiten, dan haalde de eerste `undo` alleen de groep weg
        en bleven er negentien losse vormen op het bed liggen.
        """
        op_type = OPERATION_TYPES.get(plan["operation"])
        if op_type is None:
            raise DesignError(f"Onbekende bewerking: {plan['operation']}")

        # Het hele bord, niet alleen de vakjes: opschriften en randkader worden
        # net zo goed gebrand, en juist die staken links en boven uit (T11).
        buiten_x = plan.get("outer_x_mm", plan["origin_x_mm"])
        buiten_y = plan.get("outer_y_mm", plan["origin_y_mm"])
        buiten_b = plan.get("outer_width_mm", plan["width_mm"])
        buiten_h = plan.get("outer_height_mm", plan["height_mm"])
        bed = self._bed_mm()
        # Alleen rechts en onder is dit een weigering. Links en boven staken de
        # opschriften al uit sinds T11, en daar is bewust voor melden gekozen in
        # plaats van blokkeren: het rasterdeel brandt dan gewoon, alleen de
        # labels niet. `label_room` en `board_room` zeggen het in het voorbeeld.
        if bed and (buiten_x + buiten_b > bed[0] or buiten_y + buiten_h > bed[1]):
            raise DesignError(
                f"Het bord ({buiten_b:.0f}×{buiten_h:.0f} mm vanaf "
                f"{buiten_x:.0f},{buiten_y:.0f}) valt buiten het bed "
                f"van {bed[0]:.0f}×{bed[1]:.0f} mm."
            )

        # Zonder dit belandt elke cel óók in elke bestaande operatie waarvan de
        # kleur matcht — de engine classificeert nieuwe elementen automatisch.
        # Het raster zou dan dubbel gebrand worden: één keer op de instelling van
        # de cel en één keer op die van de andere laag. Dat maakt de test
        # waardeloos en verbrandt materiaal.
        classify = getattr(self.elements, "classify_new", None)
        if classify is not None:
            self.elements.classify_new = False
        try:
            drawn, group = self._draw_cells(plan, cells)
        finally:
            if classify is not None:
                self.elements.classify_new = classify

        self.elements.signal("rebuild_tree", "all")
        self.elements.signal("refresh_scene", "Scene")
        return drawn, (getattr(group, "id", None) if group is not None else None)

    def _group_board(self, members: list):
        """
        Vouw dít bord tot één groep — vakjes, aslabels, opschrift en kader.

        Een raster is één ding: half verslepen slaat nergens op, en als losse
        vierkanten vult het de selectie en het canvas met ruis. De cellen
        houden wél elk hun eigen operatie — anders brandt de sweep niet.

        Wie erbij hoort is wat dit bord zelf getekend heeft, niet wat een
        rondgang door het document oplevert. Die rondgang zocht de opschriften
        op de labellaag — en die is gedeeld door álle borden, dus een tweede
        bord trok de opschriften van het eerste zijn eigen groep in. Daarna
        selecteerde één aslabel van bord 1 het hele bord 2, en verhuisde het
        mee zodra je bord 2 versleepte.
        """
        if len(members) < 2:
            return None
        self.elements.set_emphasis(members)
        self.kernel.console("group\n")
        for node in self.elements.elem_branch.flat():
            if node.type == "group" and any(c in members for c in node.children):
                # Een naam, zodat het paneel en de selectiebalk "Testraster"
                # kunnen zeggen in plaats van "groep".
                node.label = BOARD_LABEL
                return node
        return None

    def _draw_cells(self, plan: dict, cells: list[dict]) -> tuple[list[dict], object]:
        op_type = OPERATION_TYPES[plan["operation"]]
        drawn = []
        # Alles wat níét een vakje is maar wel bij dit bord hoort.
        extras: list = []
        with self.elements.undoscope("Testraster genereren"):
            for cell in cells:
                node = self._square(cell, gevuld=op_type == "op raster")
                instelling = {
                    "type": op_type,
                    "speed": cell["speed_mm_s"],
                    # MeerK40t's power runs 0-1000, not 0-100.
                    "power": cell["power_percent"] * 10,
                    "label": _cel_label(plan, cell),
                    # Voor het hele bord gelijk; de sweep zit in snelheid,
                    # vermogen en interval.
                    "passes": int(plan.get("passes") or 1),
                }
                # De lijnafstand heet bij de engine dpi. Alleen een rasterop
                # kent hem; op de andere zou het een genegeerde sleutel zijn.
                if op_type == "op raster" and cell.get("interval_mm"):
                    instelling["dpi"] = int(round(25.4 / cell["interval_mm"]))
                operation = self.elements.op_branch.add(**instelling)
                operation.add_reference(node)
                drawn.append({**cell, "element_id": None, "operation_id": None,
                              "_node": node, "_op": operation})

            # T10: LightBurn heeft `Enable Text` en `Enable Border`. Voor een
            # proefje op een restje is het opschrift verspilling; voor een bord
            # dat in de kast gaat is het het halve bewijsstuk. Standaard aan.
            if plan.get("text", True):
                self._label_axes(plan, cells, extras)
                self._caption(plan, extras)
            if plan.get("border"):
                self._border(plan, extras)

            # Binnen dezelfde handeling: het bord is één ding, dus ook één stap
            # in de geschiedenis.
            group = self._group_board([entry["_node"] for entry in drawn] + extras)

        # Ids only exist once the engine has handed them out.
        self.elements.validate_ids()
        for entry in drawn:
            entry["element_id"] = entry.pop("_node").id
            entry["operation_id"] = entry.pop("_op").id
        return drawn, group

    def _label_axes(self, plan: dict, cells: list[dict], extras: list):
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
            labels = labels or self._label_op(plan)
            self._place(
                node,
                right=plan["origin_x_mm"] - 2,
                middle=plan["origin_y_mm"] + row * pitch + plan["cell_mm"] / 2,
            )
            labels.add_reference(node)
            extras.append(node)

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
            extras.append(node)

    def _caption(self, plan: dict, extras: list):
        """
        Het opschrift op het bord: wat is dit, waarvan, wanneer.

        Een gebrand raster zonder opschrift is over twee weken een raadselachtig
        stuk hout. Het staat in de labellaag, dus met een vaste, veilige
        instelling — het opschrift moet leesbaar zijn ongeacht welke cel het
        beste uitpakt.
        """
        # Wat `plan_grid` al uitrekende, zodat wat hier gebrand wordt dezelfde
        # regels zijn als waar het bord op gemaat is — hoogte inbegrepen.
        regels = plan.get("caption_lines")
        if regels is None:
            regels = caption_lines(plan)
        regels = [r for r in regels if r]
        if not regels:
            return

        hoogte = float(plan.get("caption_height_mm") or 0) or max(
            2.5, plan["cell_mm"] * 0.4
        )
        # Binnen de breedte van het bord blijven. Op ware grootte werd dit
        # opschrift 70 mm breed op een bord van 46 mm — het stak er rechts
        # uit, en dan klopt de maat die we melden (T9) niet met wat er brandt.
        # `plan_grid` heeft de hoogte hierop al gekozen; deze meting is de
        # vangnet voor de tekens waar de schatting van CAPTION_CHAR_RATIO
        # naast zit. Het bord groeit er niet meer voor: liever een iets
        # kleinere regel dan een bord dat breder is dan zijn eigen proef.
        rand = BORDER_PAD_MM if plan.get("border") else 0.0
        beschikbaar = plan.get("outer_width_mm", plan["width_mm"]) - 2 * rand
        labels = None
        for index, regel in enumerate(regels):
            node = self._text(regel, hoogte)
            if node is None:
                return
            breedte = self._breedte_mm(node)
            if breedte > beschikbaar:
                self._scale_to_height(node, hoogte * beschikbaar / breedte)
            labels = labels or self._label_op(plan)
            self._place(
                node,
                # Links uitgelijnd op het bord, niet op de vakjes: de rijlabels
                # steken links uit, en een opschrift dat halverwege begint
                # leest als een onderschrift bij de verkeerde kolom.
                left=plan.get("outer_x_mm", plan["origin_x_mm"]) + rand,
                # Bóven de kolomlabels, met dezelfde marge als die labels zelf
                # — en op de plek die `plan_grid` ervoor reserveerde, dus met
                # de volle opschrifthoogte en niet met de gekrompen maat.
                # Anders zakt een gekrompen opschrift naar beneden en gaat het
                # dwars door de kolomlabels heen; op een bord met grote vakjes
                # was dat precies wat er gebeurde. De onderste regel houdt zijn
                # oude plek; elke regel erboven schuift een regelafstand op.
                bottom=plan["origin_y_mm"]
                - 4
                - hoogte
                - (len(regels) - 1 - index) * CAPTION_LINE_PITCH * hoogte,
            )
            labels.add_reference(node)
            extras.append(node)

    @staticmethod
    def _breedte_mm(node) -> float:
        from meerk40t.core.units import UNITS_PER_MM

        x0, _, x1, _ = node.bounds
        return (x1 - x0) / UNITS_PER_MM

    def _border(self, plan: dict, extras: list):
        """
        Het randkader om het hele bord (T10).

        Om álles heen, opschriften inbegrepen — een kader dwars door de rijlabels
        maakt het bord juist onleesbaar. Het staat in de labellaag, dus met
        dezelfde veilige instelling als de opschriften: het kader hoort te
        blijven staan wat er ook uit de sweep komt.
        """
        x = plan.get("outer_x_mm", plan["origin_x_mm"])
        y = plan.get("outer_y_mm", plan["origin_y_mm"])
        breedte = plan.get("outer_width_mm", plan["width_mm"])
        hoogte = plan.get("outer_height_mm", plan["height_mm"])
        before = {id(n) for n in self.elements.elems()}
        self.kernel.console(f"rect {x}mm {y}mm {breedte}mm {hoogte}mm\n")
        node = next((n for n in self.elements.elems() if id(n) not in before), None)
        if node is None:
            return
        self._label_op(plan).add_reference(node)
        extras.append(node)

    def _label_op(self, plan: dict | None = None):
        """De laag waar alle opschriften in gaan; één voor alle rasters samen."""
        # Sinds T10 in te stellen: hardgecodeerd 80 mm/s @ 30% werkt op berken en
        # niet op acryl, en dan brandt je opschrift er dwars doorheen.
        plan = plan or {}
        snelheid = float(plan.get("label_speed_mm_s") or DEFAULT_LABEL_SPEED_MM_S)
        vermogen = (
            float(plan.get("label_power_percent") or DEFAULT_LABEL_POWER_PERCENT) * 10
        )
        for node in self.elements.op_branch.children:
            if getattr(node, "label", None) == LABEL_LAYER:
                # De laag is er al van een vorig bord. Wie nu een andere
                # labelinstelling vraagt, krijgt hem ook: anders zet je iets in
                # het formulier dat stilletjes niets doet.
                node.speed = snelheid
                node.power = vermogen
                return node
        return self.elements.op_branch.add(
            type="op engrave",
            speed=snelheid,
            power=vermogen,
            label=LABEL_LAYER,
        )

    def _label_font(self) -> str | None:
        """
        De letter waarin een opschrift op het bord komt.

        Altijd dezelfde, en altijd een die er is: we vragen het de engine in
        plaats van een naam aan te nemen, want een lettertype dat hij niet kan
        openen laat `linetext` terugvallen op — juist ja — `last_font`.
        """
        registry = getattr(self.kernel.root, "fonts", None)
        if registry is None:
            return None
        for naam in LABEL_FONTS:
            try:
                if registry._validate_font(naam):
                    return naam
            except Exception:
                continue
        return None

    def _text(self, text: str, height_mm: float):
        """
        Vector text via the Hershey fonts; bitmap text has no geometry.

        Lettertype en grootte staan hier vast en worden expliciet meegegeven.
        Zonder `-f` pakt de engine `last_font` — de letter van de laatste tekst
        die de gebruiker plaatste — en dan is het opschrift op het bord een
        toevalstreffer. Wat we van die instelling aantreffen, zetten we erna
        terug: het testraster is te gast in andermans document.
        """
        before = {id(n) for n in self.elements.elems()}
        font = self._label_font()
        opdracht = ["linetext 0mm 0mm"]
        if font:
            opdracht.append(f'-f "{font}"')
            opdracht.append(f"-s {LABEL_FONT_SIZE_PX}px")
        opdracht.append(f'"{text}"')
        root = self.kernel.root
        root.setting(str, "last_font", "")
        vorige = root.last_font
        try:
            self.kernel.console(" ".join(opdracht) + "\n")
        except Exception:
            return None
        finally:
            # `create_linetext_node` zet `last_font` op wat het net gebruikte.
            # Dat is hier onze eigen keuze, en die hoort niet de voorkeur van
            # de gebruiker te worden.
            root.last_font = vorige
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

    def _square(self, cell: dict, gevuld: bool = False):
        """
        Eén vakje van het bord.

        `gevuld` bij een rasterbord, en dat is geen opsmuk: de rasteraar brandt
        alleen wat een vulling heeft. Zonder vulling zet hij de omtrek neer
        (zie `test_an_unfilled_shape_burns_its_outline_and_not_its_middle`), en
        dan komt er van een graveerproef een bord met negen lege kadertjes uit
        de machine in plaats van negen vlakken in oplopende zwarting. Een
        rasterproef gaat juist over hoe donker het vlák wordt.
        """
        before = set(id(n) for n in self.elements.elems())
        self.kernel.console(
            f"rect {cell['x_mm']}mm {cell['y_mm']}mm "
            f"{cell['width_mm']}mm {cell['height_mm']}mm\n"
        )
        for node in self.elements.elems():
            if id(node) not in before:
                if gevuld:
                    from meerk40t.svgelements import Color

                    node.fill = Color("black")
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
