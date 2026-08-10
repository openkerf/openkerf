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
    assert set(bundle.namelist()) == {"design.svg", "library.json"}
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
