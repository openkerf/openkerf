# Projects kept on the server — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Projects are saved and opened on the server, in a folder of `.openkerf` files, with a current project named in the top bar; download and upload stay as the second way.

**Architecture:** A `Projects` class in the API owns a folder and the name of the open project, writing and reading through the existing `export_project` / `import_project`. Five routes expose list, save, open, rename and delete; the design snapshot carries `project` beside `dirty`. On the frontend a `projects.svelte.ts` store holds the list and the flows, `actions.ts` holds the verbs, the top bar shows the name, and two dialogs (Projects, Unsaved changes) do the asking. The Docker entrypoint passes `-r /data/projects`.

**Tech Stack:** FastAPI + the MeerK40t kernel (Python 3.13/3.14), pytest; SvelteKit 2 with Svelte 5 runes, TypeScript, `node:test`, Playwright for the server-backed tests; the handbook's picture script.

**Spec:** `docs/superpowers/specs/2026-09-04-server-projects-design.md`

## Global Constraints

- Nothing under `meerk40t/` changes. The project file format (`.openkerf`) does not change.
- A name is letters, digits, spaces, `-`, `_` and `.`; at most 60 characters; no leading dot; trimmed. The same rule in `api/openkerf_api/projects.py:clean_name` and `frontend/src/lib/projects.svelte.ts:cleanName`, held to each other by a test.
- Refusals are `ProjectError` (subclass of `DesignError`) with a whole sentence and a code: `project.badName`, `project.exists`, `project.missing`, `project.busy`.
- Every mutating route is guarded by `Depends(require_write)` — `api/tests/test_write_actions.py` checks that no write route slips in unguarded.
- Tests must not write where the user lives: a third autouse fixture in `api/tests/conftest.py` gives every test server a projects folder under `tmp_path`.
- Default folder outside Docker: `projects/` beside the library file. In the image: `/data/projects`, passed by `deploy/entrypoint.sh` with `-r`.
- English is the source language; keys are semantic; a message is a whole sentence; dates through `Intl`. Every new `en.ts` key has its `nl.ts` twin.
- Verbs live in `frontend/src/lib/actions.ts`; menu and keyboard read from there. Shortcuts: Open… `mod+o`, Save `mod+s`, Save as… `mod+shift+s`. Every new shortcut stands in the key tables of `docs/reference.md`.
- The handbook moves in the same commit as the screen: `docs/getting-started.md`, `docs/reference.md`, `docs/running-in-docker.md`; new pictures `47-projects.png` and `48-topbar-project.png` taken by `frontend/gauntlet/docs-shots.mjs`; `frontend/tests/docs.test.ts` stays green.
- Numbers in docstrings and pages are measured, never guessed.
- Never start a job or move the head in any test.
- Commit messages: a plain sentence saying what changed, a blank line, then `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Python for the API: `meerk40t/.venv/bin/python -m pytest api/tests -q`. Frontend: `cd frontend && node --test tests/*.test.ts`; server-backed tests need `OK_BASE` and a fenced server (`meerk40t/.venv/bin/meerk40t --no-gui -d -e "openkerf -p 8184 -l <tmp>/library.db -o <tmp>/operations.cfg -r <tmp>/projects -f frontend/build"` after `npm run build`).

---

## File structure

| File | Responsibility |
|---|---|
| `api/openkerf_api/projects.py` (new) | The folder, the name rule, the current project; save/open/rename/delete/adopt. |
| `api/openkerf_api/server.py` | The five routes; `project` in the snapshot; `new` clears the current project; upload adopts; export names the file. |
| `api/openkerf_api/plugin.py` | The `-r/--projects` flag. |
| `api/tests/conftest.py` | Third autouse fixture: a projects folder per test server. |
| `api/tests/test_projects.py` (new) | The class and the routes. |
| `frontend/src/lib/projects.svelte.ts` (new) | The list, the current name, `cleanName`, the three flows. |
| `frontend/src/lib/actions.ts` | `projectActions(ctx, h)`; `KEYS.open/save/saveAs`; `Handlers` gain the four project verbs. |
| `frontend/src/lib/components/TopBar.svelte` | The button reads the name; the menu reads `projectActions`. |
| `frontend/src/lib/components/Projects.svelte` (new) | The window: list, Save as… field, row menu. |
| `frontend/src/lib/components/UnsavedChanges.svelte` (new) | Save / Discard / Cancel. |
| `frontend/src/routes/+page.svelte` | Wires store, dialogs, `beforeunload`; `Replacement` gains server kinds. |
| `frontend/src/lib/i18n/en.ts`, `nl.ts` | The sentences. |
| `frontend/tests/projects.test.ts` (new) | Name parity with Python; menu order; button text. |
| `frontend/tests/projects-flow.test.ts` (new) | Server-backed: save as, list, open, cancel. |
| `frontend/gauntlet/docs-shots.mjs` | Scenes 47 and 48. |
| `docs/getting-started.md`, `docs/reference.md`, `docs/running-in-docker.md` | The words. |
| `deploy/entrypoint.sh`, `deploy/compose.yml` (comment) | `-r /data/projects`. |

---

### Task 1: The `Projects` class

**Files:**
- Create: `api/openkerf_api/projects.py`
- Create: `api/tests/test_projects.py`
- Modify: `api/tests/conftest.py`

**Interfaces:**
- Consumes: `Drawing.export_project(library, filename, sheets) -> Path` and `Drawing.import_project(path, library, sheets) -> dict` (`api/openkerf_api/drawing.py:3137`, `:3188`); `DesignError(message, code=...)` (`api/openkerf_api/edits.py:28`); `Document.clean()` (`api/openkerf_api/document.py`).
- Produces: `class ProjectError(DesignError)`; `clean_name(raw: str) -> str`; `class Projects` with `folder: Path`, `current: str | None`, `list() -> list[dict]`, `save(name, overwrite=False) -> dict`, `open(name) -> dict`, `rename(old, new) -> dict`, `delete(name) -> None`, `adopt(path: Path, wanted: str) -> dict`, `forget() -> None`, `state() -> dict` (`{"name": ..., "saved_at": ...}`).

- [ ] **Step 1: Write the failing tests**

```python
# api/tests/test_projects.py
"""
Projects kept on the server: a folder of .openkerf files and the name of the open one.

Every number a docstring here names was measured on this working copy; a test that
quotes one nobody measured is worse than one that says nothing.
"""
import json
import zipfile
from pathlib import Path

import pytest

from openkerf_api.edits import DesignError
from openkerf_api.projects import ProjectError, Projects, clean_name


@pytest.fixture
def projects(api_server, tmp_path):
    """A Projects bound to the test server's drawing, on a folder of its own."""
    server = api_server
    folder = tmp_path / "projects-under-test"
    return Projects(
        folder,
        drawing=server.drawing,
        library=server.library,
        sheets=server.sheets,
        document=server.document,
    )


def _draw_two_rects(api):
    api.post("/api/project/new")
    api.post("/api/design/elements", json={"type": "rect", "x_mm": 10, "y_mm": 10, "width_mm": 20, "height_mm": 20})
    api.post("/api/design/elements", json={"type": "rect", "x_mm": 40, "y_mm": 10, "width_mm": 20, "height_mm": 20})


def test_a_name_is_a_file_name():
    assert clean_name("  Kastje groot ") == "Kastje groot"
    assert clean_name("a/b") == "ab"
    assert clean_name("../etc") == "etc"
    assert clean_name(".hidden") == "hidden"
    assert clean_name("naïve") == "nave"
    assert clean_name("x" * 80) == "x" * 60
    assert clean_name("   ") == ""
    assert clean_name("box_1-2.v3") == "box_1-2.v3"


def test_saving_writes_one_file_that_opens_to_the_same_design(projects, api):
    _draw_two_rects(api)
    entry = projects.save("Kastje")
    files = sorted(p.name for p in projects.folder.iterdir())
    assert files == ["Kastje.openkerf"], files
    assert entry["name"] == "Kastje" and entry["current"] is True
    assert zipfile.is_zipfile(projects.folder / "Kastje.openkerf")
    before = api.get("/api/design").json()
    api.post("/api/project/new")
    assert api.get("/api/design").json()["elements"] == []
    projects.open("Kastje")
    after = api.get("/api/design").json()
    assert len(after["elements"]) == len(before["elements"]) == 2
    assert projects.current == "Kastje"


def test_saving_over_another_project_asks_first(projects, api):
    _draw_two_rects(api)
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


def test_bad_names_are_refused_with_a_sentence(projects, api):
    _draw_two_rects(api)
    for bad in ("", "   ", "../x", "a/b", "." * 3):
        with pytest.raises(ProjectError) as refused:
            projects.save(bad)
        assert refused.value.code == "project.badName", bad
        assert isinstance(refused.value, DesignError)
    assert list(projects.folder.iterdir()) == [] if projects.folder.exists() else True


def test_rename_and_delete_leave_nothing_behind(projects, api):
    _draw_two_rects(api)
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


def test_the_list_is_read_from_the_folder_every_time(projects, api, tmp_path):
    _draw_two_rects(api)
    projects.save("Mine")
    copied = projects.folder / "Copied in by hand.openkerf"
    copied.write_bytes((projects.folder / "Mine.openkerf").read_bytes())
    names = [e["name"] for e in projects.list()]
    assert set(names) == {"Mine", "Copied in by hand"}
    mine = next(e for e in projects.list() if e["name"] == "Mine")
    assert mine["current"] is True and mine["bytes"] > 0 and mine["saved_at"].endswith("Z") is False


def test_dirty_falls_after_save_and_open(projects, api):
    _draw_two_rects(api)
    assert api.get("/api/design").json()["dirty"] is True
    projects.save("Clean")
    assert api.get("/api/design").json()["dirty"] is False
    api.post("/api/design/elements", json={"type": "rect", "x_mm": 1, "y_mm": 1, "width_mm": 5, "height_mm": 5})
    assert api.get("/api/design").json()["dirty"] is True
    projects.open("Clean")
    assert api.get("/api/design").json()["dirty"] is False


def test_adopting_an_upload_moves_it_in_under_a_free_name(projects, api, tmp_path):
    _draw_two_rects(api)
    projects.save("Board")
    stray = tmp_path / "upload.openkerf"
    stray.write_bytes((projects.folder / "Board.openkerf").read_bytes())
    entry = projects.adopt(stray, "Board")
    assert entry["name"] == "Board 2" and projects.current == "Board 2"
    assert not stray.exists()
    assert sorted(p.name for p in projects.folder.iterdir()) == ["Board 2.openkerf", "Board.openkerf"]


def test_forget_clears_the_current_project(projects, api):
    _draw_two_rects(api)
    projects.save("X")
    projects.forget()
    assert projects.current is None and projects.state() == {"name": None, "saved_at": None}
```

Read `api/tests/conftest.py` for the names of the existing fixtures that give a test an `ApiServer` and a `TestClient`; the fixtures above are called `api_server` and `api` — if the suite calls them differently (grep `def api` and `def server` in `conftest.py` and one existing test such as `test_write_actions.py`), use the suite's names in this file rather than adding new ones.

- [ ] **Step 2: Run them and see them fail**

Run: `meerk40t/.venv/bin/python -m pytest api/tests/test_projects.py -q`
Expected: `ImportError: cannot import name 'Projects'` (module does not exist).

- [ ] **Step 3: Write `api/openkerf_api/projects.py`**

```python
"""
Projects kept on the server: a folder of .openkerf files, and the name of the open one.

Why a folder and not a table. The project file already exists — a zip with the design,
the sheets, the library context and the list a series burns from — and a folder of them
is something a person can look at, copy with the volume and put a file into by hand.
`list()` reads the folder every time for exactly that reason. No history: one file per
name, and saving over it is the whole story.

The name is a file name. `clean_name` is the rule, `frontend/src/lib/projects.svelte.ts`
has the same rule in TypeScript, and `frontend/tests/projects.test.ts` runs the two
against each other so that what the field shows is what the folder gets.
"""
from __future__ import annotations

import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .edits import DesignError

SUFFIX = ".openkerf"
MAX_NAME = 60
_ALLOWED = re.compile(r"[^A-Za-z0-9 ._-]")


class ProjectError(DesignError):
    """A refusal about a project, with a code the interface can say in its own words."""


def clean_name(raw: str) -> str:
    """
    What survives of a name: letters, digits, spaces, `-`, `_`, `.`; no leading dot;
    at most MAX_NAME characters; trimmed. `''` when nothing survives.
    """
    kept = _ALLOWED.sub("", raw or "")
    kept = kept.lstrip(".").strip()
    return kept[:MAX_NAME].strip()


class Projects:
    def __init__(self, folder: Path, *, drawing, library, sheets, document):
        self.folder = Path(folder)
        self.drawing = drawing
        self.library = library
        self.sheets = sheets
        self.document = document
        self.current: str | None = None

    # ------------------------------------------------------------------ reading
    def _path(self, name: str) -> Path:
        return self.folder / f"{name}{SUFFIX}"

    def _valid(self, raw: str) -> str:
        name = clean_name(raw)
        if not name or name != (raw or "").strip():
            raise ProjectError(
                "A project name may hold letters, digits, spaces, dots, hyphens and "
                "underscores, at most 60 of them, and may not start with a dot.",
                code="project.badName",
            )
        return name

    def _entry(self, path: Path) -> dict:
        stat = path.stat()
        return {
            "name": path.stem,
            "saved_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            "bytes": stat.st_size,
            "current": path.stem == self.current,
        }

    def list(self) -> list[dict]:
        if not self.folder.exists():
            return []
        entries = [self._entry(p) for p in self.folder.iterdir() if p.is_file() and p.suffix == SUFFIX]
        return sorted(entries, key=lambda e: e["saved_at"], reverse=True)

    def state(self) -> dict:
        if self.current is None or not self._path(self.current).exists():
            return {"name": self.current, "saved_at": None}
        return {"name": self.current, "saved_at": self._entry(self._path(self.current))["saved_at"]}

    # ------------------------------------------------------------------ writing
    def save(self, raw: str, overwrite: bool = False) -> dict:
        name = self._valid(raw)
        target = self._path(name)
        if target.exists() and name != self.current and not overwrite:
            raise ProjectError(
                f"There is already a project called {name}. Choose another name, or "
                "say that it may be replaced.",
                code="project.exists",
            )
        self.folder.mkdir(parents=True, exist_ok=True)
        # Written beside the target and moved over it in one step: a save that dies
        # halfway leaves the old file whole, not a half-written zip under its name.
        handle, tmp = tempfile.mkstemp(prefix=".saving-", suffix=SUFFIX, dir=self.folder)
        os.close(handle)
        try:
            written = Path(self.drawing.export_project(self.library, tmp, self.sheets))
            os.replace(written, target)
        finally:
            Path(tmp).unlink(missing_ok=True)
        self.current = name
        self.document.clean()
        return self._entry(target)

    def open(self, raw: str) -> dict:
        name = self._valid(raw)
        path = self._path(name)
        if not path.exists():
            raise ProjectError(f"There is no project called {name}.", code="project.missing")
        result = self.drawing.import_project(str(path), self.library, self.sheets)
        self.current = name
        self.document.clean()
        return {**(result or {}), "project": self._entry(path)}

    def rename(self, old_raw: str, new_raw: str) -> dict:
        old, new = self._valid(old_raw), self._valid(new_raw)
        source, target = self._path(old), self._path(new)
        if not source.exists():
            raise ProjectError(f"There is no project called {old}.", code="project.missing")
        if target.exists():
            raise ProjectError(
                f"There is already a project called {new}. Choose another name.",
                code="project.exists",
            )
        source.rename(target)
        if self.current == old:
            self.current = new
        return self._entry(target)

    def delete(self, raw: str) -> None:
        name = self._valid(raw)
        path = self._path(name)
        if not path.exists():
            raise ProjectError(f"There is no project called {name}.", code="project.missing")
        path.unlink()
        if self.current == name:
            self.current = None

    def adopt(self, path: Path, wanted: str) -> dict:
        """An uploaded file becomes a project: moved in under a free name, then opened."""
        base = clean_name(Path(wanted).stem) or "Project"
        name, n = base, 2
        self.folder.mkdir(parents=True, exist_ok=True)
        while self._path(name).exists():
            name, n = f"{base} {n}", n + 1
        os.replace(path, self._path(name))
        return self.open(name)

    def forget(self) -> None:
        """New project: no name until it is saved."""
        self.current = None
```

Check `export_project`'s signature in `drawing.py:3137`: it takes `filename` and returns the path it wrote. If it writes into its own directory rather than to the given path, pass the temporary file's full path as `filename` and read the returned `Path`; the `os.replace` above then moves whatever came back. Say in the report what it did.

- [ ] **Step 4: The fence — a third autouse fixture**

In `api/tests/conftest.py`, after `_operations_of_its_own`, add:

```python
@pytest.fixture(autouse=True)
def _projects_of_their_own(tmp_path, monkeypatch):
    """
    No test may write into the projects folder of the developer's own app.

    `ApiServer(kernel)` without `projects` falls back to `projects/` beside the library
    file, and the library's default path is keyed to the kernel name (see the fixture
    above). So every test server is handed a folder under `tmp_path` here, the way the
    library and the layer list are.
    """
    folder = tmp_path / "projects"
    original = server_module.ApiServer.__init__

    def patched(self, *args, **kwargs):
        kwargs.setdefault("projects", folder)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(server_module.ApiServer, "__init__", patched)
```

Read how `_library_of_its_own` patches the server (the same pattern, `monkeypatch` on `ApiServer.__init__` or on `default_path`) and match its shape exactly; the `projects` keyword arrives in Task 2, so this fixture must tolerate an `ApiServer.__init__` that does not yet accept it — for this task, only add the fixture body without the `setdefault` line, and add that line in Task 2, Step 4.

- [ ] **Step 5: Run the tests and see them pass**

Run: `meerk40t/.venv/bin/python -m pytest api/tests/test_projects.py -q`
Expected: 8 passed. Then the whole suite: `meerk40t/.venv/bin/python -m pytest api/tests -q` → 1613 + 8 passed.

- [ ] **Step 6: Commit**

```bash
git add api/openkerf_api/projects.py api/tests/test_projects.py api/tests/conftest.py
git commit -m "Projects have a home on the server: a folder of .openkerf files and the name of the open one

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: The routes, the flag and the snapshot

**Files:**
- Modify: `api/openkerf_api/server.py` (routes near `/api/project/*` at `:1026-1078`; snapshot at `:850-857`; `ApiServer.__init__` near `:283`; the write guard list `write = [Depends(require_write)]` at `:748`)
- Modify: `api/openkerf_api/plugin.py` (console options at `:38-75`; the `ApiServer(...)` call at `:118`)
- Modify: `api/tests/conftest.py` (the `setdefault` line)
- Modify: `api/tests/test_projects.py` (route tests appended)

**Interfaces:**
- Consumes: `Projects` from Task 1.
- Produces: `GET /api/projects` → `list[dict]`; `POST /api/projects/{name}?overwrite=0|1` → entry; `POST /api/projects/{name}/open` → import result + `project`; `POST /api/projects/{name}/rename` body `{"name"}` → entry; `DELETE /api/projects/{name}` → `{"ok": true}`; `GET /api/design` snapshot gains `"project": {"name", "saved_at"}`; `POST /api/project/new` clears the name; `POST /api/project/open` adopts; `GET /api/project/export.openkerf` names the file `<current>.openkerf` when there is one. `ApiServer(kernel, ..., projects=None)`; console flag `-r/--projects`.

- [ ] **Step 1: Write the failing route tests** (append to `api/tests/test_projects.py`)

```python
def _headers(api_server):
    return {"X-OpenKerf-Token": api_server.token}


def test_the_routes_save_list_open_rename_and_delete(api, api_server):
    _draw_two_rects(api)
    h = _headers(api_server)
    saved = api.post("/api/projects/Kastje", headers=h)
    assert saved.status_code == 200, saved.text
    assert saved.json()["name"] == "Kastje"
    assert api.get("/api/design").json()["project"] == {"name": "Kastje", "saved_at": saved.json()["saved_at"]}

    listed = api.get("/api/projects").json()
    assert [e["name"] for e in listed] == ["Kastje"] and listed[0]["current"] is True

    api.post("/api/project/new", headers=h)
    assert api.get("/api/design").json()["project"]["name"] is None

    opened = api.post("/api/projects/Kastje/open", headers=h)
    assert opened.status_code == 200 and opened.json()["project"]["name"] == "Kastje"
    assert len(api.get("/api/design").json()["elements"]) == 2

    renamed = api.post("/api/projects/Kastje/rename", json={"name": "Doos"}, headers=h)
    assert renamed.status_code == 200 and renamed.json()["name"] == "Doos"
    assert api.get("/api/design").json()["project"]["name"] == "Doos"

    gone = api.delete("/api/projects/Doos", headers=h)
    assert gone.status_code == 200
    assert api.get("/api/projects").json() == []
    assert api.get("/api/design").json()["project"]["name"] is None


def test_the_routes_refuse_with_a_code_in_the_header(api, api_server):
    _draw_two_rects(api)
    h = _headers(api_server)
    api.post("/api/projects/A", headers=h)
    api.post("/api/projects/B", headers=h)
    refused = api.post("/api/projects/A", headers=h)
    assert refused.status_code == 409
    assert refused.headers["X-OpenKerf-Error"] == "project.exists"
    assert api.post("/api/projects/A?overwrite=1", headers=h).status_code == 200
    bad = api.post("/api/projects/..%2Fx", headers=h)
    assert bad.status_code in (400, 404, 409, 422)
    missing = api.post("/api/projects/Nobody/open", headers=h)
    assert missing.status_code == 409 and missing.headers["X-OpenKerf-Error"] == "project.missing"


def test_an_upload_becomes_a_project_and_the_export_carries_its_name(api, api_server, tmp_path):
    _draw_two_rects(api)
    h = _headers(api_server)
    api.post("/api/projects/Board", headers=h)
    exported = api.get("/api/project/export.openkerf")
    assert exported.status_code == 200
    assert 'filename="Board.openkerf"' in exported.headers["content-disposition"]
    uploaded = api.post(
        "/api/project/open",
        files={"file": ("Board.openkerf", exported.content, "application/zip")},
        headers=h,
    )
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["project"]["name"] == "Board 2"
    assert sorted(e["name"] for e in api.get("/api/projects").json()) == ["Board", "Board 2"]


def test_every_project_route_that_writes_is_guarded(api):
    _draw_two_rects(api)
    for method, path in (
        ("post", "/api/projects/X"),
        ("post", "/api/projects/X/open"),
        ("post", "/api/projects/X/rename"),
        ("delete", "/api/projects/X"),
    ):
        response = getattr(api, method)(path, json={"name": "Y"}) if method == "post" else api.delete(path)
        assert response.status_code == 401, (method, path, response.status_code)
```

The refusal status: read `refuse()` in `server.py` (near `manage`, `:770`) for the status code a `DesignError` maps to; the tests above say 409 — change them to what `refuse()` really answers, and say so in the report. The guard test assumes the test server is bound so that a token is required; if the suite's `api` fixture is loopback-only and never 401s, read how `test_write_actions.py` tests the guard and follow it.

- [ ] **Step 2: Run them and see them fail**

Run: `meerk40t/.venv/bin/python -m pytest api/tests/test_projects.py -q -k routes`
Expected: 404s — the routes do not exist.

- [ ] **Step 3: Wire the server**

In `ApiServer.__init__` (near `:283`, after `self.library = ...`, `self.sheets`, `self.document` exist):

```python
        from .projects import Projects

        self.projects = Projects(
            Path(projects).expanduser() if projects else Path(self.library.path).parent / "projects",
            drawing=self.drawing,
            library=self.library,
            sheets=self.sheets,
            document=self.document,
        )
```

Add `projects=None` to the `__init__` signature beside `library_path`/`operations` (read the exact parameter names at `:260-300`).

Routes, beside the existing project routes:

```python
        @app.get("/api/projects")
        def project_list():
            """Every project in the folder, newest first, the open one marked."""
            return self.projects.list()

        @app.post("/api/projects/{name}", dependencies=write)
        def project_save(name: str, overwrite: bool = False):
            return manage(self.projects.save, name, overwrite)

        @app.post("/api/projects/{name}/open", dependencies=write)
        def project_open(name: str):
            return manage(self.projects.open, name)

        @app.post("/api/projects/{name}/rename", dependencies=write)
        def project_rename(name: str, body: dict):
            return manage(self.projects.rename, name, str(body.get("name") or ""))

        @app.delete("/api/projects/{name}", dependencies=write)
        def project_delete(name: str):
            manage(self.projects.delete, name)
            return {"ok": True}
```

Change the three existing routes:

```python
        # in new_project (:1026+), after the design is emptied:
            self.projects.forget()

        # export_project (:1056):
        def export_project(filename: str | None = None):
            """The design plus its library context in one file, named after the project."""
            from fastapi.responses import FileResponse

            wanted = filename or f"{self.projects.current or 'project'}.openkerf"
            path = manage(self.drawing.export_project, self.library, wanted, self.sheets)
            self.document.clean()
            return FileResponse(path, media_type="application/zip", filename=path.name)

        # open_project (:1069): replace the manage(import_project...) call with
            result = manage(self.projects.adopt, target, file.filename or "project.openkerf")
            return result
```

Snapshot (`:856`):

```python
            snapshot["dirty"] = self.document.dirty
            snapshot["project"] = self.projects.state()
```

`plugin.py`: a console option beside `-o`:

```python
        @kernel.console_option(
            "projects",
            "r",
            type=str,
            help=_("folder for the projects saved on this server (its own folder for testing)"),
        )
```

add `projects=None` to `openkerf_api(...)`'s parameters and `projects=projects` to the `ApiServer(...)` call.

`conftest.py`: add `kwargs.setdefault("projects", folder)` to the fixture from Task 1.

- [ ] **Step 4: Run the tests and see them pass**

Run: `meerk40t/.venv/bin/python -m pytest api/tests/test_projects.py api/tests/test_write_actions.py -q`
Expected: all pass, including `test_write_actions.py`'s check that every write route carries `require_write`. Then the whole suite.

- [ ] **Step 5: Check the fence by hand**

Run the suite once with `ls ~/Library/Application\ Support/MeerK40t/projects 2>/dev/null; ls "$(dirname "$(meerk40t/.venv/bin/python -c 'from meerk40t.kernel.functions import get_safe_path; print(get_safe_path("MeerK40t"))')")"` before and after: no `projects/` folder may appear beside the developer's library. Put the result in the report.

- [ ] **Step 6: Commit**

```bash
git add api/openkerf_api/server.py api/openkerf_api/plugin.py api/tests/conftest.py api/tests/test_projects.py
git commit -m "Five routes for the projects on the server, a flag for their folder, and the open project in the snapshot

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: The frontend store, the name rule and the verbs

**Files:**
- Create: `frontend/src/lib/projects.svelte.ts`
- Modify: `frontend/src/lib/actions.ts` (`KEYS` at `:82`; `Handlers` at `:253`; a new `projectActions`)
- Modify: `frontend/src/lib/i18n/en.ts`, `frontend/src/lib/i18n/nl.ts`
- Create: `frontend/tests/projects.test.ts`
- Modify: `frontend/tests/actions.test.ts` (only if it enumerates registries by name — read `:300-310`)

**Interfaces:**
- Consumes: routes from Task 2; `writeRefusal(ctx)` (`actions.ts:338`); the token in `localStorage['openkerf.token']` (see `control.svelte.ts:13`).
- Produces: `cleanName(raw): string`; `class ProjectsStore` exported as `projects` with `list: ProjectEntry[]`, `current: {name, saved_at} | null`, `dirty: boolean` (fed from the design store), `load()`, `save(name?, overwrite?)`, `open(name)`, `rename(old, new)`, `remove(name)`, `error: string | null`; `projectActions(ctx, h): Action[]` with ids `project.new`, `project.open`, `project.save`, `project.saveAs`, `project.download`, `project.upload`; `KEYS.open = 'mod+o'`, `KEYS.save = 'mod+s'`, `KEYS.saveAs = 'mod+shift+s'`; `Handlers` gains `newProject`, `openProjects`, `saveProject`, `saveProjectAs`, `downloadProject`, `uploadProject`.

- [ ] **Step 1: Write the failing tests**

```ts
// frontend/tests/projects.test.ts
/**
 * Projects on the server: the name rule is the server's rule, and the menu is in order.
 *
 * The name rule lives twice — `projects.svelte.ts:cleanName` and
 * `openkerf_api/projects.py:clean_name` — so the two are run against each other, the
 * way `upload-name.test.ts` does for the machine name. Without a Python the comparison
 * is skipped, not faked.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { cleanName } from '../src/lib/projects.svelte.ts';
import { projectActions, KEYS, type Context, type Handlers } from '../src/lib/actions.ts';

const here = dirname(fileURLToPath(import.meta.url));
const ROOT = join(here, '..', '..');

const NAMES = ['  Kastje groot ', 'a/b', '../etc', '.hidden', 'naïve', 'x'.repeat(80), '   ', 'box_1-2.v3', 'Doos: nr. 1?'];

test('the name rule on the screen', () => {
	assert.equal(cleanName('  Kastje groot '), 'Kastje groot');
	assert.equal(cleanName('a/b'), 'ab');
	assert.equal(cleanName('.hidden'), 'hidden');
	assert.equal(cleanName('x'.repeat(80)).length, 60);
	assert.equal(cleanName('   '), '');
});

test('the screen and the server cut a project name the same way', (t) => {
	const python = join(ROOT, 'meerk40t', '.venv-nogui', 'bin', 'python');
	if (!existsSync(python)) {
		if (process.env.OK_REQUIRE_PYTHON) assert.fail(`no interpreter at ${python} and OK_REQUIRE_PYTHON is set`);
		return t.skip(`no interpreter at ${python}; the first test still holds`);
	}
	const script =
		'import json,sys;sys.path.insert(0,"api");' +
		'from openkerf_api.projects import clean_name;' +
		'print(json.dumps([clean_name(n) for n in json.loads(sys.argv[1])]))';
	const theirs = JSON.parse(execFileSync(python, ['-c', script, JSON.stringify(NAMES)], { cwd: ROOT, encoding: 'utf8' }));
	assert.deepEqual(NAMES.map(cleanName), theirs);
});

const CTX = {
	count: 0, inGroup: false, lockedCount: 0, isImage: false, isText: false, isCropped: false, filled: false,
	bridges: { carries: false, has: false }, clipboard: 0, busy: false, offline: false, may: true,
	layers: [], sheets: [], snap: true, layerNumbers: false, empty: false,
	splittable: { shapes: 0, pieces: 0 }, under: [], columns: [], once: false
} as unknown as Context;
const H = new Proxy({}, { get: () => () => {} }) as Handlers;

test('the project menu is in order and its verbs carry their shortcuts', () => {
	const ids = projectActions(CTX, H).map((a) => a.id);
	assert.deepEqual(ids, ['project.new', 'project.open', 'project.save', 'project.saveAs', 'project.download', 'project.upload']);
	assert.equal(KEYS.open, 'mod+o');
	assert.equal(KEYS.save, 'mod+s');
	assert.equal(KEYS.saveAs, 'mod+shift+s');
});

test('without a token every project verb that writes says why', () => {
	const off = projectActions({ ...CTX, may: false }, H);
	for (const a of off) {
		if (a.id === 'project.download') assert.equal(a.off, undefined, 'downloading only reads');
		else assert.ok(a.off, `${a.id} is silent about the missing token`);
	}
});
```

- [ ] **Step 2: Run them and see them fail**

Run: `cd frontend && node --test tests/projects.test.ts`
Expected: fails to import `cleanName` / `projectActions`.

- [ ] **Step 3: The store**

```ts
// frontend/src/lib/projects.svelte.ts
/**
 * Projects kept on the server, and which one is open.
 *
 * One store for four surfaces: the project button in the top bar (name and the unsaved
 * dot), the menu behind it, the keyboard, and the Projects window. Each of them reads
 * this and none of them keeps a copy of the rule.
 */
