"""
Hoeken afronden of afschuinen.

Puur rekenwerk op geometrie, dus geen kernel en geen HTTP. Wat hier getoetst
wordt is niet "loopt het door" maar "komt er de vorm uit die je bedoelde" — en
vooral: wat gebeurt er bij de hoeken waar het niet kán. Een hoek stilzwijgend
verkeerd afsnijden is de fout die je pas op materiaal ziet.
"""

import math

import pytest
from meerk40t.core.geomstr import TYPE_ARC, TYPE_LINE, Geomstr

from openkerf_api.corners import CornerError, corner_geometry


def vierkant(zijde=100.0):
    """Een gesloten vierkant van vier losse lijnsegmenten."""
    geom = Geomstr()
    hoeken = [
        complex(0, 0),
        complex(zijde, 0),
        complex(zijde, zijde),
        complex(0, zijde),
    ]
    for a, b in zip(hoeken, hoeken[1:] + hoeken[:1]):
        geom.line(a, b)
    return geom


def soorten(geom):
    return [int(geom.segments[i][2].real) for i in range(geom.index)]


def lengte(geom):
    return sum(abs(geom.length(i)) for i in range(geom.index))


def test_chamfering_a_square_cuts_all_four_corners():
    """
    Vier hoeken eraf betekent vier zijden plus vier schuine kantjes.

    De schuine kant van een rechte hoek waarbij je aan beide zijden 10 mm
    terugsnijdt, is 10·√2 lang. Dat is met de hand na te rekenen, en daarom
    staat het hier in plaats van "er komt iets uit".
    """
    uit, gewijzigd, overgeslagen = corner_geometry(vierkant(), 10.0, "chamfer")

    assert (gewijzigd, overgeslagen) == (4, 0)
    assert len(soorten(uit)) == 8
    assert set(soorten(uit)) == {TYPE_LINE}
    schuin = 10.0 * math.sqrt(2)
    assert lengte(uit) == pytest.approx(4 * 80.0 + 4 * schuin, rel=1e-6)


def test_rounding_a_square_gives_real_arcs():
    """
    Afronden geeft bogen, geen veelhoekjes.

    Bij een rechte hoek is de terugsnijmaat gelijk aan de radius, dus dit is
    dezelfde vorm die de engine voor een rechthoek met `rx` tekent — daarmee
    zien een afgeronde rechthoek en een afgeronde veelhoek er hetzelfde uit.
    """
    uit, gewijzigd, overgeslagen = corner_geometry(vierkant(), 10.0, "round")

    assert (gewijzigd, overgeslagen) == (4, 0)
    assert soorten(uit).count(TYPE_ARC) == 4
    kwart = 2 * math.pi * 10.0 / 4
    assert lengte(uit) == pytest.approx(4 * 80.0 + 4 * kwart, rel=1e-3)


def test_a_size_too_large_for_every_corner_is_a_refusal():
    """
    Twee afschuiningen die elkaar zouden overlappen, leveren een vorm op die
    niemand bedoelde. De grens is de helft van de kortste zijde: bij een
    vierkant van 10 mm mag de maat tot 5 mm, en 8 mm niet.

    Past het bij géén enkele hoek, dan is dat een weigering en niet "klaar, 4
    overgeslagen". Dezelfde geometrie teruggeven zou betekenen dat de laag het
    ontwerp vervangt door iets identieks en de gebruiker een melding krijgt over
    werk dat niet gedaan is — dan is weigeren eerlijker, en het zegt wat hij
    eraan doet.
    """
    with pytest.raises(CornerError) as fout:
        corner_geometry(vierkant(10.0), 8.0, "chamfer")

    assert "kleinere maat" in str(fout.value)


def test_the_grens_is_half_the_shortest_edge():
    """Precies op de helft mag nog: dan sluiten twee hoeken naadloos aan."""
    uit, gewijzigd, overgeslagen = corner_geometry(vierkant(10.0), 5.0, "chamfer")

    assert (gewijzigd, overgeslagen) == (4, 0)
    # Alle rechte stukken zijn weggesneden; wat overblijft zijn vier schuinten.
    assert lengte(uit) == pytest.approx(4 * 5.0 * math.sqrt(2), rel=1e-6)


