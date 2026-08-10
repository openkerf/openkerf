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

import sqlite3
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
    air_assist    INTEGER NOT NULL DEFAULT 1,
    focus_offset_mm REAL NOT NULL DEFAULT 0,
    -- handmatig | geextrapoleerd | testraster | geimporteerd
    source        TEXT NOT NULL DEFAULT 'handmatig',
    origin_id     TEXT,
    note          TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS preset_material ON preset(material_id);
"""

OPERATIONS = ("snijden", "graveren-vector", "graveren-raster", "markeren")
SOURCES = ("handmatig", "geextrapoleerd", "testraster", "geimporteerd")


class LibraryError(RuntimeError):
    pass


def default_path(kernel) -> Path:
    """Beside MeerK40t's settings, so a profile keeps its own library."""
    from meerk40t.kernel.functions import get_safe_path

    directory = Path(get_safe_path(kernel.name, create=True))
    return directory / "openkerf-library.db"


class Library:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(SCHEMA)

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
            raise LibraryError("Een machineprofiel heeft een naam nodig.")
        with self._connect() as db:
            cursor = db.execute(
                """INSERT INTO machine_profile
                   (name, laser_type, power_watt, lens_mm, bed_width_mm, bed_height_mm)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    name,
                    fields.get("laser_type") or "co2-glass",
                    _number(fields.get("power_watt"), "power_watt", optional=True),
                    _number(fields.get("lens_mm"), "lens_mm", optional=True),
                    _number(fields.get("bed_width_mm"), "bed_width_mm", optional=True),
                    _number(fields.get("bed_height_mm"), "bed_height_mm", optional=True),
                ),
            )
            return self._one(db, "machine_profile", cursor.lastrowid)

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
            raise LibraryError("Een materiaal heeft een naam nodig.")
        joined = "|".join(str(s).strip() for s in (synonyms or []) if str(s).strip())
        try:
            with self._connect() as db:
                cursor = db.execute(
                    "INSERT INTO material (name, synonyms) VALUES (?, ?)", (name, joined)
                )
                row = self._one(db, "material", cursor.lastrowid)
        except sqlite3.IntegrityError as e:
            raise LibraryError(f"Materiaal '{name}' bestaat al.") from e
        row["synonyms"] = [s for s in row["synonyms"].split("|") if s]
        return row

    def remove_material(self, material_id: int) -> dict:
        with self._connect() as db:
            cursor = db.execute("DELETE FROM material WHERE id = ?", (material_id,))
            if not cursor.rowcount:
                raise LibraryError(f"Materiaal {material_id} bestaat niet.")
        return {"removed": material_id}

    # ---------------------------------------------------------------- presets

    def presets(self, material_id=None, operation=None) -> list[dict]:
        query = """
            SELECT p.*, m.name AS material_name, mp.name AS machine_name
            FROM preset p
            JOIN material m ON m.id = p.material_id
            LEFT JOIN machine_profile mp ON mp.id = p.machine_id
        """
        clauses, params = [], []
        if material_id is not None:
            clauses.append("p.material_id = ?")
            params.append(material_id)
        if operation:
            clauses.append("p.operation = ?")
            params.append(operation)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY m.name, p.thickness_mm, p.operation"
        with self._connect() as db:
            return [_preset_row(r) for r in db.execute(query, params)]

    def add_preset(self, **fields) -> dict:
        material_id = fields.get("material_id")
        if material_id is None:
            raise LibraryError("Een preset hoort bij een materiaal.")
        operation = str(fields.get("operation") or "").strip()
        if operation not in OPERATIONS:
            raise LibraryError(f"Onbekende bewerking: {operation or '(leeg)'}")
        source = str(fields.get("source") or "handmatig")
        if source not in SOURCES:
            raise LibraryError(f"Onbekende bron: {source}")

        speed = _number(fields.get("speed_mm_s"), "speed_mm_s", positive=True)
        power = _number(fields.get("power_percent"), "power_percent", positive=True)
        if power > 100:
            raise LibraryError("power_percent kan niet boven 100.")

        try:
            with self._connect() as db:
                cursor = db.execute(
                    """INSERT INTO preset (material_id, machine_id, thickness_mm, operation,
                            speed_mm_s, power_percent, passes, air_assist, focus_offset_mm,
                            source, origin_id, note)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        material_id,
                        fields.get("machine_id"),
                        _number(fields.get("thickness_mm"), "thickness_mm", optional=True),
                        operation,
                        speed,
                        power,
                        int(fields.get("passes") or 1),
                        1 if fields.get("air_assist", True) else 0,
                        _number(fields.get("focus_offset_mm") or 0, "focus_offset_mm"),
                        source,
                        fields.get("origin_id"),
                        str(fields.get("note") or ""),
                    ),
                )
                preset_id = cursor.lastrowid
        except sqlite3.IntegrityError as e:
            raise LibraryError("Dat materiaal bestaat niet.") from e
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
            raise LibraryError(f"Preset {preset_id} bestaat niet.")
        return _preset_row(row)

    def remove_preset(self, preset_id: int) -> dict:
        with self._connect() as db:
            cursor = db.execute("DELETE FROM preset WHERE id = ?", (preset_id,))
            if not cursor.rowcount:
                raise LibraryError(f"Preset {preset_id} bestaat niet.")
        return {"removed": preset_id}

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _one(db, table: str, row_id: int) -> dict:
        row = db.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()
        return dict(row)


def _preset_row(row) -> dict:
    data = dict(row)
    data["air_assist"] = bool(data["air_assist"])
    return data


def _number(value, name: str, positive: bool = False, optional: bool = False):
    if value is None or value == "":
        if optional:
            return None
        raise LibraryError(f"{name} is verplicht.")
    try:
        number = float(value)
    except (TypeError, ValueError) as e:
        raise LibraryError(f"{name} moet een getal zijn.") from e
    if positive and number <= 0:
        raise LibraryError(f"{name} moet groter dan nul zijn.")
    return number
