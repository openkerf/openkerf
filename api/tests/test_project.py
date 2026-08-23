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
    # `with_everything` because this material carries the preset the project is about to
    # restore, and a bare DELETE is now refused rather than cascading in silence
    # (`library.material.inUse`, pinned in test_library.py by
    # test_removing_a_material_that_carries_work_is_refused_and_names_the_count).
    # Emptying the library is the point of this line, so it says so.
    assert client.delete("/api/library/materials/1?with_everything=true").status_code == 200
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


# ---------------------------------------------------------- the list of names
#
# A design can read its text out of a list — one plate per row, the whole of
# `series.py`. The list is state beside the library, so without these four it does not
# travel with the project and a design that reads `{name}` arrives somewhere else unable
# to burn.


def a_list(client, names=("Anna", "Bram", "Cees"), column="name"):
    """Upload and attach a list, the way the Series window's own button does."""
    data = (column + "\n" + "\n".join(names) + "\n").encode("utf-8")
    uploaded = client.post(
        "/api/series/upload", files={"file": ("names.csv", data, "text/csv")}
    )
    assert uploaded.status_code == 200, uploaded.text
    attached = client.post(
        "/api/series/attach", json={"file": uploaded.json()["file"]}
    )
    assert attached.status_code == 200, attached.text
    return attached.json()


