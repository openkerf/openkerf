"""
Sheets: several pieces of material in one project.

Every sheet is a document of its own. So the heart of these tests is: does the
content of a sheet stay put when you switch away and come back, and does anything
from one sheet ever end up on another.
"""

import pytest
from fastapi.testclient import TestClient

from openkerf_api.server import ApiServer


@pytest.fixture
def client(kernel, tmp_path):
    with TestClient(ApiServer(kernel, library_path=tmp_path / "v.db").build_app()) as c:
        yield c


def a_rect(client, x=10, y=10, w=20, h=10):
    return client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": x, "y_mm": y, "width_mm": w, "height_mm": h},
    ).json()["ids"][0]


def count(client):
    return len(client.get("/api/design").json()["elements"])


def test_a_project_always_has_one_sheet(client):
    """A project without a sheet does not exist, no more than a laser without a bed."""
    state = client.get("/api/sheets").json()

    assert len(state["sheets"]) == 1
    assert state["sheets"][0]["active"] is True
    assert state["sheets"][0]["width_mm"] > 0


def test_a_new_sheet_takes_the_bed_size_by_default(client):
    bed = client.get("/api/devices").json()[0]["bed"]

    added = client.post("/api/sheets", json={}).json()

    assert len(added["sheets"]) == 2
    assert added["sheets"][1]["width_mm"] == pytest.approx(bed["width_mm"], abs=0.2)


def test_a_sheet_can_be_smaller_than_the_bed(client):
    """A sheet is a piece of material, not a copy of the bed."""
    added = client.post(
        "/api/sheets", json={"name": "Acrylic offcut", "width_mm": 120, "height_mm": 80}
    ).json()

    assert added["sheets"][1]["name"] == "Acrylic offcut"
    assert added["sheets"][1]["width_mm"] == 120


def test_switching_sheets_keeps_each_ones_content(client):
    """
    This is what it is all about: every sheet is a document of its own, so what
    you draw on one should not be on the other — and has to still be there when
    you come back.
    """
    a_rect(client, x=10)
    a_rect(client, x=50)
    assert count(client) == 2

    second = client.post("/api/sheets", json={"name": "Second"}).json()["sheets"][1]
    client.post(f"/api/sheets/{second['id']}/activate")

    assert count(client) == 0, "the second sheet starts empty"
    a_rect(client, x=30)
    assert count(client) == 1

    client.post("/api/sheets/sheet-1/activate")
    assert count(client) == 2, "the first sheet lost its content"

    client.post(f"/api/sheets/{second['id']}/activate")
    assert count(client) == 1


def test_the_selection_can_move_to_another_sheet(client):
    keep = a_rect(client, x=10)
    goes = a_rect(client, x=60)
    second = client.post("/api/sheets", json={}).json()["sheets"][1]

    response = client.post(f"/api/sheets/{second['id']}/move", json={"ids": [goes]})

    assert response.status_code == 200
    # We are on the second sheet now, with only the element that moved.
    assert response.json()["active"] == second["id"]
    assert count(client) == 1

    client.post("/api/sheets/sheet-1/activate")
    elements = client.get("/api/design").json()["elements"]
    assert len(elements) == 1
    assert elements[0]["id"] == keep


def test_moving_to_the_sheet_you_are_on_is_refused(client):
    rect = a_rect(client)

    response = client.post("/api/sheets/sheet-1/move", json={"ids": [rect]})

    assert response.status_code == 409


def test_moving_nothing_is_refused(client):
    client.post("/api/sheets", json={})

    assert client.post("/api/sheets/sheet-2/move", json={"ids": []}).status_code == 409


def test_a_sheet_can_be_renamed_and_resized(client):
    client.patch("/api/sheets/sheet-1", json={"name": "Birch 3mm", "width_mm": 300})

    sheet = client.get("/api/sheets").json()["sheets"][0]
    assert sheet["name"] == "Birch 3mm"
    assert sheet["width_mm"] == 300


def test_a_sheet_carries_one_material(client):
    """That is what makes the presets and the time estimate right per sheet."""
    material = client.post("/api/library/materials", json={"name": "Birch"}).json()

    client.patch("/api/sheets/sheet-1", json={"material_id": material["id"]})

    assert client.get("/api/sheets").json()["sheets"][0]["material_id"] == material["id"]


