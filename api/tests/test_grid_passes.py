"""
Meerdere passes op een testbord.

The case this comes from: a material that almost cuts through at 5 mm/s, and that you want
to try at 8 mm/s in two passes. One number for the whole board — passes as a third axis would
produce a board nobody reads back.

The last test in this file is the most important: a square that only made it in two passes
has to produce a preset that says so *too*. Otherwise that preset later cuts once and you
notice it on material.
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
    # An empty field is not an error: the form sends "" for "not filled in", as with the
    # label speed.
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
    Round numbers, checkable by hand.

    Four squares of 10 mm cutting at 10 mm/s: 40 mm of burn path per square, so 4 s. The jump
    to the next square is the pitch (10 + 2 mm) at 100 mm/s and belongs to each square once,
    however many passes you do.
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
    In two weeks the board has to be convertible back into a setting.

    With one pass it is not there: that is the normal state of affairs and the caption has to
    stay short — it decides the board width.
    """
    plan, _ = plan_grid(**BASE, passes=2)
    regels = " · ".join(caption_lines(plan))

    assert "2 passes" in regels
    assert "passes" not in " · ".join(caption_lines(plan_grid(**BASE)[0]))


def test_the_caption_room_is_measured_with_the_passes_in_it():
    """The measure has to cover what burns; the caption is wider with passes."""
    plan, _ = plan_grid(**BASE, passes=2)

    assert "2 passes" in plan["caption_text"]


# -------------------------------------------------------------- tekenen


def test_every_cell_layer_gets_the_passes(kernel):
    """
    Not only the field: the number the planner really reads.

    A measured fault, found on the machine: setting `passes` is not enough. The engine reads
    `implicit_passes`, and that hands back 1 as long as `passes_custom` is off
    (`core/parameters.py:401`). So the board reported two passes and burned one. Our own layer
    settings *do* set that flag (`Drawing.apply_settings`); the board built its layers directly
    on the node and skipped it.
    """
    plan, cells = plan_grid(**BASE, passes=3)
    getekend, _ = TestGridGenerator(kernel).draw(plan, cells)

    lagen = [kernel.elements.find_node(entry["operation_id"]) for entry in getekend]
    assert lagen and all(laag is not None for laag in lagen)
    assert {int(laag.passes) for laag in lagen} == {3}
    assert {laag.implicit_passes for laag in lagen} == {3}


def _brandwerk(passes) -> int:
    """
    How many times the machine goes over the work, from the cut plan itself.

    The engine can carry passes in two ways: one piece of cutcode with `passes=N`, or N copies
    with `passes=1` — that depends on `opt_merge_passes` and the optimisation state
    (`core/cutplan.py:432`). The sum
    is onder beide vormen hetzelfde, en de som is wat er brandt.
    """
    from conftest import _bootstrap

    from openkerf_api.commands import CommandRunner

    kernel = _bootstrap()
    try:
        # Without captions: the label layer rightly burns once, and that would muddy the
        # number this is about.
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
    The proof from the cut plan, because that is what goes to the machine.

    This is the test that should have caught the fault found on material: the board reported
    two passes and burned one. A test on the `passes` field went cheerfully green, because that
    field was simply right.
    """
    enkel = _brandwerk(1)
    drie = _brandwerk(3)

    # Nine squares, so nine burns at one pass and twenty-seven at three. The exact number is
    # there so that a shift in the plan's shape stands out instead of disappearing into a
    # ratio.
    assert enkel == 9
    assert drie == 27


def test_a_single_pass_board_still_says_one(kernel):
    """The engine uses 0 for 'not set'; that reads as zero times."""
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

    # And next time the number is there again: this is a setting you work out once per
    # material.
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


# ----------------------------------------------------- the loop worth having


def test_a_preset_from_a_two_pass_board_says_two_passes(client):
    """
    The square made it in two passes; the preset has to take that along.

    Without this line a successful board produces a preset that cuts once — and you only
    notice that on material, with a board that is stuck.
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

    A layer can carry `passes = 3` while the engine does one, because it reads
    `implicit_passes`. The panel and the pre-flight read the field and so reported three. That
    is precisely the number somebody plans their board on.
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

    # And with the flag it does say three — otherwise this test would have proved nothing.
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
