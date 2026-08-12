"""Planning and drawing a parametric test grid."""

import pytest
from fastapi.testclient import TestClient

from openkerf_api.design import DesignReader
from openkerf_api.edits import DesignError
from openkerf_api.server import ApiServer
from openkerf_api.testgrid import plan_grid

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
    server = ApiServer(kernel, library_path=tmp_path / "grids.db")
    with TestClient(server.build_app()) as c:
        yield c


# -------------------------------------------------------------- planning

def test_plan_sweeps_both_axes():
    plan, cells = plan_grid(**BASE)

    assert len(cells) == 9
    assert plan["width_mm"] == 28  # 3 cells of 8 plus 2 gaps of 2
    assert plan["height_mm"] == 28
    assert sorted({c["speed_mm_s"] for c in cells}) == [5, 15, 25]
    assert sorted({c["power_percent"] for c in cells}) == [40, 60, 80]


def test_cells_are_laid_out_left_to_right_top_to_bottom():
    _, cells = plan_grid(**BASE)
    first, second = cells[0], cells[1]

    assert (first["x_mm"], first["y_mm"]) == (10, 10)
    assert second["x_mm"] == 20  # one cell plus one gap further along
    assert second["y_mm"] == 10
    assert cells[3]["y_mm"] == 20  # next row


def test_power_varies_across_a_row_and_speed_down_a_column():
    _, cells = plan_grid(**BASE)
    row = [c for c in cells if c["row"] == 0]
    column = [c for c in cells if c["column"] == 0]

    assert [c["power_percent"] for c in row] == [40, 60, 80]
    assert len({c["speed_mm_s"] for c in row}) == 1
    assert [c["speed_mm_s"] for c in column] == [5, 15, 25]


def test_plan_rejects_impossible_ranges():
    for bad in (
        {**BASE, "speed_min": 25, "speed_max": 5},
        {**BASE, "power_min": 80, "power_max": 40},
        {**BASE, "power_max": 150},
        {**BASE, "speed_steps": 1},
        {**BASE, "cell_mm": 0},
        {**BASE, "gap_mm": -1},
        {**BASE, "speed_steps": 40, "power_steps": 40},
    ):
        with pytest.raises(DesignError):
            plan_grid(**bad)


def test_planning_touches_nothing(kernel):
    before = len(list(kernel.elements.elems()))

    plan_grid(**BASE)

    assert len(list(kernel.elements.elems())) == before


# --------------------------------------------------------------- drawing

def test_generating_draws_a_square_and_an_operation_per_cell(kernel, client):
    response = client.post("/api/library/testgrids", json=BASE)

    assert response.status_code == 201
    grid = response.json()
    assert len(grid["cells"]) == 9
    # Nine squares plus the axis labels drawn beside them.
    drawn = {n.id for n in kernel.elements.elems()}
    assert {c["element_id"] for c in grid["cells"]} <= drawn
    # Negen vakjes, de aslabels, plus het opschrift op het bord.
    assert len(drawn) == 9 + BASE["speed_steps"] + BASE["power_steps"] + 1

    snapshot = DesignReader(kernel).snapshot()
    labels = {op["label"] for op in snapshot["operations"]}
    # Het laaglabel noemt de twee grootheden die op de assen staan, met hun
    # eenheid: sinds B12 hoeft dat niet snelheid en vermogen te zijn.
    assert "5 mm/s · 40%" in labels
    assert "25 mm/s · 80%" in labels


def test_each_cell_carries_its_own_settings(kernel, client):
    grid = client.post("/api/library/testgrids", json=BASE).json()

    for cell in grid["cells"]:
        operation = kernel.elements.find_node(cell["operation_id"])
        assert operation.speed == cell["speed_mm_s"]
        # 0-1000 in the engine, percent in the library.
        assert operation.power == pytest.approx(cell["power_percent"] * 10)


def test_cells_know_which_element_they_drew(kernel, client):
    grid = client.post("/api/library/testgrids", json=BASE).json()

    for cell in grid["cells"]:
        node = kernel.elements.find_node(cell["element_id"])
        assert node is not None
        assert node.type == "elem rect"


def test_a_grid_that_does_not_fit_the_bed_is_refused(kernel, client):
    """5 cells of 8mm plus 4 gaps of 2mm is 48mm; from 300 that runs off a 320mm bed."""
    response = client.post(
        "/api/library/testgrids",
        json={**BASE, "origin_x_mm": 300, "speed_steps": 5, "power_steps": 5},
    )

    assert response.status_code == 409
    assert "bed" in str(response.json()["detail"])
    assert len(list(kernel.elements.elems())) == 0


