# Projects kept on the server — design

*4 September 2026. Agreed in conversation; the implementation plan follows from this.*

## Purpose

Today **Save project** is a download of one `.openkerf` file and **Open project…** is an
upload of one. That suits a laptop and not a box beside the laser: the person at the
tablet has no file system to speak of, and the box has a data volume that already
survives restarts and updates. Projects therefore get a home on the server, in a folder
of `.openkerf` files, and the app gets a **current project** with a name. Download and
upload stay as the second way, for moving a project to another device.

## Decisions

| Question | Decision | Why |
|---|---|---|
| Where projects live | A folder of `.openkerf` files, one per project, named after the project | The file already exists and holds everything (design, sheets, library context, series list). A folder is browsable, copyable with the volume, and needs no new database. No history or versions: one file per name. |
| Which folder | Default `projects/` beside the library file; in the image `/data/projects`, passed by `entrypoint.sh` through a new flag `-r/--projects <path>` | The API knows no container paths. The flag exists for the same reason as `-l` and `-o`: tests and the picture script must not write where the user lives. |
| A current project | Yes. The server remembers the name of the open project (or none) and sends it in the design snapshot beside `dirty` | Save writes to it without asking; Save as… asks a name. The top bar shows which project is open and whether it has unsaved changes. |
| Unsaved changes | New, Open and Upload ask first when `dirty`: save, discard or cancel. Closing the tab warns (`beforeunload`). | The autosave stays what it is — a safety net for a crash, offered at start — and does not become a substitute for saving. |
| Names | Letters, digits, spaces, hyphens, underscores and dots; at most 60 characters; no leading dot; nothing else. Applied while typing, and refused server-side with a sentence and a code | A name is a file name. The same rule on both sides, held to each other by a test, as the machine name is. |
| Overwrite | Saving under an existing name that is not the current project needs `overwrite=1`; the interface asks | A save must not silently replace another project. |
| Download and upload | Stay, as **Download** and **Upload…** below a separator in the same menu. An uploaded file becomes a project in the folder under its own (cleaned) name and is opened | Second way, not gone. |
| Verbs | In `frontend/src/lib/actions.ts` with shortcuts ⌘O (Open…), ⌘S (Save), ⌘⇧S (Save as…) and the reason each cannot run | The menu, the keyboard and the reference page read from one place. |

## The server

`api/openkerf_api/projects.py`, class `Projects(folder: Path, drawing, library, sheets, document)`:

- `list() -> list[dict]`: `{name, saved_at (ISO 8601), bytes, current: bool}` sorted by
  `saved_at` descending; reads the folder every time, so a file copied in by hand appears.
- `save(name, overwrite=False) -> dict`: validates the name; refuses `ProjectError(...,
  code="project.exists")` if a different project has that name and `overwrite` is false;
  writes through `drawing.export_project` into a temporary file in the same folder and
  `os.replace`s it over the target (atomic); sets `current = name`; calls
  `document.clean()`; returns the list entry.
- `open(name) -> dict`: `drawing.import_project(path, library, sheets)`; `current = name`;
  `document.clean()`; returns what `import_project` returns plus the entry.
- `rename(old, new)`, `delete(name)`: file operations with the same validation; renaming
  or deleting the current project updates or clears `current`.
- `adopt(path, name)`: used by the upload route — moves an uploaded file into the folder
  under a cleaned name (adding ` 2`, ` 3`… when taken) and opens it.
- `current: str | None`, cleared by **New project**.
- `clean_name(raw) -> str`: the rule above; returns `''` when nothing survives.

Refusals are `ProjectError` (a `DesignError` subclass) with codes `project.badName`,
`project.exists`, `project.missing`, `project.busy` (a job is running — same guard the
other write routes use).

Routes in `server.py`, all write routes except the first, all in `WRITE_ROUTES`:

