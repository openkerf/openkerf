"""
Het pure rekenwerk achter de tegels: opdelen, scheidslijn, merken, uitlijnen.

Geen kernel, geen bestanden, geen HTTP. Dit is het deel waar de fouten zitten
die je op materiaal betaalt, dus het is het deel dat volledig getest is.
"""

import math

import pytest

from openkerf_api.tiling import Rect, TilingError, TilingSettings, best_split, tile_layout


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