def test_generating_is_undoable(kernel, client):
    client.post("/api/library/testgrids", json=BASE)
    before = len(list(kernel.elements.elems()))
    assert before >= 9

    client.post("/api/design/undo")

    assert len(list(kernel.elements.elems())) < before


# ----------------------------------------------------------------- stored

def test_the_grid_is_remembered(client):
    created = client.post("/api/library/testgrids", json=BASE).json()

    listed = client.get("/api/library/testgrids").json()
    fetched = client.get(f"/api/library/testgrids/{created['id']}").json()

    assert [g["id"] for g in listed] == [created["id"]]
    assert fetched["speed_steps"] == 3
    assert fetched["operation"] == "snijden"
    assert len(fetched["cells"]) == 9
    assert fetched["photo_path"] is None


def test_a_grid_can_reference_a_material(client):
    material = client.post("/api/library/materials", json={"name": "Multiplex"}).json()

    grid = client.post(
        "/api/library/testgrids",
        json={**BASE, "material_id": material["id"], "thickness_mm": 3},
    ).json()

    assert grid["material_id"] == material["id"]
    assert grid["material_name"] == "Multiplex"


def test_preview_plans_without_drawing(kernel, client):
    response = client.post("/api/library/testgrids/preview", json=BASE)

    assert response.status_code == 200
    assert len(response.json()["cells"]) == 9
    assert len(list(kernel.elements.elems())) == 0
    assert client.get("/api/library/testgrids").json() == []


def test_removing_a_grid(client):
    created = client.post("/api/library/testgrids", json=BASE).json()

    client.delete(f"/api/library/testgrids/{created['id']}")

    assert client.get("/api/library/testgrids").json() == []


def test_unknown_grid_is_a_409(client):
    assert client.get("/api/library/testgrids/999").status_code == 409


def test_cells_are_not_also_classified_into_other_operations(kernel, client):
    """
    The engine auto-classifies new elements into every operation whose colour
    matches. Left alone, each grid square would land in a pre-existing layer as
    well, and the job would burn the grid twice — once per cell setting and
    once at that layer's — which ruins the test and the material.
    """
    kernel.console("rect 200mm 150mm 10mm 10mm\n")
    kernel.console("element* cut -s 20 -p 30\n")

    grid = client.post("/api/library/testgrids", json=BASE).json()

    snapshot = DesignReader(kernel).snapshot()
    by_id = {e["id"]: e for e in snapshot["elements"]}
    for cell in grid["cells"]:
        assert by_id[cell["element_id"]]["operation_ids"] == [cell["operation_id"]]


def test_the_axes_are_labelled(kernel, client):
    """A grid you cannot read afterwards is not a test."""
    client.post("/api/library/testgrids", json=BASE)

    snapshot = DesignReader(kernel).snapshot()
    labels = [op for op in snapshot["operations"] if op["label"] == "Raster-labels"]

    assert labels, "there is a layer holding the axis labels"
    # One per row, one per column, plus the caption on the board.
    assert (
        len(labels[0]["element_ids"])
        == BASE["speed_steps"] + BASE["power_steps"] + 1
    )


def test_labels_sit_outside_the_grid(kernel, client):
    grid = client.post("/api/library/testgrids", json=BASE).json()
    snapshot = DesignReader(kernel).snapshot()
    per_mm = snapshot["units_per_mm"]
    label_ids = {
        e
        for op in snapshot["operations"]
        if op["label"] == "Raster-labels"
        for e in op["element_ids"]
    }
    cell_ids = {c["element_id"] for c in grid["cells"]}

    for element in snapshot["elements"]:
        if element["id"] not in label_ids:
            continue
        x0, y0, _, _ = (v / per_mm for v in element["bounds"])
        # Left of the first column or above the first row.
        assert x0 < 10 or y0 < 10, (x0, y0)
    assert label_ids.isdisjoint(cell_ids)


def test_labels_stay_on_the_bed(kernel, client):
    """
    At full size "25 mm/s" is nearly 20mm wide and ran off the left edge of the
    bed, where it would never burn. Labels scale with the cell instead.
    """
    client.post("/api/library/testgrids", json={**BASE, "origin_x_mm": 20, "origin_y_mm": 20})

    snapshot = DesignReader(kernel).snapshot()
    per_mm = snapshot["units_per_mm"]
    for element in snapshot["elements"]:
        x0, y0, _, _ = (v / per_mm for v in element["bounds"])
        assert x0 >= 0, f"{element['label']} steekt links buiten het bed"
        assert y0 >= 0, f"{element['label']} steekt boven het bed uit"


