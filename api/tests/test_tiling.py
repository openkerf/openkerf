"""
Het pure rekenwerk achter de tegels: opdelen, scheidslijn, merken, uitlijnen.

Geen kernel, geen bestanden, geen HTTP. Dit is het deel waar de fouten zitten
die je op materiaal betaalt, dus het is het deel dat volledig getest is.
"""

import math

import pytest
from meerk40t.core.geomstr import Geomstr

from openkerf_api.tiling import (
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


def settings(**kw):
    base = {"margin_mm": 10.0, "overlap_mm": 25.0, "marker_size_mm": 8.0}
    base.update(kw)
    return TilingSettings(**base)


def test_a_plate_that_fits_is_one_tile():
    """Past het, dan valt er niets op te delen — en dan is er ook geen naad."""
    tiles = tile_layout(300.0, 200.0, 500.0, 300.0, settings())

    assert len(tiles) == 1
    assert tiles[0].burn == Rect(0.0, 0.0, 300.0, 200.0)


def test_a_wide_plate_splits_only_on_the_wide_axis():
    """
    900 mm op een bed van 500: opdelen in de breedte, niet in de hoogte.

    Twee tegels, niet drie. Het bruikbare venster is 480 mm, dus twee vensters
    dekken 900 mm met 60 mm overlap — ruim boven de 25 die gevraagd is. Een
    derde tegel zou een extra keer verschuiven en uitlijnen betekenen, en elke
    uitlijning is een kans om het mis te hebben.
    """
    tiles = tile_layout(900.0, 250.0, 500.0, 300.0, settings())

    assert len(tiles) == 2
    assert {t.row for t in tiles} == {0}
    assert [t.column for t in tiles] == [0, 1]
    for tile in tiles:
        assert tile.burn.y0 == 0.0 and tile.burn.y1 == 250.0


def test_the_tile_count_is_the_fewest_that_still_overlap_enough():
    """
    Het aantal volgt uit één eis: twee opeenvolgende vensters delen minstens
    `overlap_mm`. Daaruit volgt n ≥ (plaat − overlap) / (venster − overlap), en
    dat is precies wat er gerekend hoort te worden — niet één meer.
    """
    assert len(tile_layout(900.0, 200.0, 500.0, 300.0, settings())) == 2
    assert len(tile_layout(1000.0, 200.0, 500.0, 300.0, settings())) == 3
    assert len(tile_layout(1400.0, 200.0, 500.0, 300.0, settings())) == 4


def test_the_burn_regions_tile_the_plate_exactly():
    """Aan elkaar, zonder gat en zonder overlap: anders brandt iets dubbel."""
    tiles = tile_layout(900.0, 250.0, 500.0, 300.0, settings())

    assert tiles[0].burn.x0 == 0.0
    assert tiles[-1].burn.x1 == pytest.approx(900.0)
    for left, right in zip(tiles, tiles[1:]):
        assert left.burn.x1 == pytest.approx(right.burn.x0)


def test_every_tile_fits_the_usable_window():
    """Het venster is bed min tweemaal de marge; groter kan de kop niet halen."""
    tiles = tile_layout(900.0, 250.0, 500.0, 300.0, settings())

    for tile in tiles:
        assert tile.window.x1 - tile.window.x0 <= 480.0 + 1e-9


def test_the_windows_are_spread_evenly_instead_of_leaving_a_sliver():
    """
    'Vol, vol, vol, restje' geeft een laatste tegel waar geen merk in past.

    Wat gelijk verdeeld wordt zijn de **vensters**: de plaat schuift elke keer
    even ver op. De brandgebieden zijn daarmee niet even breed, en dat hoort
    ook niet — een middelste tegel staat aan twee kanten een halve overlap af
    en brandt dus minder dan de buitenste. Waar het om gaat is dat er geen
    strookje overblijft.
    """
    tiles = tile_layout(1000.0, 200.0, 500.0, 300.0, settings())

    stappen = [b.window.x0 - a.window.x0 for a, b in zip(tiles, tiles[1:])]
    assert max(stappen) - min(stappen) < 1e-6


def test_no_tile_burns_less_than_the_strip_it_shares():
    """
    Een tegel die minder brandt dan de overlap die hij weggeeft, is geen tegel
    maar een reepje: dan kost hij een verschuiving en een uitlijning voor bijna
    niets. Nagerekend over plaatmaten van 490 tot 3000 mm is het smalste
    brandgebied 227,6 mm, ruim boven de overlap.
    """
    for plate in (490.0, 700.0, 935.1, 1000.0, 1500.0, 2400.0):
        tiles = tile_layout(plate, 200.0, 500.0, 300.0, settings())
        for tile in tiles:
            assert tile.burn.width >= settings().overlap_mm


def test_a_bed_smaller_than_the_overlap_is_refused_with_a_sentence():
    with pytest.raises(TilingError) as fout:
        tile_layout(900.0, 200.0, 40.0, 300.0, settings(overlap_mm=25.0))

    assert "overlap" in str(fout.value).lower()


def test_the_seam_falls_in_empty_space_when_there_is_any():
    """
    Een naad door de leegte zie je niet terug op het werkstuk. Vormen van
    100-140 en 180-220: tussen 140 en 180 kruist hij niets.
    """
    x = best_split(120.0, 200.0, [(100.0, 140.0), (180.0, 220.0)])

    assert 140.0 <= x <= 180.0


def test_the_seam_takes_the_least_bad_place_when_everything_is_covered():
    """
    Alles bedekt: dan de stand die de minste vormen doormidden snijdt.

    De vormen lopen hier tot buiten de zone door, want anders is de rand van de
    zone zelf al kruisingsvrij — een vorm die precies op de naad begint wordt
    niet doorgesneden, hij wordt geraakt. Dat is geen kunstgreep in de test maar
    de reden dat de randen van de zone gewoon kandidaat mogen zijn: de hele
    overlapzone is vanaf beide tegels bereikbaar.
    """
    spans = [(-10.0, 110.0), (-10.0, 40.0), (-10.0, 40.0)]

    x = best_split(0.0, 100.0, spans)

    def kruisingen(punt: float) -> int:
        return sum(1 for a, b in spans if a < punt < b)

    assert kruisingen(x) == 1
    assert kruisingen(x) < kruisingen(0.0)


def test_without_shapes_the_seam_falls_in_the_middle():
    assert best_split(100.0, 200.0, []) == pytest.approx(150.0)


def test_two_marks_land_as_far_apart_as_the_zone_allows():
    """Hoe verder uit elkaar, hoe nauwkeuriger de hoek die eruit volgt."""
    een, twee = marker_spots(Rect(400.0, 0.0, 440.0, 600.0), [], size_mm=8.0)

    assert abs(twee.y_mm - een.y_mm) > 500.0


def test_a_mark_never_lands_on_a_shape():
    """Merken horen in het afval; op het werkstuk zou je ze terugzien."""
    blokkade = Rect(400.0, 100.0, 440.0, 500.0)

    een, twee = marker_spots(Rect(400.0, 0.0, 440.0, 600.0), [blokkade], size_mm=8.0)

    for punt in (een, twee):
        assert not (100.0 <= punt.y_mm <= 500.0)


def test_no_room_is_a_refusal_and_not_a_single_mark():
    """
    Stilzwijgend terugvallen op één merk kost de scheefstandcorrectie zonder
    dat iemand het merkt. Dus: weigeren, met wat eraan te doen is.
    """
    vol = Rect(400.0, 0.0, 440.0, 600.0)

    with pytest.raises(TilingError) as fout:
        marker_spots(Rect(400.0, 0.0, 440.0, 600.0), [vol], size_mm=8.0)

    assert "overlap" in str(fout.value).lower()


def test_in_a_wide_zone_the_marks_spread_sideways():
    """
    Een plaat die in de hoogte opgedeeld wordt, geeft een brede, lage
    overlapzone. Dan moeten de merken langs de lange as uit elkaar — dezelfde
    regel, andere as, en die tak wordt anders nooit gelopen.

    Dat ze niet op dezelfde hoogte uitkomen is geen tekortkoming: het
    uitlijnen rekent met de lijn tussen twee punten, niet met een as. Wat telt
    is de afstand, want die bepaalt hoe nauwkeurig de hoek wordt.
    """
    zone = Rect(0.0, 400.0, 600.0, 440.0)

    een, twee = marker_spots(zone, [], size_mm=8.0)

    assert abs(twee.x_mm - een.x_mm) > 500.0
    for punt in (een, twee):
        assert zone.x0 <= punt.x_mm <= zone.x1
        assert zone.y0 <= punt.y_mm <= zone.y1


def test_a_plate_that_only_moved_gives_a_pure_shift():
    merk1, merk2 = Point(470.0, 40.0), Point(470.0, 560.0)
    gemeten1, gemeten2 = Point(30.0, 45.0), Point(30.0, 565.0)

    uit = alignment(merk1, merk2, gemeten1, gemeten2)

    assert uit.angle_deg == pytest.approx(0.0, abs=1e-6)
    assert uit.dx_mm == pytest.approx(-440.0)
    assert uit.dy_mm == pytest.approx(5.0)


def test_a_skewed_plate_gives_the_angle_it_lies_at():
    """Twee graden scheef: dat moet er als twee graden uit komen, niet als vier."""
    hoek = math.radians(2.0)
    merk1, merk2 = Point(0.0, 0.0), Point(0.0, 500.0)
    gemeten1 = Point(0.0, 0.0)
    gemeten2 = Point(-500.0 * math.sin(hoek), 500.0 * math.cos(hoek))

    uit = alignment(merk1, merk2, gemeten1, gemeten2)

    assert uit.angle_deg == pytest.approx(2.0, abs=1e-6)


def test_marks_that_moved_apart_are_a_refusal():
    """
    De afstand tussen twee gebrande merken verandert niet. Verandert hij toch,
    dan is er verkeerd aangetikt — en dan moet je stoppen, niet doorrekenen.
    """
    with pytest.raises(TilingError) as fout:
        alignment(
            Point(0.0, 0.0), Point(0.0, 500.0), Point(0.0, 0.0), Point(0.0, 504.0)
        )

    assert "uit elkaar" in str(fout.value)


def test_an_impossible_angle_is_a_refusal():
    hoek = math.radians(12.0)
    with pytest.raises(TilingError) as fout:
        alignment(
            Point(0.0, 0.0),
            Point(0.0, 500.0),
            Point(0.0, 0.0),
            Point(-500.0 * math.sin(hoek), 500.0 * math.cos(hoek)),
        )

    assert "scheef" in str(fout.value).lower()


def test_the_first_tile_aligns_on_the_plate_corner_without_an_angle():
    """Tegel 1 heeft geen merken; die lijnt uit op de plaat, zonder scheefstand."""
    uit = alignment_from_corner(Point(0.0, 0.0), Point(25.0, 15.0))

    assert uit == Alignment(
        angle_deg=0.0, dx_mm=25.0, dy_mm=15.0, distance_error_mm=0.0
    )


def _length(geom) -> float:
    return sum(abs(geom.length(i)) for i in range(geom.index))


def test_a_line_across_the_seam_is_cut_in_two_without_losing_length():
    """Samen even lang als het origineel: niets dubbel, niets kwijt."""
    lijn = Geomstr()
    lijn.line(complex(0, 50), complex(200, 50))

    links = clip_geometry(lijn, Rect(0, 0, 100, 100))
    rechts = clip_geometry(lijn, Rect(100, 0, 200, 100))

    assert _length(links) == pytest.approx(100.0, rel=1e-3)
    assert _length(rechts) == pytest.approx(100.0, rel=1e-3)


def test_the_original_geometry_is_left_alone():
    """Het ontwerp van de gebruiker mag door het klippen niet veranderen."""
    lijn = Geomstr()
    lijn.line(complex(0, 50), complex(200, 50))
    voor = lijn.index

    clip_geometry(lijn, Rect(0, 0, 100, 100))

    assert lijn.index == voor


def test_an_arc_across_the_seam_stays_an_arc():
    """
    Dit pint de aanname vast waar het hele ontwerp op rust: splitsen gebeurt op
    de parameter, er wordt niet geïnterpoleerd. Een cirkel die de naad kruist
    mag geen veelhoek worden — dat zou je op het werkstuk zien.
    """
    from meerk40t.core.geomstr import TYPE_ARC

    cirkel = Geomstr.circle(60, 100, 50)

    geklipt = clip_geometry(cirkel, Rect(0, -100, 100, 200))

    soorten = {int(geklipt.segments[i][2].real) for i in range(geklipt.index)}
    assert TYPE_ARC in soorten


def test_a_circle_split_in_two_keeps_all_of_its_length():
    """
    De regressietest op de reden dat we `geomstr.Clip` niet gebruiken: die liet
    een kwartboog vallen die de grens niet eens kruiste, en dat is precies de
    fout die je pas op materiaal ziet — een cirkel met een hap eruit.
    """
    cirkel = Geomstr.circle(60, 100, 50)

    links = clip_geometry(cirkel, Rect(0, -100, 100, 200))
    rechts = clip_geometry(cirkel, Rect(100, -100, 200, 200))

    assert _length(links) + _length(rechts) == pytest.approx(_length(cirkel), rel=1e-6)


def test_geometry_entirely_outside_comes_back_empty():
    lijn = Geomstr()
    lijn.line(complex(500, 50), complex(600, 50))

    assert clip_geometry(lijn, Rect(0, 0, 100, 100)).index == 0
