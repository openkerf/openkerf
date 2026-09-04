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
        # `Drawing.export_project` ignores any directory in the filename it is given —
        # it keeps only the basename and writes into a temporary directory of its own,
        # returning the path it actually used. So there is nothing to write "beside the
        # target" ourselves; we ask for the name we want, then move whatever came back
        # onto the target in one step, the same way `/api/project/export.openkerf`
        # hands its result straight to `FileResponse` without touching it further.
        written = Path(self.drawing.export_project(self.library, f"{name}{SUFFIX}", self.sheets))
        os.replace(written, target)
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
                f"There is already a project called {new}. Choose another name, or "
                "say that it may be replaced.",
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
        self.open(name)
        return self._entry(self._path(name))

    def forget(self) -> None:
        """New project: no name until it is saved."""
        self.current = None