# ------------------------------------------------- foto en preset-extractie

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.fixture
def grid_with_material(client):
    material = client.post("/api/library/materials", json={"name": "Multiplex"}).json()
    return client.post(
        "/api/library/testgrids",
        json={**BASE, "material_id": material["id"], "thickness_mm": 3},
    ).json()


def test_photo_is_stored_and_served(client, grid_with_material):
    grid_id = grid_with_material["id"]

    upload = client.post(
        f"/api/library/testgrids/{grid_id}/photo",
        files={"file": ("raster.png", PNG, "image/png")},
    )

    assert upload.status_code == 200
    assert upload.json()["photo_path"].endswith(f"grid-{grid_id}.png")
    assert client.get(f"/api/library/testgrids/{grid_id}/photo").status_code == 200


def test_photo_before_upload_is_a_404(client, grid_with_material):
    response = client.get(f"/api/library/testgrids/{grid_with_material['id']}/photo")
    assert response.status_code == 404


def test_odd_photo_formats_are_refused(client, grid_with_material):
    response = client.post(
        f"/api/library/testgrids/{grid_with_material['id']}/photo",
        files={"file": ("raster.exe", b"MZ", "application/octet-stream")},
    )
    assert response.status_code == 409


def test_a_chosen_cell_becomes_a_verified_preset(client, grid_with_material):
    grid_id = grid_with_material["id"]
    cell = grid_with_material["cells"][4]

    response = client.post(
        f"/api/library/testgrids/{grid_id}/presets",
        json={"cells": [{"row": cell["row"], "column": cell["column"]}]},
    )

    assert response.status_code == 201
    preset = response.json()["presets"][0]
    assert preset["speed_mm_s"] == cell["speed_mm_s"]
    assert preset["power_percent"] == cell["power_percent"]
    assert preset["source"] == "testraster"
    assert preset["origin_id"] == f"testgrid:{grid_id}"
    assert preset["thickness_mm"] == 3
    assert preset["material_name"] == "Multiplex"


def test_several_cells_can_be_chosen_at_once(client, grid_with_material):
    """Cutting often has a "just enough" and a "with margin" setting."""
    grid_id = grid_with_material["id"]
    picks = [
        {"row": c["row"], "column": c["column"], "note": note}
        for c, note in zip(grid_with_material["cells"][:2], ("net goed", "ruim"))
    ]

    created = client.post(
        f"/api/library/testgrids/{grid_id}/presets", json={"cells": picks}
    ).json()["presets"]

    assert len(created) == 2
    assert {p["note"] for p in created} == {"net goed", "ruim"}


def test_the_grid_remembers_which_cell_produced_which_preset(client, grid_with_material):
    grid_id = grid_with_material["id"]
    cell = grid_with_material["cells"][7]

    preset = client.post(
        f"/api/library/testgrids/{grid_id}/presets",
        json={"cells": [{"row": cell["row"], "column": cell["column"]}]},
    ).json()["presets"][0]

    stored = client.get(f"/api/library/testgrids/{grid_id}").json()
    marked = [c for c in stored["cells"] if c.get("preset_id") == preset["id"]]
    assert len(marked) == 1
    assert (marked[0]["row"], marked[0]["column"]) == (cell["row"], cell["column"])


def test_a_grid_without_a_material_cannot_produce_presets(client):
    grid = client.post("/api/library/testgrids", json=BASE).json()

    response = client.post(
        f"/api/library/testgrids/{grid['id']}/presets",
        json={"cells": [{"row": 0, "column": 0}]},
    )

    assert response.status_code == 409
    assert "materiaal" in str(response.json()["detail"])


def test_a_cell_outside_the_grid_is_refused(client, grid_with_material):
    response = client.post(
        f"/api/library/testgrids/{grid_with_material['id']}/presets",
        json={"cells": [{"row": 99, "column": 99}]},
    )
    assert response.status_code == 409


def test_choosing_nothing_is_a_422(client, grid_with_material):
    response = client.post(
        f"/api/library/testgrids/{grid_with_material['id']}/presets", json={"cells": []}
    )
    assert response.status_code == 422


# --------------------------------------------- raster als één object

