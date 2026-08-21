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
    # Nine squares, the axis labels, plus the caption lines on the board.
    plan = client.post("/api/library/testgrids/preview", json=BASE).json()["plan"]
    assert len(drawn) == 9 + BASE["speed_steps"] + BASE["power_steps"] + len(
        plan["caption_lines"]
    )

    snapshot = DesignReader(kernel).snapshot()
    labels = {op["label"] for op in snapshot["operations"]}
    # The layer label names the two quantities on the axes, with their unit: since B12 that
    # need not be speed and power.
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
    # One per row, one per column, plus the caption lines on the board.
    plan = client.post("/api/library/testgrids/preview", json=BASE).json()["plan"]
    assert len(labels[0]["element_ids"]) == BASE["speed_steps"] + BASE[
        "power_steps"
    ] + len(plan["caption_lines"])


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
        assert x0 >= 0, f"{element['label']} sticks out to the left of the bed"
        assert y0 >= 0, f"{element['label']} sticks out above the bed"


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
    assert "material" in str(response.json()["detail"])


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
        assert "test grid" in str(response.json()["detail"])


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
    Grid-to-operation left live in the database and outlive a restart, while
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
    Removing a grid from sheet 1 while you are on sheet 2 erased the work there.

    Ids are handed out per document, so `meerk40t:3` on sheet 2 is a different thing from
    `meerk40t:3` on sheet 1 — and the removal looked them up purely by id. Measured: thirteen
    layers of *another* grid disappeared without a word.
    """
    grid = client.post("/api/library/testgrids", json=BASE).json()
    borrowed_op = grid["cells"][0]["operation_id"]
    geleend_elem = grid["cells"][0]["element_id"]
    groep = grid["group_id"]

    client.post("/api/sheets", json={"name": "Tweede"})
    client.post("/api/sheets/sheet-2/activate")
    layer = client.post(
        "/api/design/operations", json={"type": "cut", "speed": 99, "power_percent": 33}
    ).json()["id"]
    rect = client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 100, "y_mm": 100, "width_mm": 30, "height_mm": 30},
    ).json()["ids"][0]
    client.post("/api/design/assign", json={"ids": [rect], "operation_id": layer})
    # Exactly the collision that arises by itself in reality: the same ids.
    kernel.elements.find_node(layer).id = borrowed_op
    kernel.elements.find_node(rect).id = geleend_elem
    if groep:
        for node in kernel.elements.elems():
            node.id = groep
            break

    client.post(f"/api/library/testgrids/{grid['id']}/remove-from-design")

    remaining = client.get("/api/design").json()
    assert len(remaining["elements"]) == 1, "the work on this sheet has disappeared"
    assert any(o["id"] == borrowed_op for o in remaining["operations"])


def test_the_series_lands_on_values_a_person_would_type():
    """
    A grid that cuts rows at 11.667 mm/s is not a reference work. The start and the end stay
    exact; only the intermediate steps move to a tidy number.
    """
    from openkerf_api.testgrid import _spread

    reeks = _spread(5, 25, 4)

    assert reeks[0] == 5 and reeks[-1] == 25
    assert reeks == [5.0, 12.5, 17.5, 25.0]
    assert all(round(v * 10) == v * 10 for v in reeks), reeks


def test_a_narrow_range_keeps_its_steps_apart():
    """
    Rounding must never produce two identical rows: then you burn the same thing twice and
    have wasted a column.
    """
    from openkerf_api.testgrid import _spread

    for lo, hi, stappen in ((10, 12, 4), (0.5, 2, 4), (100, 101, 5), (5, 25, 6)):
        reeks = _spread(lo, hi, stappen)
        assert len(set(reeks)) == stappen, (lo, hi, stappen, reeks)
        assert all(reeks[i] < reeks[i + 1] for i in range(len(reeks) - 1)), reeks
        assert reeks[0] == lo and reeks[-1] == hi


def test_the_board_carries_a_caption(kernel, client):
    """
    Een gebrand raster zonder caption is over twee weken een raadselachtig
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
    boxes = [
        [v / perMm for v in e["bounds"]]
        for e in snapshot["elements"]
        if e["id"] in labels["element_ids"] and e["bounds"]
    ]

    # The text has been converted to geometry, so the letters cannot be read back. What does
    # hold: the caption is *above* the column labels and is wider than one square — no axis
    # label is.
    above = [d for d in boxes if d[3] < BASE["origin_y_mm"] - 4]
    assert above, boxes
    assert max(d[2] - d[0] for d in above) > BASE["cell_mm"] * 2, above
    # And the lines lie under each other, not on top of each other.
    by_height = sorted(above, key=lambda d: d[1])
    for hoger, lager in zip(by_height, by_height[1:]):
        assert hoger[3] <= lager[1] + 0.01, by_height