import { apiError } from './i18n/core.ts';

export type ProjectEntry = { name: string; saved_at: string; bytes: number; current: boolean };
export type CurrentProject = { name: string | null; saved_at: string | null };

export const MAX_NAME = 60;

/** The same rule as `openkerf_api/projects.py:clean_name`, held to it by a test. */
export function cleanName(raw: string): string {
	const kept = (raw ?? '').replace(/[^A-Za-z0-9 ._-]/g, '').replace(/^\.+/, '').trim();
	return kept.slice(0, MAX_NAME).trim();
}

function token(): string {
	return typeof localStorage === 'undefined' ? '' : (localStorage.getItem('openkerf.token') ?? '');
}
function headers(json = false): Record<string, string> {
	const h: Record<string, string> = {};
	if (json) h['Content-Type'] = 'application/json';
	const t = token();
	if (t) h['X-OpenKerf-Token'] = t;
	return h;
}

export class ProjectsStore {
	list = $state<ProjectEntry[]>([]);
	current = $state<CurrentProject>({ name: null, saved_at: null });
	busy = $state(false);
	error = $state<string | null>(null);

	/** Called with every design snapshot, which carries `project`. */
	follow(snapshot: { project?: CurrentProject } | null) {
		if (snapshot?.project) this.current = snapshot.project;
	}

