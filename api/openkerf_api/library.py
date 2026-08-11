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
    -- Het pad van de device-service in de engine ("lhystudios"). Hiermee weet
    -- de bibliotheek welk profiel bij de machine hoort die nú actief is; zonder
    -- die koppeling is een preset een uitspraak over niets.
    device_path  TEXT,
    -- Wat deze machine kán. Bepaalt wat er in de jog verschijnt.
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
    air_assist    INTEGER NOT NULL DEFAULT 1,
    focus_offset_mm REAL NOT NULL DEFAULT 0,
    -- handmatig | geextrapoleerd | testraster | geimporteerd
    source        TEXT NOT NULL DEFAULT 'handmatig',
    origin_id     TEXT,
    note          TEXT NOT NULL DEFAULT '',
    -- Wanneer deze instelling voor het laatst op een laag gezet is. Wie
    -- gisteren 3 mm berken sneed, zoekt vandaag niet alfabetisch; hij zoekt
    -- wat hij gisteren gebruikte.
    last_used_at  TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS test_grid (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id   INTEGER REFERENCES material(id) ON DELETE SET NULL,
    machine_id    INTEGER REFERENCES machine_profile(id) ON DELETE SET NULL,
    thickness_mm  REAL,
    operation     TEXT NOT NULL,
    speed_min     REAL NOT NULL,
    speed_max     REAL NOT NULL,
    speed_steps   INTEGER NOT NULL,
    power_min     REAL NOT NULL,
    power_max     REAL NOT NULL,
    power_steps   INTEGER NOT NULL,
    cell_mm       REAL NOT NULL,
    gap_mm        REAL NOT NULL,
    origin_x_mm   REAL NOT NULL,
    origin_y_mm   REAL NOT NULL,
    -- Elke cel met haar positie en instellingen, zodat de foto-overlay later
    -- weet welk vakje bij welke snelheid en vermogen hoort.
    cells         TEXT NOT NULL,
    photo_path    TEXT,
    group_id      TEXT,
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
        # Foto's als bestand naast de database: dat houdt de database klein en
        # de foto's gewoon te bekijken met een verkenner.
        self.photos = self.path.parent / "openkerf-photos"
        self.photos.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(SCHEMA)
            self._migrate(db)

    @staticmethod
    def _migrate(db):
        """Kolommen die later bijkwamen, voor databases van vóór die versie."""
        existing = {row["name"] for row in db.execute("PRAGMA table_info(test_grid)")}
        if "group_id" not in existing:
            db.execute("ALTER TABLE test_grid ADD COLUMN group_id TEXT")

        presets = {row["name"] for row in db.execute("PRAGMA table_info(preset)")}
        if "last_used_at" not in presets:
            db.execute("ALTER TABLE preset ADD COLUMN last_used_at TEXT")

        profiel = {row["name"] for row in db.execute("PRAGMA table_info(machine_profile)")}
        for kolom, definitie in (
            ("device_path", "TEXT"),
            ("has_z", "INTEGER NOT NULL DEFAULT 0"),
            ("has_autofocus", "INTEGER NOT NULL DEFAULT 0"),
        ):
            if kolom not in profiel:
                db.execute(f"ALTER TABLE machine_profile ADD COLUMN {kolom} {definitie}")

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
        Het profiel van de machine die nu actief is, desnoods vers aangemaakt.

        Een preset is een uitspraak over *deze laser op dit materiaal*. Zonder
        een profiel om aan te hangen zou elke preset "voor alle machines" zijn,
        en dat is precies de verwarring die dit oplost.
        """
        pad = str(device_path or "").strip()
        if not pad:
            raise LibraryError("Er is geen actieve machine om bij aan te sluiten.")
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM machine_profile WHERE device_path = ?", (pad,)
            ).fetchone()
            if row is not None:
                return dict(row)
        return self.add_machine(name=label or pad, device_path=pad)

    def update_machine(self, machine_id: int, fields: dict) -> dict:
        toegestaan = (
            "name", "laser_type", "power_watt", "lens_mm",
            "bed_width_mm", "bed_height_mm", "has_z", "has_autofocus",
        )
        stukken, waarden = [], []
        for sleutel in toegestaan:
            if sleutel not in fields:
                continue
            stukken.append(f"{sleutel} = ?")
            if sleutel in ("has_z", "has_autofocus"):
                waarden.append(1 if fields[sleutel] else 0)
            elif sleutel in ("name", "laser_type"):
                waarden.append(str(fields[sleutel]))
            else:
                waarden.append(_number(fields[sleutel], sleutel, optional=True))
        if not stukken:
            raise LibraryError("Niets om bij te werken.")
        with self._connect() as db:
            db.execute(
                f"UPDATE machine_profile SET {', '.join(stukken)} WHERE id = ?",
                (*waarden, machine_id),
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

    def presets(self, material_id=None, operation=None, machine_id=None) -> list[dict]:
        # De foto van het raster erbij: een preset die uit een testraster komt
        # heeft bewijs, en dat bewijs hoort op de kaart en niet drie schermen
        # verderop. origin_id is "testgrid:<id>".
        query = """
            SELECT p.*, m.name AS material_name, mp.name AS machine_name,
                   g.id AS grid_id, g.photo_path AS grid_photo,
                   g.created_at AS grid_date, g.cells AS grid_cells
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
            # Presets zonder profiel horen bij niemand in het bijzonder en
            # blijven dus zichtbaar: ze zijn met de hand gemaakt vóór er
            # profielen waren.
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

    # Wat je aan een bestaande preset mag bijstellen.
    PRESET_FIELDS = {
        "thickness_mm": lambda v: _number(v, "thickness_mm", optional=True),
        "speed_mm_s": lambda v: _number(v, "speed_mm_s", positive=True),
        "power_percent": lambda v: _percent(v),
        "passes": lambda v: int(_number(v, "passes", positive=True)),
        "air_assist": lambda v: 1 if v else 0,
        "focus_offset_mm": lambda v: _number(v, "focus_offset_mm"),
        "note": lambda v: str(v or ""),
        "machine_id": lambda v: v,
    }

    def update_preset(self, preset_id: int, **fields) -> dict:
        """
        Bijstellen van een bestaande preset.

        Materiaal en bewerking liggen vast: dat is een andere preset. Bron ook —
        die zegt hoe de waarden tot stand kwamen, en dat verandert niet doordat
        je een getal bijwerkt.
        """
        self.preset(preset_id)
        updates = {k: v for k, v in fields.items() if k in self.PRESET_FIELDS and v is not None}
        rejected = sorted(set(fields) - set(self.PRESET_FIELDS) - {"id"})
        if rejected:
            raise LibraryError(
                f"Niet te wijzigen: {', '.join(rejected)}. Materiaal, bewerking en "
                "bron horen bij de identiteit van een preset."
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
        Een rasterbereik rond wat je al weet.

        ARCHITECTUUR.md: de app stelt het bereik voor op basis van bestaande
        (vaak geëxtrapoleerde) presets rond het verwachte werkpunt. Zonder
        presets vallen we terug op iets breeds maar redelijks.
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
            # Een halve slag eromheen: genoeg om het werkpunt te omsluiten.
            "speed_min": max(0.1, round(min(speeds) * 0.5, 1)),
            "speed_max": round(max(speeds) * 1.5, 1),
            "power_min": max(1.0, round(min(powers) * 0.7, 1)),
            "power_max": min(100.0, round(max(powers) * 1.3, 1)),
        }

    def touch_preset(self, preset_id: int) -> None:
        """Onthoud dat deze instelling gebruikt is; dat is wat 'gisteren' maakt."""
        with self._connect() as db:
            db.execute(
                "UPDATE preset SET last_used_at = datetime('now') WHERE id = ?",
                (preset_id,),
            )

    def remove_preset(self, preset_id: int) -> dict:
        with self._connect() as db:
            cursor = db.execute("DELETE FROM preset WHERE id = ?", (preset_id,))
            if not cursor.rowcount:
                raise LibraryError(f"Preset {preset_id} bestaat niet.")
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
            raise LibraryError(f"Testraster {grid_id} bestaat niet.")
        return _grid_row(row)

    def set_grid_group(self, grid_id: int, group_id: str | None) -> None:
        with self._connect() as db:
            db.execute(
                "UPDATE test_grid SET group_id = ? WHERE id = ?", (group_id, grid_id)
            )

    def grid_operations(self) -> dict:
        """Welke operatie bij welk raster hoort — voor het lagenpaneel."""
        mapping = {}
        # test_grids() staat nieuwste eerst; setdefault laat de nieuwste winnen.
        # Element-id's worden per document uitgedeeld, dus een oud raster kan
        # dezelfde operatie-id's dragen als het huidige.
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
                        speed_min, speed_max, speed_steps, power_min, power_max, power_steps,
                        cell_mm, gap_mm, origin_x_mm, origin_y_mm, cells)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    plan.get("material_id"),
                    plan.get("machine_id"),
                    plan.get("thickness_mm"),
                    plan["operation"],
                    plan["speed_min"],
                    plan["speed_max"],
                    plan["speed_steps"],
                    plan["power_min"],
                    plan["power_max"],
                    plan["power_steps"],
                    plan["cell_mm"],
                    plan["gap_mm"],
                    plan["origin_x_mm"],
                    plan["origin_y_mm"],
                    json.dumps(cells),
                ),
            )
            grid_id = cursor.lastrowid
        return self.test_grid(grid_id)

    def remove_test_grid(self, grid_id: int) -> dict:
        with self._connect() as db:
            cursor = db.execute("DELETE FROM test_grid WHERE id = ?", (grid_id,))
            if not cursor.rowcount:
                raise LibraryError(f"Testraster {grid_id} bestaat niet.")
        return {"removed": grid_id}

    def set_grid_photo(self, grid_id: int, suffix: str, data: bytes) -> dict:
        """Store the photo of a burned grid and remember where it went."""
        grid = self.test_grid(grid_id)
        safe = (suffix or "").lower()
        if safe not in (".jpg", ".jpeg", ".png", ".webp", ".heic"):
            raise LibraryError(f"Onbekend fotoformaat: {suffix or '(geen)'}")
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
            raise LibraryError(f"Cel {row},{column} hoort niet bij raster {grid_id}.")
        with self._connect() as db:
            db.execute(
                "UPDATE test_grid SET cells = ? WHERE id = ?",
                (json.dumps(cells), grid_id),
            )
        return self.test_grid(grid_id)

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _one(db, table: str, row_id: int) -> dict:
        row = db.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()
        return dict(row)


def _grid_row(row) -> dict:
    data = dict(row)
    data["cells"] = json.loads(data["cells"])
    return data


def _preset_row(row) -> dict:
    data = dict(row)
    data["air_assist"] = bool(data["air_assist"])
    # Uit welk vakje van het raster deze preset komt. Dat is de herkomst in één
    # regel: "rij 2, kolom 3" is aanwijsbaar op de foto, "testraster" niet.
    cellen = data.pop("grid_cells", None)
    data["grid_cell"] = None
    if cellen:
        for cel in json.loads(cellen):
            if cel.get("preset_id") == data["id"]:
                data["grid_cell"] = {"row": cel["row"], "column": cel["column"]}
                break
    return data


def _percent(value):
    number = _number(value, "power_percent", positive=True)
    if number > 100:
        raise LibraryError("power_percent kan niet boven 100.")
    return number


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
