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
    assert len(list(kernel.elements.elems())) == 9

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
    assert len(list(kernel.elements.elems())) == 9

    client.post("/api/design/undo")

    assert len(list(kernel.elements.elems())) < 9


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