def test_deleting_a_sheet_removes_its_content_too(client):
    second = client.post("/api/sheets", json={}).json()["sheets"][1]
    client.post(f"/api/sheets/{second['id']}/activate")
    a_rect(client)

    client.delete(f"/api/sheets/{second['id']}")

    state = client.get("/api/sheets").json()
    assert [s["id"] for s in state["sheets"]] == ["sheet-1"]
    # And we are no longer on the sheet that is gone.
    assert state["active"] == "sheet-1"
    assert count(client) == 0


def test_the_last_sheet_cannot_be_deleted(client):
    assert client.delete("/api/sheets/sheet-1").status_code == 409


def test_an_absurd_sheet_size_is_refused(client):
    for size in ({"width_mm": 1}, {"height_mm": 9000}, {"width_mm": -50}):
        assert client.post("/api/sheets", json=size).status_code == 409


def test_sheets_survive_a_project_file(client, tmp_path):
    """
    Otherwise the project file is half a truth: you get one sheet back and the
    rest of your work is gone.
    """
    a_rect(client, x=10)
    second = client.post(
        "/api/sheets", json={"name": "Acrylic", "width_mm": 120, "height_mm": 80}
    ).json()["sheets"][1]
    client.post(f"/api/sheets/{second['id']}/activate")
    a_rect(client, x=30)
    a_rect(client, x=70)

    saved = client.get("/api/project/export.openkerf")
    assert saved.status_code == 200
    bundle = tmp_path / "project.openkerf"
    bundle.write_bytes(saved.content)

    # Throw everything away and open the project again.
    client.delete(f"/api/sheets/{second['id']}")
    client.post("/api/design/clear")

    with bundle.open("rb") as handle:
        opened = client.post(
            "/api/project/open", files={"file": ("project.openkerf", handle)}
        )
    assert opened.status_code == 200

    state = client.get("/api/sheets").json()
    assert [s["name"] for s in state["sheets"]] == ["Sheet 1", "Acrylic"]
    assert state["sheets"][1]["width_mm"] == 120

    client.post("/api/sheets/sheet-1/activate")
    assert count(client) == 1
    client.post(f"/api/sheets/{second['id']}/activate")
    assert count(client) == 2


def test_sheet_names_stay_unique(client):
    """
    Two boxes one after another used to give two sheets both called "Box 2", and
    then you cannot tell which is which.
    """
    client.post("/api/sheets", json={"name": "Box 2"})
    client.post("/api/sheets", json={"name": "Box 2"})

    names = [s["name"] for s in client.get("/api/sheets").json()["sheets"]]

    assert names == ["Sheet 1", "Box 2", "Box 2 (2)"]


# ------------------------------------------------------------- job name (P4)


def _job_labels(kernel):
    return [str(getattr(job, "label", "")) for job in kernel.device.spooler.queue]


def _burnable_rect(client, x=10):
    """A rectangle in a layer of its own: enough to be allowed to start a job."""
    rect = a_rect(client, x=x)
    layer = client.post(
        "/api/design/operations", json={"type": "cut", "label": "Cut"}
    ).json()["id"]
    client.post("/api/design/assign", json={"ids": [rect], "operation_id": layer})
    return rect


def test_a_job_carries_the_sheet_name_after_switching_sheets(kernel, client):
    """
    Every job was once called `recovery.svg`. The same mistake lives one door
    along: switching sheets loads `sheet-1.svg` back, and that internal file name
    went into the queue as the job name. At the machine you then have jobs called
    `sheet-1.svg` while the user sees "Sheet 1" and "Trial piece" on their tabs.
    """
    _burnable_rect(client)
    second = client.post("/api/sheets", json={"name": "Trial piece"}).json()["sheets"][1]
    client.post(f"/api/sheets/{second['id']}/activate")
    _burnable_rect(client, x=30)

    assert client.post("/api/job/start").status_code == 200
    assert _job_labels(kernel)[-1] == "Trial piece"

    client.post("/api/spooler/clear")
    # Back to a sheet that does have a saved file: that is the path where the
    # file name overwrote the name of the sheet.
    client.post("/api/sheets/sheet-1/activate")
    assert client.post("/api/job/start").status_code == 200
    assert _job_labels(kernel)[-1] == "Sheet 1"


# ------------------------------------------------------------------- restart


