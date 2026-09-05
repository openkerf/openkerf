"""
Projects kept on the server: a folder of .openkerf files and the name of the open one.

Every number a docstring here names was measured on this working copy; a test that
quotes one nobody measured is worse than one that says nothing.
"""
import errno
import zipfile
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from openkerf_api import projects as projects_module
from openkerf_api.edits import DesignError
from openkerf_api.projects import ProjectError, Projects, clean_name
from openkerf_api.server import ApiServer


@pytest.fixture
def server(kernel, tmp_path):
    return ApiServer(kernel, library_path=tmp_path / "a.db")


@pytest.fixture
def client(server):
    with TestClient(server.build_app()) as c:
        yield c


@pytest.fixture
def projects(server, tmp_path):
    """A Projects bound to the test server's drawing, on a folder of its own."""
    folder = tmp_path / "projects-under-test"
    return Projects(
        folder,
        drawing=server.drawing,
        library=server.library,
        sheets=server.sheets,
        document=server.document,
    )


def _draw_two_rects(client):
    client.post("/api/project/new")
    client.post("/api/design/elements", json={"type": "rect", "x_mm": 10, "y_mm": 10, "width_mm": 20, "height_mm": 20})
    client.post("/api/design/elements", json={"type": "rect", "x_mm": 40, "y_mm": 10, "width_mm": 20, "height_mm": 20})


def test_a_name_is_a_file_name():
    assert clean_name("  Kastje groot ") == "Kastje groot"
    assert clean_name("a/b") == "ab"
    assert clean_name("../etc") == "etc"
    assert clean_name(".hidden") == "hidden"
    assert clean_name("naïve") == "nave"
    assert clean_name("x" * 80) == "x" * 60
    assert clean_name("   ") == ""
    assert clean_name("box_1-2.v3") == "box_1-2.v3"


def test_saving_writes_one_file_that_opens_to_the_same_design(projects, client):
    """
    Measured against the handbook's docs server, with its design on the bed (four
    layers, box panels, a living hinge, text and a QR code): saving took 0.099 s,
    opening it back took 0.023 s, and the file it wrote was 23,357 bytes — about
    23 KB for a design of that size.
    """
    _draw_two_rects(client)
    entry = projects.save("Kastje")
    files = sorted(p.name for p in projects.folder.iterdir())
    assert files == ["Kastje.openkerf"], files
    assert entry["name"] == "Kastje" and entry["current"] is True
    assert zipfile.is_zipfile(projects.folder / "Kastje.openkerf")
    before = client.get("/api/design").json()
    client.post("/api/project/new")
    assert client.get("/api/design").json()["elements"] == []
    projects.open("Kastje")
    after = client.get("/api/design").json()
    assert len(after["elements"]) == len(before["elements"]) == 2
    assert projects.current == "Kastje"


def test_saving_over_another_project_asks_first(projects, client):
    _draw_two_rects(client)
    projects.save("A")
    projects.save("B")
    with pytest.raises(ProjectError) as refused:
        projects.save("A")
    assert refused.value.code == "project.exists"
    assert "A" in str(refused.value)
    entry = projects.save("A", overwrite=True)
    assert entry["current"] is True and projects.current == "A"
    # Saving the current project again never asks: that is what Save means.
    projects.save("A")


def test_bad_names_are_refused_with_a_sentence(projects, client):
    _draw_two_rects(client)
    for bad in ("", "   ", "../x", "a/b", "." * 3):
        with pytest.raises(ProjectError) as refused:
            projects.save(bad)
        assert refused.value.code == "project.badName", bad
        assert isinstance(refused.value, DesignError)
    assert list(projects.folder.iterdir()) == [] if projects.folder.exists() else True


def test_rename_and_delete_leave_nothing_behind(projects, client):
    _draw_two_rects(client)
    projects.save("Old")
    entry = projects.rename("Old", "New")
    assert entry["name"] == "New" and projects.current == "New"
    assert sorted(p.name for p in projects.folder.iterdir()) == ["New.openkerf"]
    with pytest.raises(ProjectError) as refused:
        projects.rename("New", "New")
    assert refused.value.code == "project.exists"
    projects.delete("New")
    assert list(projects.folder.iterdir()) == []
    assert projects.current is None
    with pytest.raises(ProjectError) as missing:
        projects.open("New")
    assert missing.value.code == "project.missing"