	async load() {
		const response = await fetch('/api/projects');
		if (response.ok) this.list = await response.json();
	}

	private async run(path: string, init: RequestInit): Promise<Response | null> {
		this.busy = true;
		this.error = null;
		try {
			const response = await fetch(path, init);
			if (!response.ok) {
				this.error = await apiError(response);
				return null;
			}
			await this.load();
			return response;
		} finally {
			this.busy = false;
		}
	}

	async save(name: string, overwrite = false): Promise<ProjectEntry | null> {
		const response = await this.run(
			`/api/projects/${encodeURIComponent(name)}${overwrite ? '?overwrite=1' : ''}`,
			{ method: 'POST', headers: headers() }
		);
		if (!response) return null;
		const entry = (await response.json()) as ProjectEntry;
		this.current = { name: entry.name, saved_at: entry.saved_at };
		return entry;
	}

	async open(name: string): Promise<boolean> {
		return (await this.run(`/api/projects/${encodeURIComponent(name)}/open`, { method: 'POST', headers: headers() })) !== null;
	}

	async rename(from: string, to: string): Promise<boolean> {
		return (
			(await this.run(`/api/projects/${encodeURIComponent(from)}/rename`, {
				method: 'POST',
				headers: headers(true),
				body: JSON.stringify({ name: to })
			})) !== null
		);
	}