# ------------------------------- het caption blijft binnen het bord (punt 3)


def test_the_caption_never_makes_the_board_wider_than_its_grid():
    """
    The caption was on one line and the board got room added on the right until that line
    fitted: a grid of 38 mm became a board of 134 mm. That is no longer a board but a banner.
    The board is now never wider than its squares plus the row labels on the left.
    """
    plan, _ = plan_grid(
        **{**BASE, "cell_mm": 8, "speed_steps": 4, "power_steps": 4},
        material_name="Acrylaat (geëxtrudeerd)",
        thickness_mm=3,
        caption="3MM Acryl Graveren",
        stamp="2026-08-13",
    )

    # Everything to the right of the squares is zero: the width is the label margin plus the
    # squares and nothing else.
    assert plan["outer_width_mm"] == pytest.approx(
        plan["label_margin_mm"] + plan["width_mm"]
    )
    assert plan["outer_width_mm"] < plan["width_mm"] * 1.5


def test_the_caption_does_not_repeat_what_the_user_already_wrote():
    """
    "3MM Acryl Engrave · Acrylic (extruded) · 3 mm · engrave-raster" is the same sentence
    three times. What the user named themselves the board does not repeat — what they did
    *not* name (raster against vector) it does.
    """
    from openkerf_api.testgrid import caption_lines

    regels = caption_lines(
        {
            "caption": "3MM Acryl Graveren",
            "material_name": "Acrylaat (geëxtrudeerd)",
            "thickness_mm": 3,
            "operation": "graveren-raster",
            "row_axis": "speed",
            "column_axis": "power",
            "stamp": "2026-08-13",
        }
    )
    text = " ".join(regels).lower()

    assert regels[0] == "3MM Acryl Graveren"
    assert "acrylaat" not in text
    assert "3 mm" not in text
    assert text.count("graveren") == 1
    assert "raster" in text  # the part they did *not* say stays
    assert "graveren-raster" not in text  # no database key on the wood


def test_the_caption_still_names_everything_when_the_user_says_nothing():
    """Zonder eigen caption draagt het bord materiaal, dikte en bewerking."""
    from openkerf_api.testgrid import caption_lines

    text = " ".join(
        caption_lines(
            {
                "material_name": "Berkentriplex",
                "thickness_mm": 3,
                "operation": "snijden",
                "row_axis": "speed",
                "column_axis": "power",
                "stamp": "2026-08-13",
            }
        )
    )

    assert "Berkentriplex" in text
    assert "3 mm" in text
    assert "cut" in text
    assert "2026-08-13" in text


