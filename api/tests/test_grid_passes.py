"""
Meerdere passes op een testbord.

Het geval waar dit uit komt: een materiaal dat op 5 mm/s bijna doorsnijdt, en
dat je op 8 mm/s in twee passes wilt proberen. Eén getal voor het hele bord —
passes als derde as zou een bord opleveren dat niemand meer terugleest.

De laatste test in dit bestand is de belangrijkste: een vakje dat het alleen in
twee passes haalde, moet een preset opleveren die dat óók zegt. Anders snijdt
die preset later één keer en merk je het op materiaal.
"""

import pytest
from fastapi.testclient import TestClient

from openkerf_api.edits import DesignError
from openkerf_api.server import ApiServer
from openkerf_api.testgrid import TestGridGenerator, caption_lines, plan_grid

BASE = {
    "operation": "snijden",
    "speed_min": 5,
    "speed_max": 25,
    "speed_steps": 3,
    "power_min": 40,
    "power_max": 80,
    "power_steps": 3,
    "cell_mm": 8,
    "gap_mm": 2,
    "origin_x_mm": 10,
    "origin_y_mm": 10,
}


@pytest.fixture
def client(kernel, tmp_path):
    with TestClient(ApiServer(kernel, library_path=tmp_path / "grids.db").build_app()) as c:
        yield c


# ------------------------------------------------------------------ planning


def test_a_board_burns_once_unless_you_ask_for_more():
    plan, _ = plan_grid(**BASE)

    assert plan["passes"] == 1
    # Een leeg veld is geen fout: het formulier stuurt "" voor "niet ingevuld",
    # net als bij de labelsnelheid.
    assert plan_grid(**BASE, passes="")[0]["passes"] == 1


def test_a_board_can_ask_for_more_than_one_pass():
    plan, _ = plan_grid(**BASE, passes=2)

    assert plan["passes"] == 2


@pytest.mark.parametrize("waarde", [0, -1, 2.5, "veel"])
def test_a_pass_count_that_is_not_a_whole_number_of_passes_is_refused(waarde):
    with pytest.raises(DesignError):
        plan_grid(**BASE, passes=waarde)


def test_the_estimate_counts_every_pass():
    """
    Ronde getallen, met de hand na te rekenen.

    Vier vakjes van 10 mm snijden op 10 mm/s: 40 mm brandweg per vakje, dus 4 s.
    De sprong naar het volgende vakje is de steek (10 + 2 mm) op 100 mm/s en
    hoort één keer bij elk vakje, hoeveel passes je ook doet.
    """
    een = dict(
        BASE,
        speed_min=10,
        speed_max=10,
        speed_steps=2,
        power_min=50,
        power_max=50,
        power_steps=2,
        cell_mm=10,
        gap_mm=2,
    )
    reizen = 4 * 12 / 100.0
    enkel, cellen = plan_grid(**een)
    dubbel, _ = plan_grid(**een, passes=2)

    assert len(cellen) == 4
    assert enkel["seconds"] == pytest.approx(4 * 4.0 + reizen, abs=0.05)
    assert dubbel["seconds"] == pytest.approx(2 * (4 * 4.0) + reizen, abs=0.05)


def test_the_caption_says_how_many_passes():
    """
    Over twee weken moet het bord terug te rekenen zijn naar een instelling.

    Bij één pass staat het er niet: dat is de normale gang van zaken en het
    opschrift moet kort blijven — het bepaalt de bordbreedte.
    """
    plan, _ = plan_grid(**BASE, passes=2)
    regels = " · ".join(caption_lines(plan))

    assert "2 passes" in regels
    assert "passes" not in " · ".join(caption_lines(plan_grid(**BASE)[0]))


def test_the_caption_room_is_measured_with_the_passes_in_it():
    """De maat moet dekken wat er brandt; het opschrift is breder met passes."""
    plan, _ = plan_grid(**BASE, passes=2)

    assert "2 passes" in plan["caption_text"]


# -------------------------------------------------------------- tekenen


