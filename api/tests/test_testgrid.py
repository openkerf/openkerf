"""Planning and drawing a parametric test grid."""

import pytest
from fastapi.testclient import TestClient

from openkerf_api.design import DesignReader
from openkerf_api.edits import DesignError
from openkerf_api.server import ApiServer
from openkerf_api.testgrid import LABEL_FONTS, plan_grid

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


def test_removing_a_grid_never_touches_another_sheets_work(kernel, client):
    """
    Een raster van vel 1 weghalen terwijl je op vel 2 staat, wiste daar het werk.

    Id's worden per document uitgedeeld, dus `meerk40t:3` op vel 2 is een ander
    ding dan `meerk40t:3` op vel 1 — en het weghalen zocht ze puur op id op.
    Gemeten: dertien lagen van een ánder raster verdwenen zonder een woord.
    """
    grid = client.post("/api/library/testgrids", json=BASE).json()
    geleend_op = grid["cells"][0]["operation_id"]
    geleend_elem = grid["cells"][0]["element_id"]
    groep = grid["group_id"]

    client.post("/api/sheets", json={"name": "Tweede"})
    client.post("/api/sheets/vel-2/activate")
    laag = client.post(
        "/api/design/operations", json={"type": "cut", "speed": 99, "power_percent": 33}
    ).json()["id"]
    rect = client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 100, "y_mm": 100, "width_mm": 30, "height_mm": 30},
    ).json()["ids"][0]
    client.post("/api/design/assign", json={"ids": [rect], "operation_id": laag})
    # Precies de botsing die in het echt vanzelf ontstaat: dezelfde id's.
    kernel.elements.find_node(laag).id = geleend_op
    kernel.elements.find_node(rect).id = geleend_elem
    if groep:
        for node in kernel.elements.elems():
            node.id = groep
            break

    client.post(f"/api/library/testgrids/{grid['id']}/remove-from-design")

    overgebleven = client.get("/api/design").json()
    assert len(overgebleven["elements"]) == 1, "het werk op dit vel is verdwenen"
    assert any(o["id"] == geleend_op for o in overgebleven["operations"])


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
    `render-op/make_raster`. Die dienst registreert upstream **alleen de
    wxPython-GUI** (`meerk40t/gui/plugin.py:79`); zonder hem neemt `preprocess`
    de `strip_rasters`-tak, gooit de laag zijn kinderen weg en komt het bord
    blanco uit de machine.

    Onze plugin registreert er sinds `openkerf_api/rasterizer.py` zelf een. Deze
    engine kán dus rasteren, en het voorbeeld hoort dat te melden. Wordt dit
    weer `False`, dan is de rasteraar niet geladen en brandt elke rasterlaag
    niets — dan hoort de blokkade in TestGrid.svelte terug.
    """
    antwoord = client.post("/api/library/testgrids/preview", json=RASTER).json()

    assert antwoord["engine"]["raster"] is True


def test_a_raster_grid_produces_cutcode_on_a_headless_engine(kernel, client):
    """
    De meting onder de melding hierboven. Voorheen gaf ditzelfde ontwerp
    0 stukken over 0,0 s — negen rasterlagen die niets deden. Met de rasteraar
    uit `openkerf_api/rasterizer.py` levert het werk dat tijd kost.

    De tegenproef staat eronder: zonder de dienst is het weer nul.
    """
    client.post("/api/library/testgrids", json=RASTER)
    # De labellaag brandt wél (die is een engrave); alleen de sweep meten.
    for operation in kernel.elements.ops():
        if getattr(operation, "label", None) == "Raster-labels":
            operation.output = False

    exact = client.get("/api/job/estimate?exact=1").json()

    assert exact["parts"] >= 1
    assert exact["seconds"] > 0
    assert len([laag for laag in exact["layers"] if laag["type"] == "op raster"]) == 9


def test_without_a_rasteriser_the_same_grid_burns_nothing(kernel, client):
    """
    Waarom de rasteraar er moest komen, in één meting: haal hem weg en het bord
    is leeg. Dit is de stand waarin MeerK40t headless uit de doos draait.
    """
    kernel.root.register("render-op/make_raster", None)
    client.post("/api/library/testgrids", json=RASTER)
    for operation in kernel.elements.ops():
        if getattr(operation, "label", None) == "Raster-labels":
            operation.output = False

    exact = client.get("/api/job/estimate?exact=1").json()

    assert exact["parts"] == 0
    assert exact["seconds"] == 0.0


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


def test_a_preset_says_whether_its_photo_is_aligned(client):
    """
    De markering op de foto valt zonder uitlijning terug op vier
    standaardhoeken, en dan ligt de omtrek er ongeveer. De bibliotheek moet dat
    kunnen zeggen; anders suggereert de kaart een precisie die er niet is.
    """
    material = client.post("/api/library/materials", json={"name": "Berken"}).json()
    grid = client.post(
        "/api/library/testgrids", json={**BASE, "material_id": material["id"]}
    ).json()
    cell = grid["cells"][0]
    client.post(
        f"/api/library/testgrids/{grid['id']}/presets",
        json={"cells": [{"row": cell["row"], "column": cell["column"]}]},
    )

    zonder = client.get("/api/library/presets?all_machines=true").json()[0]
    assert zonder["grid_aligned"] is False

    client.put(
        f"/api/library/testgrids/{grid['id']}/alignment",
        json={"corners": [{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.1},
                          {"x": 0.9, "y": 0.9}, {"x": 0.1, "y": 0.9}]},
    )

    met = client.get("/api/library/presets?all_machines=true").json()[0]
    assert met["grid_aligned"] is True


def test_a_preset_without_a_grid_has_no_alignment_claim(client):
    """Een handmatige preset heeft geen raster, dus ook geen uitlijning."""
    material = client.post("/api/library/materials", json={"name": "Acryl"}).json()
    client.post(
        "/api/library/presets",
        json={
            "material_id": material["id"],
            "operation": "snijden",
            "speed_mm_s": 12,
            "power_percent": 65,
        },
    )

    preset = client.get("/api/library/presets?all_machines=true").json()[0]

    assert preset["grid_id"] is None
    assert preset["grid_aligned"] is False


# ------------------------- vanaf de hoek of vanaf het midden (gat T9)


def test_the_corner_is_still_the_default():
    """Wat er stond blijft staan: Start X/Y is de hoek van de vakjes."""
    plan, cells = plan_grid(**BASE)

    assert plan["anchor"] == "corner"
    assert (plan["origin_x_mm"], plan["origin_y_mm"]) == (10, 10)
    assert (cells[0]["x_mm"], cells[0]["y_mm"]) == (10, 10)


def test_centring_puts_the_middle_of_the_board_on_the_point():
    """
    Een testbord leg je op een reststuk, en dan weet je waar het mídden van dat
    stuk ligt. Het midden slaat op het hele bord: het raster centreren terwijl
    de rijlabels er links buiten steken, legt het bord scheef.
    """
    plan, _ = plan_grid(**{**BASE, "anchor": "center", "origin_x_mm": 200, "origin_y_mm": 150})

    assert plan["center_x_mm"] == pytest.approx(200)
    assert plan["center_y_mm"] == pytest.approx(150)
    assert plan["outer_x_mm"] == pytest.approx(200 - plan["outer_width_mm"] / 2)
    assert plan["outer_y_mm"] == pytest.approx(150 - plan["outer_height_mm"] / 2)
    # De vakjes zijn opgeschoven, niet het opschrift eromheen.
    assert plan["origin_x_mm"] > plan["outer_x_mm"]
    assert plan["width_mm"] == 28


def test_a_centred_board_is_wider_than_its_cells():
    """De gemelde maat is inclusief labels en opschrift — precies wat T11 miste."""
    plan, _ = plan_grid(**BASE)

    assert plan["outer_width_mm"] > plan["width_mm"]
    assert plan["outer_height_mm"] > plan["height_mm"]


def test_an_unknown_anchor_is_refused():
    with pytest.raises(DesignError):
        plan_grid(**{**BASE, "anchor": "ergens"})


def test_the_reported_size_covers_everything_that_is_drawn(kernel, client):
    """
    Gemeten in plaats van gerekend: het gemelde kader moet elke vorm bevatten
    die er werkelijk gebrand wordt, opschrift en randkader inbegrepen. Dit is
    de test die een verschoven schatting vangt.
    """
    plan = client.post(
        "/api/library/testgrids/preview",
        json={**BASE, "origin_x_mm": 60, "origin_y_mm": 60, "border": True},
    ).json()["plan"]
    client.post(
        "/api/library/testgrids",
        json={**BASE, "origin_x_mm": 60, "origin_y_mm": 60, "border": True},
    )

    snapshot = DesignReader(kernel).snapshot()
    per_mm = snapshot["units_per_mm"]
    for element in snapshot["elements"]:
        if not element["bounds"]:
            continue
        x0, y0, x1, y1 = (v / per_mm for v in element["bounds"])
        assert x0 >= plan["outer_x_mm"] - 0.5, element["id"]
        assert y0 >= plan["outer_y_mm"] - 0.5, element["id"]
        assert x1 <= plan["outer_x_mm"] + plan["outer_width_mm"] + 0.5, element["id"]
        assert y1 <= plan["outer_y_mm"] + plan["outer_height_mm"] + 0.5, element["id"]


def test_a_centred_board_that_runs_off_the_bed_is_refused(kernel, client):
    response = client.post(
        "/api/library/testgrids",
        json={**BASE, "anchor": "center", "origin_x_mm": 315, "origin_y_mm": 150},
    )

    assert response.status_code == 409
    assert "bed" in str(response.json()["detail"])
    assert len(list(kernel.elements.elems())) == 0


def test_a_board_that_starts_left_of_the_bed_is_reported_not_refused():
    """
    Zoals bij T11: links uitsteken kost je de opschriften, niet het raster.
    Melden dus, en niet blokkeren — het bord zelf brandt gewoon.
    """
    plan, _ = plan_grid(**{**BASE, "origin_x_mm": 2})

    assert plan["board_room"] is False
    assert plan["label_room"] is False


# ---------------------------- de letter op het bord staat vast (bug-raster 1)


def _label_fonts(kernel) -> set[str]:
    """De lettertypen van alles wat op het bord aan tekst staat."""
    return {
        element["text"]["font"]
        for element in DesignReader(kernel).snapshot()["elements"]
        if element.get("text")
    }


def test_the_board_uses_its_own_font_whatever_the_user_last_picked(kernel, client):
    """
    Jelle's bevinding: kies een lettertype in het tekstvenster, maak daarna een
    testraster, en de opschriften staan in dát lettertype.

    De oorzaak zit in de engine: `linetext` zonder `-f` valt terug op
    `context.last_font`, een instelling die elke tekstplaatsing overschrijft.
    Een bord is een bewijsstuk — wat erop staat mag niet afhangen van wat je
    een uur eerder toevallig koos.
    """
    client.post(
        "/api/design/elements",
        json={
            "type": "text",
            "x_mm": 10,
            "y_mm": 10,
            "text": "Hallo",
            "font": "Apple Chancery.ttf",
            "font_size_mm": 8,
        },
    )
    client.post("/api/library/testgrids", json=BASE)

    fonts = _label_fonts(kernel)
    assert "Apple Chancery.ttf" in fonts, "de tekst van de gebruiker zelf"
    assert fonts - {"Apple Chancery.ttf"} == {LABEL_FONTS[0]}


def test_the_board_leaves_the_users_font_choice_alone(kernel, client):
    """
    Onze keuze mag geen voorkeur worden.

    `create_linetext_node` zet `last_font` op wat het net gebruikte, dus zonder
    herstel zou het volgende stuk tekst van de gebruiker in ónze labelletter
    verschijnen — dezelfde fout, andere kant op.
    """
    client.post(
        "/api/design/elements",
        json={"type": "text", "x_mm": 10, "y_mm": 10, "text": "Voor", "font": "Arial.ttf"},
    )
    client.post("/api/library/testgrids", json=BASE)
    client.post(
        "/api/design/elements",
        json={"type": "text", "x_mm": 10, "y_mm": 60, "text": "Na"},
    )

    na = [
        element
        for element in DesignReader(kernel).snapshot()["elements"]
        if element.get("text") and element["text"]["text"] == "Na"
    ]
    assert na and na[0]["text"]["font"] == "Arial.ttf"


# ------------------------------- tekst en rand zijn te kiezen (gat T10)


def test_text_can_be_switched_off(kernel, client):
    """Voor een proefje op een restje is het opschrift verspilling."""
    client.post("/api/library/testgrids", json={**BASE, "text": False})

    snapshot = DesignReader(kernel).snapshot()
    assert [op for op in snapshot["operations"] if op["label"] == "Raster-labels"] == []
    assert len(snapshot["elements"]) == 9  # alleen de vakjes


def test_text_is_on_by_default(kernel, client):
    """Het bord is een bewijsstuk; het opschrift hoort er standaard op."""
    client.post("/api/library/testgrids", json=BASE)

    snapshot = DesignReader(kernel).snapshot()
    assert [op for op in snapshot["operations"] if op["label"] == "Raster-labels"]


def test_a_board_without_text_needs_no_room_beside_it():
    plan, _ = plan_grid(**{**BASE, "text": False})

    assert plan["outer_width_mm"] == plan["width_mm"]
    assert plan["outer_height_mm"] == plan["height_mm"]
    assert plan["label_room"] is True


def test_the_border_frames_the_whole_board(kernel, client):
    """
    Een kader dwars door de rijlabels maakt het bord juist onleesbaar, dus het
    ligt om alles heen — en het brandt in de labellaag, niet in de sweep.
    """
    grid = client.post(
        "/api/library/testgrids", json={**BASE, "origin_x_mm": 40, "border": True}
    ).json()

    snapshot = DesignReader(kernel).snapshot()
    per_mm = snapshot["units_per_mm"]
    labels = [op for op in snapshot["operations"] if op["label"] == "Raster-labels"][0]
    dozen = [
        [v / per_mm for v in e["bounds"]]
        for e in snapshot["elements"]
        if e["id"] in labels["element_ids"] and e["bounds"]
    ]
    kader = max(dozen, key=lambda d: (d[2] - d[0]) * (d[3] - d[1]))
    # Elke andere vorm ligt erbinnen — ook de vakjes.
    for cell in grid["cells"]:
        element = next(e for e in snapshot["elements"] if e["id"] == cell["element_id"])
        x0, y0, x1, y1 = (v / per_mm for v in element["bounds"])
        assert kader[0] <= x0 and kader[1] <= y0
        assert x1 <= kader[2] and y1 <= kader[3]


def test_there_is_no_border_unless_you_ask(kernel, client):
    """Nieuw werk aanzetten voor iedereen die niets vroeg, verandert stil zijn bord."""
    client.post("/api/library/testgrids", json=BASE)

    snapshot = DesignReader(kernel).snapshot()
    # Negen vakjes, drie rijlabels, drie kolomlabels, één opschrift.
    assert len(snapshot["elements"]) == 16


def test_the_label_layer_can_be_set(kernel, client):
    """80 mm/s @30% werkt op berken en niet op acryl."""
    client.post(
        "/api/library/testgrids",
        json={**BASE, "label_speed_mm_s": 120, "label_power_percent": 18},
    )

    labels = next(
        op for op in kernel.elements.ops() if getattr(op, "label", "") == "Raster-labels"
    )
    assert labels.speed == 120
    assert labels.power == pytest.approx(180)  # 0-1000 in de engine


def test_the_label_layer_falls_back_to_what_it_always_was(kernel, client):
    client.post("/api/library/testgrids", json=BASE)

    labels = next(
        op for op in kernel.elements.ops() if getattr(op, "label", "") == "Raster-labels"
    )
    assert labels.speed == 80
    assert labels.power == pytest.approx(300)


def test_an_impossible_label_layer_is_refused():
    with pytest.raises(DesignError):
        plan_grid(**{**BASE, "label_power_percent": 140})


def test_the_choices_survive_into_the_stored_grid(client):
    """
    Zonder dit vergeet T3 hoe je het bord neerlegde: de volgende keer stond het
    weer vanaf de hoek, met een opschrift dat je net had uitgezet.
    """
    material = client.post("/api/library/materials", json={"name": "Vilt"}).json()
    client.post(
        "/api/library/testgrids",
        json={
            **BASE,
            "material_id": material["id"],
            "anchor": "center",
            "origin_x_mm": 200,
            "origin_y_mm": 150,
            "text": False,
            "border": True,
        },
    )

    vorige = client.get(
        f"/api/library/testgrids/defaults?material_id={material['id']}"
    ).json()

    assert vorige["anchor"] == "center"
    assert vorige["text_enabled"] is False
    assert vorige["border_enabled"] is True
    # En het punt dat je intikte komt terug, niet de hoek die eruit gerekend is.
    assert vorige["anchor_x_mm"] == pytest.approx(200)
    assert vorige["anchor_y_mm"] == pytest.approx(150)


# --------------------------------- benoemde generatorpresets (gat T7)


def test_a_recipe_keeps_its_settings_under_a_name(client):
    material = client.post("/api/library/materials", json={"name": "Berken"}).json()

    recept = client.post(
        "/api/library/testgrids/recipes",
        json={
            "name": "Berk snijden",
            "material_id": material["id"],
            "settings": {**BASE, "speed_mm_s": 12},
        },
    ).json()

    assert recept["name"] == "Berk snijden"
    assert recept["settings"]["operation"] == "snijden"
    assert recept["settings"]["speed_min"] == 5
    assert recept["material_name"] == "Berken"


def test_two_recipes_for_one_material_live_side_by_side(client):
    """
    Precies wat T3 niet kon: "berk snijden" naast "berk graveren". Eén
    instelling per materiaal onthouden dekt de wekelijkse proef, niet de twee
    recepten die je afwisselt.
    """
    material = client.post("/api/library/materials", json={"name": "Berken"}).json()
    for naam, bewerking in (("Snijden", "snijden"), ("Graveren", "graveren-vector")):
        client.post(
            "/api/library/testgrids/recipes",
            json={
                "name": naam,
                "material_id": material["id"],
                "settings": {**BASE, "operation": bewerking},
            },
        )

    recepten = client.get(
        f"/api/library/testgrids/recipes?material_id={material['id']}"
    ).json()

    assert [r["name"] for r in recepten] == ["Graveren", "Snijden"]  # alfabetisch
    assert {r["settings"]["operation"] for r in recepten} == {
        "snijden",
        "graveren-vector",
    }


def test_saving_the_same_name_twice_updates_it(client):
    """Anders staan er twee regels waartussen je niet kunt kiezen."""
    client.post(
        "/api/library/testgrids/recipes",
        json={"name": "Snel", "settings": {**BASE, "cell_mm": 8}},
    )
    client.post(
        "/api/library/testgrids/recipes",
        json={"name": "snel", "settings": {**BASE, "cell_mm": 12}},
    )

    recepten = client.get("/api/library/testgrids/recipes").json()

    assert len(recepten) == 1
    assert recepten[0]["settings"]["cell_mm"] == 12


def test_a_recipe_without_a_material_shows_up_everywhere(client):
    """"Snelle 4×4" hoort bij geen plank; juist bij iets nieuws wil je hem zien."""
    material = client.post("/api/library/materials", json={"name": "Acryl"}).json()
    client.post("/api/library/testgrids/recipes", json={"name": "Snel", "settings": BASE})

    recepten = client.get(
        f"/api/library/testgrids/recipes?material_id={material['id']}"
    ).json()

    assert [r["name"] for r in recepten] == ["Snel"]
    assert recepten[0]["material_id"] is None


def test_a_recipe_for_another_material_stays_out_of_the_way(client):
    berk = client.post("/api/library/materials", json={"name": "Berken"}).json()
    acryl = client.post("/api/library/materials", json={"name": "Acryl"}).json()
    client.post(
        "/api/library/testgrids/recipes",
        json={"name": "Berk snijden", "material_id": berk["id"], "settings": BASE},
    )

    assert client.get(
        f"/api/library/testgrids/recipes?material_id={acryl['id']}"
    ).json() == []


def test_a_nameless_recipe_is_refused(client):
    response = client.post(
        "/api/library/testgrids/recipes", json={"name": "  ", "settings": BASE}
    )

    assert response.status_code == 409


def test_rubbish_is_kept_out_of_a_recipe(client):
    """Een recept is een JSON-blob, en dat is waar rommel binnenkomt."""
    recept = client.post(
        "/api/library/testgrids/recipes",
        json={"name": "Snel", "settings": {**BASE, "drop table": "x", "cell_mm": "acht"}},
    ).json()

    assert "drop table" not in recept["settings"]
    assert "cell_mm" not in recept["settings"]


def test_a_recipe_can_be_thrown_away(client):
    recept = client.post(
        "/api/library/testgrids/recipes", json={"name": "Snel", "settings": BASE}
    ).json()

    assert client.delete(f"/api/library/testgrids/recipes/{recept['id']}").status_code == 200
    assert client.get("/api/library/testgrids/recipes").json() == []
    assert client.delete(f"/api/library/testgrids/recipes/{recept['id']}").status_code == 409


def test_a_recipe_reads_like_a_previous_grid(client):
    """
    Eén vorm voor beide: de wizard hoeft niet te weten of hij een vorig raster
    of een recept invult. Dat was de reden om T7 óp T3 te bouwen.
    """
    material = client.post("/api/library/materials", json={"name": "Berken"}).json()
    client.post(
        "/api/library/testgrids",
        json={**BASE, "material_id": material["id"]},
    )
    vorige = client.get(
        f"/api/library/testgrids/defaults?material_id={material['id']}"
    ).json()
    recept = client.post(
        "/api/library/testgrids/recipes",
        json={"name": "Zelfde", "material_id": material["id"], "settings": vorige},
    ).json()

    gedeeld = set(recept["settings"]) & set(vorige)
    assert "speed_min" in gedeeld and "cell_mm" in gedeeld
    for sleutel in gedeeld:
        assert recept["settings"][sleutel] == vorige[sleutel], sleutel
