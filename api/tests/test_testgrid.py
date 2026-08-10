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
    assert len(drawn) == 9 + BASE["speed_steps"] + BASE["power_steps"]

    snapshot = DesignReader(kernel).snapshot()
    labels = {op["label"] for op in snapshot["operations"]}
    assert "5.0mm/s @40.0%" in labels
    assert "25.0mm/s @80.0%" in labels


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
    # One per row plus one per column.
    assert len(labels[0]["element_ids"]) == BASE["speed_steps"] + BASE["power_steps"]


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