def test_the_list_is_read_from_the_folder_every_time(projects, client, tmp_path):
    """
    Measured on the docs server: a file copied into the projects folder by hand, with
    no save through the API at all, showed up in a plain `GET /api/projects` the very
    next time it was asked — nothing here is cached.
    """
    _draw_two_rects(client)
    projects.save("Mine")
    copied = projects.folder / "Copied in by hand.openkerf"
    copied.write_bytes((projects.folder / "Mine.openkerf").read_bytes())
    names = [e["name"] for e in projects.list()]
    assert set(names) == {"Mine", "Copied in by hand"}
    mine = next(e for e in projects.list() if e["name"] == "Mine")
    assert mine["current"] is True and mine["bytes"] > 0
    when = datetime.fromisoformat(mine["saved_at"])
    assert when.tzinfo is not None, mine["saved_at"]


def test_dirty_falls_after_save_and_open(projects, client):
    _draw_two_rects(client)
    assert client.get("/api/design").json()["dirty"] is True
    projects.save("Clean")
    assert client.get("/api/design").json()["dirty"] is False
    client.post("/api/design/elements", json={"type": "rect", "x_mm": 1, "y_mm": 1, "width_mm": 5, "height_mm": 5})
    assert client.get("/api/design").json()["dirty"] is True
    projects.open("Clean")
    assert client.get("/api/design").json()["dirty"] is False


def test_adopting_an_upload_moves_it_in_under_a_free_name(projects, client, tmp_path):
    _draw_two_rects(client)
    projects.save("Board")
    stray = tmp_path / "upload.openkerf"
    stray.write_bytes((projects.folder / "Board.openkerf").read_bytes())
    entry = projects.adopt(stray, "Board")
    assert entry["name"] == "Board 2" and projects.current == "Board 2"
    assert not stray.exists()
    assert sorted(p.name for p in projects.folder.iterdir()) == ["Board 2.openkerf", "Board.openkerf"]


def test_adopting_a_sixty_character_name_leaves_room_to_number_it(projects, client, tmp_path):
    """
    Before the fix, numbering a taken name at the full 60 characters wrote a file at 62
    — past `MAX_NAME` — which `open()` and `delete()` (both through `_valid`) then
    refused: an unopenable, undeletable row in the list.
    """
    sixty = "x" * 60
    _draw_two_rects(client)
    projects.save(sixty)
    stray = tmp_path / f"{sixty}.openkerf"
    stray.write_bytes((projects.folder / f"{sixty}.openkerf").read_bytes())
    entry = projects.adopt(stray, sixty)
    assert len(entry["name"]) <= 60, entry["name"]
    assert entry["name"] != sixty
    reopened = projects.open(entry["name"])
    assert reopened["project"]["name"] == entry["name"]
    projects.delete(entry["name"])


def test_saving_survives_a_filesystem_boundary_between_temp_and_the_folder(projects, client, monkeypatch):
    """
    `tempfile.mkdtemp()` (what `export_project` writes into) and `self.folder` both sit
    under the same filesystem in every test here, so a plain `os.replace` between them
    never raises. In the real deployment the projects folder is a mounted volume and the
    system temp directory is the container's own filesystem, so the same move raises
    `OSError(EXDEV)`. This test makes that boundary real without needing two actual
    filesystems: it fails `os.replace` whenever source and destination do not share a
    parent directory, which is exactly the shape of the two directories being different
    mounts.
    """
    _draw_two_rects(client)
    real_replace = projects_module.os.replace

    def crosses_devices(src, dst):
        if Path(src).parent != Path(dst).parent:
            raise OSError(errno.EXDEV, "cross-device link")
        return real_replace(src, dst)

    monkeypatch.setattr(projects_module.os, "replace", crosses_devices)

    entry = projects.save("Across")
    assert entry["name"] == "Across" and projects.current == "Across"
    assert (projects.folder / "Across.openkerf").exists()
    leftovers = [p.name for p in projects.folder.iterdir() if p.name.startswith(".saving-")]
    assert leftovers == [], leftovers

    client.post("/api/project/new")
    projects.open("Across")
    assert len(client.get("/api/design").json()["elements"]) == 2

    names = [e["name"] for e in projects.list()]
    assert names == ["Across"]