def test_a_grid_becomes_one_group(kernel, client):
    """Half a grid dragging around makes no sense; it moves as one thing."""
    grid = client.post("/api/library/testgrids", json=BASE).json()

    assert grid["group_id"]
    group = kernel.elements.find_node(grid["group_id"])
    assert group is not None and group.type == "group"
    # Every cell square sits inside the group.
    inside = {n.id for n in group.flat()}
    for cell in grid["cells"]:
        assert cell["element_id"] in inside


def test_cells_keep_their_own_operations_inside_the_group(kernel, client):
    """Grouping is presentation; the sweep still needs one operation per cell."""
    grid = client.post("/api/library/testgrids", json=BASE).json()

    for cell in grid["cells"]:
        operation = kernel.elements.find_node(cell["operation_id"])
        assert operation.speed == cell["speed_mm_s"]


def test_grid_layers_are_marked_as_such(client):
    grid = client.post("/api/library/testgrids", json=BASE).json()

    operations = client.get("/api/design").json()["operations"]
    marked = [o for o in operations if o.get("grid")]

    assert len(marked) == len(grid["cells"])
    assert {o["grid"]["grid_id"] for o in marked} == {grid["id"]}
    assert all("row" in o["grid"] and "column" in o["grid"] for o in marked)


def test_speed_and_power_of_a_grid_cell_are_locked(client):
    grid = client.post("/api/library/testgrids", json=BASE).json()
    operation_id = grid["cells"][0]["operation_id"]

    for blocked in ({"speed": 50}, {"power_percent": 20}, {"label": "eigen naam"}):
        response = client.patch(f"/api/design/operations/{operation_id}", json=blocked)
        assert response.status_code == 409, blocked
        assert "testraster" in str(response.json()["detail"])


def test_burning_a_single_cell_can_be_switched_off(kernel, client):
    """A row that clearly cuts straight through can be skipped."""
    grid = client.post("/api/library/testgrids", json=BASE).json()
    operation_id = grid["cells"][0]["operation_id"]

    response = client.patch(f"/api/design/operations/{operation_id}", json={"output": False})

    assert response.status_code == 200
    assert kernel.elements.find_node(operation_id).output is False


def test_removing_a_grid_clears_the_design_but_keeps_the_record(kernel, client):
    grid = client.post("/api/library/testgrids", json=BASE).json()
    assert list(kernel.elements.elems())

    response = client.post(f"/api/library/testgrids/{grid['id']}/remove-from-design")

    assert response.status_code == 200
    assert list(kernel.elements.elems()) == []
    for cell in grid["cells"]:
        assert kernel.elements.find_node(cell["operation_id"]) is None
    # The grid itself survives: the photo and preset provenance hang off it.
    assert client.get(f"/api/library/testgrids/{grid['id']}").status_code == 200


def test_removing_a_grid_takes_the_label_layer_too(kernel, client):
    """Otherwise every generated grid leaves a Raster-labels layer behind."""
    grid = client.post("/api/library/testgrids", json=BASE).json()

    client.post(f"/api/library/testgrids/{grid['id']}/remove-from-design")

    labels = [o for o in kernel.elements.ops() if getattr(o, "label", None) == "Raster-labels"]
    assert labels == []


def test_a_stale_grid_id_does_not_lock_an_unrelated_layer(kernel, client, tmp_path):
    """
    Grid-to-operation links live in the database and outlive a restart, while
    element ids are handed out per document. An id from an old grid can land on
    a new operation by coincidence; that must not silently lock it.
    """
    grid = client.post("/api/library/testgrids", json=BASE).json()
    borrowed = grid["cells"][0]["operation_id"]
    client.post(f"/api/library/testgrids/{grid['id']}/remove-from-design")

    # A fresh layer that happens to carry the same id, with different settings.
    fresh = client.post(
        "/api/design/operations", json={"type": "cut", "speed": 99, "power_percent": 33}
    ).json()
    node = kernel.elements.find_node(fresh["id"])
    node.id = borrowed
    kernel.elements.signal("rebuild_tree", "all")

    marked = [o for o in client.get("/api/design").json()["operations"] if o.get("grid")]
    assert all(o["id"] != borrowed for o in marked)
    assert client.patch(f"/api/design/operations/{borrowed}", json={"speed": 50}).status_code == 200