	async remove(name: string): Promise<boolean> {
		return (await this.run(`/api/projects/${encodeURIComponent(name)}`, { method: 'DELETE', headers: headers() })) !== null;
	}

	/** Whether saving under this name would replace another project. */
	taken(name: string): boolean {
		return this.list.some((e) => e.name === name && e.name !== this.current.name);
	}
}

export const projects = new ProjectsStore();
```

Read `apiError` in `i18n/core.ts`: it turns a refused response into the sentence in the reader's language through the `X-OpenKerf-Error` header; if its signature differs (takes the response, or the header and the text), call it the way `library.svelte.ts` does.

- [ ] **Step 4: The verbs**

In `actions.ts`: `KEYS` gains `open: 'mod+o', save: 'mod+s', saveAs: 'mod+shift+s'`. `Handlers` gains:

```ts
	newProject: () => void;
	openProjects: () => void;
	saveProject: () => void;
	saveProjectAs: () => void;
	downloadProject: () => void;
	uploadProject: () => void;
```

and, beside `alignActions`:

```ts
/**
 * The project menu: what you do with the whole of the work.
 *
 * Saving and opening happen on the server since the round of 4 September 2026: the box
 * beside the laser has the data volume, the tablet in front of it has no file system
 * worth the name. Download and Upload are the way to another device, and stand below
 * a separator for that reason. Downloading only reads, so it is never off for a token.
 */
