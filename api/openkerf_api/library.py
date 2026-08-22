"""
The local material library: machine profiles, materials and presets.

SQLite in a single file next to MeerK40t's own settings — no service, no
port, nothing for the user to install. This is the personal library; the
community repository (presetariat) syncs into it later, which is why presets
carry a `source` and an optional `origin_id` from the start.

The schema follows the data model in ARCHITECTUUR.md: a preset is only
reusable once you know which machine produced it, so machine_profile is a
separate table that presets point at.
"""

import json
import re
import sqlite3
import unicodedata
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS machine_profile (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    laser_type   TEXT NOT NULL DEFAULT 'co2-glass',
    power_watt   REAL,
    lens_mm      REAL,
    bed_width_mm REAL,
    bed_height_mm REAL,
    -- The path of the device service in the engine ("lhystudios"). With this the library
    -- knows which profile belongs to the machine that is active *now*; without that link a
    -- preset is a statement about nothing.
    device_path  TEXT,
    -- What this machine *can* do. Decides what appears in the jog.
    has_z        INTEGER NOT NULL DEFAULT 0,
    has_autofocus INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS material (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT NOT NULL UNIQUE,
    synonyms  TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS preset (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id   INTEGER NOT NULL REFERENCES material(id) ON DELETE CASCADE,
    machine_id    INTEGER REFERENCES machine_profile(id) ON DELETE SET NULL,
    thickness_mm  REAL,
    operation     TEXT NOT NULL,
    speed_mm_s    REAL NOT NULL,
    power_percent REAL NOT NULL,
    passes        INTEGER NOT NULL DEFAULT 1,
    -- Line spacing when rastering. Since B12 a test grid can sweep on it, so it comes
    -- along from the winning square as well; empty when cutting.
    interval_mm   REAL,
    air_assist    INTEGER NOT NULL DEFAULT 1,
    focus_offset_mm REAL NOT NULL DEFAULT 0,
    -- handmatig | geextrapoleerd | testraster | geimporteerd
    source        TEXT NOT NULL DEFAULT 'handmatig',
    origin_id     TEXT,
    note          TEXT NOT NULL DEFAULT '',
    -- When this setting was last put on a layer. Anybody who cut 3 mm birch yesterday is
    -- not searching alphabetically today; they are looking for
    -- wat hij gisteren gebruikte.
    last_used_at  TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- New columns on `test_grid` belong in `_migrate` as well: existing databases get them
-- there, fresh ones here.
CREATE TABLE IF NOT EXISTS test_grid (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id   INTEGER REFERENCES material(id) ON DELETE SET NULL,
    machine_id    INTEGER REFERENCES machine_profile(id) ON DELETE SET NULL,
    thickness_mm  REAL,
    operation     TEXT NOT NULL,
    -- The same for the whole board: how many times the head goes over each square.
    passes        INTEGER NOT NULL DEFAULT 1,
    speed_min     REAL NOT NULL,
    speed_max     REAL NOT NULL,
    speed_steps   INTEGER NOT NULL,
    power_min     REAL NOT NULL,
    power_max     REAL NOT NULL,
    power_steps   INTEGER NOT NULL,
    -- Decision B12: interval is the third quantity. Two of them sit on the axes, the third
    -- is fixed — then min and max are equal and steps is 1.
    interval_min  REAL,
    interval_max  REAL,
    interval_steps INTEGER,
    row_axis      TEXT NOT NULL DEFAULT 'speed',
    column_axis   TEXT NOT NULL DEFAULT 'power',
    rows          INTEGER,
    columns       INTEGER,
    cell_mm       REAL NOT NULL,
    gap_mm        REAL NOT NULL,
    origin_x_mm   REAL NOT NULL,
    origin_y_mm   REAL NOT NULL,
    -- Every cell with its position and settings, so that the photo overlay later knows
    -- which square belongs to which speed and power.
    cells         TEXT NOT NULL,
    photo_path    TEXT,
    -- The four corners of the burned board on the photo (0–1). Belongs here and not in
    -- localStorage: you align on the desktop and point out the square on the tablet, and
    -- then the overlay has to be the same.
    alignment     TEXT,
    group_id      TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Named generator settings (gap T7).
--
-- T3 onthoudt één setting per material: het vórige grid. Dat dekt "ik
-- test elke week 3 mm berk" but not "berk snijden" náást "berk graveren" —
-- two recipes for the same material cannot sit side by side there. This is the same
-- content under a name, and deliberately in the same shape: one row with exactly the keys
-- `Library.GRID_DEFAULTS` describes, so that a recipe and a previous grid are
-- interchangeable to the wizard.
CREATE TABLE IF NOT EXISTS grid_recipe (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    material_id INTEGER REFERENCES material(id) ON DELETE CASCADE,
    settings    TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS preset_material ON preset(material_id);
"""

OPERATIONS = ("snijden", "graveren-vector", "graveren-raster", "markeren")
SOURCES = ("handmatig", "geextrapoleerd", "testraster", "geimporteerd")

# Decision B7: the library is exchangeable. One file, because a library without the grid
# photos is half of one — those photos *are* the evidence. Hence a zip: the JSON with the
# data, the photos beside it.
BUNDLE_FORMAT = "openkerf-library"
BUNDLE_VERSION = 1
BUNDLE_SUFFIX = ".openkerf-lib"
BUNDLE_INDEX = "library.json"
# What this index was called before the interface became English. A library
# exported by that version still opens.
LEGACY_BUNDLE_INDEX = "bibliotheek.json"
BUNDLE_PHOTOS = "photos"

# When two names are about the same material. The catalogue writes "Birch plywood" where
# the library has "Plywood birch" — that is one board, not two. We never merge it by
# ourselves (a wrong guess costs you your own measurements), but we do point it out.
MATERIAL_FAMILIES = {
    # The key is the word that ends up in the explanation on screen, so it is English.
    # The trigger words stay multilingual: people name their own boards in their own
    # language, and "Berkentriplex" has to keep landing on birch plywood.
    "plywood": ("multiplex", "triplex", "plywood", "ply"),
    "birch": ("berken", "berk", "birch"),
    "poplar": ("populier", "poplar"),
    "oak": ("eiken", "eik", "oak"),
    "mdf": ("mdf",),
    "acrylic": ("acryl", "acrylaat", "acrylic", "plexiglas", "plexi", "pmma"),
    "cardboard": ("karton", "kartonnen", "cardboard"),
    "paper": ("papier", "paper"),
    "leather": ("leer", "leder", "leather"),
    "felt": ("vilt", "felt"),
    "steel": ("rvs", "inox", "staal", "steel"),
    "aluminium": ("aluminium", "alu"),
}


class LibraryError(RuntimeError):
    """
    A refusal the user can act on, in the user's own terms.

    `code` is optional and exists for one reason: the interface can then say it in
    the reader's language. The message is English — the source language of this
    layer — and is what a client without a catalogue shows: curl, a script, a log.
    A raise without a code is one whose message only a developer reads.
    """

    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.code = code


def default_path(kernel) -> Path:
    """Beside MeerK40t's settings, so a profile keeps its own library."""
    from meerk40t.kernel.functions import get_safe_path

    directory = Path(get_safe_path(kernel.name, create=True))
    return directory / "openkerf-library.db"


class Library:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Photos as files beside the database: that keeps the database small and the
        # photos simply viewable in a file browser.
        self.photos = self.path.parent / "openkerf-photos"
        self.photos.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(SCHEMA)
            self._migrate(db)

    @staticmethod
    def _migrate(db):
        """Columns that came later, for databases from before that version."""
        existing = {row["name"] for row in db.execute("PRAGMA table_info(test_grid)")}
        for column, definition in (
            ("group_id", "TEXT"),
            ("alignment", "TEXT"),
            ("interval_min", "REAL"),
            ("interval_max", "REAL"),
            ("interval_steps", "INTEGER"),
            ("row_axis", "TEXT NOT NULL DEFAULT 'speed'"),
            ("column_axis", "TEXT NOT NULL DEFAULT 'power'"),
            ("rows", "INTEGER"),
            ("columns", "INTEGER"),
            # T9/T10: what the board hangs off and what else gets burned on it. Grids from
            # before this version always started from the corner, with captions and without
            # a frame — which is exactly these defaults.
            ("anchor", "TEXT NOT NULL DEFAULT 'corner'"),
            ("text_enabled", "INTEGER NOT NULL DEFAULT 1"),
            ("border_enabled", "INTEGER NOT NULL DEFAULT 0"),
            ("label_speed_mm_s", "REAL"),
            ("label_power_percent", "REAL"),
            # Boards from before this version burned over each square once.
            ("passes", "INTEGER NOT NULL DEFAULT 1"),
        ):
            if column not in existing:
                db.execute(f"ALTER TABLE test_grid ADD COLUMN {column} {definition}")
        # Rasters van vóór B12 hadden altijd speed × power.
        db.execute(
            "UPDATE test_grid SET rows = speed_steps WHERE rows IS NULL"
        )
        db.execute(
            "UPDATE test_grid SET columns = power_steps WHERE columns IS NULL"
        )

        presets = {row["name"] for row in db.execute("PRAGMA table_info(preset)")}
        if "last_used_at" not in presets:
            db.execute("ALTER TABLE preset ADD COLUMN last_used_at TEXT")
        if "interval_mm" not in presets:
            db.execute("ALTER TABLE preset ADD COLUMN interval_mm REAL")

        profile = {row["name"] for row in db.execute("PRAGMA table_info(machine_profile)")}
        for column, definition in (
            ("device_path", "TEXT"),
            ("has_z", "INTEGER NOT NULL DEFAULT 0"),
            ("has_autofocus", "INTEGER NOT NULL DEFAULT 0"),
        ):
            if column not in profile:
                db.execute(f"ALTER TABLE machine_profile ADD COLUMN {column} {definition}")
        Library._dedupe_machines(db)

    @staticmethod
    def _dedupe_machines(db):
        """
        One profile per device, and after that a lock on that rule.

        `profile_for_device` deed eerst een SELECT en daarna een INSERT. De
        library loads `/api/library/presets`, `/api/library/machines` and
        `/api/library/active-machine` at the same time, and several of those ask for the
        active profile — so three requests drove through that gap and three profiles for the
        same laser stood in the list. Measured with eight simultaneous calls: eight profiles.
        Jelle's library has two `lihuiyu-device` rows with the same second on them.

        What stays is the oldest profile; presets, grids and settings from the duplicates
        move to it, because they are about the same machine.
        """
        rows = db.execute(
            "SELECT id, device_path FROM machine_profile "
            "WHERE device_path IS NOT NULL AND device_path <> '' ORDER BY id"
        ).fetchall()
        keep: dict[str, int] = {}
        for row in rows:
            path = row["device_path"]
            if path in keep:
                db.execute(
                    "UPDATE preset SET machine_id = ? WHERE machine_id = ?",
                    (keep[path], row["id"]),
                )
                db.execute(
                    "UPDATE test_grid SET machine_id = ? WHERE machine_id = ?",
                    (keep[path], row["id"]),
                )
                db.execute("DELETE FROM machine_profile WHERE id = ?", (row["id"],))
            else:
                keep[path] = row["id"]
        db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS machine_profile_device "
            "ON machine_profile(device_path) WHERE device_path IS NOT NULL"
        )

    def _connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        return db

    # ------------------------------------------------------- machine profiles

    def machines(self) -> list[dict]:
        with self._connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM machine_profile ORDER BY name")]

    def add_machine(self, **fields) -> dict:
        name = str(fields.get("name") or "").strip()
        if not name:
            raise LibraryError("A machine profile needs a name.")
        with self._connect() as db:
            cursor = db.execute(
                """INSERT INTO machine_profile
                   (name, laser_type, power_watt, lens_mm, bed_width_mm,
                    bed_height_mm, device_path, has_z, has_autofocus)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    name,
                    fields.get("laser_type") or "co2-glass",
                    _number(fields.get("power_watt"), "power_watt", optional=True),
                    _number(fields.get("lens_mm"), "lens_mm", optional=True),
                    _number(fields.get("bed_width_mm"), "bed_width_mm", optional=True),
                    _number(fields.get("bed_height_mm"), "bed_height_mm", optional=True),
                    str(fields.get("device_path") or "") or None,
                    1 if fields.get("has_z") else 0,
                    1 if fields.get("has_autofocus") else 0,
                ),
            )
            return self._one(db, "machine_profile", cursor.lastrowid)

    def profile_for_device(self, device_path: str, label: str | None = None) -> dict:
        """
        The profile of the machine that is active now, freshly created if need be.

        A preset is a statement about *this laser on this material*. Without a profile to
        hang off, every preset would be "for all machines", and that is exactly the confusion
        this solves.

        The name is a copy of what the machine is called in the engine, and that copy stays
        fresh. Otherwise the library still holds the name from the moment the profile came
        into being: at Jelle's the device is called "KH-5030 50W" and the profile still "K50
        CO2", and on a fresh installation that is the internal name of MeerK40t's default
        device ("lihuiyu-device"). Then nobody can tell their machines apart. Renaming
        happens at the machine itself; here it is only followed up.
        """
        path = str(device_path or "").strip()
        if not path:
            raise LibraryError("There is no active machine to attach to.")
        name = str(label or "").strip() or path
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM machine_profile WHERE device_path = ?", (path,)
            ).fetchone()
            if row is not None:
                if row["name"] != name:
                    db.execute(
                        "UPDATE machine_profile SET name = ? WHERE id = ?",
                        (name, row["id"]),
                    )
                    return self._one(db, "machine_profile", row["id"])
                return dict(row)
        try:
            return self.add_machine(name=name, device_path=path)
        except sqlite3.IntegrityError:
            # A simultaneous request beat us to it; the lock on device_path does its work
            # and we take what is there now.
            with self._connect() as db:
                row = db.execute(
                    "SELECT * FROM machine_profile WHERE device_path = ?", (path,)
                ).fetchone()
            if row is None:  # pragma: no cover - only on a different lock
                raise
            return dict(row)

    def refresh_names(self, labels: dict) -> None:
        """
        Bringing existing profiles' names into line with the machines.

        `profile_for_device` does this for the machine you are working on, but the list shows
        them all — and then the machines you are not working on right now still carry the
        name from the moment their profile came into being. Creates nothing: a machine
        without settings does not need a profile yet.
        """
        if not labels:
            return
        with self._connect() as db:
            for path, name in labels.items():
                name = str(name or "").strip() or path
                db.execute(
                    "UPDATE machine_profile SET name = ? "
                    "WHERE device_path = ? AND name <> ?",
                    (name, path, name),
                )

    def machine_usage(self, machine_id: int) -> dict:
        """How much evidence hangs off this profile."""
        with self._connect() as db:
            return {
                "presets": db.execute(
                    "SELECT COUNT(*) FROM preset WHERE machine_id = ?", (machine_id,)
                ).fetchone()[0],
                "test_grids": db.execute(
                    "SELECT COUNT(*) FROM test_grid WHERE machine_id = ?", (machine_id,)
                ).fetchone()[0],
            }

    def remove_machine(self, machine_id: int) -> dict:
        """
        Een profile opruimen.

        Only when nothing hangs off it. A preset without a machine is a speed without a
        laser beside it, and that is precisely the statement-about-nothing this table is
        meant to prevent — so better a refusal with a reason than a list that quietly becomes
        untrustworthy.
        """
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM machine_profile WHERE id = ?", (machine_id,)
            ).fetchone()
        if row is None:
            raise LibraryError(f"Machine profile {machine_id} does not exist.")
        gebruik = self.machine_usage(machine_id)
        if gebruik["presets"] or gebruik["test_grids"]:
            raise LibraryError(
                f"'{row['name']}' still carries {gebruik['presets']} setting(s) and "
                f"{gebruik['test_grids']} test grid(s). Remove or move those first."
            )
        with self._connect() as db:
            db.execute("DELETE FROM machine_profile WHERE id = ?", (machine_id,))
        return {"removed": machine_id}

    def update_machine(self, machine_id: int, fields: dict) -> dict:
        toegestaan = (
            "name", "laser_type", "power_watt", "lens_mm",
            "bed_width_mm", "bed_height_mm", "has_z", "has_autofocus",
        )
        parts, values = [], []
        for key in toegestaan:
            if key not in fields:
                continue
            parts.append(f"{key} = ?")
            if key in ("has_z", "has_autofocus"):
                values.append(1 if fields[key] else 0)
            elif key in ("name", "laser_type"):
                values.append(str(fields[key]))
            else:
                values.append(_number(fields[key], key, optional=True))
        if not parts:
            raise LibraryError("Nothing to update.")
        with self._connect() as db:
            db.execute(
                f"UPDATE machine_profile SET {', '.join(parts)} WHERE id = ?",
                (*values, machine_id),
            )
            return self._one(db, "machine_profile", machine_id)

    # -------------------------------------------------------------- materials

    def materials(self) -> list[dict]:
        with self._connect() as db:
            rows = [dict(r) for r in db.execute("SELECT * FROM material ORDER BY name")]
        for row in rows:
            row["synonyms"] = [s for s in row["synonyms"].split("|") if s]
        return rows

    def add_material(self, name: str, synonyms=None) -> dict:
        name = str(name or "").strip()
        if not name:
            raise LibraryError("A material needs a name.")
        joined = "|".join(str(s).strip() for s in (synonyms or []) if str(s).strip())
        try:
            with self._connect() as db:
                cursor = db.execute(
                    "INSERT INTO material (name, synonyms) VALUES (?, ?)", (name, joined)
                )
                row = self._one(db, "material", cursor.lastrowid)
        except sqlite3.IntegrityError as e:
            raise LibraryError(f"Material '{name}' already exists.") from e
        row["synonyms"] = [s for s in row["synonyms"].split("|") if s]
        return row

    def remove_material(self, material_id: int) -> dict:
        with self._connect() as db:
            cursor = db.execute("DELETE FROM material WHERE id = ?", (material_id,))
            if not cursor.rowcount:
                raise LibraryError(f"Material {material_id} does not exist.")
        return {"removed": material_id}

    # ---------------------------------------------------------------- presets

    def presets(self, material_id=None, operation=None, machine_id=None) -> list[dict]:
        # The grid's photo with it: a preset that comes from a test grid has evidence, and
        # that evidence belongs on the card and not three screens further on. origin_id is
        # "testgrid:<id>".
        query = """
            SELECT p.*, m.name AS material_name, mp.name AS machine_name,
                   g.id AS grid_id, g.photo_path AS grid_photo,
                   g.created_at AS grid_date, g.cells AS grid_cells,
                   -- Is that grid's photo aligned? If not, the marker on the photo falls
                   -- back on four default corners and the outline is approximate, not
                   -- exact. The library should be able to say so rather than suggest a
                   -- precision that is not there.
                   (g.alignment IS NOT NULL) AS grid_aligned
            FROM preset p
            JOIN material m ON m.id = p.material_id
            LEFT JOIN machine_profile mp ON mp.id = p.machine_id
            LEFT JOIN test_grid g ON p.origin_id = 'testgrid:' || g.id
        """
        clauses, params = [], []
        if material_id is not None:
            clauses.append("p.material_id = ?")
            params.append(material_id)
        if operation:
            clauses.append("p.operation = ?")
            params.append(operation)
        if machine_id is not None:
            # Presets without a profile belong to nobody in particular and so stay
            # visible: they were made by hand before there were profiles.
            clauses.append("(p.machine_id = ? OR p.machine_id IS NULL)")
            params.append(machine_id)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY m.name, p.thickness_mm, p.operation"
        with self._connect() as db:
            return [_preset_row(r) for r in db.execute(query, params)]

    def add_preset(self, **fields) -> dict:
        material_id = fields.get("material_id")
        if material_id is None:
            raise LibraryError("A preset belongs to a material.")
        operation = str(fields.get("operation") or "").strip()
        if operation not in OPERATIONS:
            raise LibraryError(f"Unknown operation: {operation or '(empty)'}")
        source = str(fields.get("source") or "handmatig")
        if source not in SOURCES:
            raise LibraryError(f"Unknown source: {source}")

        speed = _number(fields.get("speed_mm_s"), "speed_mm_s", positive=True)
        power = _number(fields.get("power_percent"), "power_percent", positive=True)
        if power > 100:
            raise LibraryError("power_percent cannot go above 100.")

        try:
            with self._connect() as db:
                cursor = db.execute(
                    """INSERT INTO preset (material_id, machine_id, thickness_mm, operation,
                            speed_mm_s, power_percent, passes, interval_mm, air_assist,
                            focus_offset_mm, source, origin_id, note)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        material_id,
                        fields.get("machine_id"),
                        _number(fields.get("thickness_mm"), "thickness_mm", optional=True),
                        operation,
                        speed,
                        power,
                        int(fields.get("passes") or 1),
                        _number(fields.get("interval_mm"), "interval_mm", optional=True),
                        1 if fields.get("air_assist", True) else 0,
                        _number(fields.get("focus_offset_mm") or 0, "focus_offset_mm"),
                        source,
                        fields.get("origin_id"),
                        str(fields.get("note") or ""),
                    ),
                )
                preset_id = cursor.lastrowid
        except sqlite3.IntegrityError as e:
            raise LibraryError("That material does not exist.") from e
        return self.preset(preset_id)

    def preset(self, preset_id: int) -> dict:
        with self._connect() as db:
            row = db.execute(
                """SELECT p.*, m.name AS material_name, mp.name AS machine_name
                   FROM preset p
                   JOIN material m ON m.id = p.material_id
                   LEFT JOIN machine_profile mp ON mp.id = p.machine_id
                   WHERE p.id = ?""",
                (preset_id,),
            ).fetchone()
        if row is None:
            raise LibraryError(f"Preset {preset_id} does not exist.")
        return _preset_row(row)

    # What you may adjust on an existing preset.
    PRESET_FIELDS = {
        "thickness_mm": lambda v: _number(v, "thickness_mm", optional=True),
        "speed_mm_s": lambda v: _number(v, "speed_mm_s", positive=True),
        "power_percent": lambda v: _percent(v),
        "passes": lambda v: int(_number(v, "passes", positive=True)),
        "interval_mm": lambda v: _number(v, "interval_mm", optional=True),
        "air_assist": lambda v: 1 if v else 0,
        "focus_offset_mm": lambda v: _number(v, "focus_offset_mm"),
        "note": lambda v: str(v or ""),
        "machine_id": lambda v: v,
    }

    def update_preset(self, preset_id: int, **fields) -> dict:
        """
        Adjusting an existing preset.

        Material and operation are fixed: that is a different preset. The source too — it
        says how the values came about, and that does not change because you update a number.
        """
        self.preset(preset_id)
        updates = {k: v for k, v in fields.items() if k in self.PRESET_FIELDS and v is not None}
        rejected = sorted(set(fields) - set(self.PRESET_FIELDS) - {"id"})
        if rejected:
            raise LibraryError(
                f"Cannot be changed: {', '.join(rejected)}. Material, operation and "
                "source belong to the identity of a preset."
            )
        if not updates:
            return self.preset(preset_id)
        columns = ", ".join(f"{k} = ?" for k in updates)
        values = [self.PRESET_FIELDS[k](v) for k, v in updates.items()]
        with self._connect() as db:
            db.execute(f"UPDATE preset SET {columns} WHERE id = ?", (*values, preset_id))
        return self.preset(preset_id)

    def suggest_range(self, material_id=None, operation=None, thickness_mm=None) -> dict:
        """
        A grid range around what you already know.

        ARCHITECTUUR.md: the app proposes the range on the basis of existing (often
        extrapolated) presets around the expected working point. Without presets we fall
        back on something wide but reasonable.
        """
        presets = self.presets(material_id, operation)
        if thickness_mm is not None:
            near = [
                p
                for p in presets
                if p["thickness_mm"] is not None
                and abs(p["thickness_mm"] - float(thickness_mm)) < 0.51
            ]
            presets = near or presets
        if not presets:
            return {
                "based_on": 0,
                "speed_min": 5,
                "speed_max": 25,
                "power_min": 40,
                "power_max": 80,
            }
        speeds = [p["speed_mm_s"] for p in presets]
        powers = [p["power_percent"] for p in presets]
        return {
            "based_on": len(presets),
            # Half a turn around it: enough to enclose the working point.
            "speed_min": max(0.1, round(min(speeds) * 0.5, 1)),
            "speed_max": round(max(speeds) * 1.5, 1),
            "power_min": max(1.0, round(min(powers) * 0.7, 1)),
            "power_max": min(100.0, round(max(powers) * 1.3, 1)),
        }

    def touch_preset(self, preset_id: int) -> None:
        """Remember that this setting was used; that is what makes 'yesterday'."""
        with self._connect() as db:
            db.execute(
                "UPDATE preset SET last_used_at = datetime('now') WHERE id = ?",
                (preset_id,),
            )

    def remove_preset(self, preset_id: int) -> dict:
        with self._connect() as db:
            cursor = db.execute("DELETE FROM preset WHERE id = ?", (preset_id,))
            if not cursor.rowcount:
                raise LibraryError(f"Preset {preset_id} does not exist.")
        return {"removed": preset_id}

    # ------------------------------------------------------------ testrasters

    def test_grids(self) -> list[dict]:
        with self._connect() as db:
            rows = db.execute(
                """SELECT g.*, m.name AS material_name
                   FROM test_grid g
                   LEFT JOIN material m ON m.id = g.material_id
                   ORDER BY g.created_at DESC, g.id DESC"""  # created_at heeft secondenresolutie
            ).fetchall()
        return [_grid_row(r) for r in rows]

    def test_grid(self, grid_id: int) -> dict:
        with self._connect() as db:
            row = db.execute(
                """SELECT g.*, m.name AS material_name
                   FROM test_grid g
                   LEFT JOIN material m ON m.id = g.material_id
                   WHERE g.id = ?""",
                (grid_id,),
            ).fetchone()
        if row is None:
            raise LibraryError(f"Test grid {grid_id} does not exist.")
        return _grid_row(row)

    def set_grid_group(self, grid_id: int, group_id: str | None) -> None:
        with self._connect() as db:
            db.execute(
                "UPDATE test_grid SET group_id = ? WHERE id = ?", (group_id, grid_id)
            )

    def set_grid_alignment(self, grid_id: int, corners) -> dict:
        """
        Where the burned board lies on the photo: four corners, each 0–1.

        In the database and not in the browser: you align on the desktop and point out the
        square on the tablet, and then the same overlay should be there. `None` erases the
        alignment and puts it back on the proposal.
        """
        self.test_grid(grid_id)
        if corners is None:
            clean = None
        else:
            clean = _alignment(corners)
            if clean is None:
                raise LibraryError(
                    "An alignment consists of four points with an x and a y."
                )
            for point in clean:
                if not (0 <= point["x"] <= 1 and 0 <= point["y"] <= 1):
                    raise LibraryError("A corner lies outside the photo.")
        with self._connect() as db:
            db.execute(
                "UPDATE test_grid SET alignment = ? WHERE id = ?",
                (json.dumps(clean) if clean else None, grid_id),
            )
        return self.test_grid(grid_id)

    # The settings the next grid of the same material adopts. The same list carries T7's
    # named recipes: one shape, so that the wizard does not have to know whether it is
    # filling in a previous grid or a recipe.
    GRID_DEFAULTS = (
        "operation", "thickness_mm", "passes", "row_axis", "column_axis",
        "speed_min", "speed_max", "speed_steps",
        "power_min", "power_max", "power_steps",
        "interval_min", "interval_max", "interval_steps",
        "cell_mm", "gap_mm", "origin_x_mm", "origin_y_mm",
        "anchor", "text_enabled", "border_enabled",
        "label_speed_mm_s", "label_power_percent",
    )

    def last_grid_settings(self, material_id=None) -> dict | None:
        """
        What you set up last time for this material.

        Anybody testing 3 mm birch weekly fills in the same form every week. No separate
        table is needed for it: the previous grid *is* the setting, and so it survives an
        export and import as well.
        """
        grids = self.test_grids()
        if material_id is not None:
            grids = [g for g in grids if g["material_id"] == material_id]
        if not grids:
            return None
        latest = grids[0]  # test_grids() puts the newest first
        setting = {
            key: latest.get(key) for key in self.GRID_DEFAULTS
        }
        _with_anchor(setting)
        setting["from_grid"] = latest["id"]
        setting["from_date"] = latest["created_at"]
        return setting

    # ---------------------------------------------- named recipes (gap T7)

    def grid_recipes(self, material_id=None) -> list[dict]:
        """
        De bewaarde generatorinstellingen.

        Without a material you get everything; with a material the recipes of *that*
        material plus the material-less ones — those last are the general ones ("quick
        4×4"), and those are exactly what you want to see when you start something new.
        """
        with self._connect() as db:
            rows = [
                dict(r)
                for r in db.execute(
                    """SELECT r.*, m.name AS material_name
                       FROM grid_recipe r
                       LEFT JOIN material m ON m.id = r.material_id
                       ORDER BY r.name COLLATE NOCASE"""
                )
            ]
        for row in rows:
            row["settings"] = _recipe_settings(json.loads(row["settings"]))
            _with_anchor(row["settings"])
        if material_id is None:
            return rows
        return [
            r for r in rows if r["material_id"] in (material_id, None)
        ]

    def save_grid_recipe(self, name: str, settings: dict, material_id=None) -> dict:
        """
        Saving a recipe, or overwriting the one with the same name.

        Overwriting and not refusing: saving "cut birch" while a "cut birch" already exists
        means you have adjusted it. A second one with the same name would produce a list you
        can no longer choose from.
        """
        name = str(name or "").strip()
        if not name:
            raise LibraryError("A recipe needs a name.")
        if len(name) > 60:
            raise LibraryError("Keep the name under 60 characters.")
        if not isinstance(settings, dict):
            raise LibraryError("A recipe consists of settings.")
        clean = _recipe_settings(settings)
        if not clean:
            raise LibraryError("There were no usable settings in this recipe.")
        if material_id is not None and not any(
            m["id"] == material_id for m in self.materials()
        ):
            raise LibraryError(f"Material {material_id} does not exist.")
        with self._connect() as db:
            existing = db.execute(
                """SELECT id FROM grid_recipe
                   WHERE name = ? COLLATE NOCASE AND material_id IS ?""",
                (name, material_id),
            ).fetchone()
            if existing is None:
                cursor = db.execute(
                    "INSERT INTO grid_recipe (name, material_id, settings) VALUES (?, ?, ?)",
                    (name, material_id, json.dumps(clean)),
                )
                recipe_id = cursor.lastrowid
            else:
                recipe_id = existing["id"]
                db.execute(
                    """UPDATE grid_recipe SET name = ?, settings = ?, updated_at = ?
                       WHERE id = ?""",
                    (name, json.dumps(clean), _now(), recipe_id),
                )
        return self.grid_recipe(recipe_id)

    def grid_recipe(self, recipe_id: int) -> dict:
        for recipe in self.grid_recipes():
            if recipe["id"] == recipe_id:
                return recipe
        raise LibraryError(f"Recipe {recipe_id} does not exist.")

    def remove_grid_recipe(self, recipe_id: int) -> dict:
        with self._connect() as db:
            cursor = db.execute("DELETE FROM grid_recipe WHERE id = ?", (recipe_id,))
            if not cursor.rowcount:
                raise LibraryError(f"Recipe {recipe_id} does not exist.")
        return {"removed": recipe_id}

    def grid_operations(self) -> dict:
        """Which operation belongs to which grid — for the layer panel."""
        mapping = {}
        # test_grids() is newest first; setdefault lets the newest win. Element ids are
        # handed out per document, so an old grid can carry the same operation ids as the
        # current one.
        for grid in self.test_grids():
            for cell in grid["cells"]:
                op = cell.get("operation_id")
                if op:
                    mapping.setdefault(op, {
                        "grid_id": grid["id"],
                        "row": cell["row"],
                        "column": cell["column"],
                        "speed_mm_s": cell["speed_mm_s"],
                        "power_percent": cell["power_percent"],
                    })
        return mapping

    def add_test_grid(self, plan: dict, cells: list[dict]) -> dict:
        with self._connect() as db:
            cursor = db.execute(
                """INSERT INTO test_grid (material_id, machine_id, thickness_mm, operation,
                        passes,
                        speed_min, speed_max, speed_steps, power_min, power_max, power_steps,
                        interval_min, interval_max, interval_steps,
                        row_axis, column_axis, rows, columns,
                        cell_mm, gap_mm, origin_x_mm, origin_y_mm, cells,
                        anchor, text_enabled, border_enabled,
                        label_speed_mm_s, label_power_percent)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                           ?, ?, ?, ?, ?, ?)""",
                (
                    plan.get("material_id"),
                    plan.get("machine_id"),
                    plan.get("thickness_mm"),
                    plan["operation"],
                    int(plan.get("passes") or 1),
                    plan["speed_min"],
                    plan["speed_max"],
                    plan["speed_steps"],
                    plan["power_min"],
                    plan["power_max"],
                    plan["power_steps"],
                    plan.get("interval_min"),
                    plan.get("interval_max"),
                    plan.get("interval_steps"),
                    plan.get("row_axis") or "speed",
                    plan.get("column_axis") or "power",
                    plan.get("rows") or plan["speed_steps"],
                    plan.get("columns") or plan["power_steps"],
                    plan["cell_mm"],
                    plan["gap_mm"],
                    plan["origin_x_mm"],
                    plan["origin_y_mm"],
                    json.dumps(cells),
                    plan.get("anchor") or "corner",
                    0 if plan.get("text") is False else 1,
                    1 if plan.get("border") else 0,
                    plan.get("label_speed_mm_s"),
                    plan.get("label_power_percent"),
                ),
            )
            grid_id = cursor.lastrowid
        return self.test_grid(grid_id)

    def remove_test_grid(self, grid_id: int) -> dict:
        with self._connect() as db:
            cursor = db.execute("DELETE FROM test_grid WHERE id = ?", (grid_id,))
            if not cursor.rowcount:
                raise LibraryError(f"Test grid {grid_id} does not exist.")
        return {"removed": grid_id}

    def set_grid_photo(self, grid_id: int, suffix: str, data: bytes) -> dict:
        """Store the photo of a burned grid and remember where it went."""
        grid = self.test_grid(grid_id)
        safe = (suffix or "").lower()
        if safe not in (".jpg", ".jpeg", ".png", ".webp", ".heic"):
            raise LibraryError(f"Unknown photo format: {suffix or '(none)'}")
        target = self.photos / f"grid-{grid['id']}{safe}"
        target.write_bytes(data)
        with self._connect() as db:
            db.execute(
                "UPDATE test_grid SET photo_path = ? WHERE id = ?",
                (str(target), grid_id),
            )
        return self.test_grid(grid_id)

    def mark_cell(self, grid_id: int, row: int, column: int, preset_id: int) -> dict:
        """Record which preset came out of which cell, for provenance."""
        grid = self.test_grid(grid_id)
        cells = grid["cells"]
        for cell in cells:
            if cell["row"] == row and cell["column"] == column:
                cell["preset_id"] = preset_id
                break
        else:
            raise LibraryError(f"Cell {row},{column} does not belong to grid {grid_id}.")
        with self._connect() as db:
            db.execute(
                "UPDATE test_grid SET cells = ? WHERE id = ?",
                (json.dumps(cells), grid_id),
            )
        return self.test_grid(grid_id)

    # --------------------------------------------------- uitwisselen (B7)

    def export_bundle(self, filename: str = "library") -> Path:
        """
        The whole library as one file: data plus evidence.

        Materials, presets with their provenance, machine profiles, test grids and those
        grids' photos. The photos have to come along: a preset with source "testgrid" and no
        photo is a claim with nothing left under it.
        """
        import tempfile
        import zipfile
        from datetime import datetime, timezone

        safe = Path(str(filename)).name or "library"
        if not safe.lower().endswith(BUNDLE_SUFFIX):
            safe += BUNDLE_SUFFIX
        target = Path(tempfile.mkdtemp(prefix="openkerf-lib-")) / safe

        grids = self.test_grids()
        presets = []
        for preset in self.presets():
            # The join fields from the view do not belong in the file: they are derived
            # again on reading. The names do stay, because they are what the merging works
            # on.
            for key in (
                "grid_photo", "grid_date", "grid_id", "grid_cell", "grid_aligned"
            ):
                preset.pop(key, None)
            presets.append(preset)

        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as bundle:
            for grid in grids:
                path = grid.pop("photo_path", None)
                grid["photo_file"] = None
                if path and Path(path).exists():
                    name = f"{BUNDLE_PHOTOS}/grid-{grid['id']}{Path(path).suffix.lower()}"
                    bundle.write(path, name)
                    grid["photo_file"] = name
            payload = {
                "format": BUNDLE_FORMAT,
                "version": BUNDLE_VERSION,
                "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "machines": self.machines(),
                "materials": self.materials(),
                "presets": presets,
                "test_grids": grids,
                # T7: a named recipe is work you sorted out yourself, so it belongs in the
                # same backup as the rest.
                "grid_recipes": self.grid_recipes(),
            }
            bundle.writestr(
                BUNDLE_INDEX,
                json.dumps(payload, indent=1, ensure_ascii=False, default=str),
            )
        return target

    def read_bundle(self, path) -> dict:
        """Read it and refuse at once what is not a library."""
        import zipfile

        source = Path(path)
        if not source.exists():
            raise LibraryError("That file is not there (any more).")
        if not zipfile.is_zipfile(source):
            raise LibraryError(
                "This is not an OpenKerf library. A library file ends "
                f"in {BUNDLE_SUFFIX}."
            )
        with zipfile.ZipFile(source) as bundle:
            names = bundle.namelist()
            index = BUNDLE_INDEX if BUNDLE_INDEX in names else LEGACY_BUNDLE_INDEX
            if index not in names:
                raise LibraryError("This file holds no library.")
            try:
                data = json.loads(bundle.read(index))
            except ValueError as e:
                raise LibraryError("The library in this file is damaged.") from e
        if not isinstance(data, dict) or data.get("format") != BUNDLE_FORMAT:
            raise LibraryError("This file did not come from an OpenKerf library.")
        if int(data.get("version") or 0) > BUNDLE_VERSION:
            raise LibraryError(
                "This file comes from a newer version of OpenKerf. Update first."
            )
        return data

    def preview_import(self, path, merge_materials: dict | None = None) -> dict:
        """
        What is going to happen, before it happens.

        Nobody wants to discover they have overwritten their own measurements. So this
        works out both choices — merging *and* replacing — so that the difference is on the
        screen at the moment you choose.
        """
        data = self.read_bundle(path)
        linked = _merge_map(merge_materials)

        incoming = [m for m in (data.get("materials") or []) if m.get("name")]
        mine = self.materials()
        new, existing, looks_like = [], [], []
        names = {}
        for material in incoming:
            name = str(material["name"]).strip()
            pointed_at = linked.get(_norm(name))
            match = next((m for m in mine if m["id"] == pointed_at), None) if pointed_at else None
            match = match or _same_material(name, material.get("synonyms"), mine)
            if match is not None:
                existing.append({"name": name, "as": match["name"], "material_id": match["id"]})
                names[material.get("id")] = match["name"]
                continue
            names[material.get("id")] = name
            new.append(name)
            similar = _looks_like(name, mine)
            if similar:
                neighbour, why = similar
                looks_like.append(
                    {
                        "name": name,
                        "match": neighbour["name"],
                        "material_id": neighbour["id"],
                        "why": why,
                    }
                )

        mine_by_key = {}
        for preset in self.presets():
            mine_by_key.setdefault(_preset_key(preset["material_name"], preset), preset)
        new_presets, identical, clashes = 0, 0, []
        for preset in data.get("presets") or []:
            name = names.get(preset.get("material_id")) or preset.get("material_name")
            mine = mine_by_key.get(_preset_key(name, preset))
            if mine is None:
                new_presets += 1
            elif _same_values(mine, preset):
                identical += 1
            else:
                clashes.append(
                    {
                        "material": name,
                        "thickness_mm": preset.get("thickness_mm"),
                        "operation": preset.get("operation"),
                        "machine": preset.get("machine_name"),
                        "mine": _values(mine),
                        "theirs": _values(preset),
                    }
                )

        my_grids = {_grid_key(g) for g in self.test_grids()}
        grids = data.get("test_grids") or []
        new_grids = sum(1 for g in grids if _grid_key(g) not in my_grids)
        my_machines = {_norm(m["name"]) for m in self.machines()}
        machines = [m for m in (data.get("machines") or []) if m.get("name")]

        current = self._counts()
        return {
            "exported_at": data.get("exported_at"),
            "contains": {
                "materials": len(incoming),
                "presets": len(data.get("presets") or []),
                "machines": len(machines),
                "test_grids": len(grids),
                "photos": sum(1 for g in grids if g.get("photo_file")),
            },
            "current": current,
            "merge": {
                "materials": {"new": new, "existing": existing, "similar": looks_like},
                "machines": {
                    "new": [m["name"] for m in machines if _norm(m["name"]) not in my_machines],
                    "existing": [m["name"] for m in machines if _norm(m["name"]) in my_machines],
                },
                "presets": {
                    "new": new_presets,
                    "identical": identical,
                    "conflicts": clashes,
                },
                "test_grids": {"new": new_grids, "existing": len(grids) - new_grids},
            },
            "replace": {"removes": current},
        }

    def import_bundle(
        self,
        path,
        mode: str = "merge",
        merge_materials: dict | None = None,
        on_conflict: str = "mine",
    ) -> dict:
        """
        Actually reading the file in.

        `mode` is an explicit choice: merging leaves what you have, replacing throws it
        away. `on_conflict` decides who wins when the same preset carries different numbers on
        both sides; your own by default, because you measured those yourself.

        The source stays as it was. This is your own library coming back from a backup or
        another computer — rewriting "testgrid" to "imported" would throw away exactly the
        evidence this function is meant to preserve. The photos come along for the same
        reason.
        """
        import zipfile

        if mode not in ("merge", "replace"):
            raise LibraryError(f"Unknown choice: {mode}")
        if on_conflict not in ("mine", "file"):
            raise LibraryError(f"Unknown choice on a clash: {on_conflict}")
        data = self.read_bundle(path)
        linked = _merge_map(merge_materials)
        removed = self._counts() if mode == "replace" else None
        if mode == "replace":
            self.clear()

        # 1. Materials. Everything hangs off them, so this goes first.
        material_id = {}
        for material in data.get("materials") or []:
            name = str(material.get("name") or "").strip()
            if not name:
                continue
            mine = self.materials()
            pointed_at = linked.get(_norm(name))
            match = next((m for m in mine if m["id"] == pointed_at), None) if pointed_at else None
            match = match or _same_material(name, material.get("synonyms"), mine)
            if match is None:
                match = self.add_material(name, material.get("synonyms"))
            material_id[material.get("id")] = match["id"]

        # 2. Machine profiles, by name.
        machine_id = {}
        for machine in data.get("machines") or []:
            name = str(machine.get("name") or "").strip()
            if not name:
                continue
            mine = self.machines()
            match = next((m for m in mine if _norm(m["name"]) == _norm(name)), None)
            if match is None and machine.get("device_path"):
                # One profile per device is a hard rule in the schema. If the file carries
                # a different *word* for the same laser, that is the same laser and not a
                # second one.
                match = next(
                    (m for m in mine if m["device_path"] == machine["device_path"]),
                    None,
                )
            if match is None:
                match = self.add_machine(**{k: v for k, v in machine.items() if k != "id"})
            machine_id[machine.get("id")] = match["id"]

        with zipfile.ZipFile(Path(path)) as bundle:
            names = set(bundle.namelist())

            # 3. Test grids, with their photo. Before the presets, because a preset points
            #    with origin_id at the grid it came from.
            grid_id = {}
            my_grids = {_grid_key(g): g["id"] for g in self.test_grids()}
            for grid in data.get("test_grids") or []:
                already = my_grids.get(_grid_key(grid))
                if already is not None:
                    grid_id[grid.get("id")] = already
                    continue
                fresh = self._insert_grid(grid, material_id, machine_id)
                grid_id[grid.get("id")] = fresh
                photo = grid.get("photo_file")
                if photo and photo in names:
                    self.set_grid_photo(fresh, Path(photo).suffix.lower(), bundle.read(photo))

        # 4. Presets, with their provenance renumbered to the new grid ids.
        mine_by_key = {}
        for preset in self.presets():
            mine_by_key.setdefault(_preset_key(preset["material_name"], preset), preset)
        source_name = {
            m.get("id"): str(m.get("name") or "").strip()
            for m in data.get("materials") or []
        }
        preset_id = {}
        added = updated = skipped = 0
        for preset in data.get("presets") or []:
            target = material_id.get(preset.get("material_id"))
            if target is None:
                skipped += 1
                continue
            name = next(
                (m["name"] for m in self.materials() if m["id"] == target),
                source_name.get(preset.get("material_id"), ""),
            )
            mine = mine_by_key.get(_preset_key(name, preset))
            if mine is not None:
                if _same_values(mine, preset) or on_conflict == "mine":
                    preset_id[preset.get("id")] = mine["id"]
                    skipped += 1
                    continue
                self.update_preset(
                    mine["id"],
                    speed_mm_s=preset.get("speed_mm_s"),
                    power_percent=preset.get("power_percent"),
                    passes=preset.get("passes") or 1,
                    interval_mm=preset.get("interval_mm"),
                )
                preset_id[preset.get("id")] = mine["id"]
                updated += 1
                continue
            preset_id[preset.get("id")] = self._insert_preset(
                preset, target, machine_id, grid_id
            )
            added += 1

        # 5. And back: which square of which grid became which preset. Without this step
        #    the photo is still there but points at nothing.
        self._relink_cells(grid_id, preset_id)

        # 6. The named recipes (T7), with their material renumbered. A recipe of your own
        #    with the same name stays: as with presets, your own setting is the setting you
        #    measured.
        recipes = 0
        my_recipes = {
            (r["name"].casefold(), r["material_id"]) for r in self.grid_recipes()
        }
        for recipe in data.get("grid_recipes") or []:
            name = str(recipe.get("name") or "").strip()
            if not name:
                continue
            target = material_id.get(recipe.get("material_id"))
            if (name.casefold(), target) in my_recipes:
                continue
            settings = recipe.get("settings")
            if isinstance(settings, str):
                settings = json.loads(settings)
            try:
                self.save_grid_recipe(name, settings or {}, target)
            except LibraryError:
                continue
            recipes += 1

        return {
            "mode": mode,
            "removed": removed,
            "materials": len(material_id),
            "machines": len(machine_id),
            "test_grids": len({v for v in grid_id.values()}),
            "grid_recipes": recipes,
            "presets": {
                "added": added,
                "updated": updated,
                "skipped": skipped,
            },
        }

    def clear(self) -> dict:
        """Everything gone — only for 'replace', and only after a confirmation."""
        gone = self._counts()
        with self._connect() as db:
            for table in (
                "preset", "test_grid", "grid_recipe", "material", "machine_profile"
            ):
                db.execute(f"DELETE FROM {table}")
        for photo in self.photos.glob("grid-*"):
            photo.unlink(missing_ok=True)
        return gone

    def _counts(self) -> dict:
        with self._connect() as db:
            def count_of(table):
                return db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]

            return {
                "materials": count_of("material"),
                "presets": count_of("preset"),
                "machines": count_of("machine_profile"),
                "test_grids": count_of("test_grid"),
            }

    def _insert_grid(self, grid: dict, material_id: dict, machine_id: dict) -> int:
        """Take over a grid with its date: that date is the evidence."""
        cells = grid.get("cells")
        if isinstance(cells, str):
            cells = json.loads(cells)
        with self._connect() as db:
            cursor = db.execute(
                """INSERT INTO test_grid (material_id, machine_id, thickness_mm, operation,
                        speed_min, speed_max, speed_steps, power_min, power_max, power_steps,
                        interval_min, interval_max, interval_steps,
                        row_axis, column_axis, rows, columns,
                        cell_mm, gap_mm, origin_x_mm, origin_y_mm, cells, alignment,
                        group_id, created_at,
                        anchor, text_enabled, border_enabled,
                        label_speed_mm_s, label_power_percent)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                           ?, ?, ?, ?, ?)""",
                (
                    material_id.get(grid.get("material_id")),
                    machine_id.get(grid.get("machine_id")),
                    grid.get("thickness_mm"),
                    grid.get("operation") or "snijden",
                    grid.get("speed_min"), grid.get("speed_max"), grid.get("speed_steps"),
                    grid.get("power_min"), grid.get("power_max"), grid.get("power_steps"),
                    grid.get("interval_min"), grid.get("interval_max"),
                    grid.get("interval_steps"),
                    grid.get("row_axis") or "speed",
                    grid.get("column_axis") or "power",
                    grid.get("rows") or grid.get("speed_steps"),
                    grid.get("columns") or grid.get("power_steps"),
                    grid.get("cell_mm"), grid.get("gap_mm"),
                    grid.get("origin_x_mm"), grid.get("origin_y_mm"),
                    json.dumps(cells or []),
                    # The alignment was done by hand; it belongs with the photo and so
                    # comes back from a backup with it.
                    json.dumps(_alignment(grid.get("alignment")))
                    if _alignment(grid.get("alignment"))
                    else None,
                    grid.get("group_id"),
                    grid.get("created_at") or _now(),
                    grid.get("anchor") or "corner",
                    0 if grid.get("text_enabled") is False else 1,
                    1 if grid.get("border_enabled") else 0,
                    grid.get("label_speed_mm_s"),
                    grid.get("label_power_percent"),
                ),
            )
            return cursor.lastrowid

    def _insert_preset(self, preset: dict, material_id: int, machine_id: dict, grid_id: dict) -> int:
        origin = preset.get("origin_id")
        if isinstance(origin, str) and origin.startswith("testgrid:"):
            old = origin.split(":", 1)[1]
            fresh = grid_id.get(int(old)) if old.isdigit() else None
            origin = f"testgrid:{fresh}" if fresh else None
        source = preset.get("source")
        with self._connect() as db:
            cursor = db.execute(
                """INSERT INTO preset (material_id, machine_id, thickness_mm, operation,
                        speed_mm_s, power_percent, passes, interval_mm, air_assist,
                        focus_offset_mm, source, origin_id, note, last_used_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    material_id,
                    machine_id.get(preset.get("machine_id")),
                    preset.get("thickness_mm"),
                    preset.get("operation"),
                    preset.get("speed_mm_s"),
                    preset.get("power_percent"),
                    int(preset.get("passes") or 1),
                    preset.get("interval_mm"),
                    1 if preset.get("air_assist", True) else 0,
                    preset.get("focus_offset_mm") or 0,
                    source if source in SOURCES else "geimporteerd",
                    origin,
                    str(preset.get("note") or ""),
                    preset.get("last_used_at"),
                    preset.get("created_at") or _now(),
                ),
            )
            return cursor.lastrowid

    def _relink_cells(self, grid_id: dict, preset_id: dict) -> None:
        if not grid_id or not preset_id:
            return
        for old, fresh in grid_id.items():
            try:
                grid = self.test_grid(fresh)
            except LibraryError:
                continue
            veranderd = False
            for cel in grid["cells"]:
                target = preset_id.get(cel.get("preset_id"))
                if target is not None and target != cel.get("preset_id"):
                    cel["preset_id"] = target
                    veranderd = True
            if veranderd:
                with self._connect() as db:
                    db.execute(
                        "UPDATE test_grid SET cells = ? WHERE id = ?",
                        (json.dumps(grid["cells"]), fresh),
                    )

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _one(db, table: str, row_id: int) -> dict:
        row = db.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()
        return dict(row)


def _grid_row(row) -> dict:
    data = dict(row)
    data["cells"] = json.loads(data["cells"])
    data["alignment"] = _alignment(data.get("alignment"))
    # SQLite has no booleans; the wizard does set ticks with them.
    for key in ("text_enabled", "border_enabled"):
        if key in data:
            data[key] = bool(data[key])
    return data


# The values of the quantities that are *not* on an axis. They belong to a recipe —
# otherwise "engrave birch at 40%" is not a recipe but half a recipe — but not to
# GRID_DEFAULTS, because there they appear as min == max in the series.
_VASTE_VELDEN = ("speed_mm_s", "power_percent", "interval_mm")


def _recipe_settings(raw: dict) -> dict:
    """
    Only the keys that describe a grid, in the right type.

    A recipe is a JSON blob in the database, and that is exactly where rubbish gets in. Here
    what does not belong goes out, so that the wizard can trust it blindly.
    """
    uit = {}
    for key in tuple(Library.GRID_DEFAULTS) + _VASTE_VELDEN:
        if key not in raw or raw[key] is None:
            continue
        value = raw[key]
        if key in ("text_enabled", "border_enabled"):
            uit[key] = bool(value)
        elif key in ("operation", "row_axis", "column_axis", "anchor"):
            uit[key] = str(value)
        else:
            try:
                uit[key] = float(value)
            except (TypeError, ValueError):
                continue
    return uit


def _with_anchor(setting: dict) -> dict:
    """
    The point as the user typed it: a corner, or a centre (T9).

    The database always holds the top-left corner of the squares — that is what the photo
    overlay computes with. Anybody who laid the board out on its centre has to see that
    centre back in the form and not a corner they never typed. The centre comes from the same
    `plan_grid` that worked it out; rebuilding it here would give two sums that can drift
    apart.
    """
    anchor_x = setting.get("origin_x_mm")
    anchor_y = setting.get("origin_y_mm")
    setting["anchor_x_mm"] = anchor_x
    setting["anchor_y_mm"] = anchor_y
    if setting.get("anchor") != "center":
        return setting
    from .testgrid import plan_grid

    fields = {k: v for k, v in setting.items() if v is not None}
    fields["text"] = fields.pop("text_enabled", True)
    fields["border"] = fields.pop("border_enabled", False)
    fields.pop("anchor", None)
    fields.pop("anchor_x_mm", None)
    fields.pop("anchor_y_mm", None)
    fields.pop("thickness_mm", None)
    for as_ in ("speed", "power", "interval"):
        if fields.get(f"{as_}_steps") == 1:
            fields.pop(f"{as_}_steps", None)
            fields.pop(f"{as_}_max", None)
    try:
        plan = plan_grid(**fields)[0]
    except Exception:
        return setting
    setting["anchor_x_mm"] = plan["center_x_mm"]
    setting["anchor_y_mm"] = plan["center_y_mm"]
    return setting


def _alignment(raw):
    """The four corners as a list of points, or None when nothing is stored."""
    if not raw:
        return None
    try:
        points = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return None
    if not isinstance(points, list) or len(points) != 4:
        return None
    try:
        return [
            {"x": float(p["x"]), "y": float(p["y"])}
            for p in points
        ]
    except (TypeError, KeyError, ValueError):
        return None


def _preset_row(row) -> dict:
    data = dict(row)
    data["air_assist"] = bool(data["air_assist"])
    # SQLite hands back 0/1 for a boolean expression; the card that shows this has to be
    # able to make "yes or no" of it without having to think about it.
    if "grid_aligned" in data:
        data["grid_aligned"] = bool(data["grid_aligned"])
    # Which square of the grid this preset comes from. That is the provenance in one line:
    # "row 2, column 3" can be pointed at on the photo, "testgrid" cannot.
    cells = data.pop("grid_cells", None)
    data["grid_cell"] = None
    if cells:
        for cel in json.loads(cells):
            if cel.get("preset_id") == data["id"]:
                data["grid_cell"] = {"row": cel["row"], "column": cel["column"]}
                break
    return data


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _norm(text) -> str:
    """Comparing names without accents, capitals or double spaces."""
    flat = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore")
    return re.sub(r"\s+", " ", flat.decode().lower()).strip()


def _merge_map(choices: dict | None) -> dict:
    """{"Birch plywood": 3} → {"birch plywood": 3}, so that the name matters and the form does not."""
    return {_norm(k): int(v) for k, v in (choices or {}).items() if v is not None}


def _same_material(name: str, synonyms, existing: list[dict]) -> dict | None:
    """Exactly the same name, or a name already known as a synonym."""
    target = _norm(name)
    incoming = {_norm(s) for s in (synonyms or [])}
    for material in existing:
        if _norm(material["name"]) == target:
            return material
        known = {_norm(s) for s in material.get("synonyms") or []}
        if target in known or _norm(material["name"]) in incoming or (known & incoming):
            return material
    return None


def _families(name: str) -> set[str]:
    """
    Which material families a name holds.

    Splitting on separate words is not enough: "Berkentriplex" is one word that says two
    things. So we look for the family words *inside* the text.
    """
    flat = _norm(name)
    found = set()
    for family, words in MATERIAL_FAMILIES.items():
        if any(word in flat for word in words):
            found.add(family)
    return found


def _looks_like(name: str, existing: list[dict]) -> tuple[dict, str] | None:
    """
    A material that is probably the same, with the reason beside it.

    Two shared families is the threshold: "birch" shared alone could be birch plywood beside
    solid birch, and those are two very different cuts. Birch *and* plywood together is one
    board.
    """
    families = _families(name)
    if len(families) < 2:
        return None
    for material in existing:
        shared = families & _families(material["name"])
        if len(shared) >= 2:
            words = sorted(shared)
            return material, f"both are about {' and '.join(words)}"
    return None


def _round_mm(value):
    """3 and 3.0 are the same thickness; None stays None."""
    return None if value in (None, "") else round(float(value), 2)


def _preset_key(material_name, preset: dict) -> tuple:
    """When two presets are about the same thing: same board, same cut, same laser."""
    return (
        _norm(material_name),
        _round_mm(preset.get("thickness_mm")),
        str(preset.get("operation") or ""),
        _norm(preset.get("machine_name") or ""),
    )


def _values(preset: dict) -> dict:
    return {
        "speed_mm_s": preset.get("speed_mm_s"),
        "power_percent": preset.get("power_percent"),
        "passes": preset.get("passes") or 1,
        "source": preset.get("source"),
        "note": preset.get("note") or "",
    }


def _same_values(mine: dict, theirs: dict) -> bool:
    if _round_mm(mine.get("interval_mm")) != _round_mm(theirs.get("interval_mm")):
        return False
    for key in ("speed_mm_s", "power_percent"):
        if _round_mm(mine.get(key)) != _round_mm(theirs.get(key)):
            return False
    return int(mine.get("passes") or 1) == int(theirs.get("passes") or 1)


def _grid_key(grid: dict) -> tuple:
    """A grid is the same grid when it was burned at the same moment."""
    return (
        str(grid.get("created_at") or ""),
        str(grid.get("operation") or ""),
        _round_mm(grid.get("speed_min")),
        _round_mm(grid.get("power_min")),
        _round_mm(grid.get("cell_mm")),
    )


def _percent(value):
    number = _number(value, "power_percent", positive=True)
    if number > 100:
        raise LibraryError("power_percent cannot go above 100.")
    return number


def _number(value, name: str, positive: bool = False, optional: bool = False):
    if value is None or value == "":
        if optional:
            return None
        raise LibraryError(f"{name} is verplicht.")
    try:
        number = float(value)
    except (TypeError, ValueError) as e:
        raise LibraryError(f"{name} has to be a number.") from e
    if positive and number <= 0:
        raise LibraryError(f"{name} has to be greater than zero.")
    return number