def test_the_newest_grid_wins_a_shared_operation_id(client):
    """
    Two grids in the library can carry the same operation ids, because ids are
    handed out per document. The grid on the canvas now is the newest one, so
    its cells must be the ones recognised.
    """
    first = client.post("/api/library/testgrids", json=BASE).json()
    client.post(f"/api/library/testgrids/{first['id']}/remove-from-design")
    second = client.post("/api/library/testgrids", json=BASE).json()

    marked = [o for o in client.get("/api/design").json()["operations"] if o.get("grid")]

    assert len(marked) == len(second["cells"])
    assert {o["grid"]["grid_id"] for o in marked} == {second["id"]}


def test_the_series_lands_on_values_a_person_would_type():
    """
    Een raster dat rijen snijdt op 11,667 mm/s is geen naslagwerk. Begin en eind
    blijven exact; alleen de tussenstappen schuiven naar een net getal.
    """
    from openkerf_api.testgrid import _spread

    reeks = _spread(5, 25, 4)

    assert reeks[0] == 5 and reeks[-1] == 25
    assert reeks == [5.0, 12.5, 17.5, 25.0]
    assert all(round(v * 10) == v * 10 for v in reeks), reeks


def test_a_narrow_range_keeps_its_steps_apart():
    """
    Afronden mag nooit twee identieke rijen opleveren: dan brand je twee keer
    hetzelfde en heb je een kolom verspild.
    """
    from openkerf_api.testgrid import _spread

    for lo, hi, stappen in ((10, 12, 4), (0.5, 2, 4), (100, 101, 5), (5, 25, 6)):
        reeks = _spread(lo, hi, stappen)
        assert len(set(reeks)) == stappen, (lo, hi, stappen, reeks)
        assert all(reeks[i] < reeks[i + 1] for i in range(len(reeks) - 1)), reeks
        assert reeks[0] == lo and reeks[-1] == hi


def test_the_board_carries_a_caption(kernel, client):
    """
    Een gebrand raster zonder opschrift is over twee weken een raadselachtig
    stuk hout. Materiaal, dikte, bewerking en datum horen erop.
    """
    material = client.post("/api/library/materials", json={"name": "Berkentriplex"}).json()
    client.post(
        "/api/library/testgrids",
        json={**BASE, "material_id": material["id"], "thickness_mm": 3},
    )

    snapshot = DesignReader(kernel).snapshot()
    perMm = snapshot["units_per_mm"]
    labels = [op for op in snapshot["operations"] if op["label"] == "Raster-labels"][0]
    dozen = [
        [v / perMm for v in e["bounds"]]
        for e in snapshot["elements"]
        if e["id"] in labels["element_ids"] and e["bounds"]
    ]

    # De tekst is omgezet naar geometrie, dus de letters zijn niet terug te
    # lezen. Wat wel klopt: het opschrift staat bóven de kolomlabels en is
    # breder dan één vakje — geen enkel aslabel is dat.
    boven = [d for d in dozen if d[3] < BASE["origin_y_mm"] - 4]
    assert len(boven) == 1, dozen
    assert boven[0][2] - boven[0][0] > BASE["cell_mm"] * 2, boven


# ------------------------------------------------- interval als derde as (B12)

RASTER = {
    **BASE,
    "operation": "graveren-raster",
    "row_axis": "interval",
    "column_axis": "power",
    "interval_min": 0.05,
    "interval_max": 0.3,
    "interval_steps": 3,
    "speed_mm_s": 200,
}


def test_interval_can_be_an_axis_with_speed_held_fixed():
    """
    B12: bij graveren bepaalt de lijnafstand het resultaat minstens zoveel als
    het vermogen. Wat níét op een as staat, ligt vast voor het hele bord.
    """
    plan, cells = plan_grid(**RASTER)

    assert plan["rows"] == 3 and plan["columns"] == 3
    assert sorted({c["interval_mm"] for c in cells}) == [0.05, 0.15, 0.3]
    assert {c["speed_mm_s"] for c in cells} == {200}
    # De vaste grootheid staat als één punt in de rij: min == max, één stap.
    assert (plan["speed_min"], plan["speed_max"], plan["speed_steps"]) == (200, 200, 1)


def test_the_interval_varies_down_the_rows_it_was_put_on():
    _, cells = plan_grid(**RASTER)
    kolom = [c for c in cells if c["column"] == 0]

    assert [c["interval_mm"] for c in kolom] == [0.05, 0.15, 0.3]
    assert len({c["power_percent"] for c in kolom}) == 1


def test_interval_is_refused_where_it_means_nothing():
    """Bij snijden legt de kop één lijn; een lijnafstand-as zou daar niets doen."""
    with pytest.raises(DesignError) as fout:
        plan_grid(**{**RASTER, "operation": "snijden"})

    assert "rasteren" in str(fout.value)