- `GET /api/projects`
- `POST /api/projects/{name}?overwrite=0|1` — save
- `POST /api/projects/{name}/open`
- `POST /api/projects/{name}/rename` body `{"name": "..."}`
- `DELETE /api/projects/{name}`
- `POST /api/project/new` (existing) also clears `current`
- `POST /api/project/open` (existing upload) now ends in `projects.adopt(...)`
- `GET /api/project/export.openkerf` (existing) names the file after the current project

The design snapshot gains `"project": {"name": str | None, "saved_at": str | None}`.

`plugin.py` gains `-r/--projects` beside `-l` and `-o`; `ApiServer.__init__` takes
`projects=None` and defaults to `Path(self.library.path).parent / "projects"`.
`api/tests/conftest.py` gains a third autouse fixture giving every test server a
temporary projects folder.

## The interface

- **Top bar.** The project button reads `Project · <name>` or `Project · untitled`, with a
  dot before the name when `dirty`. Below 1200 px the word drops as today and the name
  moves to the tooltip.
- **Menu**, in order: New project · Open… · Save · Save as… · separator · Download ·
  Upload…. Save on an untitled project behaves as Save as…. Each row is an `Action` with
  `off` when the server is unreachable, the token is missing, or a job is running.
- **Projects window** (a `Dialog`, `frontend/src/lib/components/Projects.svelte`): rows
  with name, saved-at (through `Intl`), the current one marked; Open on double-click or
  the row's button; a ⋮ menu per row with Rename and Delete, each behind a confirmation
  sentence. For **Save as…** the same window shows a name field and a Save button at the
  bottom; picking a row fills the field; an existing name asks before overwriting. The
  field applies `cleanName` while typing, as the machine-name field does.
- **Unsaved changes** (`frontend/src/lib/components/UnsavedChanges.svelte`): "{name} has
  changes that are not saved." with Save, Discard and Cancel, in front of New, Open and
  Upload; Save on an untitled project goes through Save as… first. `beforeunload` warns
  on the same flag.
- **State** in `frontend/src/lib/projects.svelte.ts`: the list, the current name,
  `dirty` from the snapshot, and the three flows, so the top bar, the menu, the keyboard
  and the dialogs read one thing.

## Tests

- `api/tests/test_projects.py`: save writes one file that `import_project` reads back to
  the same counts of elements, sheets and operations; save over another name is refused
  without `overwrite` and works with it; rename and delete leave nothing behind; `../x`
  and forbidden characters are refused with code and sentence; `current` follows open,
  save-as, rename and new; `dirty` is false after save and open; a file copied into the
  folder appears in the list; the fence — a server without the flag writes beside the
  library, with it only there.
- `frontend/tests/actions.test.ts` sees the three verbs. A new `projects.test.ts` holds
  the name rule against the server's `clean_name` the way `upload-name.test.ts` does for
  the machine name, and checks the menu order and the button text from a snapshot.
  A server-backed `projects-flow.test.ts` (skips without `OK_BASE`) saves as, finds the
  row, opens it, and checks that Cancel in the unsaved-changes question changes nothing.
- `frontend/tests/docs.test.ts` keeps passing: the window title is named on a page, the
  shortcuts stand in the reference tables, every quoted sentence is in `en.ts`.

## Measured before it lands

The size of the handbook design's `.openkerf` and the time of one save and one open
through the route; that a file copied into the folder shows in the list; that a project
on the ThinkCentre survives `docker compose restart` in `/data/projects`. Numbers go into
docstrings and the handbook, not guesses.

## Handbook

`getting-started.md`, section "Keeping the work": the current project in the top bar, the
menu, the Projects window (new picture) and the top bar with a name (new picture); download
and upload as the way to another device. `reference.md`: three shortcuts, six menu rows.
`running-in-docker.md`: `/data/projects` under "Where the data lives".

## Out of scope

History or versions of a project, folders inside the projects folder, sharing between
users, projects in the library database, and any change to what a `.openkerf` contains.