def test_every_cell_layer_gets_the_passes(kernel):
    """
    Niet alleen het veld: het getal dat de planner werkelijk leest.

    Gemeten fout, en op de machine gevonden: `passes` zetten is niet genoeg. De
    engine leest `implicit_passes`, en die geeft 1 terug zolang `passes_custom`
    uit staat (`core/parameters.py:401`). Het bord meldde dus twee passes en
    brandde er één. Onze eigen laaginstellingen zetten die vlag wél
    (`Drawing.apply_settings`); het bord bouwde zijn lagen rechtstreeks op de
    knoop en sloeg hem over.
    """
    plan, cells = plan_grid(**BASE, passes=3)
    getekend, _ = TestGridGenerator(kernel).draw(plan, cells)

    lagen = [kernel.elements.find_node(entry["operation_id"]) for entry in getekend]
    assert lagen and all(laag is not None for laag in lagen)
    assert {int(laag.passes) for laag in lagen} == {3}
    assert {laag.implicit_passes for laag in lagen} == {3}


def _brandwerk(passes) -> int:
    """
    Hoeveel keer de machine over het werk gaat, uit het snijplan zelf.

    De engine kan passes op twee manieren dragen: één stuk cutcode met
    `passes=N`, of N kopieën met `passes=1` — dat hangt af van
    `opt_merge_passes` en de optimalisatiestand (`core/cutplan.py:432`). De som
    is onder beide vormen hetzelfde, en de som is wat er brandt.
    """
    from conftest import _bootstrap

    from openkerf_api.commands import CommandRunner

    kernel = _bootstrap()
    try:
        # Zonder opschriften: de labellaag brandt terecht één keer, en die zou
        # het getal waar het hier om gaat vertroebelen.
        opzet = dict(BASE, text=False)
        plan, cells = plan_grid(**opzet, passes=passes)
        TestGridGenerator(kernel).draw(plan, cells)
        CommandRunner(kernel).run("plan copy preprocess validate blob")
        stappen = kernel.planner.get_or_make_plan("0").plan
        return sum(
            int(getattr(stuk, "passes", 0) or 0)
            for stap in stappen
            for stuk in (stap if hasattr(stap, "__iter__") else [])
            if hasattr(stuk, "passes")
        )
    finally:
        kernel()


def test_the_cutcode_really_burns_every_square_three_times():
    """
    Het bewijs uit het snijplan, want dat is wat naar de machine gaat.

    Dit is de test die de fout had moeten vangen die op materiaal gevonden werd:
    het bord meldde twee passes en brandde er één. Een test op het veld `passes`
    ging vrolijk groen, want dat veld stond gewoon goed.
    """
    enkel = _brandwerk(1)
    drie = _brandwerk(3)

    # Negen vakjes, dus negen keer branden bij één pass en zevenentwintig bij
    # drie. Het exacte getal staat er zodat een verschuiving in de vorm van het
    # plan opvalt in plaats van weg te vallen in een verhouding.
    assert enkel == 9
    assert drie == 27


def test_a_single_pass_board_still_says_one(kernel):
    """De engine gebruikt 0 voor 'niet ingesteld'; dat leest als nul keer."""
    plan, cells = plan_grid(**BASE)
    getekend, _ = TestGridGenerator(kernel).draw(plan, cells)

    lagen = [kernel.elements.find_node(entry["operation_id"]) for entry in getekend]
    assert {int(laag.passes) for laag in lagen} == {1}
    assert {laag.implicit_passes for laag in lagen} == {1}


# -------------------------------------------------------------- onthouden


def test_the_board_remembers_its_passes(client):
    materiaal = client.post("/api/library/materials", json={"name": "Berk 3"}).json()
    gemaakt = client.post(
        "/api/library/testgrids",
        json={**BASE, "passes": 2, "material_id": materiaal["id"]},
    )
    assert gemaakt.status_code == 201, gemaakt.text
    grid = gemaakt.json()

    assert grid["passes"] == 2
    assert client.get(f"/api/library/testgrids/{grid['id']}").json()["passes"] == 2

    # En de volgende keer staat het getal er weer: dit is een instelling die je
    # per materiaal één keer uitzoekt.
    vorige = client.get(
        "/api/library/testgrids/defaults", params={"material_id": materiaal["id"]}
    ).json()
    assert vorige["passes"] == 2