def test_two_axes_cannot_be_the_same_quantity():
    with pytest.raises(DesignError):
        plan_grid(**{**BASE, "row_axis": "power", "column_axis": "power"})


def test_swapping_the_axes_swaps_the_board():
    """Snelheid naar rechts in plaats van naar beneden, en verder niets anders."""
    _, cells = plan_grid(**{**BASE, "row_axis": "power", "column_axis": "speed"})
    rij = [c for c in cells if c["row"] == 0]

    assert [c["speed_mm_s"] for c in rij] == [5, 15, 25]
    assert len({c["power_percent"] for c in rij}) == 1


def test_an_interval_grid_sets_the_dpi_on_each_operation(kernel, client):
    """
    De engine kent geen interval maar dpi. Zonder deze omrekening zou elk vakje
    op dezelfde lijnafstand branden en test je niets.
    """
    grid = client.post("/api/library/testgrids", json=RASTER).json()

    for cell in grid["cells"]:
        operation = kernel.elements.find_node(cell["operation_id"])
        assert operation.type == "op raster"
        assert operation.dpi == pytest.approx(round(25.4 / cell["interval_mm"]), abs=1)


def test_the_stored_grid_remembers_which_axis_was_which(client):
    grid = client.post("/api/library/testgrids", json=RASTER).json()

    assert grid["row_axis"] == "interval"
    assert grid["column_axis"] == "power"
    assert (grid["rows"], grid["columns"]) == (3, 3)
    assert grid["interval_steps"] == 3


def test_a_preset_from_an_interval_grid_carries_its_interval(client):
    """
    Zonder de lijnafstand is de preset niet na te branden: dezelfde snelheid en
    hetzelfde vermogen op een ander interval geven een ander resultaat.
    """
    material = client.post("/api/library/materials", json={"name": "Berken"}).json()
    grid = client.post(
        "/api/library/testgrids", json={**RASTER, "material_id": material["id"]}
    ).json()
    cell = grid["cells"][4]

    made = client.post(
        f"/api/library/testgrids/{grid['id']}/presets",
        json={"cells": [{"row": cell["row"], "column": cell["column"]}]},
    )

    assert made.status_code == 201
    assert made.json()["presets"][0]["interval_mm"] == cell["interval_mm"]


# ------------------------------------------------------- uitlijning (gat T4)

def test_alignment_survives_a_different_browser(client):
    """
    T4: uitlijnen doe je op de desktop, het vakje aanwijzen op de tablet naast
    de machine. In localStorage was die tweede helft een leeg raster over een
    schuine foto.
    """
    grid = client.post("/api/library/testgrids", json=BASE).json()
    hoeken = [
        {"x": 0.12, "y": 0.08},
        {"x": 0.91, "y": 0.14},
        {"x": 0.88, "y": 0.93},
        {"x": 0.09, "y": 0.87},
    ]

    response = client.put(
        f"/api/library/testgrids/{grid['id']}/alignment", json={"corners": hoeken}
    )

    assert response.status_code == 200
    assert response.json()["alignment"] == hoeken
    # En hij komt terug bij het ophalen, niet alleen in het antwoord.
    assert client.get(f"/api/library/testgrids/{grid['id']}").json()["alignment"] == hoeken


def test_a_fresh_grid_has_no_alignment_yet(client):
    grid = client.post("/api/library/testgrids", json=BASE).json()

    assert grid["alignment"] is None


def test_a_broken_alignment_is_refused(client):
    grid = client.post("/api/library/testgrids", json=BASE).json()

    for kapot in ([], [{"x": 0, "y": 0}], [{"x": 5, "y": 0}] * 4, "linksboven"):
        response = client.put(
            f"/api/library/testgrids/{grid['id']}/alignment", json={"corners": kapot}
        )
        assert response.status_code == 409, kapot


def test_alignment_can_be_cleared(client):
    grid = client.post("/api/library/testgrids", json=BASE).json()
    client.put(
        f"/api/library/testgrids/{grid['id']}/alignment",
        json={"corners": [{"x": 0.1, "y": 0.1}] * 4},
    )

    response = client.put(
        f"/api/library/testgrids/{grid['id']}/alignment", json={"corners": None}
    )

    assert response.json()["alignment"] is None


# ------------------------------------- het vakje aanwijzen op de foto (gat M4)

def _foto(kleur=(120, 90, 60), maat=(200, 160)):
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", maat, kleur).save(buffer, format="JPEG")
    return buffer.getvalue()