def test_a_restart_comes_back_to_the_sheet_you_left(kernel, tmp_path):
    """
    After a restart the sheet bar said "Sheet 1" while the canvas was empty: the
    sheet had never been loaded. Anybody who then switched sheets once lost
    everything — switching away sees an empty tree and throws `sheet-1.svg` out.
    """
    library = tmp_path / "v.db"
    with TestClient(ApiServer(kernel, library_path=library).build_app()) as first:
        a_rect(first)
        first.post("/api/sheets", json={"name": "Tweede"})
        first.post("/api/sheets/sheet-2/activate")
        first.post("/api/sheets/sheet-1/activate")
        assert count(first) == 1

    # The restart: a fresh server, an empty element tree, the same directory on disk.
    kernel.elements.clear_all()
    with TestClient(ApiServer(kernel, library_path=library).build_app()) as second:
        # The sheet bar asks for this when the page opens.
        second.get("/api/sheets")
        assert count(second) == 1, "the active sheet should be back on the table"

        second.post("/api/sheets/sheet-2/activate")

    saved = tmp_path / "openkerf-sheets" / "sheet-1.svg"
    assert saved.is_file(), "switching after a restart threw the sheet away"


# ------------------------------------------------------------------ material

def test_a_sheet_carries_a_material_and_a_thickness(client):
    """
    Decision B1: material and thickness hang off the sheet.

    Without that nothing downstream knows what you are burning in — not the
    library, not the test grid, and certainly not the pre-flight.
    """
    material = client.post("/api/library/materials", json={"name": "Birch"}).json()

    state = client.patch(
        "/api/sheets/sheet-1", json={"material_id": material["id"], "thickness_mm": 3}
    ).json()

    sheet = state["sheets"][0]
    assert sheet["material_id"] == material["id"]
    assert sheet["thickness_mm"] == 3


def test_a_sheet_without_a_material_stays_empty(client):
    """An offcut of unknown thickness does not need a made-up number."""
    sheet = client.get("/api/sheets").json()["sheets"][0]

    assert sheet["material_id"] is None
    assert sheet["thickness_mm"] is None


def test_the_thickness_can_be_cleared_again(client):
    client.patch("/api/sheets/sheet-1", json={"thickness_mm": 3})

    state = client.patch("/api/sheets/sheet-1", json={"thickness_mm": None}).json()

    assert state["sheets"][0]["thickness_mm"] is None


def test_an_impossible_thickness_is_refused(client):
    assert client.patch("/api/sheets/sheet-1", json={"thickness_mm": -2}).status_code == 409
    assert client.patch("/api/sheets/sheet-1", json={"thickness_mm": 900}).status_code == 409


def test_each_sheet_keeps_its_own_material(client):
    """Thin and thick in one project: that is why this goes per sheet."""
    birch = client.post("/api/library/materials", json={"name": "Birch"}).json()
    acrylic = client.post("/api/library/materials", json={"name": "Acrylic"}).json()
    client.patch("/api/sheets/sheet-1", json={"material_id": birch["id"], "thickness_mm": 3})
    client.post("/api/sheets", json={"material_id": acrylic["id"], "thickness_mm": 5})

    sheets = client.get("/api/sheets").json()["sheets"]

    assert [s["material_id"] for s in sheets] == [birch["id"], acrylic["id"]]
    assert [s["thickness_mm"] for s in sheets] == [3, 5]


# --------------------------------------------------------------------- tiles


def test_a_sheet_starts_without_tiling(client):
    """Tiles are an exception, not the standard way of working."""
    sheet = client.get("/api/sheets").json()["sheets"][0]

    assert sheet["tiling"]["enabled"] is False


def test_an_overlap_too_small_for_a_mark_is_refused_at_the_setting(client):
    """
    Not refusing only at burning time: by then you are already standing there
    with a plate in the machine.
    """
    sheet = client.get("/api/sheets").json()["sheets"][0]

    answer = client.patch(
        f"/api/sheets/{sheet['id']}",
        json={"tiling": {"enabled": True, "overlap_mm": 6.0, "marker_size_mm": 8.0}},
    )

    assert answer.status_code == 409
    assert "marker" in answer.json()["detail"]


def test_tiling_settings_survive_a_reload(client):
    sheet = client.get("/api/sheets").json()["sheets"][0]
    client.patch(
        f"/api/sheets/{sheet['id']}",
        json={"tiling": {"enabled": True, "overlap_mm": 30.0}},
    )

    again = client.get("/api/sheets").json()["sheets"][0]

    assert again["tiling"]["enabled"] is True
    assert again["tiling"]["overlap_mm"] == 30.0