def test_the_fixed_quantity_reaches_the_caption():
    """
    The quantity that is *not* on an axis belongs on the board: without it, in two weeks it
    cannot be converted back into a setting. The branch already existed, but `plan_grid` never
    passed the keys along — so it never fired.
    """
    plan, _ = plan_grid(**{**BASE, "operation": "graveren-raster", "interval_mm": 0.1})

    assert "interval" in plan["caption_text"]
    assert "0.1" in plan["caption_text"]


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
    B12: when engraving, the line spacing decides the result at least as much as the power.
    What is *not* on an axis is fixed for the whole board.
    """
    plan, cells = plan_grid(**RASTER)

    assert plan["rows"] == 3 and plan["columns"] == 3
    assert sorted({c["interval_mm"] for c in cells}) == [0.05, 0.15, 0.3]
    assert {c["speed_mm_s"] for c in cells} == {200}
    # The fixed quantity is one point in the series: min == max, one step.
    assert (plan["speed_min"], plan["speed_max"], plan["speed_steps"]) == (200, 200, 1)


def test_the_interval_varies_down_the_rows_it_was_put_on():
    _, cells = plan_grid(**RASTER)
    kolom = [c for c in cells if c["column"] == 0]

    assert [c["interval_mm"] for c in kolom] == [0.05, 0.15, 0.3]
    assert len({c["power_percent"] for c in kolom}) == 1


def test_interval_is_refused_where_it_means_nothing():
    """When cutting the head lays one line; a line-spacing axis would do nothing there."""
    with pytest.raises(DesignError) as error:
        plan_grid(**{**RASTER, "operation": "snijden"})

    assert "rastering" in str(error.value)


def test_two_axes_cannot_be_the_same_quantity():
    with pytest.raises(DesignError):
        plan_grid(**{**BASE, "row_axis": "power", "column_axis": "power"})


def test_swapping_the_axes_swaps_the_board():
    """Speed to the right instead of downwards, and nothing else."""
    _, cells = plan_grid(**{**BASE, "row_axis": "power", "column_axis": "speed"})
    rij = [c for c in cells if c["row"] == 0]

    assert [c["speed_mm_s"] for c in rij] == [5, 15, 25]
    assert len({c["power_percent"] for c in rij}) == 1


def test_an_interval_grid_sets_the_dpi_on_each_operation(kernel, client):
    """
    The engine does not know interval but dpi. Without this conversion every square would
    burn at the same line spacing and you would be testing nothing.
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
    Without the line spacing the preset cannot be burned again: the same speed and the same
    power at a different interval give a different result.
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
    T4: you align on the desktop and point out the square on the tablet beside the machine.
    In localStorage that second half was an empty grid over a skewed photo.
    """
    grid = client.post("/api/library/testgrids", json=BASE).json()
    corners = [
        {"x": 0.12, "y": 0.08},
        {"x": 0.91, "y": 0.14},
        {"x": 0.88, "y": 0.93},
        {"x": 0.09, "y": 0.87},
    ]

    response = client.put(
        f"/api/library/testgrids/{grid['id']}/alignment", json={"corners": corners}
    )

    assert response.status_code == 200
    assert response.json()["alignment"] == corners
    # And it comes back on fetching, not only in the answer.
    assert client.get(f"/api/library/testgrids/{grid['id']}").json()["alignment"] == corners


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


# ------------------------------ pointing out the square on the photo (gap M4)

def _foto(kleur=(120, 90, 60), maat=(200, 160)):
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", maat, kleur).save(buffer, format="JPEG")
    return buffer.getvalue()


def test_the_photo_can_come_back_with_the_chosen_cell_marked(client):
    """
    M4: the provenance said "row 2, column 3" and nothing was marked on the photo. With
    ?cell= the server draws the same overlay into the image itself, so that the marker comes
    along in every <img> that shows the photo.
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
    The same cell, two alignments: the marker should move along. Otherwise it points at a
    place where nothing was burned.
    """
    from PIL import Image
    from io import BytesIO

    grid = client.post("/api/library/testgrids", json=BASE).json()
    client.post(
        f"/api/library/testgrids/{grid['id']}/photo",
        files={"file": ("bord.jpg", _foto(), "image/jpeg")},
    )

    first = client.get(f"/api/library/testgrids/{grid['id']}/photo?cell=0-0").content
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
    after = client.get(f"/api/library/testgrids/{grid['id']}/photo?cell=0-0").content

    assert first != after
    # And it stays a readable photo of the same size.
    assert Image.open(BytesIO(after)).size == Image.open(BytesIO(first)).size


def test_marking_a_cell_that_is_not_there_is_a_clean_error(client):
    grid = client.post("/api/library/testgrids", json=BASE).json()
    client.post(
        f"/api/library/testgrids/{grid['id']}/photo",
        files={"file": ("bord.jpg", _foto(), "image/jpeg")},
    )

    assert client.get(f"/api/library/testgrids/{grid['id']}/photo?cell=9-9").status_code == 409
    assert client.get(f"/api/library/testgrids/{grid['id']}/photo?cell=kwart").status_code == 422


# ------------------------------------------ previous instelling onthouden (T3)

def test_the_next_grid_starts_where_the_last_one_for_this_material_left_off(client):
    """
    T3: anybody testing 3 mm birch weekly sets up the same thing every week. The previous
    grid *is* that setting; no separate preferences table is needed for it.
    """
    berk = client.post("/api/library/materials", json={"name": "Berken"}).json()
    client.post(
        "/api/library/testgrids",
        json={**BASE, "material_id": berk["id"], "thickness_mm": 3, "speed_max": 40},
    )

    previous = client.get(f"/api/library/testgrids/defaults?material_id={berk['id']}").json()

    assert previous["speed_max"] == 40
    assert previous["thickness_mm"] == 3
    assert previous["operation"] == "snijden"
    assert previous["row_axis"] == "speed"


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
    """An interval grid's fixed speed should be there again next time."""
    berk = client.post("/api/library/materials", json={"name": "Berken"}).json()
    client.post("/api/library/testgrids", json={**RASTER, "material_id": berk["id"]})

    previous = client.get(f"/api/library/testgrids/defaults?material_id={berk['id']}").json()

    assert previous["row_axis"] == "interval"
    assert (previous["speed_min"], previous["speed_steps"]) == (200, 1)