def test_the_photo_can_come_back_with_the_chosen_cell_marked(client):
    """
    M4: de herkomst zei "rij 2, kolom 3" en op de foto was niets gemarkeerd.
    Met ?cell= tekent de server dezelfde overlay in het beeld zelf, zodat de
    markering meekomt in elk <img> dat de foto toont.
    """
    grid = client.post("/api/library/testgrids", json=BASE).json()
    client.post(
        f"/api/library/testgrids/{grid['id']}/photo",
        files={"file": ("bord.jpg", _foto(), "image/jpeg")},
    )

    kaal = client.get(f"/api/library/testgrids/{grid['id']}/photo")
    gemerkt = client.get(f"/api/library/testgrids/{grid['id']}/photo?cell=1-2")

    assert kaal.status_code == 200 and gemerkt.status_code == 200
    assert gemerkt.headers["content-type"] == "image/jpeg"
    assert gemerkt.content != kaal.content


def test_the_mark_follows_the_alignment(client):
    """
    Dezelfde cel, twee uitlijningen: het merkteken hoort mee te schuiven. Anders
    wijst hij naar een plek waar niets gebrand is.
    """
    from PIL import Image
    from io import BytesIO

    grid = client.post("/api/library/testgrids", json=BASE).json()
    client.post(
        f"/api/library/testgrids/{grid['id']}/photo",
        files={"file": ("bord.jpg", _foto(), "image/jpeg")},
    )

    eerst = client.get(f"/api/library/testgrids/{grid['id']}/photo?cell=0-0").content
    client.put(
        f"/api/library/testgrids/{grid['id']}/alignment",
        json={
            "corners": [
                {"x": 0.3, "y": 0.3},
                {"x": 0.95, "y": 0.3},
                {"x": 0.95, "y": 0.95},
                {"x": 0.3, "y": 0.95},
            ]
        },
    )
    daarna = client.get(f"/api/library/testgrids/{grid['id']}/photo?cell=0-0").content

    assert eerst != daarna
    # En het blijft een leesbare foto van hetzelfde formaat.
    assert Image.open(BytesIO(daarna)).size == Image.open(BytesIO(eerst)).size


def test_marking_a_cell_that_is_not_there_is_a_clean_error(client):
    grid = client.post("/api/library/testgrids", json=BASE).json()
    client.post(
        f"/api/library/testgrids/{grid['id']}/photo",
        files={"file": ("bord.jpg", _foto(), "image/jpeg")},
    )

    assert client.get(f"/api/library/testgrids/{grid['id']}/photo?cell=9-9").status_code == 409
    assert client.get(f"/api/library/testgrids/{grid['id']}/photo?cell=kwart").status_code == 422


# ------------------------------------------ vorige instelling onthouden (T3)

def test_the_next_grid_starts_where_the_last_one_for_this_material_left_off(client):
    """
    T3: wie wekelijks 3 mm berk test, stelt elke week hetzelfde in. Het vorige
    raster ís die instelling; daar is geen aparte voorkeurentabel voor nodig.
    """
    berk = client.post("/api/library/materials", json={"name": "Berken"}).json()
    client.post(
        "/api/library/testgrids",
        json={**BASE, "material_id": berk["id"], "thickness_mm": 3, "speed_max": 40},
    )

    vorige = client.get(f"/api/library/testgrids/defaults?material_id={berk['id']}").json()

    assert vorige["speed_max"] == 40
    assert vorige["thickness_mm"] == 3
    assert vorige["operation"] == "snijden"
    assert vorige["row_axis"] == "speed"


def test_defaults_are_per_material(client):
    berk = client.post("/api/library/materials", json={"name": "Berken"}).json()
    acryl = client.post("/api/library/materials", json={"name": "Acryl"}).json()
    client.post(
        "/api/library/testgrids", json={**BASE, "material_id": berk["id"], "speed_max": 40}
    )

    assert client.get(f"/api/library/testgrids/defaults?material_id={acryl['id']}").json() is None
    assert (
        client.get(f"/api/library/testgrids/defaults?material_id={berk['id']}").json()[
            "speed_max"
        ]
        == 40
    )


def test_defaults_remember_a_fixed_quantity_too(client):
    """De vaste snelheid van een intervalraster hoort er de volgende keer weer te staan."""
    berk = client.post("/api/library/materials", json={"name": "Berken"}).json()
    client.post("/api/library/testgrids", json={**RASTER, "material_id": berk["id"]})

    vorige = client.get(f"/api/library/testgrids/defaults?material_id={berk['id']}").json()

    assert vorige["row_axis"] == "interval"
    assert (vorige["speed_min"], vorige["speed_steps"]) == (200, 1)


