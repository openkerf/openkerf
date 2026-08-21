"""
Sheets: more than one piece of material in one project.

Like the plates of a 3D slicer, with one difference that matters for a laser:
**a sheet is a piece of material, not a copy of the bed.** It has a size of its
own — often smaller than the bed — and one material, so that the presets and the
time estimate are right per sheet.

Every sheet is a **document of its own**. Switching means: save the current
sheet, empty the element tree, load the other sheet. That was chosen deliberately
over one tree with sheet labels: what you see is then always exactly what gets
burned. With one shared tree that depends on a filter at the moment of spooling,
and a mistake in that filter costs material — or worse.

The price is that undo works per sheet and that switching takes a moment. That
does not outweigh burning the wrong sheet by accident.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from .edits import DesignError, _finite, _positive

MAX_SHEETS = 20

# The name a first sheet gets when no client supplied one. English, like the rest
# of this layer: our own web app sends the name it wants in the reader's language,
# and anything else gets the source language.
DEFAULT_SHEET_NAME = "Sheet 1"

DEFAULT_TILING = {
    "enabled": False,
    "margin_mm": 10.0,
    "overlap_mm": 25.0,
    "marker_size_mm": 8.0,
}


class Sheets:
    def __init__(self, kernel, drawing, document, directory: Path | str):
        self.kernel = kernel
        self.drawing = drawing
        self.document = document
        self.directory = Path(directory)
        self._active: str | None = None
        # Whether the active sheet has actually been put on the table this run.
        # Zie `_materialiseer`.
        self._loaded = False

    # ------------------------------------------------------------- opslag

    @property
    def index_path(self) -> Path:
        return self.directory / "vellen.json"

    def _read(self) -> list[dict]:
        try:
            data = json.loads(self.index_path.read_text())
        except (OSError, ValueError):
            return []
        for sheet in data if isinstance(data, list) else []:
            sheet.setdefault("tiling", dict(DEFAULT_TILING))
        return data if isinstance(data, list) else []

    def _write(self, sheets: list[dict]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(json.dumps(sheets, indent=1, ensure_ascii=False))

    def _file(self, sheet_id: str) -> Path:
        return self.directory / f"{sheet_id}.svg"

    # ------------------------------------------------------------ state

    def state(self) -> dict:
        sheets = self._ensure()
        return {
            "active": self._active,
            "sheets": [
                {**sheet, "active": sheet["id"] == self._active} for sheet in sheets
            ],
        }

    @property
    def active_id(self) -> str | None:
        self._ensure()
        return self._active

    def active(self) -> dict | None:
        """The sheet being worked on now — including its material."""
        sheets = self._ensure()
        for sheet in sheets:
            if sheet["id"] == self._active:
                return dict(sheet)
        return None

    def _ensure(self) -> list[dict]:
        """
        There is always at least one sheet.

        That saves an empty state nobody understands: a project without a sheet
        does not exist, no more than a laser without a bed.
        """
        sheets = self._read()
        if not sheets:
            width, height = self._bed()
            sheets = [
                {
                    "id": "sheet-1",
                    "name": DEFAULT_SHEET_NAME,
                    "width_mm": width,
                    "height_mm": height,
                    "material_id": None,
                    "thickness_mm": None,
                    "tiling": dict(DEFAULT_TILING),
                }
            ]
            self._write(sheets)
        elif any("thickness_mm" not in sheet for sheet in sheets):
            # Thickness came later (decision B1). Sheets from an older project are
            # missing the key; without this line the top bar trips over it.
            for sheet in sheets:
                sheet.setdefault("thickness_mm", None)
            self._write(sheets)
        if self._active is None or all(s["id"] != self._active for s in sheets):
            self._active = sheets[0]["id"]
        self._materialiseer()
        return sheets

    def _materialiseer(self) -> None:
        """
        Load the active sheet on the first question after startup.

        Without this the sheet bar said "Sheet 1" after a restart while the canvas
        was empty: the file was there, but nobody had loaded it. Worse than the
        empty look was what happened next — switching away sees an empty tree, reads
        that as "the user emptied this sheet", and throws `sheet-1.svg` away. One
        click, everything gone.

        Only when the tree is empty: if there is work in it already (recovery after
        a crash, or something drawn before the first question), that wins.
        """
        if self._loaded:
            return
        self._loaded = True
        if any(True for _ in self.kernel.elements.elems()):
            return
        if self._active and self._file(self._active).is_file():
            self._load(self._active)

    def _bed(self) -> tuple[float, float]:
        from meerk40t.core.units import Length

        device = getattr(self.kernel, "device", None)

        def side(name, fallback):
            try:
                return round(float(Length(getattr(device, name)).mm), 1)
            except Exception:
                return fallback

        return side("bedwidth", 500.0), side("bedheight", 300.0)

    def _find(self, sheets, sheet_id):
        for sheet in sheets:
            if sheet["id"] == sheet_id:
                return sheet
        names = ", ".join(f"'{s['name']}'" for s in sheets) or "none"
        raise DesignError(
            f"Sheet '{sheet_id}' does not exist. Available: {names}. Pick one from "
            "the sheet bar above the canvas.",
            code="sheet.unknown",
        )

    # ------------------------------------------------------------ beheren

    def add(
        self,
        name=None,
        width_mm=None,
        height_mm=None,
        material_id=None,
        thickness_mm=None,
    ) -> dict:
        sheets = self._ensure()
        if len(sheets) >= MAX_SHEETS:
            raise DesignError(
                f"More than {MAX_SHEETS} sheets becomes unmanageable.",
                code="sheet.tooMany",
            )
        bed_width, bed_height = self._bed()
        number = max(
            (int(s["id"].rsplit("-", 1)[-1]) for s in sheets if s["id"][-1].isdigit()),
            default=0,
        )
        # Keeping names unique: two boxes one after another used to give two
        # sheets both called "Box 2", and then you cannot tell which is which.
        wanted = str(name or f"{DEFAULT_SHEET_NAME.rstrip('1')}{number + 1}").strip()[:40]
        taken = {s["name"] for s in sheets}
        unique, suffix = wanted, 2
        while unique in taken:
            unique = f"{wanted} ({suffix})"
            suffix += 1

        sheet = {
            "id": f"sheet-{number + 1}",
            "name": unique,
            "width_mm": self._side(width_mm, bed_width, "width_mm"),
            "height_mm": self._side(height_mm, bed_height, "height_mm"),
            "material_id": material_id,
            "thickness_mm": self._thickness(thickness_mm),
            "tiling": dict(DEFAULT_TILING),
        }
        sheets.append(sheet)
        self._write(sheets)
        return self.state()

    def _thickness(self, value):
        """
        The thickness of this piece of material, or nothing.

        Empty is a valid answer: someone putting an offcut of unknown thickness in
        the machine should not have to invent a number first. A preset without a
        thickness has to be possible — forcing one would turn the top bar into a
        formulier veranderen.
        """
        if value is None or value == "":
            return None
        thickness = _positive(value, "thickness_mm")
        if thickness > 500:
            raise DesignError(
                "A sheet more than 500 mm thick does not go in.",
                code="sheet.tooThick",
            )
        return round(thickness, 2)

    def _side(self, value, fallback, label):
        if value is None:
            return fallback
        size = _positive(value, label)
        if not 5 <= size <= 5000:
            raise DesignError(f"{label} has to be between 5 and 5000 mm.")
        return round(size, 1)

    def _tiling(self, current, asked) -> dict:
        """
        The tile settings of this sheet, checked for coherence.

        Margin, overlap and marker size hang together: if no marker fits in the
        overlap strip, there is nothing to align on. That has to stop here and not
        only at burning time — by then you are already standing there with a plate
        in the machine.
        """
        block = dict(DEFAULT_TILING)
        block.update(current or {})
        if not isinstance(asked, dict):
            raise DesignError("tiling has to be a block of settings.")
        block["enabled"] = bool(asked.get("enabled", block["enabled"]))
        for key in ("margin_mm", "overlap_mm", "marker_size_mm"):
            if asked.get(key) is not None:
                block[key] = round(_positive(asked[key], key), 1)

        slack = 4.0
        if block["overlap_mm"] < block["marker_size_mm"] + slack:
            raise DesignError(
                f"An alignment marker is {block['marker_size_mm']:g} mm across and does "
                f"not fit in an overlap of {block['overlap_mm']:g} mm. Make the overlap "
                f"at least {block['marker_size_mm'] + slack:g} mm."
            )
        if block["margin_mm"] > 100:
            raise DesignError(
                "A margin of more than 100 mm leaves no bed.", code="sheet.marginTooBig"
            )
        return block

    def update(self, sheet_id: str, **fields) -> dict:
        sheets = self._ensure()
        sheet = self._find(sheets, sheet_id)
        if fields.get("name") is not None:
            name = str(fields["name"]).strip()[:40]
            if not name:
                raise DesignError("A sheet needs a name.", code="sheet.needsName")
            sheet["name"] = name
        for key in ("width_mm", "height_mm"):
            if fields.get(key) is not None:
                sheet[key] = self._side(fields[key], sheet[key], key)
        if "material_id" in fields:
            sheet["material_id"] = fields["material_id"]
        if "thickness_mm" in fields:
            sheet["thickness_mm"] = self._thickness(fields["thickness_mm"])
        if fields.get("tiling") is not None:
            sheet["tiling"] = self._tiling(sheet.get("tiling"), fields["tiling"])
        self._write(sheets)
        return self.state()

    def remove(self, sheet_id: str) -> dict:
        sheets = self._ensure()
        if len(sheets) == 1:
            raise DesignError(
                "The last sheet cannot go; a project has one.", code="sheet.needsOne"
            )
        sheet = self._find(sheets, sheet_id)
        if sheet["id"] == self._active:
            # Away from the sheet that is disappearing first, otherwise the contents
            # of a removed sheet stay on the canvas.
            other = next(s for s in sheets if s["id"] != sheet_id)
            self.activate(other["id"])
            sheets = self._read()
        self._file(sheet_id).unlink(missing_ok=True)
        self._write([s for s in sheets if s["id"] != sheet_id])
        return self.state()

    def reset(self) -> dict:
        """
        Back to one empty sheet — what "new project" does to the sheets.

        The saved sheets go with it. They sit beside the database and would
        otherwise survive the new project: you start clean and still find
        yesterday's boxes in the sheet bar.
        """
        self.directory.mkdir(parents=True, exist_ok=True)
        for old in self.directory.glob("*.svg"):
            old.unlink(missing_ok=True)
        self.index_path.unlink(missing_ok=True)
        self._active = None
        # There is nothing to load and the tree has just been emptied; without this
        # `_ensure` would still want to fetch the sheet we just threw away.
        self._loaded = True
        return self.state()

    # ------------------------------------------------------------ wisselen

    def activate(self, sheet_id: str) -> dict:
        sheets = self._ensure()
        sheet = self._find(sheets, sheet_id)
        if sheet["id"] == self._active:
            return self.state()

        self.save_active()
        self._load(sheet["id"])
        self._active = sheet["id"]
        return self.state()

    def save_active(self) -> None:
        """Write out the current sheet. Happens on every switch and on save."""
        if self._active is None:
            return
        target = self._file(self._active)
        self.directory.mkdir(parents=True, exist_ok=True)
        if not any(True for _ in self.kernel.elements.elems()):
            # An empty sheet: no file, otherwise coming back looks as if something
            # broke.
            target.unlink(missing_ok=True)
            return
        written = self.drawing.export_svg("sheet.svg")
        shutil.copyfile(written, target)

    def _load(self, sheet_id: str) -> None:
        self.kernel.elements.clear_all()
        self.drawing.user_operations.clear()
        source = self._file(sheet_id)
        if source.is_file():
            self.drawing.runner.run(f'load "{source}"')
            self.kernel.elements.validate_ids()
            # Mark the layers of this sheet as "the user's" again. A fresh tree has well
            # over two hundred empty default operations; without this marking the layers you
            # made yourself cannot be told apart from that noise and they disappear from the
            # list.
            for operation in self.kernel.elements.ops():
                if getattr(operation, "id", None):
                    self.drawing.user_operations.add(operation.id)
            # `load` puts the file name on the document, and that name comes back as
            # the job name in the spooler: every job was called `sheet-2.svg` while the
            # user sees "Test piece" on their tab — the same mistake as `herstel.svg`
            # in autosave.py. This file is our storage, not a document the user gave a
            # name, so the document stays nameless and the sheet bar decides the name.
            try:
                self.kernel.elements._filename = None
            except Exception:  # pragma: no cover - the engine must not break us
                pass
        self.kernel.elements.signal("rebuild_tree", "all")
        self.kernel.elements.signal("refresh_scene", "Scene")

    # ------------------------------------------------------- verplaatsen

    def move_selection(self, ids, sheet_id: str) -> dict:
        """
        Move the selection to another sheet.

        Via the engine's clipboard: that lives on the elements service and therefore
        survives switching sheets. Cut before the switch, paste after — exactly the
        order in which nothing falls between the two.
        """
        sheets = self._ensure()
        self._find(sheets, sheet_id)
        if sheet_id == self._active:
            raise DesignError(
                "That is the sheet you are already working on.", code="sheet.sameSheet"
            )

        nodes = []
        for element_id in ids or []:
            node = self.kernel.elements.find_node(element_id)
            if node is None:
                raise DesignError(f"Element {element_id} does not exist (any more).")
            nodes.append(node)
        if not nodes:
            raise DesignError(
                "Choose what should come along first.", code="sheet.nothingSelected"
            )

        self.kernel.elements.set_emphasis(nodes)
        self.drawing.runner.run("clipboard cut")
        self.activate(sheet_id)
        self.drawing.runner.run("clipboard paste")
        self.kernel.elements.validate_ids()
        self.kernel.elements.signal("rebuild_tree", "all")
        self.document.touch()
        return {**self.state(), "moved": len(nodes)}

    # -------------------------------------------------------- projectbestand

    def export_into(self, bundle) -> list[dict]:
        """Put the sheets into a project file; returns the index."""
        self.save_active()
        sheets = self._ensure()
        for sheet in sheets:
            source = self._file(sheet["id"])
            if source.is_file():
                bundle.write(source, f"sheets/{sheet['id']}.svg")
        return sheets

    def import_from(self, bundle, sheets: list[dict], active: str | None = None) -> None:
        """Restore sheets from a project file; replaces what was there."""
        if not sheets:
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        for old in self.directory.glob("*.svg"):
            old.unlink(missing_ok=True)
        names = set(bundle.namelist())
        for sheet in sheets:
            # `vellen/` is where these lived before the interface became English; a project
            # from that version still opens.
            for name in (f"sheets/{sheet['id']}.svg", f"vellen/{sheet['id']}.svg"):
                if name in names:
                    self._file(sheet["id"]).write_bytes(bundle.read(name))
                    break
        self._write(sheets)
        self._active = active if any(s["id"] == active for s in sheets) else sheets[0]["id"]