def test_the_preview_shows_the_longer_time_before_anything_is_drawn(client):
    enkel = client.post("/api/library/testgrids/preview", json=BASE).json()
    dubbel = client.post(
        "/api/library/testgrids/preview", json={**BASE, "passes": 2}
    ).json()

    assert dubbel["plan"]["passes"] == 2
    assert dubbel["plan"]["seconds"] > enkel["plan"]["seconds"]


# --------------------------------------------------- de lus die het waard is


def test_a_preset_from_a_two_pass_board_says_two_passes(client):
    """
    Het vakje haalde het in twee passes; de preset moet dat meenemen.

    Zonder deze regel levert een geslaagd bord een preset op die één keer
    snijdt — en dat merk je pas op materiaal, met een plaat die vastzit.
    """
    materiaal = client.post("/api/library/materials", json={"name": "Berk 3"}).json()
    grid = client.post(
        "/api/library/testgrids",
        json={**BASE, "passes": 2, "material_id": materiaal["id"]},
    ).json()

    antwoord = client.post(
        f"/api/library/testgrids/{grid['id']}/presets",
        json={"cells": [{"row": 1, "column": 1, "note": "net doorgesneden"}]},
    )
    assert antwoord.status_code == 201, antwoord.text
    preset = antwoord.json()["presets"][0]

    assert preset["passes"] == 2
    assert preset["speed_mm_s"] == 15
    assert preset["source"] == "testraster"


# ------------------------------------------ wat het scherm erover zegt


def test_a_layer_that_only_looks_like_three_passes_is_reported_as_one(client, kernel):
    """
    De omgekeerde leugen, en dezelfde oorzaak.

    Een laag kan `passes = 3` dragen terwijl de engine er één doet, want zij
    leest `implicit_passes`. Het paneel en de pre-flight lazen het veld en
    meldden dus drie. Dat is precies het getal waarop iemand zijn plaat
    inplant.
    """
    vorm = client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 10, "y_mm": 10, "width_mm": 20, "height_mm": 20},
    ).json()["ids"][0]
    laag = client.post("/api/design/operations", json={"type": "cut"}).json()
    client.post("/api/design/assign", json={"ids": [vorm], "operation_id": laag["id"]})

    node = kernel.elements.find_node(laag["id"])
    node.passes = 3
    node.passes_custom = False

    getoond = next(
        op
        for op in client.get("/api/design").json()["operations"]
        if op["id"] == laag["id"]
    )
    assert getoond["passes"] == 1

    # En met de vlag erbij zegt hij wél drie — anders had deze test niets bewezen.
    node.passes_custom = True
    getoond = next(
        op
        for op in client.get("/api/design").json()["operations"]
        if op["id"] == laag["id"]
    )
    assert getoond["passes"] == 3


def test_the_estimate_only_counts_passes_the_machine_will_do(client, kernel):
    """
    Elke extra pass kost precies één keer branden, en de vlag uit kost niets.

    Geen verdrievoudiging als verwachting: in de schatting zit ook reistijd, en
    die gaat niet mee omhoog. De aanwas per pass is wat hier klopt moet zijn.
    """
    vorm = client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 10, "y_mm": 10, "width_mm": 20, "height_mm": 20},
    ).json()["ids"][0]
    laag = client.post("/api/design/operations", json={"type": "cut", "speed": 10}).json()
    client.post("/api/design/assign", json={"ids": [vorm], "operation_id": laag["id"]})
    node = kernel.elements.find_node(laag["id"])

    def schatting(passes, vlag):
        node.passes, node.passes_custom = passes, vlag
        return client.get("/api/job/estimate").json()["seconds"]

    een = schatting(1, False)
    stil = schatting(3, False)
    twee = schatting(2, True)
    drie = schatting(3, True)

    # De vlag uit verandert niets, hoe hoog het veld ook staat.
    assert stil == pytest.approx(een, rel=0.01)
    # En met de vlag aan kost elke pass erbij hetzelfde stuk werk.
    assert twee - een > 0
    assert drie - twee == pytest.approx(twee - een, rel=0.02)