# ------------------------------------------- ruimte voor de rijlabels


def test_the_plan_says_how_much_room_the_row_labels_need():
    """
    De rijlabels worden links van het raster gegraveerd. Bij Start X 10 mm en
    driecijferige snelheden staan ze buiten het bed: de machine brandt ze niet
    en het bord is naderhand onleesbaar. Het plan meldt dat vóór het branden.
    """
    krap = plan_grid(**{**BASE, "speed_min": 100, "speed_max": 300, "origin_x_mm": 10})[0]

    assert krap["label_margin_mm"] > 10
    assert krap["label_room"] is False

    ruim = plan_grid(
        **{**BASE, "speed_min": 100, "speed_max": 300, "origin_x_mm": 40}
    )[0]

    assert ruim["label_room"] is True


# ------------------------- kan deze engine wel rasteren? (gemeten, niet gehoopt)


def test_the_preview_says_whether_this_engine_can_burn_a_raster(client):
    """
    `op raster` zet zijn vormen tijdens het plannen om in een bitmap via
    `render-op/make_raster`, en die dienst registreert **alleen de wxPython-GUI**
    (`meerk40t/gui/plugin.py:79`). Headless neemt `preprocess` de
    `strip_rasters`-tak: de laag gooit zijn kinderen weg en levert nul cutcode.
    Het bord komt dan blanco uit de machine.

    Deze test legt de stand vast waarin we draaien. Wordt hij rood omdat er
    ineens `True` staat, dan is er een rasteraar bijgekomen en mag de
    waarschuwing in TestGrid.svelte weg.
    """
    antwoord = client.post("/api/library/testgrids/preview", json=RASTER).json()

    assert antwoord["engine"]["raster"] is False


def test_a_raster_grid_produces_no_cutcode_on_a_headless_engine(kernel, client):
    """
    De meting onder de waarschuwing hierboven: een ontwerp met alleen
    rasterlagen levert nul brandtijd over nul delen. Dit is het bewijs dat de
    melding geen voorzichtigheid is maar een feit.
    """
    client.post("/api/library/testgrids", json=RASTER)
    # De labellaag brandt wél (die is een engrave); alleen de sweep meten.
    for operation in kernel.elements.ops():
        if getattr(operation, "label", None) == "Raster-labels":
            operation.output = False

    exact = client.get("/api/job/estimate?exact=1").json()

    assert exact["parts"] == 0
    assert exact["seconds"] == 0.0
    # En de lagen bestaan wél — het zijn er negen, ze doen alleen niets.
    assert len([laag for laag in exact["layers"] if laag["type"] == "op raster"]) == 9


def test_a_vector_grid_does_produce_cutcode(kernel, client):
    """Het tegenbewijs: snijden en vectorgraveren branden wel, ook headless."""
    client.post("/api/library/testgrids", json=BASE)
    for operation in kernel.elements.ops():
        if getattr(operation, "label", None) == "Raster-labels":
            operation.output = False

    exact = client.get("/api/job/estimate?exact=1").json()

    # `parts` telt hier de stukken van het snijplan, niet de vormen; wat telt is
    # dat er iets te branden is en dat het tijd kost.
    assert exact["parts"] >= 1
    assert exact["seconds"] > 0


def test_the_plan_prices_the_board_in_seconds():
    """
    Wat het gaat kosten, vóór er iets getekend is. Interval als as kan de
    brandtijd stil vermenigvuldigen; dan hoort er een getal te staan dat
    meebeweegt.
    """
    snijden = plan_grid(**BASE)[0]
    assert snijden["seconds"] > 0

    # Zelfde bord, halve snelheid: ruwweg dubbele brandtijd.
    langzamer = plan_grid(**{**BASE, "speed_min": 2.5, "speed_max": 12.5})[0]
    assert langzamer["seconds"] > snijden["seconds"] * 1.5

    # En een fijner interval kost meer regels, dus meer tijd.
    grof = plan_grid(**{**RASTER, "interval_min": 0.3, "interval_max": 0.4})[0]
    fijn = plan_grid(**{**RASTER, "interval_min": 0.05, "interval_max": 0.06})[0]
    assert fijn["seconds"] > grof["seconds"] * 4, (fijn["seconds"], grof["seconds"])
