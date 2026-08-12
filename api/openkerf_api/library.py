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
    -- Lijnafstand bij rasteren. Sinds B12 kan een testraster hierop sweepen,
    -- dus komt hij ook uit het winnende vakje mee; leeg bij snijden.
    interval_mm   REAL,
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

-- Nieuwe kolommen op `test_grid` horen ook in `_migrate` te staan: bestaande
-- databases krijgen ze daar, verse hier.
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
    -- Besluit B12: interval is de derde grootheid. Twee ervan staan op de
    -- assen, de derde ligt vast — dan zijn min en max gelijk en steps 1.
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
    -- Elke cel met haar positie en instellingen, zodat de foto-overlay later
    -- weet welk vakje bij welke snelheid en vermogen hoort.
    cells         TEXT NOT NULL,
    photo_path    TEXT,
    -- De vier hoeken van het gebrande bord op de foto (0–1). Hoort hier en
    -- niet in localStorage: je lijnt uit op de desktop en wijst het vakje aan
    -- op de tablet, en dan moet de overlay dezelfde zijn.
    alignment     TEXT,
    group_id      TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Benoemde generatorinstellingen (gat T7).
--
-- T3 onthoudt één instelling per materiaal: het vórige raster. Dat dekt "ik
-- test elke week 3 mm berk" maar niet "berk snijden" náást "berk graveren" —
-- twee recepten voor hetzelfde materiaal kunnen daar niet naast elkaar staan.
-- Dit is dezelfde inhoud onder een naam, en bewust in dezelfde vorm: één rij
-- met precies de sleutels die `Library.GRID_DEFAULTS` beschrijft, zodat een
-- recept en een vorig raster onderling verwisselbaar zijn voor de wizard.
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

# Besluit B7: de bibliotheek is uitwisselbaar. Eén bestand, want een
# bibliotheek zonder de rasterfoto's is de helft — die foto's zíjn het bewijs.
# Daarom een zip: de JSON met de gegevens, de foto's ernaast.
BUNDLE_FORMAT = "openkerf-library"
BUNDLE_VERSION = 1
BUNDLE_SUFFIX = ".openkerf-lib"
BUNDLE_INDEX = "bibliotheek.json"
BUNDLE_PHOTOS = "fotos"