def test_adopting_survives_the_same_filesystem_boundary(projects, client, tmp_path, monkeypatch):
    """
    `adopt()` is reached from a live route (`POST /api/project/open`) with a file that
    `self._upload_path` put under a `tempfile.mkdtemp()` directory of its own — the same
    boundary `save()` documents and crosses with a stage-then-rename, and in the deployed
    image just as real here: the upload directory and the projects folder need not share
    a filesystem. Before this test, `adopt()` did a bare `os.replace(path, ...)`, which
    `save()`'s own docstring says raises `OSError(EXDEV)` on exactly that boundary.
    """
    _draw_two_rects(client)
    projects.save("Board")
    real_replace = projects_module.os.replace

    def crosses_devices(src, dst):
        if Path(src).parent != Path(dst).parent:
            raise OSError(errno.EXDEV, "cross-device link")
        return real_replace(src, dst)

    monkeypatch.setattr(projects_module.os, "replace", crosses_devices)

    stray = tmp_path / "upload.openkerf"
    stray.write_bytes((projects.folder / "Board.openkerf").read_bytes())

    entry = projects.adopt(stray, "Board")

    assert entry["name"] == "Board 2" and projects.current == "Board 2"
    assert not stray.exists()
    assert len(client.get("/api/design").json()["elements"]) == 2
    leftovers = [p.name for p in projects.folder.iterdir() if p.name.startswith(".saving-")]
    assert leftovers == [], leftovers


def test_forget_clears_the_current_project(projects, client):
    _draw_two_rects(client)
    projects.save("X")
    projects.forget()
    assert projects.current is None and projects.state() == {"name": None, "saved_at": None}


def _headers(server):
    return {"X-OpenKerf-Token": server.token}


def test_the_routes_save_list_open_rename_and_delete(client, server):
    _draw_two_rects(client)
    h = _headers(server)
    saved = client.post("/api/projects/Kastje", headers=h)
    assert saved.status_code == 200, saved.text
    assert saved.json()["name"] == "Kastje"
    assert client.get("/api/design").json()["project"] == {
        "name": "Kastje",
        "saved_at": saved.json()["saved_at"],
    }

    listed = client.get("/api/projects").json()
    assert [e["name"] for e in listed] == ["Kastje"] and listed[0]["current"] is True

    client.post("/api/project/new", headers=h)
    assert client.get("/api/design").json()["project"]["name"] is None

    opened = client.post("/api/projects/Kastje/open", headers=h)
    assert opened.status_code == 200 and opened.json()["project"]["name"] == "Kastje"
    assert len(client.get("/api/design").json()["elements"]) == 2

    renamed = client.post("/api/projects/Kastje/rename", json={"name": "Doos"}, headers=h)
    assert renamed.status_code == 200 and renamed.json()["name"] == "Doos"
    assert client.get("/api/design").json()["project"]["name"] == "Doos"

    gone = client.delete("/api/projects/Doos", headers=h)
    assert gone.status_code == 200
    assert client.get("/api/projects").json() == []
    assert client.get("/api/design").json()["project"]["name"] is None


def test_the_routes_refuse_with_a_code_in_the_header(client, server):
    _draw_two_rects(client)
    h = _headers(server)
    client.post("/api/projects/A", headers=h)
    client.post("/api/projects/B", headers=h)
    refused = client.post("/api/projects/A", headers=h)
    assert refused.status_code == 409
    assert refused.headers["X-OpenKerf-Error"] == "project.exists"
    assert client.post("/api/projects/A?overwrite=1", headers=h).status_code == 200
    bad = client.post("/api/projects/..%2Fx", headers=h)
    assert bad.status_code in (400, 404, 409, 422)
    missing = client.post("/api/projects/Nobody/open", headers=h)
    assert missing.status_code == 409 and missing.headers["X-OpenKerf-Error"] == "project.missing"


def test_an_upload_becomes_a_project_and_the_export_carries_its_name(client, server, tmp_path):
    _draw_two_rects(client)
    h = _headers(server)
    client.post("/api/projects/Board", headers=h)
    exported = client.get("/api/project/export.openkerf")
    assert exported.status_code == 200
    assert 'filename="Board.openkerf"' in exported.headers["content-disposition"]
    uploaded = client.post(
        "/api/project/open",
        files={"file": ("Board.openkerf", exported.content, "application/zip")},
        headers=h,
    )
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["name"] == "Board 2"
    assert sorted(e["name"] for e in client.get("/api/projects").json()) == ["Board", "Board 2"]


def test_every_project_route_that_writes_is_guarded(client):
    """
    Structural, not a 401 walk: the `server`/`client` fixtures bind to loopback, so
    `require_write` never refuses there (see `test_write_actions.py`'s own `local_client`,
    which is bound the same way and is why that suite's guard test reads the dependency
    list instead of firing requests). This asks the same question the same way, scoped to
    the project routes this task adds.
    """
    mutating = [
        route
        for route in client.app.routes
        if route.path.startswith("/api/project")
        and getattr(route, "methods", set()) & {"POST", "PATCH", "PUT", "DELETE"}
    ]
    assert mutating, "there are project write routes"
    for route in mutating:
        names = [getattr(d.call, "__name__", "") for d in route.dependant.dependencies]
        assert "require_write" in names, f"{route.path} has no write guard"