# -------------------------------------------- room for the row labels


def test_the_plan_says_how_much_room_the_row_labels_need():
    """
    The row labels are engraved to the left of the grid. At Start X 10 mm and three-digit
    speeds they are off the bed: the machine does not burn them and the board is unreadable
    afterwards. The plan reports that before burning.
    """
    krap = plan_grid(**{**BASE, "speed_min": 100, "speed_max": 300, "origin_x_mm": 10})[0]

    assert krap["label_margin_mm"] > 10
    assert krap["label_room"] is False

    ruim = plan_grid(
        **{**BASE, "speed_min": 100, "speed_max": 300, "origin_x_mm": 40}
    )[0]

    assert ruim["label_room"] is True


# ------------------- can this engine raster at all? (measured, not hoped for)


def test_the_preview_says_whether_this_engine_can_burn_a_raster(client):
    """
    During planning `op raster` turns its shapes into a bitmap through
    `render-op/make_raster`. Upstream that service is registered **only by the wxPython GUI**
    (`meerk40t/gui/plugin.py:79`); without it `preprocess` takes the `strip_rasters` branch,
    the layer throws its children away and the board comes out of the machine blank.

    Since `openkerf_api/rasterizer.py` our plugin registers one itself. So this engine *can*
    raster, and the preview should say so. If this becomes `False` again, the rasteriser is
    not loaded and every raster layer burns nothing — then the block in TestGrid.svelte
    belongs back.
    """
    antwoord = client.post("/api/library/testgrids/preview", json=RASTER).json()

    assert antwoord["engine"]["raster"] is True


def test_a_raster_grid_produces_cutcode_on_a_headless_engine(kernel, client):
    """
    The measurement under the report above. Previously this same design gave 0 parts over
    0.0 s — nine raster layers that did nothing. With the rasteriser from
    `openkerf_api/rasterizer.py` it produces work that costs time.

    The counter-proof is below it: without the service it is zero again.
    """
    client.post("/api/library/testgrids", json=RASTER)
    # The label layer *does* burn (it is an engrave); measure only the sweep.
    for operation in kernel.elements.ops():
        if getattr(operation, "label", None) == "Raster-labels":
            operation.output = False

    exact = client.get("/api/job/estimate?exact=1").json()

    assert exact["parts"] >= 1
    assert exact["seconds"] > 0
    assert len([layer for layer in exact["layers"] if layer["type"] == "op raster"]) == 9


def test_without_a_rasteriser_the_same_grid_burns_nothing(kernel, client):
    """
    Why the rasteriser had to be built, in one measurement: take it away and the board is
    empty. This is the state MeerK40t runs in headless out of the box.
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
    """The counter-proof: cutting and vector engraving do burn, headless as well."""
    client.post("/api/library/testgrids", json=BASE)
    for operation in kernel.elements.ops():
        if getattr(operation, "label", None) == "Raster-labels":
            operation.output = False

    exact = client.get("/api/job/estimate?exact=1").json()

    # Here `parts` counts the cut plan's pieces, not the shapes; what counts is that there
    # is something to burn and that it costs time.
    assert exact["parts"] >= 1
    assert exact["seconds"] > 0


def test_the_plan_prices_the_board_in_seconds():
    """
    What it is going to cost, before anything has been drawn. Interval as an axis can
    silently multiply the burn time; then there should be a number that moves with it.
    """
    snijden = plan_grid(**BASE)[0]
    assert snijden["seconds"] > 0

    # Zelfde bord, halve snelheid: ruwweg dubbele brandtijd.
    langzamer = plan_grid(**{**BASE, "speed_min": 2.5, "speed_max": 12.5})[0]
    assert langzamer["seconds"] > snijden["seconds"] * 1.5

    # And a finer interval costs more lines, so more time.
    coarse = plan_grid(**{**RASTER, "interval_min": 0.3, "interval_max": 0.4})[0]
    fine = plan_grid(**{**RASTER, "interval_min": 0.05, "interval_max": 0.06})[0]
    assert fine["seconds"] > coarse["seconds"] * 4, (fine["seconds"], coarse["seconds"])


def test_a_preset_says_whether_its_photo_is_aligned(client):
    """
    Without an alignment the marker on the photo falls back on four default corners, and
    then the outline is approximate. The library has to be able to say so; otherwise the card
    suggests a precision that is not there.
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
    """A manual preset has no grid, so no alignment either."""
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