def a_variable_text(client, template="{name}"):
    """One vector text on the bed that reads from the list. Returns its element id."""
    response = client.post(
        "/api/design/elements",
        json={
            "type": "text",
            "x_mm": 20,
            "y_mm": 20,
            "text": template,
            "font_size_mm": 8,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["ids"][0]


def burned_text(kernel, element_id):
    """What the engine has really rendered into this node, not what we asked for."""
    for node in kernel.elements.elems():
        if getattr(node, "id", None) == element_id:
            return getattr(node, "_translated_text", None)
    raise AssertionError(f"There is no element {element_id} on the bed.")


def without(data: bytes, name: str) -> bytes:
    """The same bundle with one entry taken out — a project from before that entry."""
    out = io.BytesIO()
    source = zipfile.ZipFile(io.BytesIO(data))
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as bundle:
        for entry in source.namelist():
            if entry != name:
                bundle.writestr(entry, source.read(entry))
    return out.getvalue()


def test_the_list_travels_in_the_project_bundle_and_the_run_does_not(
    server, client, kernel
):
    """
    Mailing a project mails the names; it does not mail somebody's half-done afternoon.

    Measured on a bundle written before `series.json` existed, opening it in a workshop
    that has never seen the list: the text came back with `mktext` `{name}` and the
    geometry of whatever row the sender happened to be on (`Anna`), nothing attached,
    `check()` calling it a ghost with `missing: ['name']`, and `POST /api/job/start`
    answering 409 `series.noList`. So the receiver had the drawing and no way to burn it
    until they went looking for the spreadsheet — and the first thing that re-rendered
    that text (attaching any other list, or detaching) turned it into the empty string:
    bounds `(nan, nan, nan, nan)` and nought elements in `DesignReader.snapshot()`,
    while the Engrave layer went on reporting one element and `burns` true. Invisible on
    the canvas, present in the job.

    The run is the other half and it is deliberately absent. `done`, the fingerprint and
    the pointer are a count of plates made at somebody else's machine; `start` writes an
    empty `done`, so a resumed stranger's run cannot even be undone. The receiver gets
    the list standing on its first row.

    Detaching before opening stands in for opening the project in another workshop: the
    state beside the library is what a fresh machine has none of.
    """
    a_variable_text(client)
    a_list(client)
    assert client.post("/api/series/start", json={}).status_code == 200

    data = client.get("/api/project/export.openkerf").content

    bundle = zipfile.ZipFile(io.BytesIO(data))
    assert "series.json" in bundle.namelist()
    carried = json.loads(bundle.read("series.json"))
    assert [row["name"] for row in carried["rows"]] == ["Anna", "Bram", "Cees"]
    assert carried["columns"] == ["name"]
    # Where they came from travels too, so the window can still say what it read.
    assert carried["source"]["kind"] == "file"
    assert carried["source"]["name"] == "names.csv"
    assert carried["source"]["delimiter"] == ","
    assert "run" not in carried
    assert "current_row" not in carried

    assert client.post("/api/series/stop").status_code == 200
    assert client.delete("/api/series").json()["attached"] is False
    assert server.series.path.exists() is False
    assert client.post(
        "/api/project/open", files={"file": ("p.openkerf", data, "application/zip")}
    ).status_code == 200

    state = client.get("/api/series").json()
    assert state["attached"] is True
    assert state["row_count"] == 3
    assert state["current_row"] == 0
    assert state["run"] is None
    assert state["ghosts"] == []
    # The bed shows the row that is about to burn, which is the whole promise, and the
    # shape is in the snapshot rather than a hole in it.
    element = client.get("/api/design").json()["elements"][0]["id"]
    assert burned_text(kernel, element) == "Anna"
    # And the gate every burn passes no longer refuses this design.
    server.series.vet()


def test_a_project_from_before_the_lists_leaves_the_attached_one_alone(client):
    """
    A bundle that says nothing about lists does not get to throw one away.

    Every project made before this feature has no `series.json` in it, and silence is
    not an instruction. Fails on the tempting shortcut of "no list in the bundle means
    detach", which would take somebody's afternoon away for opening a drawing from last
    month.
    """
    a_variable_text(client)
    a_list(client)
    data = without(client.get("/api/project/export.openkerf").content, "series.json")

    assert client.post(
        "/api/project/open", files={"file": ("p.openkerf", data, "application/zip")}
    ).status_code == 200

    state = client.get("/api/series").json()
    assert state["attached"] is True
    assert [row["name"] for row in state["rows"]] == ["Anna", "Bram", "Cees"]


def test_a_project_that_has_no_list_takes_the_attached_one_away(client, kernel):
    """
    `null` in the bundle is a statement, and the opposite one from an absent file.

    This is the case that costs plates if it goes the other way: open a project whose
    text reads `{name}` and which carries no list, with last week's names still
    attached, and every burn takes a name from a list this project never had — fifty
    plates deep, with nothing on the screen disagreeing. So the list goes, and the text
    is honest about having nothing to say: `Plate ` rather than `Plate Xander`.

    `Plate {name}` and not a bare `{name}`, and that is a measurement rather than taste:
    a text that is *only* a placeholder has no geometry while nothing is attached, so
    the engine writes it into the SVG as `<path d="">` and reads it back as an
    `elem point` with no `mktext` and bounds `(nan, nan, nan, nan)`. A word beside the
    placeholder gives the shape something to be.
    """
    a_variable_text(client, "Plate {name}")
    data = client.get("/api/project/export.openkerf").content
    assert json.loads(zipfile.ZipFile(io.BytesIO(data)).read("series.json")) is None
    a_list(client, names=("Xander", "Yara"))

    assert client.post(
        "/api/project/open", files={"file": ("p.openkerf", data, "application/zip")}
    ).status_code == 200

    assert client.get("/api/series").json()["attached"] is False
    node = [n for n in kernel.elements.elems() if getattr(n, "mktext", None)][0]
    assert node.mktext == "Plate {name}"
    assert node._translated_text == "Plate "


def test_a_project_will_not_open_over_a_running_series(client, kernel):
    """
    A run counts plates made from *this* drawing, and opening replaces the drawing.

    Refused rather than quietly ended: `start` writes an empty `done`, so a count thrown
    away here cannot be got back by any button. Asked before one shape is touched, which
    is what the second half asserts — a refusal that arrived after the sheets were in
    would leave a project half opened, with the receiver's design under the sender's
    sheets.
    """
    a_variable_text(client)
    a_list(client)
    data = client.get("/api/project/export.openkerf").content
    assert client.post("/api/series/start", json={}).status_code == 200
    before = [node.id for node in kernel.elements.elems()]

    response = client.post(
        "/api/project/open", files={"file": ("p.openkerf", data, "application/zip")}
    )

    assert response.status_code == 409
    assert response.headers["X-OpenKerf-Error"] == "series.runGoingProject"
    assert [node.id for node in kernel.elements.elems()] == before
    assert client.get("/api/series").json()["run"] is not None