export function projectActions(ctx: Context, h: Handlers): Action[] {
	const off = mayWrite(ctx);
	return [
		{ id: 'project.new', label: t('topbar.project.new'), icon: 'new', off, run: h.newProject },
		{ id: 'project.open', label: t('topbar.project.open'), icon: 'folder', key: K('open'), off, run: h.openProjects },
		{ id: 'project.save', label: t('topbar.project.save'), icon: 'save', key: K('save'), off, run: h.saveProject },
		{ id: 'project.saveAs', label: t('topbar.project.saveAs'), icon: 'save', key: K('saveAs'), off, run: h.saveProjectAs },
		{ id: 'project.download', label: t('topbar.project.download'), icon: 'download', explain: t('topbar.project.hint'), run: h.downloadProject },
		{ id: 'project.upload', label: t('topbar.project.upload'), icon: 'upload', off, run: h.uploadProject }
	];
}
```

Check which icon names `ArrangeIcon.svelte` knows; use existing ones or add the four (folder, save, download, upload, new) as small 24-px paths there. The separator between the fourth and fifth row is drawn by the menu (a `'separator'` in a `Group`, see `Menu` type at `actions.ts:60-62`) — `TopBar` builds `[{ items: [...first four, 'separator', ...last two] }]`.

`en.ts` (beside `'topbar.project.save'` at `:44`):

```ts
	'topbar.project.saveAs': 'Save as…',
	'topbar.project.download': 'Download',
	'topbar.project.upload': 'Upload…',
	'topbar.project.untitled': 'untitled',
	'topbar.project.name': 'Project · {name}',
	'topbar.project.unsaved': 'Unsaved changes',
	'projects.title': 'Projects',
	'projects.saveAs.title': 'Save as…',
	'projects.empty': 'No projects on this server yet. Save the work under a name and it appears here.',
	'projects.column.name': 'Name',
	'projects.column.saved': 'Saved',
	'projects.open': 'Open',
	'projects.current': 'open now',
	'projects.rename': 'Rename…',
	'projects.rename.ask': 'New name for {name}',
	'projects.delete': 'Delete',
	'projects.delete.ask': 'Delete the project {name}? This cannot be undone.',
	'projects.name': 'Name',
	'projects.save': 'Save',
	'projects.overwrite.ask': 'There is already a project called {name}. Replace it?',
	'projects.overwrite': 'Replace',
	'unsaved.title': 'Unsaved changes',
	'unsaved.body': '{name} has changes that are not saved.',
	'unsaved.save': 'Save',
	'unsaved.discard': 'Discard',
	'unsaved.leave': 'The work has changes that are not saved.',
	'reason.needsProjectName': 'Type a name first',
```

`nl.ts` gets each with a Dutch whole sentence (`'Opslaan als…'`, `'Downloaden'`, `'Uploaden…'`, `'naamloos'`, `'Project · {name}'`, `'Niet opgeslagen wijzigingen'`, `'Projecten'`, `'Nog geen projecten op deze server. Sla het werk onder een naam op en het verschijnt hier.'`, `'Naam'`, `'Opgeslagen'`, `'Openen'`, `'nu open'`, `'Hernoemen…'`, `'Nieuwe naam voor {name}'`, `'Verwijderen'`, `'Het project {name} verwijderen? Dit kan niet ongedaan worden gemaakt.'`, `'Naam'`, `'Opslaan'`, `'Er is al een project met de naam {name}. Vervangen?'`, `'Vervangen'`, `'Niet opgeslagen wijzigingen'`, `'{name} heeft wijzigingen die niet zijn opgeslagen.'`, `'Opslaan'`, `'Weggooien'`, `'Het werk heeft wijzigingen die niet zijn opgeslagen.'`, `'Typ eerst een naam'`). The i18n test (`frontend/tests/i18n.test.ts` or wherever key parity is checked — grep `nl.ts` in `tests/`) must stay green.

- [ ] **Step 5: Run the tests and see them pass**

Run: `cd frontend && node --test tests/projects.test.ts tests/actions.test.ts` and the i18n parity test. Expected: all pass, the Python parity test included (the interpreter at `meerk40t/.venv-nogui/bin/python` exists on this machine).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/projects.svelte.ts frontend/src/lib/actions.ts frontend/src/lib/i18n/en.ts frontend/src/lib/i18n/nl.ts frontend/tests/projects.test.ts frontend/src/lib/components/ArrangeIcon.svelte
git commit -m "The project verbs, their shortcuts and the name rule, held to the server's

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: The top bar, the window and the question

**Files:**
- Modify: `frontend/src/lib/components/TopBar.svelte` (the project button and menu at `:296-400`; `openProjectMenu` at `:111`)
- Create: `frontend/src/lib/components/Projects.svelte`
- Create: `frontend/src/lib/components/UnsavedChanges.svelte`
- Modify: `frontend/src/routes/+page.svelte` (`Replacement`, `maybeAskFirst`, `runIt`, `openProject`, `newProject` at `:199-400`; the `<TopBar>` props at `:1420` and `:1452`; keyboard handling where `KEYS` are dispatched)
- Modify: `frontend/src/lib/design.svelte.ts` (call `projects.follow(snapshot)` in `load()` at `:817`)
- Create: `frontend/tests/projects-flow.test.ts`

**Interfaces:**
- Consumes: `projects` store, `projectActions`, `cleanName` (Task 3); `Dialog` (`Dialog.svelte`: props `title`, `open` bindable, `width`, children); `Menu` (`Menu.svelte`: `menu`, `x`, `y`, `upward`, `onClose`); the design store's `dirty` getter (`design.svelte.ts:539`) and `isEmpty`.
- Produces: `<Projects bind:open mode="open" | "saveAs" onDone={(name) => ...}>`; `<UnsavedChanges bind:open name onSave onDiscard>`; TopBar props `projectName: string | null`, `dirty: boolean`, `menu: Menu` (built from `projectActions`).

- [ ] **Step 1: Write the failing server-backed test**

```ts
// frontend/tests/projects-flow.test.ts
/**
 * Save as, find it, open it, and a Cancel that changes nothing — against a live server.
 *
 *   OK_BASE=http://127.0.0.1:8184 node --test frontend/tests/projects-flow.test.ts
 *
 * Skips without a reachable server (`OK_REQUIRE_SERVER=1` turns that into a failure).
 * The server must have been started with `-r <its own folder>`; this test writes
 * projects. Nothing here touches a machine.
 */
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { chromium, type Browser, type Page } from 'playwright';
import { noServer } from './no-server.ts';