# ------------------------ from the corner or from the centre (gap T9)


def test_the_corner_is_still_the_default():
    """What was there stays: Start X/Y is the corner of the squares."""
    plan, cells = plan_grid(**BASE)

    assert plan["anchor"] == "corner"
    assert (plan["origin_x_mm"], plan["origin_y_mm"]) == (10, 10)
    assert (cells[0]["x_mm"], cells[0]["y_mm"]) == (10, 10)


def test_centring_puts_the_middle_of_the_board_on_the_point():
    """
    You put a test board on an offcut, and then you know where the *centre* of that piece
    is. The centre refers to the whole board: centring the grid while the row labels stick out
    to the left of it lays the board askew.
    """
    plan, _ = plan_grid(**{**BASE, "anchor": "center", "origin_x_mm": 200, "origin_y_mm": 150})

    assert plan["center_x_mm"] == pytest.approx(200)
    assert plan["center_y_mm"] == pytest.approx(150)
    assert plan["outer_x_mm"] == pytest.approx(200 - plan["outer_width_mm"] / 2)
    assert plan["outer_y_mm"] == pytest.approx(150 - plan["outer_height_mm"] / 2)
    # The squares have moved, not the caption around them.
    assert plan["origin_x_mm"] > plan["outer_x_mm"]
    assert plan["width_mm"] == 28


def test_a_centred_board_is_wider_than_its_cells():
    """De gemelde maat is inclusief labels en caption — precies wat T11 miste."""
    plan, _ = plan_grid(**BASE)

    assert plan["outer_width_mm"] > plan["width_mm"]
    assert plan["outer_height_mm"] > plan["height_mm"]


def test_an_unknown_anchor_is_refused():
    with pytest.raises(DesignError):
        plan_grid(**{**BASE, "anchor": "ergens"})


def test_the_reported_size_covers_everything_that_is_drawn(kernel, client):
    """
    Measured rather than computed: the reported frame has to contain every shape that really
    gets burned, caption and border frame included. This is the test that catches a shifted
    estimate.
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


def test_a_wrapped_caption_stays_inside_the_reported_board(kernel, client):
    """
    The same as above, but for the case point 3 introduced: a caption breaking over several
    lines, *with* a border frame around it. If the height reservation does not grow with the
    number of lines, the top line sticks through the frame.
    """
    material = client.post("/api/library/materials", json={"name": "Acrylaat"}).json()
    vraag = {
        **BASE,
        "cell_mm": 4,
        "origin_x_mm": 60,
        "origin_y_mm": 60,
        "border": True,
        "material_id": material["id"],
        "thickness_mm": 3,
        "caption": "proef achterkant tweede poging",
    }
    plan = client.post("/api/library/testgrids/preview", json=vraag).json()["plan"]
    client.post("/api/library/testgrids", json=vraag)

    assert len(plan["caption_lines"]) >= 2, plan["caption_lines"]
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
    As with T11: sticking out on the left costs you the captions, not the grid. So report it
    and do not block — the board itself simply burns.
    """
    plan, _ = plan_grid(**{**BASE, "origin_x_mm": 2})

    assert plan["board_room"] is False
    assert plan["label_room"] is False


# ------------------- the typeface on the board is fixed (grid bug 1)


def _label_fonts(kernel) -> set[str]:
    """The typefaces of everything on the board that is text."""
    return {
        element["text"]["font"]
        for element in DesignReader(kernel).snapshot()["elements"]
        if element.get("text")
    }


