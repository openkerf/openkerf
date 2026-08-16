"""
Het pure rekenwerk achter de tegels: opdelen, scheidslijn, merken, uitlijnen.

Geen kernel, geen bestanden, geen HTTP. Dit is het deel waar de fouten zitten
die je op materiaal betaalt, dus het is het deel dat volledig getest is.
"""

import math

import pytest

from openkerf_api.tiling import Rect, TilingError, TilingSettings, tile_layout


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
    """900 mm op een bed van 500: opdelen in de breedte, niet in de hoogte."""
    tiles = tile_layout(900.0, 250.0, 500.0, 300.0, settings())

    assert len(tiles) == 3
    assert {t.row for t in tiles} == {0}
    assert [t.column for t in tiles] == [0, 1, 2]
    for tile in tiles:
        assert tile.burn.y0 == 0.0 and tile.burn.y1 == 250.0


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


def test_tiles_are_spread_evenly_instead_of_leaving_a_sliver():
    """
    'Vol, vol, vol, restje' geeft een laatste tegel waar geen merk in past.
    Gelijk verdelen maakt de overlap groter dan het minimum, en dat is precies
    de bedoeling.
    """
    tiles = tile_layout(1000.0, 200.0, 500.0, 300.0, settings())

    breedtes = [t.burn.x1 - t.burn.x0 for t in tiles]
    assert max(breedtes) - min(breedtes) < 1e-6


def test_a_bed_smaller_than_the_overlap_is_refused_with_a_sentence():
    with pytest.raises(TilingError) as fout:
        tile_layout(900.0, 200.0, 40.0, 300.0, settings(overlap_mm=25.0))

    assert "overlap" in str(fout.value).lower()