const BASE = process.env.OK_BASE ?? 'http://127.0.0.1:8184';
let reachable = false;
let browser: Browser | null = null;
let page: Page;
const NAME = `Flow ${Date.now() % 100000}`;

before(async () => {
	reachable = await fetch(`${BASE}/api/health`, { signal: AbortSignal.timeout(2000) }).then((r) => r.ok).catch(() => false);
	if (!reachable) return;
	browser = await chromium.launch();
	page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
	await fetch(`${BASE}/api/project/new`, { method: 'POST' });
	await fetch(`${BASE}/api/design/elements`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify({ type: 'rect', x_mm: 20, y_mm: 20, width_mm: 30, height_mm: 30 })
	});
});
after(async () => {
	await browser?.close();
});

async function openProjectMenu() {
	await page.locator('button.project-button').click();
	await page.waitForSelector('[role="menu"]', { timeout: 5000 });
}

test('Save as… puts the work in the list under its name, and the top bar says so', async (t) => {
	if (!reachable) return noServer(t, BASE);
	await page.goto(`${BASE}/?tab=design`, { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(2500);
	await openProjectMenu();
	await page.getByRole('menuitem', { name: 'Save as…' }).click();
	const field = page.locator('[role="dialog"] input.project-name');
	await field.waitFor({ timeout: 5000 });
	await field.fill(NAME);
	await page.locator('[role="dialog"] button.save').click();
	await page.waitForTimeout(1500);
	const listed = (await (await fetch(`${BASE}/api/projects`)).json()) as { name: string; current: boolean }[];
	const mine = listed.find((e) => e.name === NAME);
	assert.ok(mine, `${NAME} is not in the list`);
	assert.equal(mine.current, true);
	assert.match(await page.locator('button.project-button').innerText(), new RegExp(NAME));
});

test('Open… lists it, and Cancel in the question leaves the work alone', async (t) => {
	if (!reachable) return noServer(t, BASE);
	await fetch(`${BASE}/api/design/elements`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify({ type: 'rect', x_mm: 60, y_mm: 20, width_mm: 10, height_mm: 10 })
	});
	await page.reload({ waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(2500);
	const beforeCount = (await (await fetch(`${BASE}/api/design`)).json()).elements.length;
	await openProjectMenu();
	await page.getByRole('menuitem', { name: 'Open…' }).click();
	await page.waitForSelector('[role="dialog"]', { timeout: 5000 });
	await page.locator(`[role="dialog"] .row:has-text("${NAME}") button.open`).click();
	// The work is dirty (a rect was added after the save), so the question comes.
	await page.getByRole('button', { name: 'Cancel' }).click();
	await page.waitForTimeout(800);
	const afterCount = (await (await fetch(`${BASE}/api/design`)).json()).elements.length;
	assert.equal(afterCount, beforeCount, 'Cancel changed the design');
});
```

The guard test's exact selectors (`input.project-name`, `button.save`, `.row`, `button.open`) are the contract for Step 3's markup; keep them.

- [ ] **Step 2: Run it and see it fail**

Build and start a fenced server (see Global Constraints), then:
Run: `cd frontend && OK_BASE=http://127.0.0.1:8184 node --test tests/projects-flow.test.ts`
Expected: fails at the `Save as…` menu item (not there yet).

- [ ] **Step 3: The two dialogs**

```svelte
<!-- frontend/src/lib/components/Projects.svelte -->
<script lang="ts">
	/**
	 * The Projects window: what is on the server, and — in `saveAs` mode — the name to
	 * save the work under.
	 *
	 * One window for both because they show the same list: choosing a row while saving
	 * fills the field, and an existing name asks before it is replaced. The name rule is
	 * applied while you type, as the machine-name field does it, so what is in the box
	 * is what the folder gets.
	 */
	import Dialog from './Dialog.svelte';
	import Menu from './Menu.svelte';
	import { t } from '$lib/i18n/index.svelte';
	import { projects, cleanName, MAX_NAME, type ProjectEntry } from '$lib/projects.svelte';
	import type { Menu as MenuList } from '$lib/actions';

	let {
		open = $bindable(),
		mode = 'open',
		onOpen,
		onSaved
	}: {
		open: boolean;
		mode?: 'open' | 'saveAs';
		/** The user chose a row to open; the page asks about unsaved work first. */
		onOpen?: (name: string) => void;
		onSaved?: (entry: ProjectEntry) => void;
	} = $props();

	let typed = $state('');
	let askOverwrite = $state<string | null>(null);
	let rowMenu = $state<{ list: MenuList; x: number; y: number } | null>(null);

	$effect(() => {
		if (open) {
			projects.load();
			typed = projects.current.name ?? '';
			askOverwrite = null;
		}
	});

	const saveOff = $derived(
		projects.busy ? t('reason.busy') : cleanName(typed) === '' ? t('reason.needsProjectName') : undefined
	);
	const when = (iso: string) =>
		new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(iso));

	function nameTyped(event: Event & { currentTarget: HTMLInputElement }) {
		const field = event.currentTarget;
		const kept = cleanName(field.value);
		if (kept !== field.value.trim()) {
			const at = field.selectionStart ?? kept.length;
			field.value = kept;
			field.setSelectionRange(Math.min(at, kept.length), Math.min(at, kept.length));
		}
		typed = kept;
	}

	async function save(overwrite = false) {
		const name = cleanName(typed);
		if (!name) return;
		if (!overwrite && projects.taken(name)) {
			askOverwrite = name;
			return;
		}
		const entry = await projects.save(name, overwrite);
		if (entry) {
			askOverwrite = null;
			open = false;
			onSaved?.(entry);
		}
	}

	function menuFor(entry: ProjectEntry, at: HTMLElement) {
		const box = at.getBoundingClientRect();
		rowMenu = {
			x: box.right,
			y: box.bottom,
			list: [
				{
					items: [
						{
							id: 'project.rename',
							label: t('projects.rename'),
							run: async () => {
								const next = cleanName(window.prompt(t('projects.rename.ask', { name: entry.name }), entry.name) ?? '');
								if (next && next !== entry.name) await projects.rename(entry.name, next);
							}
						},
						{
							id: 'project.delete',
							label: t('projects.delete'),
							danger: true,
							run: async () => {
								if (window.confirm(t('projects.delete.ask', { name: entry.name }))) await projects.remove(entry.name);
							}
						}
					]
				}
			]
		};
	}
</script>

<Dialog title={mode === 'saveAs' ? t('projects.saveAs.title') : t('projects.title')} bind:open width="560px">
	{#if projects.error}
		<p class="error" role="alert">{projects.error}</p>
	{/if}
	{#if projects.list.length === 0}
		<p class="hint">{t('projects.empty')}</p>
	{:else}
		<div class="rows" role="list">
			<div class="head"><span>{t('projects.column.name')}</span><span>{t('projects.column.saved')}</span><span></span></div>
			{#each projects.list as entry (entry.name)}
				<div
					class="row"
					class:current={entry.current}
					role="listitem"
					ondblclick={() => (mode === 'saveAs' ? (typed = entry.name) : onOpen?.(entry.name))}
				>
					<span class="name">{entry.name}{#if entry.current} <em>{t('projects.current')}</em>{/if}</span>
					<span class="when">{when(entry.saved_at)}</span>
					<span class="verbs">
						{#if mode === 'open'}
							<button class="btn open" onclick={() => onOpen?.(entry.name)}>{t('projects.open')}</button>
						{:else}
							<button class="btn" onclick={() => (typed = entry.name)}>{t('projects.name')}</button>
						{/if}
						<button class="btn more" aria-haspopup="menu" aria-label={t('common.more')} onclick={(e) => menuFor(entry, e.currentTarget as HTMLElement)}>⋮</button>
					</span>
				</div>
			{/each}
		</div>
	{/if}
	{#if mode === 'saveAs'}
		<div class="saveas">
			<label>
				<span>{t('projects.name')}</span>
				<input class="project-name" type="text" maxlength={MAX_NAME} value={typed} oninput={nameTyped} />
			</label>
			<button class="btn primary save" disabled={Boolean(saveOff)} title={saveOff} onclick={() => save(false)}>{t('projects.save')}</button>
		</div>
		{#if askOverwrite}
			<p class="ask" role="alert">
				{t('projects.overwrite.ask', { name: askOverwrite })}
				<button class="btn danger" onclick={() => save(true)}>{t('projects.overwrite')}</button>
				<button class="btn" onclick={() => (askOverwrite = null)}>{t('common.cancel')}</button>
			</p>
		{/if}
	{/if}
</Dialog>
{#if rowMenu}
	<Menu menu={rowMenu.list} x={rowMenu.x} y={rowMenu.y} onClose={() => (rowMenu = null)} />
{/if}

<style>
	.rows { display: grid; gap: 2px; }
	.head, .row { display: grid; grid-template-columns: 1fr auto auto; gap: var(--space-3); align-items: center; padding: var(--space-2) var(--space-3); }
	.head { font-size: var(--text-xs); color: var(--text-2); text-transform: uppercase; letter-spacing: 0.04em; }
	.row { border-radius: var(--radius-field); min-height: 44px; }
	.row:hover { background: var(--surface-2); }
	.row.current .name { font-weight: 600; }
	.row em { font-style: normal; color: var(--text-2); font-size: var(--text-xs); margin-left: var(--space-2); }
	.when { color: var(--text-2); font-size: var(--text-sm); white-space: nowrap; }
	.verbs { display: flex; gap: var(--space-2); }
	.saveas { display: flex; gap: var(--space-2); align-items: end; margin-top: var(--space-4); }
	.saveas label { display: grid; gap: 4px; flex: 1; }
	.saveas input { min-height: 44px; padding: 0 var(--space-3); border: 1px solid var(--line); border-radius: var(--radius-field); font: inherit; }
	.ask { display: flex; gap: var(--space-2); align-items: center; flex-wrap: wrap; margin-top: var(--space-3); }
	.hint, .error { color: var(--text-2); }
	.error { color: var(--danger, #b3261e); }
</style>
```

Check `t()`'s signature for placeholders (`t('key', { name })`) in `i18n/index.svelte.ts` and that `common.more` exists (else add `'common.more': 'More'` / `'Meer'`). If the repo's convention forbids `window.prompt`/`window.confirm` (grep for `confirm(` in components), replace Rename and Delete with two small in-window rows using the same `ask` pattern as the overwrite question.

```svelte
<!-- frontend/src/lib/components/UnsavedChanges.svelte -->
<script lang="ts">
	/**
	 * The question in front of New, Open and Upload when the work is not saved.
	 *
	 * Three answers and nothing else: Save, Discard, Cancel. Save on an untitled project
	 * goes through Save as… first, which the page arranges; this window only asks.
	 */
	import Dialog from './Dialog.svelte';
	import { t } from '$lib/i18n/index.svelte';
	let {
		open = $bindable(),
		name,
		onSave,
		onDiscard
	}: { open: boolean; name: string | null; onSave: () => void; onDiscard: () => void } = $props();
</script>

<Dialog title={t('unsaved.title')} bind:open width="420px">
	<p>{t('unsaved.body', { name: name ?? t('topbar.project.untitled') })}</p>
	<div class="answers">
		<button class="btn primary" onclick={() => { open = false; onSave(); }}>{t('unsaved.save')}</button>
		<button class="btn danger" onclick={() => { open = false; onDiscard(); }}>{t('unsaved.discard')}</button>
		<button class="btn" onclick={() => (open = false)}>{t('common.cancel')}</button>
	</div>
</Dialog>

<style>
	.answers { display: flex; gap: var(--space-2); justify-content: flex-end; margin-top: var(--space-4); }
</style>
```

- [ ] **Step 4: The top bar**

In `TopBar.svelte`: props gain `projectName: string | null`, `dirty: boolean`, `projectMenu: Menu`. The button text becomes:

```svelte
		<span class="btn-label">{t('topbar.project.name', { name: projectName ?? t('topbar.project.untitled') })}</span>
		{#if dirty}<span class="dot" title={t('topbar.project.unsaved')} aria-label={t('topbar.project.unsaved')}>●</span>{/if}
```

with the tooltip `title` carrying the same name for the narrow case. Replace the hand-built `.projectmenu` rows with `<Menu menu={projectMenu} x={projectPos.x} y={projectPos.y} onClose={() => (projectOpen = false)} />` so the rows, their reasons and their shortcuts come from `projectActions`. Keep the hidden `<input type="file">` for Upload…: the `project.upload` action's handler on the page clicks it (pass a `bind:this` up, or keep the input in the page and have the handler click it). Remove `onOpenProject`/`onNewProject` props once the page drives everything through handlers.

- [ ] **Step 5: The page**

In `+page.svelte`:

- Import `projects` and the two dialogs. `Replacement` becomes
  `{ kind: 'project'; file: File } | { kind: 'fresh' } | { kind: 'server'; name: string }`, and `runIt` opens a server project with `await projects.open(name)` followed by the same reloads as `laadProject`.
- `maybeAskFirst` keeps its "is there work" check; when `design.dirty`, instead of running, it sets `unsavedOpen = true` with `pending = action`. `UnsavedChanges`'s `onDiscard` runs `pending`; `onSave` calls `saveProject()` (below) and then runs `pending` when the save succeeded.
- Handlers for `projectActions`:

```ts
	let projectsOpen = $state(false);
	let projectsMode = $state<'open' | 'saveAs'>('open');
	let unsavedOpen = $state(false);
	let afterSave: (() => Promise<void>) | null = null;

	async function saveProject() {
		if (projects.current.name) {
			const entry = await projects.save(projects.current.name);
			if (entry) await afterSave?.();
			afterSave = null;
			return;
		}
		saveProjectAs();
	}
	function saveProjectAs() {
		projectsMode = 'saveAs';
		projectsOpen = true;
	}
	function openProjects() {
		projectsMode = 'open';
		projectsOpen = true;
	}
	function downloadProject() {
		const a = document.createElement('a');
		a.href = '/api/project/export.openkerf';
		a.download = `${projects.current.name ?? 'project'}.openkerf`;
		a.click();
	}
	const projectHandlers = {
		newProject,
		openProjects,
		saveProject,
		saveProjectAs,
		downloadProject,
		uploadProject: () => fileInput?.click()
	};
```

  and the menu passed to the top bar: `[{ items: [...projectActions(ctx, h).slice(0, 4), 'separator', ...projectActions(ctx, h).slice(4)] }]` where `ctx` is the same context the other menus get and `h` is the page's handlers object extended with `projectHandlers`.
- Keyboard: where `KEYS` are matched (grep `comboOf(` in `+page.svelte`), route `open`, `save`, `saveAs` to the three handlers; `mod+s` must `preventDefault` so the browser does not offer to save the page.
- `beforeunload`: `$effect(() => { const warn = (e: BeforeUnloadEvent) => { if (design.dirty) { e.preventDefault(); e.returnValue = t('unsaved.leave'); } }; window.addEventListener('beforeunload', warn); return () => window.removeEventListener('beforeunload', warn); })`.
- `<Projects bind:open={projectsOpen} mode={projectsMode} onOpen={(name) => { projectsOpen = false; maybeAskFirst({ kind: 'server', name }); }} onSaved={async () => { await afterSave?.(); afterSave = null; }} />` and `<UnsavedChanges bind:open={unsavedOpen} name={projects.current.name} onSave={() => { afterSave = async () => { if (pending) await runIt(pending); pending = null; }; saveProject(); }} onDiscard={() => { if (pending) runIt(pending); pending = null; }} />`.
- `design.svelte.ts` `load()`: after the snapshot is stored, `projects.follow(snapshot)`.

- [ ] **Step 6: Build, run the flow test and the rest**

```bash
cd frontend && npm run build
# fenced server on 8184 with -r <tmp>/projects (see Global Constraints)
OK_BASE=http://127.0.0.1:8184 node --test tests/projects-flow.test.ts   # 2 pass
node --test tests/*.test.ts                                              # everything else green (server-backed ones skip or pass)
npx svelte-check --tsconfig ./tsconfig.json                              # no new errors beyond the 4 pre-existing
```

Also by hand in a browser against that server: save as, rename from the ⋮ menu, delete, `mod+s`, close the tab with unsaved work (the browser asks). Note what you saw in the report.

- [ ] **Step 7: Commit**

```bash
git add frontend/src frontend/tests/projects-flow.test.ts
git commit -m "The top bar names the open project; Open, Save and Save as… work on the server, and unsaved work is asked about

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: The handbook, the pictures and Docker

**Files:**
- Modify: `docs/getting-started.md` (section "Keeping the work", `:222-235`), `docs/reference.md` (key table near `:20`; the menu list), `docs/running-in-docker.md` (section "Where the data lives")
- Modify: `frontend/gauntlet/docs-shots.mjs` (scenes `47-projects.png`, `48-topbar-project.png` after scene 46)
- Modify: `deploy/entrypoint.sh` (`-r /data/projects`), `deploy/compose.yml` (the volume comment)
- Modify: `api/tests/test_projects.py` docstrings with the measured numbers

**Interfaces:**
- Consumes: everything above; the docs server recipe in `frontend/gauntlet/README.md:53-58` (add `-r /tmp/docs/lib/projects` to it).

- [ ] **Step 1: Write the failing docs test state**

Add to `docs/getting-started.md` under "### Keeping the work", replacing the two paragraphs about **Project → Save project** and **Export**:

```markdown
**Project → Save** writes the lot to the server, under the name in the top bar —
"Design, sheets, materials and machine profiles in one file." The first time, and every
time you choose **Save as…**, a window asks for the name; after that **Save** (⌘S) just
saves. The top bar reads "Project · {name}", and a dot in front of the name means there
are changes that are not saved.

**Project → Open…** (⌘O) shows every project on this server, newest first, the open one
marked "open now". Open one with its button or a double click. Behind ⋮ on a row sit
**Rename…** and **Delete**; deleting asks first: "Delete the project {name}? This cannot
be undone."

![The Projects window: the title Projects at the top, under it a list of rows with a name, when it was saved and an Open button, the first row marked open now, and a ⋮ button at the end of each row.](images/47-projects.png)

If the work has changes that are not saved, **New project**, **Open…** and **Upload…**
ask first — "{name} has changes that are not saved." — with **Save**, **Discard** and
**Cancel**. Closing the browser tab asks too.

Projects live in a folder on the server; in Docker that is `/data/projects` on the data
volume, so they survive a restart and an update and go with the volume's backup.

**Download** and **Upload…**, below the line in the same menu, are the way to another
device: the download is the same file the server keeps, and an uploaded file becomes a
project here under its own name.

![The top bar with the project button reading Project · Kastje, a dot in front of the name, and the menu under it open: New project, Open…, Save, Save as…, a line, Download, Upload….](images/48-topbar-project.png)

**Export** beside it does something narrower: "Save this sheet as SVG" — one
sheet, as a drawing, for another program. It does not carry the layers, the
material or the machine.
```

Run `cd frontend && node --test tests/docs.test.ts` → fails: the two pictures do not exist and `⌘S`/`⌘O` are not in the key table.

- [ ] **Step 2: The reference page**

In `docs/reference.md`'s key table add rows for `⌘O / Ctrl+O | Open a project | open`, `⌘S / Ctrl+S | Save the project | save`, `⌘⇧S / Ctrl+Shift+S | Save the project under another name | saveAs`, matching the table's existing shape. Where the page lists the Project menu, list the six rows in order with the separator noted.

- [ ] **Step 3: The pictures**

In `docs-shots.mjs`, after scene 46:

```js
/**
 * The Projects window with two projects in it, the open one marked.
 *
 * Seeded through the routes, not the mouse: the design on the bed is saved twice under
 * two names, so the list has something to show and the second is the open one.
 */
await scene('47-projects.png', '/?tab=design', { selector: DIALOG, pad: 0 }, async (page) => {
	await api('POST', '/api/projects/Box%20panels');
	await api('POST', '/api/projects/Kastje');
	await page.locator('button.project-button').click();
	await page.getByRole('menuitem', { name: 'Open…' }).click();
	await page.waitForSelector(`${DIALOG} .row`, { timeout: 10000 });
	await page.waitForTimeout(800);
});

/** The top bar naming the open project, with the menu open under it. */
await scene('48-topbar-project.png', '/?tab=design', { selector: '.topbar', pad: 0 }, async (page) => {
	await api('POST', '/api/design/elements', { type: 'rect', x_mm: 400, y_mm: 250, width_mm: 10, height_mm: 10 });
	await page.reload({ waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(2000);
	await page.locator('button.project-button').click();
	await page.waitForSelector('[role="menu"]', { timeout: 5000 });
	await page.waitForTimeout(600);
});
```

Check the top bar's root class (grep `class="topbar` or the `<header` in `TopBar.svelte`) and the `api()` helper's token handling in the script (it posts to write routes elsewhere, so it already sends one). Then `node gauntlet/docs-shots.mjs 47 && node gauntlet/docs-shots.mjs 48` against the docs server started with `-r`, look at both pictures, and fix the alt text to what is in them.

- [ ] **Step 4: Docker**

`deploy/entrypoint.sh`: the `--execute` string gains `-r /data/projects` before `-t`; a comment says the projects folder is on the volume. `deploy/compose.yml` volume comment gains "and the projects". `docs/running-in-docker.md`, "Where the data lives": add `/data/projects/` with one sentence, and the backup command already covers it. `frontend/gauntlet/README.md:53-58`: add `-r /tmp/docs/lib/projects` to the docs-server line.

- [ ] **Step 5: Measure, and write the numbers down**

Against the docs server: `curl -s -o /dev/null -w '%{time_total}\n' -X POST -H "X-OpenKerf-Token: $TOKEN" http://127.0.0.1:8092/api/projects/Timing` for the save, the same on `/open`, and `ls -l` the file for its size. Copy a file into the folder by hand and `GET /api/projects` to see it appear. Put the three numbers in the docstrings of `test_saving_writes_one_file_that_opens_to_the_same_design` and `test_the_list_is_read_from_the_folder_every_time`, and the size in the handbook sentence about the folder if it helps the reader ("a project of the handbook's design is N KB"). Rebuild the image (`docker build -f deploy/Dockerfile -t openkerf:dev .`), run `deploy/smoke.sh openkerf:dev`, then a compose run with `-r` in effect: save a project through the API, `docker compose restart`, list again — the project is still there. Numbers into the report and the Docker page.

- [ ] **Step 6: Run the docs test, the suites, and commit**

```bash
cd frontend && node --test tests/docs.test.ts && node --test tests/*.test.ts
cd .. && meerk40t/.venv/bin/python -m pytest api/tests -q
git add docs frontend/gauntlet deploy api/tests/test_projects.py
git commit -m "The handbook says how projects are kept on the server, with the pictures and the numbers; the image keeps them in /data/projects

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Self-review against the spec

- Folder of `.openkerf` files, name rule, current project, atomic save, adopt on upload, forget on new — Task 1 and 2.
- Five routes, guard, snapshot field, export named after the project, `-r` flag, conftest fence — Task 2.
- Store, `cleanName` parity, `projectActions`, shortcuts, `Handlers` — Task 3.
- Top bar name and dot, menu from actions, Projects window (open and save-as modes, row menu), Unsaved changes question, `beforeunload`, keyboard — Task 4.
- Server-backed flow test, name parity test, menu-order test — Tasks 3 and 4.
- Handbook pages, two pictures, reference tables, Docker page, entrypoint `-r /data/projects`, measurements — Task 5.
- Out of scope untouched: no versions, no folders, no sharing, no change to the file format.