def test_the_board_uses_its_own_font_whatever_the_user_last_picked(kernel, client):
    """
    Jelle's finding: choose a typeface in the text dialog, then make a test grid, and the
    captions are in *that* typeface.

    The cause is in the engine: without `-f`, `linetext` falls back on
    `context.last_font`, a setting every text placement overwrites. A board is a piece of
    evidence — what is on it must not depend on what you happened to choose an hour
    earlier.
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
    assert "Apple Chancery.ttf" in fonts, "the user's own text"
    assert fonts - {"Apple Chancery.ttf"} == {LABEL_FONTS[0]}


def test_the_board_leaves_the_users_font_choice_alone(kernel, client):
    """
    Our choice must not become a preference.

    `create_linetext_node` sets `last_font` to what it has just used, so without restoring it
    the user's next piece of text would appear in *our* label typeface — the same fault, the
    other way round.
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


# ------------------------------- text en rand zijn te kiezen (gat T10)


def test_text_can_be_switched_off(kernel, client):
    """For a quick trial on an offcut the caption is a waste."""
    client.post("/api/library/testgrids", json={**BASE, "text": False})

    snapshot = DesignReader(kernel).snapshot()
    assert [op for op in snapshot["operations"] if op["label"] == "Raster-labels"] == []
    assert len(snapshot["elements"]) == 9  # only the squares