def test_a_corner_against_a_curve_is_skipped():
    """
    Terugsnijden langs een boog is een ander probleem dan terugsnijden langs een
    lijn. Zulke hoeken laten we staan in plaats van er iets van te maken.
    """
    geom = Geomstr()
    geom.line(complex(0, 0), complex(100, 0))
    geom.line(complex(100, 0), complex(100, 100))
    geom.arc(complex(100, 100), complex(50, 150), complex(0, 100))
    geom.line(complex(0, 100), complex(0, 0))

    uit, gewijzigd, overgeslagen = corner_geometry(geom, 10.0, "chamfer")

    # Alleen de twee hoeken tussen twee lijnen doen mee: (100,0) en (0,0).
    assert gewijzigd == 2
    assert overgeslagen == 2
    assert TYPE_ARC in soorten(uit)


def test_an_open_polyline_has_no_corner_at_its_loose_ends():
    """Een los uiteinde is geen hoek: daar komt maar één zijde op uit."""
    geom = Geomstr()
    geom.line(complex(0, 0), complex(100, 0))
    geom.line(complex(100, 0), complex(100, 100))

    uit, gewijzigd, overgeslagen = corner_geometry(geom, 10.0, "chamfer")

    assert (gewijzigd, overgeslagen) == (1, 0)
    assert len(soorten(uit)) == 3


def test_nothing_to_do_is_a_refusal_with_a_sentence():
    """
    Een selectie zonder één bruikbare hoek moet dat zeggen. Stil niets doen
    laat de gebruiker denken dat de knop stuk is.
    """
    geom = Geomstr()
    geom.line(complex(0, 0), complex(100, 0))

    with pytest.raises(CornerError) as fout:
        corner_geometry(geom, 10.0, "chamfer")

    assert "hoek" in str(fout.value).lower()


def test_the_original_geometry_is_left_alone():
    origineel = vierkant()
    voor = origineel.index

    corner_geometry(origineel, 10.0, "chamfer")

    assert origineel.index == voor


def test_an_unknown_style_is_refused():
    with pytest.raises(CornerError):
        corner_geometry(vierkant(), 10.0, "schuinweg")


def test_a_sharp_corner_gets_the_right_arc():
    """
    Alle andere tests hier gebruiken rechte hoeken, en bij 90° valt de
    terugsnijmaat samen met de radius — dan klopt de trigonometrie ook als je
    hem verkeerd hebt. Een gelijkzijdige driehoek heeft hoeken van 60°, en daar
    lopen ze uiteen: radius = maat · tan(30°), en de boog draait 120°.
    """
    zijde = 100.0
    hoog = zijde * math.sqrt(3) / 2
    punten = [complex(0, 0), complex(zijde, 0), complex(zijde / 2, hoog)]
    geom = Geomstr()
    for a, b in zip(punten, punten[1:] + punten[:1]):
        geom.line(a, b)

    maat = 10.0
    uit, gewijzigd, overgeslagen = corner_geometry(geom, maat, "round")

    assert (gewijzigd, overgeslagen) == (3, 0)
    radius = maat * math.tan(math.radians(30))
    boog = radius * math.radians(120)
    recht = 3 * (zijde - 2 * maat)
    assert lengte(uit) == pytest.approx(recht + 3 * boog, rel=2e-3)


def test_a_sharp_corner_chamfers_to_the_right_width():
    """
    Bij 60° is de schuine kant korter dan bij 90°: met de cosinusregel is hij
    maat·√(2−2·cos60°) = maat. Dat is met de hand na te rekenen en pint vast dat
    de terugsnijmaat langs de zíjde gemeten wordt, niet ergens anders.
    """
    zijde = 100.0
    hoog = zijde * math.sqrt(3) / 2
    punten = [complex(0, 0), complex(zijde, 0), complex(zijde / 2, hoog)]
    geom = Geomstr()
    for a, b in zip(punten, punten[1:] + punten[:1]):
        geom.line(a, b)

    maat = 10.0
    uit, _gewijzigd, _overgeslagen = corner_geometry(geom, maat, "chamfer")

    schuin = maat * math.sqrt(2 - 2 * math.cos(math.radians(60)))
    assert lengte(uit) == pytest.approx(3 * (zijde - 2 * maat) + 3 * schuin, rel=1e-6)
