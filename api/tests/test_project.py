"""The project file: design plus library context in one bundle."""

import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from openkerf_api.server import ApiServer


@pytest.fixture
def server(kernel, tmp_path):
    return ApiServer(kernel, library_path=tmp_path / "p.db")


@pytest.fixture
def client(server):
    with TestClient(server.build_app()) as c:
        yield c


def stocked(client):
    material = client.post("/api/library/materials", json={"name": "Multiplex"}).json()
    client.post(
        "/api/library/presets",
        json={
            "material_id": material["id"],
            "operation": "snijden",
            "speed_mm_s": 12,
            "power_percent": 65,
        },
    )
    client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 20, "y_mm": 15, "width_mm": 60, "height_mm": 40},
    )


def test_a_project_carries_design_and_library(client):
    """
    An SVG keeps the shapes but not which material they were for; that lives in
    the database. A project is the two together.
    """
    stocked(client)

    response = client.get("/api/project/export.openkerf")

    assert response.status_code == 200
    bundle = zipfile.ZipFile(io.BytesIO(response.content))
    # design.svg is the active sheet and stays separate, so that an older version
    # of OpenKerf can still open the project.
    assert {"design.svg", "library.json", "sheets.json"} <= set(bundle.namelist())
    assert bundle.read("design.svg").startswith(b"<svg")
    context = json.loads(bundle.read("library.json"))
    assert [m["name"] for m in context["materials"]] == ["Multiplex"]
    assert len(context["presets"]) == 1


def test_opening_a_project_restores_both(kernel, client, tmp_path):
    stocked(client)
    data = client.get("/api/project/export.openkerf").content
    client.post("/api/design/clear")
    client.delete("/api/library/materials/1")
    assert client.get("/api/library/materials").json() == []

    response = client.post(
        "/api/project/open", files={"file": ("p.openkerf", data, "application/zip")}
    )

    assert response.status_code == 200
    assert len(list(kernel.elements.elems())) == 1
    assert [m["name"] for m in client.get("/api/library/materials").json()] == ["Multiplex"]
    assert len(client.get("/api/library/presets").json()) == 1


def test_opening_replaces_the_design(kernel, client):
    stocked(client)
    data = client.get("/api/project/export.openkerf").content
    client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 90, "y_mm": 90, "width_mm": 10, "height_mm": 10},
    )
    assert len(list(kernel.elements.elems())) == 2

    client.post("/api/project/open", files={"file": ("p.openkerf", data, "application/zip")})

    assert len(list(kernel.elements.elems())) == 1


def test_opening_does_not_duplicate_what_is_already_there(client):
    """Opening someone's project must not multiply your own library."""
    stocked(client)
    data = client.get("/api/project/export.openkerf").content

    client.post("/api/project/open", files={"file": ("p.openkerf", data, "application/zip")})

    assert len(client.get("/api/library/materials").json()) == 1
    assert len(client.get("/api/library/presets").json()) == 1


def test_a_project_leaves_the_document_clean(client):
    stocked(client)
    data = client.get("/api/project/export.openkerf").content

    client.post("/api/project/open", files={"file": ("p.openkerf", data, "application/zip")})

    assert client.get("/api/design").json()["dirty"] is False


def test_something_that_is_not_a_project_is_refused(client):
    response = client.post(
        "/api/project/open", files={"file": ("x.openkerf", b"geen zip", "application/zip")}
    )
    assert response.status_code == 409


def test_a_zip_without_a_design_is_refused(client):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr("library.json", "{}")

    response = client.post(
        "/api/project/open",
        files={"file": ("x.openkerf", buffer.getvalue(), "application/zip")},
    )

    assert response.status_code == 409


# ------------------------------------------------------------- new project


def test_a_new_project_empties_the_bed(client, kernel):
    """Starting over did not exist: only saving and opening."""
    stocked(client)
    assert len(list(kernel.elements.elems())) == 1

    response = client.post("/api/project/new")

    assert response.status_code == 200
    assert list(kernel.elements.elems()) == []
    assert client.get("/api/design").json()["dirty"] is False


def test_a_new_project_keeps_the_library(client):
    """
    Materials and presets are what you know about your laser, not what is lying on
    the bed. They belong to the workshop and not to this project.
    """
    stocked(client)

    client.post("/api/project/new")

    assert [m["name"] for m in client.get("/api/library/materials").json()] == ["Multiplex"]
    assert len(client.get("/api/library/presets?all_machines=true").json()) == 1


def test_a_new_project_leaves_one_empty_sheet(client, kernel):
    client.post("/api/sheets", json={"name": "Box"})
    client.post("/api/design/elements",
                json={"type": "rect", "x_mm": 5, "y_mm": 5, "width_mm": 10, "height_mm": 10})

    state = client.post("/api/project/new").json()

    assert [s["name"] for s in state["sheets"]] == ["Sheet 1"]
    assert state["active"] == "sheet-1"
    assert list(kernel.elements.elems()) == []


def test_the_sheets_of_the_old_project_are_gone(server, client, kernel):
    """
    A sheet lives as a file beside the database and otherwise survives the new
    project: you start clean and find yesterday's box in the sheet bar.
    """
    client.post("/api/design/elements",
                json={"type": "rect", "x_mm": 5, "y_mm": 5, "width_mm": 10, "height_mm": 10})
    client.post("/api/sheets", json={"name": "Box"})
    client.post("/api/sheets/sheet-2/activate")  # writes sheet-1 out to disk
    assert list(server.sheets.directory.glob("*.svg"))

    client.post("/api/project/new")

    assert list(server.sheets.directory.glob("*.svg")) == []
    assert list(kernel.elements.elems()) == []


def test_a_new_project_does_not_inherit_yesterdays_provenance(server, client):
    """
    Sheet numbers are reused, so without this a note on "sheet-1" sticks to the
    first sheet of the next project — and then it says "from a test grid" under a
    setting nobody applied.
    """
    server.provenance.record(
        "sheet-1", "op-1", {"id": 1, "source": "testraster", "speed_mm_s": 12, "power_percent": 65}
    )
    assert server.provenance.lookup("sheet-1", "op-1", 12, 65) is not None

    client.post("/api/project/new")

    assert server.provenance.lookup("sheet-1", "op-1", 12, 65) is None