# Wanneer twee namen over hetzelfde materiaal gaan. De catalogus schrijft
# "Berkentriplex" waar de bibliotheek "Multiplex berken" heeft — dat is één
# plank, geen twee. We voegen het nooit vanzelf samen (een verkeerde gok kost
# je je eigen metingen), maar we wijzen het wel aan.
MATERIAL_FAMILIES = {
    "multiplex": ("multiplex", "triplex", "plywood", "ply"),
    "berken": ("berken", "berk", "birch"),
    "populier": ("populier", "poplar"),
    "eiken": ("eiken", "eik", "oak"),
    "mdf": ("mdf",),
    "acryl": ("acryl", "acrylaat", "acrylic", "plexiglas", "plexi", "pmma"),
    "karton": ("karton", "kartonnen", "cardboard"),
    "papier": ("papier", "paper"),
    "leer": ("leer", "leder", "leather"),
    "vilt": ("vilt", "felt"),
    "rvs": ("rvs", "inox", "staal", "steel"),
    "aluminium": ("aluminium", "alu"),
}


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
        for kolom, definitie in (
            ("group_id", "TEXT"),
            ("alignment", "TEXT"),
            ("interval_min", "REAL"),
            ("interval_max", "REAL"),
            ("interval_steps", "INTEGER"),
            ("row_axis", "TEXT NOT NULL DEFAULT 'speed'"),
            ("column_axis", "TEXT NOT NULL DEFAULT 'power'"),
            ("rows", "INTEGER"),
            ("columns", "INTEGER"),
            # T9/T10: waar het bord aan hangt en wat er verder op gebrand wordt.
            # Rasters van vóór deze versie stonden altijd vanaf de hoek, met
            # opschriften en zonder kader — dat zijn precies deze standaarden.
            ("anchor", "TEXT NOT NULL DEFAULT 'corner'"),
            ("text_enabled", "INTEGER NOT NULL DEFAULT 1"),
            ("border_enabled", "INTEGER NOT NULL DEFAULT 0"),
            ("label_speed_mm_s", "REAL"),
            ("label_power_percent", "REAL"),
        ):
            if kolom not in existing:
                db.execute(f"ALTER TABLE test_grid ADD COLUMN {kolom} {definitie}")
        # Rasters van vóór B12 hadden altijd snelheid × vermogen.
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
                   g.created_at AS grid_date, g.cells AS grid_cells,
                   -- Is de foto van dat raster uitgelijnd? Zo niet, dan valt de
                   -- markering op de foto terug op vier standaardhoeken en ligt
                   -- de omtrek er ongeveer, niet precies. De bibliotheek hoort
                   -- dat te kunnen zeggen in plaats van een precisie te
                   -- suggereren die er niet is.
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
        "interval_mm": lambda v: _number(v, "interval_mm", optional=True),
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

    def set_grid_alignment(self, grid_id: int, corners) -> dict:
        """
        Waar het gebrande bord op de foto ligt: vier hoeken, elk 0–1.

        In de database en niet in de browser: je lijnt uit op de desktop en
        wijst het vakje aan op de tablet, en dan hoort dezelfde overlay er te
        liggen. `None` wist de uitlijning en zet hem terug op het voorstel.
        """
        self.test_grid(grid_id)
        if corners is None:
            schoon = None
        else:
            schoon = _uitlijning(corners)
            if schoon is None:
                raise LibraryError(
                    "Een uitlijning bestaat uit vier punten met een x en een y."
                )
            for punt in schoon:
                if not (0 <= punt["x"] <= 1 and 0 <= punt["y"] <= 1):
                    raise LibraryError("Een hoek ligt buiten de foto.")
        with self._connect() as db:
            db.execute(
                "UPDATE test_grid SET alignment = ? WHERE id = ?",
                (json.dumps(schoon) if schoon else None, grid_id),
            )
        return self.test_grid(grid_id)

    # De instellingen die het volgende raster van hetzelfde materiaal overneemt.
    # Dezelfde lijst draagt de benoemde recepten van T7: één vorm, zodat de
    # wizard niet hoeft te weten of hij een vorig raster of een recept invult.
    GRID_DEFAULTS = (
        "operation", "thickness_mm", "row_axis", "column_axis",
        "speed_min", "speed_max", "speed_steps",
        "power_min", "power_max", "power_steps",
        "interval_min", "interval_max", "interval_steps",
        "cell_mm", "gap_mm", "origin_x_mm", "origin_y_mm",
        "anchor", "text_enabled", "border_enabled",
        "label_speed_mm_s", "label_power_percent",
    )

    def last_grid_settings(self, material_id=None) -> dict | None:
        """
        Wat je de vorige keer voor dit materiaal instelde.

        Wie wekelijks 3 mm berk test, vult elke week hetzelfde formulier in.
        Er is geen aparte tabel voor nodig: het vorige raster ís de instelling,
        en die overleeft daarmee ook een export en import.
        """
        rasters = self.test_grids()
        if material_id is not None:
            rasters = [g for g in rasters if g["material_id"] == material_id]
        if not rasters:
            return None
        vorige = rasters[0]  # test_grids() staat nieuwste eerst
        instelling = {
            sleutel: vorige.get(sleutel) for sleutel in self.GRID_DEFAULTS
        }
        _met_ankerpunt(instelling)
        instelling["from_grid"] = vorige["id"]
        instelling["from_date"] = vorige["created_at"]
        return instelling

    # ------------------------------------------- benoemde recepten (gat T7)

    def grid_recipes(self, material_id=None) -> list[dict]:
        """
        De bewaarde generatorinstellingen.

        Zonder materiaal krijg je alles; met een materiaal de recepten van dát
        materiaal plus de materiaalloze — die laatste zijn de algemene ("snelle
        4×4"), en die wil je juist zien als je aan iets nieuws begint.
        """
        with self._connect() as db:
            rijen = [
                dict(r)
                for r in db.execute(
                    """SELECT r.*, m.name AS material_name
                       FROM grid_recipe r
                       LEFT JOIN material m ON m.id = r.material_id
                       ORDER BY r.name COLLATE NOCASE"""
                )
            ]
        for rij in rijen:
            rij["settings"] = _recept_instellingen(json.loads(rij["settings"]))
            _met_ankerpunt(rij["settings"])
        if material_id is None:
            return rijen
        return [
            r for r in rijen if r["material_id"] in (material_id, None)
        ]

    def save_grid_recipe(self, name: str, settings: dict, material_id=None) -> dict:
        """
        Een recept opslaan, of het gelijknamige overschrijven.

        Overschrijven en niet weigeren: "berk snijden" opslaan terwijl er al een
        "berk snijden" staat betekent dat je hem hebt bijgesteld. Een tweede met
        dezelfde naam zou een lijst opleveren waarin je niet meer kunt kiezen.
        """
        naam = str(name or "").strip()
        if not naam:
            raise LibraryError("Een recept heeft een naam nodig.")
        if len(naam) > 60:
            raise LibraryError("Hou de naam onder de 60 tekens.")
        if not isinstance(settings, dict):
            raise LibraryError("Een recept bestaat uit instellingen.")
        schoon = _recept_instellingen(settings)
        if not schoon:
            raise LibraryError("Er zaten geen bruikbare instellingen in dit recept.")
        if material_id is not None and not any(
            m["id"] == material_id for m in self.materials()
        ):
            raise LibraryError(f"Materiaal {material_id} bestaat niet.")
        with self._connect() as db:
            bestaand = db.execute(
                """SELECT id FROM grid_recipe
                   WHERE name = ? COLLATE NOCASE AND material_id IS ?""",
                (naam, material_id),
            ).fetchone()
            if bestaand is None:
                cursor = db.execute(
                    "INSERT INTO grid_recipe (name, material_id, settings) VALUES (?, ?, ?)",
                    (naam, material_id, json.dumps(schoon)),
                )
                recept_id = cursor.lastrowid
            else:
                recept_id = bestaand["id"]
                db.execute(
                    """UPDATE grid_recipe SET name = ?, settings = ?, updated_at = ?
                       WHERE id = ?""",
                    (naam, json.dumps(schoon), _now(), recept_id),
                )
        return self.grid_recipe(recept_id)

    def grid_recipe(self, recipe_id: int) -> dict:
        for recept in self.grid_recipes():
            if recept["id"] == recipe_id:
                return recept
        raise LibraryError(f"Recept {recipe_id} bestaat niet.")

    def remove_grid_recipe(self, recipe_id: int) -> dict:
        with self._connect() as db:
            cursor = db.execute("DELETE FROM grid_recipe WHERE id = ?", (recipe_id,))
            if not cursor.rowcount:
                raise LibraryError(f"Recept {recipe_id} bestaat niet.")
        return {"removed": recipe_id}

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
                        interval_min, interval_max, interval_steps,
                        row_axis, column_axis, rows, columns,
                        cell_mm, gap_mm, origin_x_mm, origin_y_mm, cells,
                        anchor, text_enabled, border_enabled,
                        label_speed_mm_s, label_power_percent)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                           ?, ?, ?, ?, ?)""",
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

    # --------------------------------------------------- uitwisselen (B7)

    def export_bundle(self, filename: str = "bibliotheek") -> Path:
        """
        De hele bibliotheek als één bestand: gegevens plus bewijs.

        Materialen, presets met hun herkomst, machineprofielen, testrasters en
        de foto's van die rasters. De foto's moeten mee: een preset met bron
        "testraster" en geen foto is een bewering waar niets meer onder ligt.
        """
        import tempfile
        import zipfile
        from datetime import datetime, timezone

        veilig = Path(str(filename)).name or "bibliotheek"
        if not veilig.lower().endswith(BUNDLE_SUFFIX):
            veilig += BUNDLE_SUFFIX
        doel = Path(tempfile.mkdtemp(prefix="openkerf-lib-")) / veilig

        rasters = self.test_grids()
        presets = []
        for preset in self.presets():
            # De koppelvelden uit de weergave horen niet in het bestand: ze
            # worden bij het inlezen opnieuw afgeleid. De namen blijven wél,
            # want die zijn waar het samenvoegen op werkt.
            for sleutel in (
                "grid_photo", "grid_date", "grid_id", "grid_cell", "grid_aligned"
            ):
                preset.pop(sleutel, None)
            presets.append(preset)

        with zipfile.ZipFile(doel, "w", zipfile.ZIP_DEFLATED) as bundel:
            for raster in rasters:
                pad = raster.pop("photo_path", None)
                raster["photo_file"] = None
                if pad and Path(pad).exists():
                    naam = f"{BUNDLE_PHOTOS}/grid-{raster['id']}{Path(pad).suffix.lower()}"
                    bundel.write(pad, naam)
                    raster["photo_file"] = naam
            payload = {
                "format": BUNDLE_FORMAT,
                "version": BUNDLE_VERSION,
                "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "machines": self.machines(),
                "materials": self.materials(),
                "presets": presets,
                "test_grids": rasters,
                # T7: een benoemd recept is werk dat je zelf hebt uitgezocht,
                # dus het hoort in dezelfde back-up als de rest.
                "grid_recipes": self.grid_recipes(),
            }
            bundel.writestr(
                BUNDLE_INDEX,
                json.dumps(payload, indent=1, ensure_ascii=False, default=str),
            )
        return doel

    def read_bundle(self, path) -> dict:
        """Inlezen en meteen afwijzen wat geen bibliotheek is."""
        import zipfile

        bron = Path(path)
        if not bron.exists():
            raise LibraryError("Dat bestand is er niet (meer).")
        if not zipfile.is_zipfile(bron):
            raise LibraryError(
                "Dit is geen OpenKerf-bibliotheek. Een bibliotheekbestand eindigt "
                f"op {BUNDLE_SUFFIX}."
            )
        with zipfile.ZipFile(bron) as bundel:
            if BUNDLE_INDEX not in bundel.namelist():
                raise LibraryError("Dit bestand bevat geen bibliotheek.")
            try:
                data = json.loads(bundel.read(BUNDLE_INDEX))
            except ValueError as e:
                raise LibraryError("De bibliotheek in dit bestand is beschadigd.") from e
        if not isinstance(data, dict) or data.get("format") != BUNDLE_FORMAT:
            raise LibraryError("Dit bestand komt niet uit een OpenKerf-bibliotheek.")
        if int(data.get("version") or 0) > BUNDLE_VERSION:
            raise LibraryError(
                "Dit bestand komt uit een nieuwere versie van OpenKerf. Werk eerst bij."
            )
        return data

    def preview_import(self, path, merge_materials: dict | None = None) -> dict:
        """
        Wat er gaat gebeuren, vóórdat het gebeurt.

        Niemand wil ontdekken dat hij zijn eigen metingen heeft overschreven.
        Daarom rekent dit beide keuzes door — samenvoegen én vervangen — zodat
        het verschil op het scherm staat op het moment dat je kiest.
        """
        data = self.read_bundle(path)
        koppeling = _merge_map(merge_materials)

        materialen = [m for m in (data.get("materials") or []) if m.get("name")]
        eigen = self.materials()
        nieuw, bestaand, lijkt_op = [], [], []
        namen = {}
        for materiaal in materialen:
            naam = str(materiaal["name"]).strip()
            gekoppeld = koppeling.get(_norm(naam))
            treffer = next((m for m in eigen if m["id"] == gekoppeld), None) if gekoppeld else None
            treffer = treffer or _same_material(naam, materiaal.get("synonyms"), eigen)
            if treffer is not None:
                bestaand.append({"name": naam, "as": treffer["name"], "material_id": treffer["id"]})
                namen[materiaal.get("id")] = treffer["name"]
                continue
            namen[materiaal.get("id")] = naam
            nieuw.append(naam)
            gelijkend = _looks_like(naam, eigen)
            if gelijkend:
                buur, waarom = gelijkend
                lijkt_op.append(
                    {
                        "name": naam,
                        "match": buur["name"],
                        "material_id": buur["id"],
                        "why": waarom,
                    }
                )

        van_mij = {}
        for preset in self.presets():
            van_mij.setdefault(_preset_key(preset["material_name"], preset), preset)
        nieuwe_presets, gelijk, botsingen = 0, 0, []
        for preset in data.get("presets") or []:
            naam = namen.get(preset.get("material_id")) or preset.get("material_name")
            mijne = van_mij.get(_preset_key(naam, preset))
            if mijne is None:
                nieuwe_presets += 1
            elif _same_values(mijne, preset):
                gelijk += 1
            else:
                botsingen.append(
                    {
                        "material": naam,
                        "thickness_mm": preset.get("thickness_mm"),
                        "operation": preset.get("operation"),
                        "machine": preset.get("machine_name"),
                        "mine": _values(mijne),
                        "theirs": _values(preset),
                    }
                )

        eigen_rasters = {_grid_key(g) for g in self.test_grids()}
        rasters = data.get("test_grids") or []
        nieuwe_rasters = sum(1 for g in rasters if _grid_key(g) not in eigen_rasters)
        eigen_machines = {_norm(m["name"]) for m in self.machines()}
        machines = [m for m in (data.get("machines") or []) if m.get("name")]

        huidig = self._counts()
        return {
            "exported_at": data.get("exported_at"),
            "bevat": {
                "materials": len(materialen),
                "presets": len(data.get("presets") or []),
                "machines": len(machines),
                "test_grids": len(rasters),
                "photos": sum(1 for g in rasters if g.get("photo_file")),
            },
            "huidig": huidig,
            "samenvoegen": {
                "materials": {"new": nieuw, "existing": bestaand, "similar": lijkt_op},
                "machines": {
                    "new": [m["name"] for m in machines if _norm(m["name"]) not in eigen_machines],
                    "existing": [m["name"] for m in machines if _norm(m["name"]) in eigen_machines],
                },
                "presets": {
                    "new": nieuwe_presets,
                    "identical": gelijk,
                    "conflicts": botsingen,
                },
                "test_grids": {"new": nieuwe_rasters, "existing": len(rasters) - nieuwe_rasters},
            },
            "vervangen": {"removes": huidig},
        }

    def import_bundle(
        self,
        path,
        mode: str = "samenvoegen",
        merge_materials: dict | None = None,
        on_conflict: str = "eigen",
    ) -> dict:
        """
        Het bestand daadwerkelijk inlezen.

        `mode` is een expliciete keuze: samenvoegen laat staan wat je hebt,
        vervangen gooit het weg. `on_conflict` bepaalt wie wint als dezelfde
        preset aan beide kanten andere getallen draagt; standaard je eigen, want
        die heb je zelf gemeten.

        De bron blijft staan zoals hij was. Dit is je eigen bibliotheek die
        terugkomt van een back-up of een andere computer — "testraster"
        omschrijven naar "geïmporteerd" zou precies het bewijs weggooien dat
        deze functie moet bewaren. De foto's komen om dezelfde reden mee.
        """
        import zipfile

        if mode not in ("samenvoegen", "vervangen"):
            raise LibraryError(f"Onbekende keuze: {mode}")
        if on_conflict not in ("eigen", "bestand"):
            raise LibraryError(f"Onbekende keuze bij botsing: {on_conflict}")
        data = self.read_bundle(path)
        koppeling = _merge_map(merge_materials)
        verwijderd = self._counts() if mode == "vervangen" else None
        if mode == "vervangen":
            self.clear()

        # 1. Materialen. Alles hangt hieraan, dus dit gaat eerst.
        materiaal_id = {}
        for materiaal in data.get("materials") or []:
            naam = str(materiaal.get("name") or "").strip()
            if not naam:
                continue
            eigen = self.materials()
            gekoppeld = koppeling.get(_norm(naam))
            treffer = next((m for m in eigen if m["id"] == gekoppeld), None) if gekoppeld else None
            treffer = treffer or _same_material(naam, materiaal.get("synonyms"), eigen)
            if treffer is None:
                treffer = self.add_material(naam, materiaal.get("synonyms"))
            materiaal_id[materiaal.get("id")] = treffer["id"]

        # 2. Machineprofielen, op naam.
        machine_id = {}
        for machine in data.get("machines") or []:
            naam = str(machine.get("name") or "").strip()
            if not naam:
                continue
            treffer = next(
                (m for m in self.machines() if _norm(m["name"]) == _norm(naam)), None
            )
            if treffer is None:
                treffer = self.add_machine(**{k: v for k, v in machine.items() if k != "id"})
            machine_id[machine.get("id")] = treffer["id"]

        with zipfile.ZipFile(Path(path)) as bundel:
            namen = set(bundel.namelist())

            # 3. Testrasters, met hun foto. Vóór de presets, want een preset
            #    wijst met origin_id naar het raster waar hij uit komt.
            raster_id = {}
            eigen_rasters = {_grid_key(g): g["id"] for g in self.test_grids()}
            for raster in data.get("test_grids") or []:
                bestaat = eigen_rasters.get(_grid_key(raster))
                if bestaat is not None:
                    raster_id[raster.get("id")] = bestaat
                    continue
                nieuw = self._insert_grid(raster, materiaal_id, machine_id)
                raster_id[raster.get("id")] = nieuw
                foto = raster.get("photo_file")
                if foto and foto in namen:
                    self.set_grid_photo(nieuw, Path(foto).suffix.lower(), bundel.read(foto))

        # 4. Presets, met hun herkomst omgenummerd naar de nieuwe raster-id's.
        van_mij = {}
        for preset in self.presets():
            van_mij.setdefault(_preset_key(preset["material_name"], preset), preset)
        bron_naam = {
            m.get("id"): str(m.get("name") or "").strip()
            for m in data.get("materials") or []
        }
        preset_id = {}
        toegevoegd = bijgewerkt = overgeslagen = 0
        for preset in data.get("presets") or []:
            doel = materiaal_id.get(preset.get("material_id"))
            if doel is None:
                overgeslagen += 1
                continue
            naam = next(
                (m["name"] for m in self.materials() if m["id"] == doel),
                bron_naam.get(preset.get("material_id"), ""),
            )
            mijne = van_mij.get(_preset_key(naam, preset))
            if mijne is not None:
                if _same_values(mijne, preset) or on_conflict == "eigen":
                    preset_id[preset.get("id")] = mijne["id"]
                    overgeslagen += 1
                    continue
                self.update_preset(
                    mijne["id"],
                    speed_mm_s=preset.get("speed_mm_s"),
                    power_percent=preset.get("power_percent"),
                    passes=preset.get("passes") or 1,
                    interval_mm=preset.get("interval_mm"),
                )
                preset_id[preset.get("id")] = mijne["id"]
                bijgewerkt += 1
                continue
            preset_id[preset.get("id")] = self._insert_preset(
                preset, doel, machine_id, raster_id
            )
            toegevoegd += 1

        # 5. En terug: welk vakje van welk raster werd welke preset. Zonder deze
        #    stap staat de foto er nog, maar wijst niets meer aan.
        self._relink_cells(raster_id, preset_id)

        # 6. De benoemde recepten (T7), met hun materiaal omgenummerd. Een
        #    gelijknamig recept van jezelf blijft staan: net als bij presets is
        #    je eigen instelling de instelling die je gemeten hebt.
        recepten = 0
        eigen_recepten = {
            (r["name"].casefold(), r["material_id"]) for r in self.grid_recipes()
        }
        for recept in data.get("grid_recipes") or []:
            naam = str(recept.get("name") or "").strip()
            if not naam:
                continue
            doel = materiaal_id.get(recept.get("material_id"))
            if (naam.casefold(), doel) in eigen_recepten:
                continue
            instellingen = recept.get("settings")
            if isinstance(instellingen, str):
                instellingen = json.loads(instellingen)
            try:
                self.save_grid_recipe(naam, instellingen or {}, doel)
            except LibraryError:
                continue
            recepten += 1

        return {
            "mode": mode,
            "removed": verwijderd,
            "materials": len(materiaal_id),
            "machines": len(machine_id),
            "test_grids": len({v for v in raster_id.values()}),
            "grid_recipes": recepten,
            "presets": {
                "added": toegevoegd,
                "updated": bijgewerkt,
                "skipped": overgeslagen,
            },
        }

    def clear(self) -> dict:
        """Alles weg — alleen voor 'vervangen', en alleen na een bevestiging."""
        weg = self._counts()
        with self._connect() as db:
            for tabel in (
                "preset", "test_grid", "grid_recipe", "material", "machine_profile"
            ):
                db.execute(f"DELETE FROM {tabel}")
        for foto in self.photos.glob("grid-*"):
            foto.unlink(missing_ok=True)
        return weg

    def _counts(self) -> dict:
        with self._connect() as db:
            def tellen(tabel):
                return db.execute(f"SELECT count(*) FROM {tabel}").fetchone()[0]

            return {
                "materials": tellen("material"),
                "presets": tellen("preset"),
                "machines": tellen("machine_profile"),
                "test_grids": tellen("test_grid"),
            }

    def _insert_grid(self, raster: dict, materiaal_id: dict, machine_id: dict) -> int:
        """Een raster overnemen mét zijn datum: die datum ís het bewijs."""
        cellen = raster.get("cells")
        if isinstance(cellen, str):
            cellen = json.loads(cellen)
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
                    materiaal_id.get(raster.get("material_id")),
                    machine_id.get(raster.get("machine_id")),
                    raster.get("thickness_mm"),
                    raster.get("operation") or "snijden",
                    raster.get("speed_min"), raster.get("speed_max"), raster.get("speed_steps"),
                    raster.get("power_min"), raster.get("power_max"), raster.get("power_steps"),
                    raster.get("interval_min"), raster.get("interval_max"),
                    raster.get("interval_steps"),
                    raster.get("row_axis") or "speed",
                    raster.get("column_axis") or "power",
                    raster.get("rows") or raster.get("speed_steps"),
                    raster.get("columns") or raster.get("power_steps"),
                    raster.get("cell_mm"), raster.get("gap_mm"),
                    raster.get("origin_x_mm"), raster.get("origin_y_mm"),
                    json.dumps(cellen or []),
                    # De uitlijning is met de hand gedaan; die hoort bij de foto
                    # en gaat dus mee terug uit een back-up.
                    json.dumps(_uitlijning(raster.get("alignment")))
                    if _uitlijning(raster.get("alignment"))
                    else None,
                    raster.get("group_id"),
                    raster.get("created_at") or _now(),
                    raster.get("anchor") or "corner",
                    0 if raster.get("text_enabled") is False else 1,
                    1 if raster.get("border_enabled") else 0,
                    raster.get("label_speed_mm_s"),
                    raster.get("label_power_percent"),
                ),
            )
            return cursor.lastrowid

    def _insert_preset(self, preset: dict, material_id: int, machine_id: dict, raster_id: dict) -> int:
        herkomst = preset.get("origin_id")
        if isinstance(herkomst, str) and herkomst.startswith("testgrid:"):
            oud = herkomst.split(":", 1)[1]
            nieuw = raster_id.get(int(oud)) if oud.isdigit() else None
            herkomst = f"testgrid:{nieuw}" if nieuw else None
        bron = preset.get("source")
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
                    bron if bron in SOURCES else "geimporteerd",
                    herkomst,
                    str(preset.get("note") or ""),
                    preset.get("last_used_at"),
                    preset.get("created_at") or _now(),
                ),
            )
            return cursor.lastrowid

    def _relink_cells(self, raster_id: dict, preset_id: dict) -> None:
        if not raster_id or not preset_id:
            return
        for oud, nieuw in raster_id.items():
            try:
                raster = self.test_grid(nieuw)
            except LibraryError:
                continue
            veranderd = False
            for cel in raster["cells"]:
                doel = preset_id.get(cel.get("preset_id"))
                if doel is not None and doel != cel.get("preset_id"):
                    cel["preset_id"] = doel
                    veranderd = True
            if veranderd:
                with self._connect() as db:
                    db.execute(
                        "UPDATE test_grid SET cells = ? WHERE id = ?",
                        (json.dumps(raster["cells"]), nieuw),
                    )

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _one(db, table: str, row_id: int) -> dict:
        row = db.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()
        return dict(row)


def _grid_row(row) -> dict:
    data = dict(row)
    data["cells"] = json.loads(data["cells"])
    data["alignment"] = _uitlijning(data.get("alignment"))
    # SQLite kent geen booleans; de wizard zet er wel vinkjes mee.
    for sleutel in ("text_enabled", "border_enabled"):
        if sleutel in data:
            data[sleutel] = bool(data[sleutel])
    return data


# De waarden van de grootheden die níét op een as staan. Ze horen bij een
# recept — "berk graveren op 40%" is anders geen recept maar een half recept —
# maar niet bij GRID_DEFAULTS, want daar staan ze als min == max in de reeks.
_VASTE_VELDEN = ("speed_mm_s", "power_percent", "interval_mm")


def _recept_instellingen(ruw: dict) -> dict:
    """
    Alleen de sleutels die een raster beschrijven, in het juiste soort.

    Een recept is een JSON-blob in de database, en dat is precies waar rommel
    binnenkomt. Hier gaat eruit wat er niet in hoort, zodat de wizard er blind
    op kan vertrouwen.
    """
    uit = {}
    for sleutel in tuple(Library.GRID_DEFAULTS) + _VASTE_VELDEN:
        if sleutel not in ruw or ruw[sleutel] is None:
            continue
        waarde = ruw[sleutel]
        if sleutel in ("text_enabled", "border_enabled"):
            uit[sleutel] = bool(waarde)
        elif sleutel in ("operation", "row_axis", "column_axis", "anchor"):
            uit[sleutel] = str(waarde)
        else:
            try:
                uit[sleutel] = float(waarde)
            except (TypeError, ValueError):
                continue
    return uit


def _met_ankerpunt(instelling: dict) -> dict:
    """
    Het punt zoals de gebruiker het intikte: een hoek, of een midden (T9).

    In de database staat altijd de linkerbovenhoek van de vakjes — daar rekent
    de foto-overlay mee. Wie het bord op het midden gelegd heeft, moet dat
    midden terugzien in het formulier en niet een hoek die hij nooit getypt
    heeft. Het midden komt uit dezelfde `plan_grid` die het ook uitrekende;
    hem hier nabouwen zou twee sommen geven die uit elkaar kunnen lopen.
    """
    hoek_x = instelling.get("origin_x_mm")
    hoek_y = instelling.get("origin_y_mm")
    instelling["anchor_x_mm"] = hoek_x
    instelling["anchor_y_mm"] = hoek_y
    if instelling.get("anchor") != "center":
        return instelling
    from .testgrid import plan_grid

    velden = {k: v for k, v in instelling.items() if v is not None}
    velden["text"] = velden.pop("text_enabled", True)
    velden["border"] = velden.pop("border_enabled", False)
    velden.pop("anchor", None)
    velden.pop("anchor_x_mm", None)
    velden.pop("anchor_y_mm", None)
    velden.pop("thickness_mm", None)
    for as_ in ("speed", "power", "interval"):
        if velden.get(f"{as_}_steps") == 1:
            velden.pop(f"{as_}_steps", None)
            velden.pop(f"{as_}_max", None)
    try:
        plan = plan_grid(**velden)[0]
    except Exception:
        return instelling
    instelling["anchor_x_mm"] = plan["center_x_mm"]
    instelling["anchor_y_mm"] = plan["center_y_mm"]
    return instelling


def _uitlijning(ruw):
    """De vier hoeken als lijst van punten, of None als er niets bewaard is."""
    if not ruw:
        return None
    try:
        punten = json.loads(ruw) if isinstance(ruw, str) else ruw
    except ValueError:
        return None
    if not isinstance(punten, list) or len(punten) != 4:
        return None
    try:
        return [
            {"x": float(p["x"]), "y": float(p["y"])}
            for p in punten
        ]
    except (TypeError, KeyError, ValueError):
        return None


def _preset_row(row) -> dict:
    data = dict(row)
    data["air_assist"] = bool(data["air_assist"])
    # SQLite geeft 0/1 terug voor een booleaanse uitdrukking; de kaart die dit
    # toont moet er "ja of nee" van kunnen maken zonder erover te hoeven denken.
    if "grid_aligned" in data:
        data["grid_aligned"] = bool(data["grid_aligned"])
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


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _norm(text) -> str:
    """Naamvergelijking zonder accenten, hoofdletters of dubbele spaties."""
    plat = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore")
    return re.sub(r"\s+", " ", plat.decode().lower()).strip()


def _merge_map(keuzes: dict | None) -> dict:
    """{"Berkentriplex": 3} → {"berkentriplex": 3}, zodat de naam ertoe doet en de vorm niet."""
    return {_norm(k): int(v) for k, v in (keuzes or {}).items() if v is not None}


def _same_material(naam: str, synonyms, eigen: list[dict]) -> dict | None:
    """Exact dezelfde naam, of een naam die al als synoniem bekend staat."""
    doel = _norm(naam)
    binnen = {_norm(s) for s in (synonyms or [])}
    for materiaal in eigen:
        if _norm(materiaal["name"]) == doel:
            return materiaal
        mijne = {_norm(s) for s in materiaal.get("synonyms") or []}
        if doel in mijne or _norm(materiaal["name"]) in binnen or (mijne & binnen):
            return materiaal
    return None


def _families(naam: str) -> set[str]:
    """
    Welke materiaalfamilies er in een naam zitten.

    Op losse woorden splitsen is niet genoeg: "Berkentriplex" is één woord dat
    twee dingen zegt. Daarom zoeken we de familiewoorden ín de tekst.
    """
    plat = _norm(naam)
    gevonden = set()
    for familie, woorden in MATERIAL_FAMILIES.items():
        if any(woord in plat for woord in woorden):
            gevonden.add(familie)
    return gevonden


def _looks_like(naam: str, eigen: list[dict]) -> tuple[dict, str] | None:
    """
    Een materiaal dat waarschijnlijk hetzelfde is, met de reden erbij.

    Twee gedeelde families is de drempel: alleen "berken" gedeeld kan berken
    multiplex naast massief berken zijn, en dat zijn twee heel verschillende
    sneden. Berken én multiplex samen is één plank.
    """
    mijn = _families(naam)
    if len(mijn) < 2:
        return None
    for materiaal in eigen:
        gedeeld = mijn & _families(materiaal["name"])
        if len(gedeeld) >= 2:
            woorden = sorted(gedeeld)
            return materiaal, f"beide gaan over {' en '.join(woorden)}"
    return None


def _rond(waarde):
    """3 en 3.0 zijn dezelfde dikte; None blijft None."""
    return None if waarde in (None, "") else round(float(waarde), 2)


def _preset_key(material_naam, preset: dict) -> tuple:
    """Wanneer twee presets over hetzelfde gaan: zelfde plank, zelfde snede, zelfde laser."""
    return (
        _norm(material_naam),
        _rond(preset.get("thickness_mm")),
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


def _same_values(mijne: dict, hunne: dict) -> bool:
    if _rond(mijne.get("interval_mm")) != _rond(hunne.get("interval_mm")):
        return False
    for sleutel in ("speed_mm_s", "power_percent"):
        if _rond(mijne.get(sleutel)) != _rond(hunne.get(sleutel)):
            return False
    return int(mijne.get("passes") or 1) == int(hunne.get("passes") or 1)


def _grid_key(raster: dict) -> tuple:
    """Een raster is hetzelfde raster als het op hetzelfde moment gebrand is."""
    return (
        str(raster.get("created_at") or ""),
        str(raster.get("operation") or ""),
        _rond(raster.get("speed_min")),
        _rond(raster.get("power_min")),
        _rond(raster.get("cell_mm")),
    )


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