def test_text_is_on_by_default(kernel, client):
    """The board is a piece of evidence; the caption belongs on it by default."""
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
    A frame straight through the row labels makes the board unreadable, so it lies around
    everything — and it burns in the label layer, not in the sweep.
    """
    grid = client.post(
        "/api/library/testgrids", json={**BASE, "origin_x_mm": 40, "border": True}
    ).json()

    snapshot = DesignReader(kernel).snapshot()
    per_mm = snapshot["units_per_mm"]
    labels = [op for op in snapshot["operations"] if op["label"] == "Raster-labels"][0]
    boxes = [
        [v / per_mm for v in e["bounds"]]
        for e in snapshot["elements"]
        if e["id"] in labels["element_ids"] and e["bounds"]
    ]
    frame = max(boxes, key=lambda d: (d[2] - d[0]) * (d[3] - d[1]))
    # Every other shape lies inside it — the squares as well.
    for cell in grid["cells"]:
        element = next(e for e in snapshot["elements"] if e["id"] == cell["element_id"])
        x0, y0, x1, y1 = (v / per_mm for v in element["bounds"])
        assert frame[0] <= x0 and frame[1] <= y0
        assert x1 <= frame[2] and y1 <= frame[3]


def test_there_is_no_border_unless_you_ask(kernel, client):
    """Switching new work on for everybody who asked for nothing silently changes their board."""
    client.post("/api/library/testgrids", json=BASE)

    snapshot = DesignReader(kernel).snapshot()
    plan = client.post("/api/library/testgrids/preview", json=BASE).json()["plan"]
    # Nine squares, three row labels, three column labels, the caption — and no frame,
    # because nobody asks for that.
    assert len(snapshot["elements"]) == 15 + len(plan["caption_lines"])


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
    Without this T3 forgets how you laid the board out: next time it was from the corner
    again, with a caption you had just switched off.
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

    previous = client.get(
        f"/api/library/testgrids/defaults?material_id={material['id']}"
    ).json()

    assert previous["anchor"] == "center"
    assert previous["text_enabled"] is False
    assert previous["border_enabled"] is True
    # And the point you typed comes back, not the corner computed from it.
    assert previous["anchor_x_mm"] == pytest.approx(200)
    assert previous["anchor_y_mm"] == pytest.approx(150)


# --------------------------------- benoemde generatorpresets (gat T7)


def test_a_recipe_keeps_its_settings_under_a_name(client):
    material = client.post("/api/library/materials", json={"name": "Berken"}).json()

    recipe = client.post(
        "/api/library/testgrids/recipes",
        json={
            "name": "Berk snijden",
            "material_id": material["id"],
            "settings": {**BASE, "speed_mm_s": 12},
        },
    ).json()

    assert recipe["name"] == "Berk snijden"
    assert recipe["settings"]["operation"] == "snijden"
    assert recipe["settings"]["speed_min"] == 5
    assert recipe["material_name"] == "Berken"


def test_two_recipes_for_one_material_live_side_by_side(client):
    """
    Precisely what T3 could not do: "cut birch" beside "engrave birch". Remembering one
    setting per material covers the weekly trial, not the two recipes you alternate between.
    """
    material = client.post("/api/library/materials", json={"name": "Berken"}).json()
    for naam, bewerking in (("Cut", "snijden"), ("Engrave", "graveren-vector")):
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

    assert [r["name"] for r in recepten] == ["Cut", "Engrave"]  # alphabetical
    assert {r["settings"]["operation"] for r in recepten} == {
        "snijden",
        "graveren-vector",
    }


def test_saving_the_same_name_twice_updates_it(client):
    """Otherwise there are two rows you cannot choose between."""
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
    """"Quick 4×4" belongs to no board; it is precisely with something new that you want to see it."""
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
    """A recipe is a JSON blob, and that is where rubbish gets in."""
    recipe = client.post(
        "/api/library/testgrids/recipes",
        json={"name": "Snel", "settings": {**BASE, "drop table": "x", "cell_mm": "acht"}},
    ).json()

    assert "drop table" not in recipe["settings"]
    assert "cell_mm" not in recipe["settings"]


def test_a_recipe_can_be_thrown_away(client):
    recipe = client.post(
        "/api/library/testgrids/recipes", json={"name": "Snel", "settings": BASE}
    ).json()

    assert client.delete(f"/api/library/testgrids/recipes/{recipe['id']}").status_code == 200
    assert client.get("/api/library/testgrids/recipes").json() == []
    assert client.delete(f"/api/library/testgrids/recipes/{recipe['id']}").status_code == 409


def test_a_recipe_reads_like_a_previous_grid(client):
    """
    One shape for both: the wizard does not have to know whether it is filling in a previous
    grid or a recipe. That was the reason to build T7 *on* T3.
    """
    material = client.post("/api/library/materials", json={"name": "Berken"}).json()
    client.post(
        "/api/library/testgrids",
        json={**BASE, "material_id": material["id"]},
    )
    previous = client.get(
        f"/api/library/testgrids/defaults?material_id={material['id']}"
    ).json()
    recipe = client.post(
        "/api/library/testgrids/recipes",
        json={"name": "Zelfde", "material_id": material["id"], "settings": previous},
    ).json()

    gedeeld = set(recipe["settings"]) & set(previous)
    assert "speed_min" in gedeeld and "cell_mm" in gedeeld
    for sleutel in gedeeld:
        assert recipe["settings"][sleutel] == previous[sleutel], sleutel


# --------------------------- a board is one thing, beside another one as well
#
# Three findings from our own use, one cause: a board had no identity of its own. Who
# belonged to it was derived from document-wide things — "which paths hang off the label
# layer" — and that label layer is shared by *all* the boards.


def _cel_rooster(design, cellen):
    """
    Row and column as they lie on the bed, derived from the positions.

    Not from the bookkeeping: the question is precisely whether square (3,5) still lies in
    (3,5)'s place after an action. A board is a measuring instrument; as soon as the squares
    are rearranged relative to each other, the photo means nothing.
    """
    plek = {
        e["id"]: (e["bounds"][0], e["bounds"][1])
        for e in design["elements"]
        if e["bounds"]
    }
    xs = sorted({round(plek[c][0], 1) for c in cellen})
    ys = sorted({round(plek[c][1], 1) for c in cellen})
    return {
        cellen[c]: (xs.index(round(plek[c][0], 1)), ys.index(round(plek[c][1], 1)))
        for c in cellen
    }


def test_a_second_board_leaves_the_first_boards_labels_alone(client):
    """
    De captions van bord 1 blijven van bord 1.

    They were looked up through the shared label layer, so board 2 pulled them into its own
    group. After that one axis label from board 1 selected the whole of board 2 — and it moved
    along when you dragged board 2.
    """
    eerste = client.post("/api/library/testgrids", json=BASE).json()
    tweede = client.post(
        "/api/library/testgrids", json={**BASE, "origin_x_mm": 120}
    ).json()

    assert eerste["group_id"] and tweede["group_id"]
    assert eerste["group_id"] != tweede["group_id"]

    design = client.get("/api/design").json()
    per_group = {}
    for element in design["elements"]:
        per_group.setdefault(element["group_id"], []).append(element)

    # Elk bord telt evenveel elementen: negen vakjes plus de captions.
    left = per_group[eerste["group_id"]]
    right = per_group[tweede["group_id"]]
    assert len(left) == len(right)
    # And they really do lie apart: no element of board 1 is in board 2's group. Board 1
    # starts at x=10, board 2 at x=120.
    boundary = 100 * design["units_per_mm"]
    assert all(e["bounds"][0] < boundary for e in left)
    assert all(e["bounds"][2] > boundary for e in right)
    # Nothing wanders outside a board: every element belongs somewhere.
    assert None not in per_group


def test_bringing_everything_back_onto_the_bed_keeps_the_cells_in_place(client):
    """
    "Put everything back on the bed" may move a board, not pull it apart.

    It nested *every* shape separately, so you got neat rows of squares of which not one lay
    in its own row and column any more. The trial is then gone: the square that turns out best
    on the photo no longer belongs to the setting beside it.
    """
    grid = client.post("/api/library/testgrids", json=BASE).json()
    client.post("/api/library/testgrids", json={**BASE, "origin_x_mm": 120})
    cellen = {c["element_id"]: (c["row"], c["column"]) for c in grid["cells"]}

    voor = _cel_rooster(client.get("/api/design").json(), cellen)
    design = client.get("/api/design").json()
    antwoord = client.post(
        "/api/design/nest",
        json={
            "ids": [e["id"] for e in design["elements"] if not e["hidden"]],
            "margin_mm": 5,
        },
    )
    assert antwoord.status_code == 200
    na = _cel_rooster(client.get("/api/design").json(), cellen)

    assert na == voor
    # And specifically the square Jelle pointed at: row 2, column 1 (zero-counted).
    assert na[(2, 1)] == voor[(2, 1)]


def test_the_group_carries_the_boards_name(kernel, client):
    """A group called "Test grid" reads as one thing in the panel and the bar."""
    grid = client.post("/api/library/testgrids", json=BASE).json()

    group = kernel.elements.find_node(grid["group_id"])
    assert group.label == "Testraster"


def test_the_label_layer_never_catches_fresh_work(client):
    """
    A board's label layer is not a layer of the user's.

    It carries the engine's default colour (#0000ff) and is therefore *not* in the palette
    strip under the canvas. If it was the only blue engrave layer — and it is as soon as
    somebody has thrown their own layers away — every fresh shape fell into it: invisible in
    the strip, and burned on a caption's setting instead of on the shape's.
    """
    client.post("/api/library/testgrids", json=BASE)
    client.delete("/api/design/operations")

    gemaakt = client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 5, "y_mm": 200, "width_mm": 10, "height_mm": 10},
    ).json()["ids"][0]

    design = client.get("/api/design").json()
    shape = next(e for e in design["elements"] if e["id"] == gemaakt)
    layers = [o for o in design["operations"] if o["id"] in shape["operation_ids"]]

    assert layers, "a fresh shape should land in a layer"
    assert all(o["label"] != "Raster-labels" for o in layers)
    assert all(not o.get("grid") for o in layers)


def test_clearing_all_layers_leaves_the_board_intact(client):
    """
    "All layers gone" should leave a board alone — its captions as well.

    The cells were already spared, the label layer was not. The caption and the border frame
    were then left behind without a layer: they were still on the canvas and no longer burned,
    on a board where nothing else looked wrong.
    """
    grid = client.post("/api/library/testgrids", json=BASE).json()
    voor = client.get("/api/design").json()
    captions = {
        e["id"]
        for e in voor["elements"]
        if e["operation_ids"]
        and all(
            o["label"] == "Raster-labels"
            for o in voor["operations"]
            if o["id"] in e["operation_ids"]
        )
    }
    assert captions, "a board with text should have captions"

    client.delete("/api/design/operations")

    na = client.get("/api/design").json()
    labellaag = [o for o in na["operations"] if o["label"] == "Raster-labels"]
    assert len(labellaag) == 1
    assert set(labellaag[0]["element_ids"]) >= captions
    # And the cells are still there, as they already were.
    assert len([o for o in na["operations"] if o.get("grid")]) == len(grid["cells"])


def test_the_colour_for_new_work_is_one_you_can_point_at(client):
    """
    The active colour is in the strip under the canvas, or it does not exist.

    The engine starts at #0000ff, and that swatch does not exist. Because of that the bottom
    edge reported "layer 1 · Grid labels" as the layer of your next shape: the only layer
    carrying that colour was the test board's label layer.
    """
    client.post("/api/library/testgrids", json=BASE)

    palet = client.get("/api/design/palette").json()

    assert palet["default_color"] in [c["color"] for c in palet["colors"]]
    # And the label layer carries no palette colour, so it can never turn out to be "the
    # layer of that swatch" either.
    design = client.get("/api/design").json()
    labellaag = next(o for o in design["operations"] if o["label"] == "Raster-labels")
    assert labellaag["color"] not in [c["color"] for c in palet["colors"]]
