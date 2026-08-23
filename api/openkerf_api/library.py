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
    -- 'unknown' and not 'co2-glass'. A profile is made the moment a device is activated,
    -- before anybody has been asked anything, and a default of 'co2-glass' made every one
    -- of them *claim* to be a glass tube: the wizard then only ever asked about the
    -- wattage, and somebody with a diode was never asked at all while the catalogue
    -- happily matched them against CO2 values. Unknown matches nothing and says so, which
    -- is the answer a machine nobody has described deserves.
    laser_type   TEXT NOT NULL DEFAULT 'unknown',
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
    -- Who this laser is, as opposed to which slot it happens to sit in. The kernel hands
    -- out device paths first-free-slot (kernel.py:3433-3437), so "ruida" is recycled the
    -- moment a machine is removed, and the next machine inherited the dead one's presets
    -- and boards. The uid is minted once by machines.py and never changes; empty means a
    -- profile from before this column, which still matches on device_path alone.
    machine_uid  TEXT NOT NULL DEFAULT '',
    -- '' | 'dismissed' | 'power_unknown'. One column rather than a boolean beside a
    -- boolean: "I do not know my tube power" is a third answer to the starting-values
    -- offer, not a second flag.
    starter_state TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS material (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT NOT NULL UNIQUE,
    synonyms  TEXT NOT NULL DEFAULT '',
    -- The import that created this material, so `remove_import_batch` can tell a board
    -- the user added themselves from one an import invented. Empty for everything a
    -- person typed in. Fourteen of the twenty materials in the author's library were
    -- created by one bulk import and none of them could be removed again.
    import_batch TEXT NOT NULL DEFAULT '',
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
    -- what they used yesterday.
    last_used_at  TEXT,
    -- The import this row came in on. An import you can take back in one call is the
    -- difference between a catalogue and a junk drawer, and it is the only defence that
    -- works on a library that already holds twenty-six rows nobody wanted.
    import_batch  TEXT NOT NULL DEFAULT '',
    -- The machine the values were *measured* on, which is not always the machine the row
    -- is filed under: an import files a stranger's 80 W measurement under your laser.
    -- NULL on an imported row means the origin is unknown, and that is what the
    -- twenty-six prefilled rows get, because their note records no machine at all.
    origin_laser_type TEXT,
    origin_power_watt REAL,
    -- Who offered the row to the shared catalogue. Not decoration: that catalogue is
    -- CC BY 4.0, so the credit is a condition of the copy and it has to survive the
    -- import — a preset whose attribution was dropped on the way in cannot be passed on
    -- lawfully, and nobody can see that it was dropped. NULL for everything that was
    -- measured or typed here, which needs no credit from anybody.
    origin_by     TEXT,
    -- When somebody last burned this setting again and it still held. The only claim one
    -- maintainer can ever check, so it is recorded and shown — and deliberately not a
    -- gate on sharing, because nobody re-burns and a gate would simply close the door.
    verified_at   TEXT,
    -- What came out of the material, in the three fields the shared catalogue's schema
    -- has room for (`result.charring`, `result.cut_through`, `result.kerf_mm`). Its own
    -- words for why they are there: "a number without an outcome is not something
    -- anybody can judge". Until this round the app threw that answer away — a
    -- contribution carried a speed and a power and not one word about whether the piece
    -- fell out or came away black — so a measured row could not be offered as measured.
    -- NULL everywhere else, and NULL is exactly what keeps a row a starting point: this
    -- is the one field the app can never work out for itself.
    result_charring TEXT,
    result_cut_through INTEGER,
    result_kerf_mm REAL,
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
    -- The board's own name, eight Crockford base32 characters (see `boardcode`). Minted
    -- for *every* board and back-filled for the ones that predate it, because eleven of
    -- the author's thirty-two boards are physically indistinguishable from another one —
    -- same material, same square size, same sweep, burned minutes apart — so filing a
    -- photograph under the right board is guesswork without a name. Whether the name is
    -- also burned on the plank is `code_enabled`; the row has it either way, so the
    -- picker can show it and a search box can find it.
    uid           TEXT,
    -- What the user typed as the caption. Everything else the caption prints — material,
    -- thickness, operation, the axes, the passes, the date — is a column already, so this
    -- is the only part of the line on the plank that the row cannot rebuild.
    caption       TEXT,
    -- The whole board, captions, code and frame included. `origin_*` is the top-left of
    -- the *squares* and stays that, because the photo overlay normalises over the squares.
    -- These four are stored so that reading an alignment off the code's corners can be
    -- added later without a second migration.
    outer_x_mm    REAL,
    outer_y_mm    REAL,
    outer_width_mm REAL,
    outer_height_mm REAL,
    -- Where the code went and how big it was, for the same reason: three numbers are what
    -- a homography off its corners needs, and they cost nothing now.
    code_enabled  INTEGER NOT NULL DEFAULT 0,
    code_size_mm  REAL,
    code_x_mm     REAL,
    code_y_mm     REAL,
    -- Whether the tile was cut loose, with whose cut setting, and along which rectangle.
    -- The setting is a real reference: a preset that is removed leaves no id claiming to
    -- be the setting the tile was cut with.
    cutout_enabled INTEGER NOT NULL DEFAULT 0,
    cutout_preset_id INTEGER REFERENCES preset(id) ON DELETE SET NULL,
    cut_x_mm      REAL,
    cut_y_mm      REAL,
    cut_width_mm  REAL,
    cut_height_mm REAL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Named generator settings (gap T7).
--
-- T3 remembers one setting per material: the previous grid. That covers "I test 3 mm
-- birch every week" but not "cut birch" beside "engrave birch" —
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

-- The unique index on machine_profile(device_path) is deliberately *not* here. It is
-- created at the end of `_dedupe_machines`, because a database from before that rule can
-- hold two rows for one device and creating the index first refuses outright — measured:
-- `UNIQUE constraint failed: machine_profile.device_path` on the very first open. A fresh
-- database reads user_version 0, so it runs the migration once and gets the index there.
"""

# What `PRAGMA user_version` reads once a database is at head. Everything from before this
# constant existed reads 0, which is why `_migrate` still sniffs columns rather than
# stepping version by version: it has to be able to carry a database from any of those
# unversioned days. The gate is only about *when* it runs, not about what it does.
SCHEMA_VERSION = 1

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

    `values` carries the numbers the sentence needs, for the refusal whose only variable
    is a constant of ours: the interface then has the number and can put it in its own
    sentence. `refuse()` reads it off any exception (server.py:150-152), so nothing else
    has to change. A refusal whose numbers are *measured* per call keeps its English
    sentence — a translated sentence without the numbers says less than an English one
    with them.
    """

    def __init__(
        self, message: str, code: str | None = None, values: dict | None = None
    ):
        super().__init__(message)
        self.code = code
        self.values = values


def default_path(kernel) -> Path:
    """
    In MeerK40t's settings directory — one library per computer, not per profile.

    The name reads like a per-profile path and is not one. `get_safe_path` takes a bare
    directory name (kernel/functions.py:21-48) and `kernel.name` is the application name,
    fixed at construction (kernel.py:146); `-P/--profile` never reaches either, because
    main.py:227-230 hands `APPLICATION_NAME` in as the profile as well. So every instance
    on this machine — the app, a test server, the gauntlet — opens the *same* file. That
    is how five of the seven profiles in the author's library came to be debris from our
    own test runs, and it is why the gauntlet harness takes `--library <path>`: the first
    run of new migration code must not happen against somebody's real 204 KB file.
    """
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
            # Cheap and idempotent, so it runs every time: it is the one thing that puts
            # a missing table back.
            db.executescript(SCHEMA)
            # And so does the column sniffing, for the same reason and against a sharper
            # trap. Gating it on the version number moved the old silent fault instead of
            # removing it: a column added to `SCHEMA` and `_add_missing_columns` without
            # anybody remembering to raise `SCHEMA_VERSION` would reach every *fresh*
            # database and no existing one, so the whole suite stays green and only
            # somebody with a library ever meets the missing column. Measured: with a
            # column added to both and the version left alone, an already-stamped database
            # did not get it. Sniffing costs one `PRAGMA table_info` per table.
            self._add_missing_columns(db)
            # And beside it, for the same reason and with the same cost: every board needs
            # a name, and a board that has one already is left alone.
            self._name_the_boards(db)
            if db.execute("PRAGMA user_version").fetchone()[0] < SCHEMA_VERSION:
                # What is *not* idempotent, or is expensive, stays behind the gate: the
                # back-fills and the one-time relabel.
                self._migrate(db)
                # PRAGMA takes no bound parameters, hence the interpolation; the value is
                # our own integer constant and never comes from outside. Stamped *after*
                # the migration, so a failure halfway means the next open tries again.
                db.execute(f"PRAGMA user_version = {int(SCHEMA_VERSION)}")
            elif not self._has_device_lock(db):
                # A database at head cannot hold two profiles for one device *while* the
                # unique index is there — that is what the index is for. So the index
                # itself, and not the version number, is the honest question to ask before
                # running a step that DELETEs rows: gone means somebody's database predates
                # the rule (or lost it), and the duplicates it was allowed to grow are
                # still in there.
                self._dedupe_machines(db)

    @staticmethod
    def _add_missing_columns(db):
        """
        Every column that came later, put back on any database that is missing it.

        Runs on **every** open, because it is cheap (one `PRAGMA table_info` per table)
        and because the alternative is a silent fault: a column has to be written twice,
        once in `SCHEMA` and once here, and a version gate over the pair means forgetting
        to raise the version hides the omission from every existing database while the
        fresh-database suite stays green.

        It sniffs rather than stepping version by version, because every database in the
        wild reads `user_version` 0 whatever it actually holds; sniffing is the only thing
        that can carry all of them to head.

        Every definition carries a default, and that is not a style rule: measured on
        SQLite 3.50.4, `ADD COLUMN ... NOT NULL` with no default is *accepted* on an empty
        table and refused on a populated one. Such a migration passes a suite that builds
        fresh databases and breaks the first user who has data.
        `test_no_column_is_not_null_without_a_default` pins it.
        """
        for table, columns in (
            (
                "test_grid",
                (
                    ("group_id", "TEXT"),
                    ("alignment", "TEXT"),
                    ("interval_min", "REAL"),
                    ("interval_max", "REAL"),
                    ("interval_steps", "INTEGER"),
                    ("row_axis", "TEXT NOT NULL DEFAULT 'speed'"),
                    ("column_axis", "TEXT NOT NULL DEFAULT 'power'"),
                    ("rows", "INTEGER"),
                    ("columns", "INTEGER"),
                    # T9/T10: what the board hangs off and what else gets burned on it.
                    # Grids from before this version always started from the corner, with
                    # captions and without a frame — which is exactly these defaults.
                    ("anchor", "TEXT NOT NULL DEFAULT 'corner'"),
                    ("text_enabled", "INTEGER NOT NULL DEFAULT 1"),
                    ("border_enabled", "INTEGER NOT NULL DEFAULT 0"),
                    ("label_speed_mm_s", "REAL"),
                    ("label_power_percent", "REAL"),
                    # Boards from before this version burned over each square once.
                    ("passes", "INTEGER NOT NULL DEFAULT 1"),
                    # The board's own name and what was drawn around it. Every one of
                    # these defaults describes a board from before this round exactly:
                    # no name burned on it, no cut-out, and nothing measured about where
                    # the whole board lay — `_name_the_boards` fills the name in, the
                    # rest stays NULL because inventing it would be a measurement we
                    # never made.
                    ("uid", "TEXT"),
                    ("caption", "TEXT"),
                    ("outer_x_mm", "REAL"),
                    ("outer_y_mm", "REAL"),
                    ("outer_width_mm", "REAL"),
                    ("outer_height_mm", "REAL"),
                    ("code_enabled", "INTEGER NOT NULL DEFAULT 0"),
                    ("code_size_mm", "REAL"),
                    ("code_x_mm", "REAL"),
                    ("code_y_mm", "REAL"),
                    ("cutout_enabled", "INTEGER NOT NULL DEFAULT 0"),
                    # With the foreign key, and that is allowed here for one reason:
                    # SQLite takes a REFERENCES clause on `ADD COLUMN` as long as the
                    # default is NULL. Measured on SQLite 3.50.4 with
                    # `PRAGMA foreign_keys = ON`: the column was added to a populated
                    # table and `DELETE FROM preset` then set it back to NULL, so the
                    # rule really is enforced and not just recorded.
                    (
                        "cutout_preset_id",
                        "INTEGER REFERENCES preset(id) ON DELETE SET NULL",
                    ),
                    ("cut_x_mm", "REAL"),
                    ("cut_y_mm", "REAL"),
                    ("cut_width_mm", "REAL"),
                    ("cut_height_mm", "REAL"),
                ),
            ),
            (
                "preset",
                (
                    ("last_used_at", "TEXT"),
                    ("interval_mm", "REAL"),
                    ("import_batch", "TEXT NOT NULL DEFAULT ''"),
                    ("origin_laser_type", "TEXT"),
                    ("origin_power_watt", "REAL"),
                    ("origin_by", "TEXT"),
                    ("verified_at", "TEXT"),
                    ("result_charring", "TEXT"),
                    ("result_cut_through", "INTEGER"),
                    ("result_kerf_mm", "REAL"),
                ),
            ),
            ("material", (("import_batch", "TEXT NOT NULL DEFAULT ''"),)),
            (
                "machine_profile",
                (
                    ("device_path", "TEXT"),
                    ("has_z", "INTEGER NOT NULL DEFAULT 0"),
                    ("has_autofocus", "INTEGER NOT NULL DEFAULT 0"),
                    ("machine_uid", "TEXT NOT NULL DEFAULT ''"),
                    ("starter_state", "TEXT NOT NULL DEFAULT ''"),
                ),
            ),
        ):
            existing = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
            for column, definition in columns:
                if column not in existing:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    @staticmethod
    def _name_the_boards(db):
        """
        Every board a name of its own, and the index that keeps it one.

        Beside `_add_missing_columns` and not inside `_migrate`, and the reason is the
        author's own library: the engine step of this round already stamped it at
        `SCHEMA_VERSION`, so a back-fill behind that gate would never run there and its
        thirty-two boards would stay nameless for ever. Here it is self-healing instead —
        `WHERE uid IS NULL OR uid = ''` matches nothing the second time, so the cost of an
        open is one scan of a table that holds tens of rows.

        The names are minted one at a time rather than in one `UPDATE`, because every board
        needs a *different* one and SQLite has no `secrets` of its own. The index is partial
        so the moment before the back-fill — every row NULL — is legal.
        """
        db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS test_grid_uid "
            "ON test_grid(uid) WHERE uid IS NOT NULL"
        )
        nameless = db.execute(
            "SELECT id FROM test_grid WHERE uid IS NULL OR uid = ''"
        ).fetchall()
        for row in nameless:
            db.execute(
                "UPDATE test_grid SET uid = ? WHERE id = ?",
                (_fresh_grid_uid(db), row["id"]),
            )

    @staticmethod
    def _migrate(db):
        """
        The one-time work on a database from before this version.

        The columns themselves are not here — `_add_missing_columns` puts those back on
        every open, for the reason its docstring gives. What is left is what may only
        happen once, or is expensive: the two back-fills for boards that predate B12, the
        relabel of the Presetariat prefill, and the machine de-duplication.
        """
        # Boards from before B12 were always speed by power.
        db.execute("UPDATE test_grid SET rows = speed_steps WHERE rows IS NULL")
        db.execute("UPDATE test_grid SET columns = power_steps WHERE columns IS NULL")
        Library._relabel_prefill(db)
        Library._dedupe_machines(db)

    @staticmethod
    def _relabel_prefill(db):
        """
        The rows the Presetariat prefill left behind, said in English.

        Twenty-six rows in the author's library carry a Dutch note in an English
        interface, written by `presetariat._note`. They cannot be back-filled — the note
        records `presetariat-prefill` and no machine — so they are relabelled and not
        dropped: they are usable values, and with `origin_power_watt` NULL beside
        `source = 'geimporteerd'` they now read as what they are, an import whose origin
        machine is unknown. That NULL needs no statement of its own; the column is new, so
        every existing row already has it.

        Only this one shape is rewritten. A note somebody typed themselves is theirs, and
        after the rewrite nothing starts with the Dutch opening any more, so running it
        twice changes nothing.
        """
        db.execute(
            """UPDATE preset
                  SET note = replace(replace(replace(note,
                        'Uit Presetariat (', 'From the Presetariat ('),
                        ', door ', ', by '),
                        'Startwaarde, niet gemeten. Brand een testraster voordat je hier op vertrouwt.',
                        'Starting value, not measured. Burn a test grid before you rely on it.')
                WHERE source = 'geimporteerd' AND note LIKE 'Uit Presetariat (%'"""
        )

    @staticmethod
    def _has_device_lock(db) -> bool:
        """Whether one-profile-per-device is actually locked down in this file."""
        return (
            db.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'index' "
                "AND name = 'machine_profile_device'"
            ).fetchone()
            is not None
        )

    @staticmethod
    def _dedupe_machines(db):
        """
        One profile per device, and after that a lock on that rule.

        `profile_for_device` did a SELECT and then an INSERT. The
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
            raise LibraryError(
                "A machine profile needs a name.", code="library.machine.needsName"
            )
        with self._connect() as db:
            cursor = db.execute(
                """INSERT INTO machine_profile
                   (name, laser_type, power_watt, lens_mm, bed_width_mm,
                    bed_height_mm, device_path, has_z, has_autofocus,
                    machine_uid, starter_state)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    name,
                    # See the column comment: a kind nobody stated is `unknown`, never a
                    # guess that reads like a statement.
                    str(fields.get("laser_type") or "unknown"),
                    _watt(fields.get("power_watt")),
                    _number(fields.get("lens_mm"), "lens_mm", optional=True),
                    _number(fields.get("bed_width_mm"), "bed_width_mm", optional=True),
                    _number(fields.get("bed_height_mm"), "bed_height_mm", optional=True),
                    str(fields.get("device_path") or "") or None,
                    1 if fields.get("has_z") else 0,
                    1 if fields.get("has_autofocus") else 0,
                    str(fields.get("machine_uid") or "").strip(),
                    _starter_state(fields.get("starter_state")),
                ),
            )
            return self._one(db, "machine_profile", cursor.lastrowid)

    def profile_for_device(
        self, device_path: str, label: str | None = None, machine_uid: str | None = None
    ) -> dict:
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

        `machine_uid` is who the laser *is*, and it is looked up before the device path,
        because a path is a slot and slots are recycled: the kernel allocates the first
        free one (kernel.py:3433-3437), so removing a Ruida and adding a different one
        hands the newcomer "ruida" back — and this function then found the dead machine's
        row, renamed it after the newcomer and handed over every preset and every board.
        A path whose row carries a *different*, non-empty uid is therefore detached
        (device_path NULL, all its evidence kept) and a fresh profile minted. A row with
        an empty uid is one from before this column and still matches on the path alone,
        which is the only thing there is to go on.
        """
        path = str(device_path or "").strip()
        if not path:
            raise LibraryError(
                "There is no active machine to attach to.",
                code="library.machine.noneActive",
            )
        name = str(label or "").strip() or path
        uid = str(machine_uid or "").strip()
        with self._connect() as db:
            row = None
            if uid:
                row = db.execute(
                    "SELECT * FROM machine_profile WHERE machine_uid = ?", (uid,)
                ).fetchone()
            if row is None:
                row = db.execute(
                    "SELECT * FROM machine_profile WHERE device_path = ?", (path,)
                ).fetchone()
                if row is not None and uid and row["machine_uid"] not in ("", uid):
                    # Same slot, different laser. Let go of the slot and keep the row:
                    # its presets and boards are measurements of a machine that existed.
                    db.execute(
                        "UPDATE machine_profile SET device_path = NULL WHERE id = ?",
                        (row["id"],),
                    )
                    row = None
            if row is not None:
                changes = {}
                if row["name"] != name:
                    changes["name"] = name
                if uid and row["machine_uid"] != uid:
                    changes["machine_uid"] = uid
                if row["device_path"] != path:
                    # Found by uid on another slot: the machine moved and its evidence
                    # moves with it. Anything else holding this slot lets go first, or the
                    # unique index refuses the update.
                    db.execute(
                        "UPDATE machine_profile SET device_path = NULL "
                        "WHERE device_path = ? AND id <> ?",
                        (path, row["id"]),
                    )
                    changes["device_path"] = path
                if changes:
                    db.execute(
                        "UPDATE machine_profile SET "
                        + ", ".join(f"{key} = ?" for key in changes)
                        + " WHERE id = ?",
                        (*changes.values(), row["id"]),
                    )
                    return self._one(db, "machine_profile", row["id"])
                return dict(row)
        try:
            return self.add_machine(name=name, device_path=path, machine_uid=uid)
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
        Clearing a profile away.

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
            raise LibraryError(
                f"Machine profile {machine_id} does not exist.",
                code="library.machine.unknown",
            )
        usage = self.machine_usage(machine_id)
        if usage["presets"] or usage["test_grids"]:
            raise LibraryError(
                f"'{row['name']}' still carries {usage['presets']} setting(s) and "
                f"{usage['test_grids']} test grid(s). Remove or move those first.",
                code="library.machine.inUse",
            )
        with self._connect() as db:
            db.execute("DELETE FROM machine_profile WHERE id = ?", (machine_id,))
        return {"removed": machine_id}

    def merge_machine(
        self,
        source_id: int,
        target_id: int,
        live_paths=None,
        active_path: str | None = None,
    ) -> dict:
        """
        Two profiles for one laser, joined into the one you are working on.

        `_dedupe_machines` structurally cannot do this: it only merges rows that share a
        device_path, and the unique index it creates prevents that case from arising. The
        case that actually exists is the other one — the author's library holds a
        device-less `5030 CO2` with 60 W and 27 presets beside a device-bound `KH-5030`
        with no wattage and 3, and they are one physical laser.

        The target keeps everything it already says about itself; only the fields it has
        nothing in are filled from the source. That is how the 60 W finally reaches the
        profile the engine actually uses, without a merge ever overwriting something the
        user typed.

        `live_paths` and `active_path` are facts about the engine, which this module has
        no way to know, so they come in from the caller. Both refusals below need them and
        neither can be guessed from the database.
        """
        if source_id == target_id:
            raise LibraryError(
                "Choose a different machine profile to move this one's work into.",
                code="library.machine.mergeSelf",
            )
        alive = {str(p) for p in (live_paths or []) if p}
        moved = {}
        with self._connect() as db:
            source = db.execute(
                "SELECT * FROM machine_profile WHERE id = ?", (source_id,)
            ).fetchone()
            target = db.execute(
                "SELECT * FROM machine_profile WHERE id = ?", (target_id,)
            ).fetchone()
            for missing, row in ((source_id, source), (target_id, target)):
                if row is None:
                    raise LibraryError(
                        f"Machine profile {missing} does not exist.",
                        code="library.machine.unknown",
                    )
            if active_path and source["device_path"] == active_path:
                raise LibraryError(
                    "This is the machine you are working on; move the other profile "
                    "into this one instead.",
                    code="library.machine.mergeActive",
                )
            if source["device_path"] in alive and target["device_path"] in alive:
                raise LibraryError(
                    "Both of these profiles belong to a machine that exists. Two lasers "
                    "are not one, and merging them would file one machine's measurements "
                    "under the other.",
                    code="library.machine.mergeTwoReal",
                )
            moved["presets"] = db.execute(
                "UPDATE preset SET machine_id = ? WHERE machine_id = ?",
                (target_id, source_id),
            ).rowcount
            moved["test_grids"] = db.execute(
                "UPDATE test_grid SET machine_id = ? WHERE machine_id = ?",
                (target_id, source_id),
            ).rowcount
            filled = {}
            for column in (
                "power_watt", "lens_mm", "bed_width_mm", "bed_height_mm", "machine_uid"
            ):
                if not target[column] and source[column]:
                    filled[column] = source[column]
            # A kind nobody stated is 'unknown', and 'unknown' has nothing to give: the
            # merge fills the target's kind only from a source that really says something.
            # Before the column default became honest, 'co2-glass' was written onto every
            # profile the moment a device was activated, so this branch also stops that old
            # claim from surviving a merge with a row that knows better.
            vague = ("", "unknown", None)
            if target["laser_type"] in vague and source["laser_type"] not in vague:
                filled["laser_type"] = source["laser_type"]
            if not target["device_path"] and source["device_path"]:
                # The source row goes in the same transaction, so the unique index on
                # device_path never sees two rows holding this path at once.
                filled["device_path"] = source["device_path"]
            db.execute("DELETE FROM machine_profile WHERE id = ?", (source_id,))
            if filled:
                db.execute(
                    "UPDATE machine_profile SET "
                    + ", ".join(f"{key} = ?" for key in filled)
                    + " WHERE id = ?",
                    (*filled.values(), target_id),
                )
            merged = self._one(db, "machine_profile", target_id)
        return {
            "machine": merged,
            "removed": source_id,
            "moved": moved,
            "filled": sorted(filled),
        }

    def adopt_presets(self, machine_id) -> dict:
        """
        The settings and boards that belong to no machine, onto one that does.

        Four presets and eleven boards in the author's library carry `machine_id IS NULL`
        — the fingerprint of the lhystudios-fallback state, measured on a machine nobody
        can name. `presets()` shows them on every machine (its WHERE is
        `machine_id = ? OR machine_id IS NULL`), which is visible but wrong; adopting them
        claims they were measured here, which is a different kind of wrong. So this is a
        button the user presses, never a step that runs by itself.
        """
        if not machine_id:
            raise LibraryError(
                "There is no machine active, so there is nothing to attach these "
                "settings to.",
                code="library.adopt.noMachine",
            )
        with self._connect() as db:
            row = db.execute(
                "SELECT id FROM machine_profile WHERE id = ?", (machine_id,)
            ).fetchone()
            if row is None:
                raise LibraryError(
                    f"Machine profile {machine_id} does not exist.",
                    code="library.machine.unknown",
                )
            presets = db.execute(
                "UPDATE preset SET machine_id = ? WHERE machine_id IS NULL",
                (machine_id,),
            ).rowcount
            grids = db.execute(
                "UPDATE test_grid SET machine_id = ? WHERE machine_id IS NULL",
                (machine_id,),
            ).rowcount
        return {"machine_id": machine_id, "presets": presets, "test_grids": grids}

    def update_machine(self, machine_id: int, fields: dict) -> dict:
        allowed = (
            "name", "laser_type", "power_watt", "lens_mm",
            "bed_width_mm", "bed_height_mm", "has_z", "has_autofocus",
            # The wizard writes the first two; the offer card writes starter_state when
            # somebody says they do not know their tube power, or waves the card away.
            "starter_state",
        )
        parts, values = [], []
        for key in allowed:
            if key not in fields:
                continue
            parts.append(f"{key} = ?")
            if key in ("has_z", "has_autofocus"):
                values.append(1 if fields[key] else 0)
            elif key in ("name", "laser_type"):
                values.append(str(fields[key]))
            elif key == "starter_state":
                values.append(_starter_state(fields[key]))
            elif key == "power_watt":
                values.append(_watt(fields[key]))
            else:
                values.append(_number(fields[key], key, optional=True))
        if not parts:
            raise LibraryError("Nothing to update.", code="library.machine.nothingToUpdate")
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

    def add_material(self, name: str, synonyms=None, import_batch: str = "") -> dict:
        name = str(name or "").strip()
        if not name:
            raise LibraryError("A material needs a name.", code="library.material.needsName")
        joined = "|".join(str(s).strip() for s in (synonyms or []) if str(s).strip())
        try:
            with self._connect() as db:
                cursor = db.execute(
                    "INSERT INTO material (name, synonyms, import_batch) "
                    "VALUES (?, ?, ?)",
                    (name, joined, str(import_batch or "")),
                )
                row = self._one(db, "material", cursor.lastrowid)
        except sqlite3.IntegrityError as e:
            # Its own code, not `nameTaken`: that one belongs to the rename in
            # `update_material` and its sentence ends "merge the two instead", which is
            # advice about two materials. Here there is one, and the answer is to use it.
            # A code has to answer to exactly one sentence or the interface can only ever
            # show one of the two translated.
            raise LibraryError(
                f"Material '{name}' already exists.", code="library.material.exists"
            ) from e
        row["synonyms"] = [s for s in row["synonyms"].split("|") if s]
        return row

    def material_usage(self, material_id: int) -> dict:
        """
        What would go with this material, counted before anybody presses anything.

        Read by the confirm dialog and by the refusal below, from one place, so the
        sentence on screen and the sentence in the log cannot disagree about the number.
        """
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM material WHERE id = ?", (material_id,)
            ).fetchone()
            if row is None:
                raise LibraryError(
                    f"Material {material_id} does not exist.",
                    code="library.material.unknown",
                )

            def count(table, extra=""):
                return db.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE material_id = ?{extra}",
                    (material_id,),
                ).fetchone()[0]

            return {
                "material_id": material_id,
                "name": row["name"],
                "presets": count("preset"),
                "test_grids": count("test_grid"),
                "grid_recipes": count("grid_recipe"),
                "photos": count("test_grid", " AND photo_path IS NOT NULL"),
                "sheets": sum(
                    1
                    for sheet in self._read_sheets()
                    if sheet.get("material_id") == material_id
                ),
            }

    def update_material(self, material_id: int, name=None, synonyms=None) -> dict:
        """
        Renaming a material, and adjusting the names it also answers to.

        There was no way to do this at all, which is why the author's library holds both
        `Multiplex berken` and `Berkentriplex` for one board. Renaming onto a name that is
        taken is refused rather than quietly merged: merging is a different verb with a
        different confirmation, and joining two sets of measurements nobody asked to join
        is exactly the kind of help nobody wants.

        The check is case-insensitive where the UNIQUE constraint on the column is not:
        `Acrylaat` beside `acrylaat` is the same rot under a different spelling.
        """
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM material WHERE id = ?", (material_id,)
            ).fetchone()
            if row is None:
                raise LibraryError(
                    f"Material {material_id} does not exist.",
                    code="library.material.unknown",
                )
            fields = {}
            if name is not None:
                clean = str(name).strip()
                if not clean:
                    raise LibraryError(
                        "A material needs a name.", code="library.material.needsName"
                    )
                taken = db.execute(
                    "SELECT id FROM material WHERE name = ? COLLATE NOCASE AND id <> ?",
                    (clean, material_id),
                ).fetchone()
                if taken is not None:
                    raise LibraryError(
                        f"There is already a material called '{clean}'. Merge the two "
                        "instead of giving them the same name.",
                        code="library.material.nameTaken",
                    )
                fields["name"] = clean
            if synonyms is not None:
                fields["synonyms"] = "|".join(
                    str(word).strip() for word in synonyms if str(word).strip()
                )
            if not fields:
                raise LibraryError(
                    "Nothing to update.", code="library.material.nothingToUpdate"
                )
            db.execute(
                "UPDATE material SET "
                + ", ".join(f"{key} = ?" for key in fields)
                + " WHERE id = ?",
                (*fields.values(), material_id),
            )
            updated = self._one(db, "material", material_id)
        updated["synonyms"] = [w for w in updated["synonyms"].split("|") if w]
        return updated

    def merge_material(self, source_id: int, target_id: int) -> dict:
        """
        Two names for one board, joined into one — without losing either side's work.

        A merge implemented as remove-and-add would throw away exactly what makes the
        library worth having: the presets, the boards, the photographs and the recipes.
        So nothing is deleted but the row itself, everything that pointed at the source
        now points at the target, and the source's name joins the target's synonyms — so
        that the next import of a bundle calling it by the old name still lands on the
        right board (`_same_material` reads those synonyms).

        Presets that become duplicates are kept, both of them. They are two measurements
        of the same thing and deciding which is right is not a merge's business.
        """
        if source_id == target_id:
            raise LibraryError(
                "A material cannot be merged into itself.",
                code="library.material.mergeSelf",
            )
        with self._connect() as db:
            rows = {}
            for material_id in (source_id, target_id):
                row = db.execute(
                    "SELECT * FROM material WHERE id = ?", (material_id,)
                ).fetchone()
                if row is None:
                    raise LibraryError(
                        f"Material {material_id} does not exist.",
                        code="library.material.unknown",
                    )
                rows[material_id] = row
            source, target = rows[source_id], rows[target_id]
            words = _union_synonyms(target, source)
            moved = {
                "presets": db.execute(
                    "UPDATE preset SET material_id = ? WHERE material_id = ?",
                    (target_id, source_id),
                ).rowcount,
                "test_grids": db.execute(
                    "UPDATE test_grid SET material_id = ? WHERE material_id = ?",
                    (target_id, source_id),
                ).rowcount,
                "grid_recipes": db.execute(
                    "UPDATE grid_recipe SET material_id = ? WHERE material_id = ?",
                    (target_id, source_id),
                ).rowcount,
            }
            db.execute(
                "UPDATE material SET synonyms = ? WHERE id = ?",
                ("|".join(words), target_id),
            )
            db.execute("DELETE FROM material WHERE id = ?", (source_id,))
            merged = self._one(db, "material", target_id)
        merged["synonyms"] = [w for w in merged["synonyms"].split("|") if w]
        sheets = self._repoint_sheets(source_id, target_id)
        return {
            "material": merged,
            "removed": source_id,
            "moved": moved,
            "sheets": sheets,
        }

    def remove_material(self, material_id: int, with_everything: bool = False) -> dict:
        """
        Removing a material, and only knowingly removing the work that hangs off it.

        This used to be a bare DELETE against `PRAGMA foreign_keys = ON`, which is a
        data-loss button with a label on it: measured on a copy of the live library,
        removing `Berkentriplex` took six settings — two of them measured, with
        photographs — orphaned two boards and answered `{"removed": 6}`. So the count
        comes first and the refusal names it, and `with_everything` is the word for
        "yes, all of it".

        The cascade does four things the foreign keys cannot, and each of them was a
        dangler somebody would have met: the squares in `test_grid.cells` name presets by
        id inside a JSON string, `preset.origin_id` names a board as the text
        `"testgrid:12"`, the photographs are files beside the database (only `clear()`
        ever unlinked one), and the sheet on the table names a material in a JSON file.

        All the SQL is one transaction. The file work happens after it commits, because
        an unlink cannot be rolled back and a photograph deleted for a delete that then
        failed is evidence lost for nothing.
        """
        usage = self.material_usage(material_id)
        carries = usage["presets"] or usage["test_grids"] or usage["grid_recipes"]
        if carries and not with_everything:
            raise LibraryError(
                f"'{usage['name']}' still carries {usage['presets']} setting(s), "
                f"{usage['test_grids']} test board(s) and {usage['grid_recipes']} "
                "recipe(s). Remove it with everything on it, or move those first.",
                code="library.material.inUse",
            )
        with self._connect() as db:
            preset_ids = [
                row[0]
                for row in db.execute(
                    "SELECT id FROM preset WHERE material_id = ?", (material_id,)
                )
            ]
            grids = db.execute(
                "SELECT id, photo_path FROM test_grid WHERE material_id = ?",
                (material_id,),
            ).fetchall()
            photos = [row["photo_path"] for row in grids]
            # Boards first, so `_forget_presets` afterwards only has to walk the boards
            # that survive.
            db.execute("DELETE FROM test_grid WHERE material_id = ?", (material_id,))
            self._forget_grids(db, [row["id"] for row in grids])
            db.execute("DELETE FROM preset WHERE material_id = ?", (material_id,))
            db.execute("DELETE FROM grid_recipe WHERE material_id = ?", (material_id,))
            self._forget_presets(db, preset_ids)
            db.execute("DELETE FROM material WHERE id = ?", (material_id,))
        return {
            "removed": material_id,
            "presets": len(preset_ids),
            "test_grids": len(grids),
            "grid_recipes": usage["grid_recipes"],
            "photos": len(self._unlink_photos(photos)),
            "sheets": self._repoint_sheets(material_id, None),
        }

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
            raise LibraryError(
                "A preset belongs to a material.", code="library.preset.needsMaterial"
            )
        operation = str(fields.get("operation") or "").strip()
        if operation not in OPERATIONS:
            raise LibraryError(
                f"Unknown operation: {operation or '(empty)'}",
                code="library.preset.unknownOperation",
            )
        source = str(fields.get("source") or "handmatig")
        if source not in SOURCES:
            raise LibraryError(
                f"Unknown source: {source}", code="library.preset.unknownSource"
            )

        speed = _number(fields.get("speed_mm_s"), "speed_mm_s", positive=True)
        power = _number(fields.get("power_percent"), "power_percent", positive=True)
        if power > 100:
            raise LibraryError(
                "power_percent cannot go above 100.",
                code="library.preset.powerRange",
                values={"max": 100},
            )

        try:
            with self._connect() as db:
                cursor = db.execute(
                    """INSERT INTO preset (material_id, machine_id, thickness_mm, operation,
                            speed_mm_s, power_percent, passes, interval_mm, air_assist,
                            focus_offset_mm, source, origin_id, note,
                            import_batch, origin_laser_type, origin_power_watt,
                            origin_by)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                        str(fields.get("import_batch") or ""),
                        str(fields.get("origin_laser_type") or "") or None,
                        # Deliberately not range-checked the way our own profile's
                        # wattage is: this records what a stranger's machine was, and a
                        # nonsense figure in a shared catalogue is a row to skip and
                        # count, not a 409 that takes the whole import down.
                        _number(
                            fields.get("origin_power_watt"),
                            "origin_power_watt",
                            optional=True,
                        ),
                        str(fields.get("origin_by") or "") or None,
                    ),
                )
                preset_id = cursor.lastrowid
        except sqlite3.IntegrityError as e:
            raise LibraryError(
                "That material does not exist.", code="library.preset.unknownMaterial"
            ) from e
        return self.preset(preset_id)

    def preset(self, preset_id: int) -> dict:
        """
        One setting, with the board behind it if there is one.

        The joins are the same ones `presets()` has, and they are here because the row
        was the only way to reach a setting one at a time and it arrived without its
        evidence: `presetariat.as_contribution` had the speed and the power and could not
        see that a photographed board was hanging off the row, so it offered every
        measurement it had as a guess. Two fields are new on both counts — `grid_uid`,
        the board's own name, which is what the shared catalogue points at, and
        `grid_machine_id`, which is the only way to notice that a measured row has since
        been filed under a different laser than the one it was burned on.
        """
        with self._connect() as db:
            row = db.execute(
                """SELECT p.*, m.name AS material_name, mp.name AS machine_name,
                          g.id AS grid_id, g.uid AS grid_uid, g.photo_path AS grid_photo,
                          g.created_at AS grid_date, g.cells AS grid_cells,
                          g.machine_id AS grid_machine_id,
                          (g.alignment IS NOT NULL) AS grid_aligned
                   FROM preset p
                   JOIN material m ON m.id = p.material_id
                   LEFT JOIN machine_profile mp ON mp.id = p.machine_id
                   LEFT JOIN test_grid g ON p.origin_id = 'testgrid:' || g.id
                   WHERE p.id = ?""",
                (preset_id,),
            ).fetchone()
        if row is None:
            raise LibraryError(
                f"Preset {preset_id} does not exist.", code="library.preset.unknown"
            )
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
        # What came out of the material. Adjustable and not fixed like the source is: the
        # source says how the numbers came about and that cannot change, while this is an
        # observation about a piece of wood that somebody may well have got wrong the
        # first time.
        "result_charring": lambda v: _charring(v),
        "result_cut_through": lambda v: 1 if v else 0,
        "result_kerf_mm": lambda v: _kerf(v),
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
                "source belong to the identity of a preset.",
                code="library.preset.fixedField",
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

    def verify_preset(self, preset_id: int) -> dict:
        """
        Somebody burned this setting again and it still held.

        The only claim about a shared setting that one maintainer can ever check, so it is
        worth recording — and deliberately *not* a condition on sharing. A share button
        that demands a re-burn is a share button nobody presses, and then the catalogue
        stays empty for a reason that sounds like rigour.
        """
        self.preset(preset_id)
        with self._connect() as db:
            db.execute(
                "UPDATE preset SET verified_at = ? WHERE id = ?", (_now(), preset_id)
            )
        return self.preset(preset_id)

    def remove_preset(self, preset_id: int) -> dict:
        with self._connect() as db:
            cursor = db.execute("DELETE FROM preset WHERE id = ?", (preset_id,))
            if not cursor.rowcount:
                raise LibraryError(
                    f"Preset {preset_id} does not exist.",
                    code="library.preset.unknown",
                )
            # The square that produced it names it by id inside a JSON string, where no
            # constraint reaches. Without this the result window keeps offering a setting
            # that is not there any more.
            self._forget_presets(db, [preset_id])
        return {"removed": preset_id}

    def remove_import_batch(self, batch: str) -> dict:
        """
        Taking one import back, in one call.

        This is the strongest defence there is against a library turning into a junk
        drawer, and the reason is arithmetic: one bulk tick-list produced fourteen of the
        author's twenty materials and twenty-six of the thirty-five presets, all bound to
        a machine nobody had described, and until now not one of them could be removed
        again. An import you can undo is not a dump.

        The materials go too, but only the ones this import created (`material.import_batch`)
        *and* that nothing else uses any more. A board the user typed in themselves keeps
        its own presets and its own name whatever an import did around it.
        """
        key = str(batch or "").strip()
        if not key:
            raise LibraryError(
                "An import needs a name to be taken back by.",
                code="library.import.needsBatch",
            )
        with self._connect() as db:
            preset_ids = [
                row[0]
                for row in db.execute(
                    "SELECT id FROM preset WHERE import_batch = ?", (key,)
                )
            ]
            material_ids = [
                row[0]
                for row in db.execute(
                    "SELECT id FROM material WHERE import_batch = ?", (key,)
                )
            ]
            if not preset_ids and not material_ids:
                raise LibraryError(
                    f"There is no import called '{key}' in this library.",
                    code="library.import.unknownBatch",
                )
            db.execute("DELETE FROM preset WHERE import_batch = ?", (key,))
            self._forget_presets(db, preset_ids)
            gone = []
            for material_id in material_ids:
                left = sum(
                    db.execute(
                        f"SELECT COUNT(*) FROM {table} WHERE material_id = ?",
                        (material_id,),
                    ).fetchone()[0]
                    for table in ("preset", "test_grid", "grid_recipe")
                )
                if left:
                    continue
                db.execute("DELETE FROM material WHERE id = ?", (material_id,))
                gone.append(material_id)
        sheets = sum(self._repoint_sheets(material_id, None) for material_id in gone)
        return {
            "batch": key,
            "presets": len(preset_ids),
            "materials": gone,
            "kept_materials": [m for m in material_ids if m not in gone],
            "sheets": sheets,
        }

    # ------------------------------------------------------------ testrasters

    def test_grids(self) -> list[dict]:
        with self._connect() as db:
            rows = db.execute(
                """SELECT g.*, m.name AS material_name
                   FROM test_grid g
                   LEFT JOIN material m ON m.id = g.material_id
                   ORDER BY g.created_at DESC, g.id DESC"""  # created_at is accurate to the second
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
            raise LibraryError(
                f"Test grid {grid_id} does not exist.", code="library.grid.unknown"
            )
        return _grid_row(row)

    def test_grid_for_uid(self, uid: str | None) -> dict | None:
        """
        The board a code names, or None when this library holds no such board.

        None rather than a refusal, and that is the point of the method: the code in a
        photograph can fail in three different ways, and only the caller knows which
        sentence the user needs. Nothing here reads back — no code found. A board that
        belongs to somebody else's library — a name this library does not know. A board
        that is not the one the user picked — the mix-up this whole feature exists to
        prevent. One raise here would flatten all three into one sentence.

        `boardcode.parse` first, so a uid typed off a plank finds the same board as one a
        camera read: `7x4m qb2k`, `OK1:7X4MQB2K` and `7X4MQB2K` are one name. The unique
        index `test_grid_uid` makes this at most one row.
        """
        from .boardcode import parse

        clean = parse(uid)
        if not clean:
            return None
        with self._connect() as db:
            row = db.execute(
                """SELECT g.*, m.name AS material_name
                   FROM test_grid g
                   LEFT JOIN material m ON m.id = g.material_id
                   WHERE g.uid = ?""",
                (clean,),
            ).fetchone()
        return _grid_row(row) if row is not None else None

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
                    "An alignment consists of four points with an x and a y.",
                    code="library.grid.badAlignment",
                )
            for point in clean:
                if not (0 <= point["x"] <= 1 and 0 <= point["y"] <= 1):
                    raise LibraryError(
                        "A corner lies outside the photo.",
                        code="library.grid.cornerOutside",
                    )
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
        # Whether the board names itself and whether the tile comes loose are choices about
        # how you work, not about this one material, so they belong with the rest of the
        # form the next board starts from. `uid` deliberately does not: a name is one
        # board's, and adopting the previous board's name would give two planks the same
        # one — which is the whole problem this feature exists to solve.
        "code_enabled", "code_size_mm", "cutout_enabled",
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
        The generator settings you saved.

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
            raise LibraryError("A recipe needs a name.", code="library.recipe.needsName")
        if len(name) > 60:
            raise LibraryError(
                "Keep the name under 60 characters.",
                code="library.recipe.nameTooLong",
                values={"max": 60},
            )
        if not isinstance(settings, dict):
            raise LibraryError(
                "A recipe consists of settings.", code="library.recipe.needsSettings"
            )
        clean = _recipe_settings(settings)
        if not clean:
            raise LibraryError(
                "There were no usable settings in this recipe.",
                code="library.recipe.emptySettings",
            )
        if material_id is not None and not any(
            m["id"] == material_id for m in self.materials()
        ):
            raise LibraryError(
                f"Material {material_id} does not exist.",
                code="library.material.unknown",
            )
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
        raise LibraryError(
            f"Recipe {recipe_id} does not exist.", code="library.recipe.unknown"
        )

    def remove_grid_recipe(self, recipe_id: int) -> dict:
        with self._connect() as db:
            cursor = db.execute("DELETE FROM grid_recipe WHERE id = ?", (recipe_id,))
            if not cursor.rowcount:
                raise LibraryError(
                    f"Recipe {recipe_id} does not exist.",
                    code="library.recipe.unknown",
                )
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
                        label_speed_mm_s, label_power_percent,
                        uid, caption,
                        outer_x_mm, outer_y_mm, outer_width_mm, outer_height_mm,
                        code_enabled, code_size_mm, code_x_mm, code_y_mm,
                        cutout_enabled, cutout_preset_id,
                        cut_x_mm, cut_y_mm, cut_width_mm, cut_height_mm)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                           ?, ?, ?, ?, ?, ?,
                           ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                    # The name the plan already minted, so the code drawn on the plank and
                    # the row in the database are the same name. A plan from before this
                    # round has none, and then the board still gets one — a board without
                    # a name cannot be found back from a photograph.
                    _fresh_grid_uid(db, plan.get("uid")),
                    plan.get("caption") or None,
                    plan.get("outer_x_mm"),
                    plan.get("outer_y_mm"),
                    plan.get("outer_width_mm"),
                    plan.get("outer_height_mm"),
                    1 if plan.get("code_enabled") else 0,
                    plan.get("code_size_mm"),
                    plan.get("code_x_mm"),
                    plan.get("code_y_mm"),
                    1 if plan.get("cutout_enabled") else 0,
                    plan.get("cutout_preset_id"),
                    plan.get("cut_x_mm"),
                    plan.get("cut_y_mm"),
                    plan.get("cut_width_mm"),
                    plan.get("cut_height_mm"),
                ),
            )
            grid_id = cursor.lastrowid
        return self.test_grid(grid_id)

    def remove_test_grid(self, grid_id: int) -> dict:
        """
        Removing a board, and the two things that would otherwise be left behind.

        `preset.origin_id` is the text `"testgrid:12"`, so no foreign key reaches it: a
        preset made from this board would go on claiming evidence that is gone, and the
        card would offer a photograph that is not there. And the photograph is a file
        beside the database — until now only `clear()` ever unlinked one, so every board
        removed left its picture on disk for ever.
        """
        with self._connect() as db:
            row = db.execute(
                "SELECT photo_path FROM test_grid WHERE id = ?", (grid_id,)
            ).fetchone()
            if row is None:
                raise LibraryError(
                    f"Test grid {grid_id} does not exist.",
                    code="library.grid.unknown",
                )
            db.execute("DELETE FROM test_grid WHERE id = ?", (grid_id,))
            self._forget_grids(db, [grid_id])
        return {
            "removed": grid_id,
            "photos": len(self._unlink_photos([row["photo_path"]])),
        }

    def set_grid_photo(self, grid_id: int, suffix: str, data: bytes) -> dict:
        """Store the photo of a burned grid and remember where it went."""
        grid = self.test_grid(grid_id)
        safe = (suffix or "").lower()
        if safe not in (".jpg", ".jpeg", ".png", ".webp", ".heic"):
            raise LibraryError(
                f"Unknown photo format: {suffix or '(none)'}",
                code="library.photo.unknownFormat",
            )
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
            raise LibraryError(
                f"Cell {row},{column} does not belong to grid {grid_id}.",
                code="library.grid.unknownCell",
            )
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
            raise LibraryError(
                "That file is not there (any more).", code="library.bundle.missingFile"
            )
        if not zipfile.is_zipfile(source):
            raise LibraryError(
                "This is not an OpenKerf library. A library file ends "
                f"in {BUNDLE_SUFFIX}.",
                code="library.bundle.notALibrary",
                values={"suffix": BUNDLE_SUFFIX},
            )
        with zipfile.ZipFile(source) as bundle:
            names = bundle.namelist()
            index = BUNDLE_INDEX if BUNDLE_INDEX in names else LEGACY_BUNDLE_INDEX
            if index not in names:
                raise LibraryError(
                    "This file holds no library.", code="library.bundle.noIndex"
                )
            try:
                data = json.loads(bundle.read(index))
            except ValueError as e:
                raise LibraryError(
                    "The library in this file is damaged.",
                    code="library.bundle.damaged",
                ) from e
        if not isinstance(data, dict) or data.get("format") != BUNDLE_FORMAT:
            raise LibraryError(
                "This file did not come from an OpenKerf library.",
                code="library.bundle.wrongFormat",
            )
        if int(data.get("version") or 0) > BUNDLE_VERSION:
            raise LibraryError(
                "This file comes from a newer version of OpenKerf. Update first.",
                code="library.bundle.tooNew",
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
        import_batch: str = "",
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

        `import_batch` stamps everything this call creates with one name, so that
        `remove_import_batch` can take exactly this import back later. Empty for a plain
        restore-from-backup: there is nothing to undo about your own library arriving.
        """
        import zipfile

        if mode not in ("merge", "replace"):
            raise LibraryError(f"Unknown choice: {mode}", code="library.bundle.unknownMode")
        if on_conflict not in ("mine", "file"):
            raise LibraryError(
                f"Unknown choice on a clash: {on_conflict}",
                code="library.bundle.unknownConflict",
            )
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
                match = self.add_material(
                    name, material.get("synonyms"), import_batch=import_batch
                )
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
                preset, target, machine_id, grid_id, import_batch
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
                        label_speed_mm_s, label_power_percent,
                        uid, caption,
                        outer_x_mm, outer_y_mm, outer_width_mm, outer_height_mm,
                        code_enabled, code_size_mm, code_x_mm, code_y_mm,
                        cutout_enabled, cut_x_mm, cut_y_mm, cut_width_mm, cut_height_mm)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                           ?, ?, ?, ?, ?,
                           ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                    # The name travels with the board, because it is burned on the plank:
                    # a photograph of that plank decodes this and nothing else. Only when
                    # it is already taken here does a fresh one get minted.
                    _fresh_grid_uid(db, grid.get("uid")),
                    grid.get("caption"),
                    grid.get("outer_x_mm"),
                    grid.get("outer_y_mm"),
                    grid.get("outer_width_mm"),
                    grid.get("outer_height_mm"),
                    1 if grid.get("code_enabled") else 0,
                    grid.get("code_size_mm"),
                    grid.get("code_x_mm"),
                    grid.get("code_y_mm"),
                    1 if grid.get("cutout_enabled") else 0,
                    grid.get("cut_x_mm"),
                    grid.get("cut_y_mm"),
                    grid.get("cut_width_mm"),
                    grid.get("cut_height_mm"),
                    # `cutout_preset_id` deliberately does not travel. Presets are inserted
                    # *after* the grids (they need the new grid ids for `origin_id`), so the
                    # number in the bundle names a row in somebody else's library; keeping
                    # it would point at whatever preset happens to have that id here.
                ),
            )
            return cursor.lastrowid

    def _insert_preset(
        self,
        preset: dict,
        material_id: int,
        machine_id: dict,
        grid_id: dict,
        import_batch: str = "",
    ) -> int:
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
                        focus_offset_mm, source, origin_id, note, last_used_at, created_at,
                        import_batch, origin_laser_type, origin_power_watt, verified_at,
                        origin_by, result_charring, result_cut_through, result_kerf_mm)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                           ?, ?, ?)""",
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
                    import_batch,
                    preset.get("origin_laser_type"),
                    preset.get("origin_power_watt"),
                    preset.get("verified_at"),
                    # The credit travels with the row. A bundle from a colleague may carry
                    # a preset that came out of the shared catalogue, and CC BY does not
                    # stop applying because the file went via somebody's laptop.
                    preset.get("origin_by"),
                    # And so does what came out of the material. A bundle carries the
                    # boards and their photographs, so leaving the outcome behind would
                    # mean a restored library could no longer offer its own measurements
                    # as measurements.
                    preset.get("result_charring"),
                    preset.get("result_cut_through"),
                    preset.get("result_kerf_mm"),
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
            changed = False
            for cell in grid["cells"]:
                target = preset_id.get(cell.get("preset_id"))
                if target is not None and target != cell.get("preset_id"):
                    cell["preset_id"] = target
                    changed = True
            if changed:
                with self._connect() as db:
                    db.execute(
                        "UPDATE test_grid SET cells = ? WHERE id = ?",
                        (json.dumps(grid["cells"]), fresh),
                    )

    # ------------------------------------------------- the four danglers ----
    #
    # Everything below cleans up after a delete in a place SQLite's own constraints
    # cannot reach. Each of them was measured on a copy of the live library, and each of
    # them is the kind of damage you only see weeks later, on the screen, in front of a
    # laser.

    @staticmethod
    def _forget_presets(db, preset_ids) -> int:
        """
        Take removed presets out of the squares that produced them.

        `test_grid.cells` is JSON, so `preset.id` sits in there as a plain number that no
        foreign key knows about. A removed preset therefore leaves its id in a square, and
        the result window then offers a setting that does not exist. Walks every board
        because a board of one material can perfectly well have produced a preset filed
        under another.
        """
        wanted = {int(i) for i in preset_ids}
        if not wanted:
            return 0
        touched = 0
        for row in db.execute("SELECT id, cells FROM test_grid").fetchall():
            try:
                cells = json.loads(row["cells"] or "[]")
            except ValueError:  # pragma: no cover - a board written by hand
                continue
            hit = False
            for cell in cells:
                if cell.get("preset_id") in wanted:
                    cell["preset_id"] = None
                    hit = True
            if hit:
                db.execute(
                    "UPDATE test_grid SET cells = ? WHERE id = ?",
                    (json.dumps(cells), row["id"]),
                )
                touched += 1
        return touched

    @staticmethod
    def _forget_grids(db, grid_ids) -> int:
        """
        Let go of a board that is gone.

        `origin_id` is a string ("testgrid:12") rather than a foreign key, so nothing
        nulls it by itself. The preset keeps its `source = 'testraster'` — it *was*
        measured, and rewriting that would be a bigger lie than a missing photograph.
        """
        forgotten = 0
        for grid_id in grid_ids:
            forgotten += db.execute(
                "UPDATE preset SET origin_id = NULL WHERE origin_id = ?",
                (f"testgrid:{grid_id}",),
            ).rowcount
        return forgotten

    def _unlink_photos(self, paths) -> list[str]:
        """
        The photo files, after the database has committed.

        Deliberately outside the transaction: an unlink cannot be rolled back, and a
        photograph deleted for a delete that then failed is evidence lost for nothing.
        Only files inside our own photo directory are touched, because `photo_path` is
        just a string in a database and an imported bundle can put anything in it.
        """
        gone = []
        for raw in paths:
            if not raw:
                continue
            path = Path(raw)
            try:
                if not path.resolve().is_relative_to(self.photos.resolve()):
                    continue
                path.unlink(missing_ok=True)
            except OSError:  # pragma: no cover - a photo directory we cannot read
                continue
            gone.append(str(path))
        return gone

    @property
    def _sheets_index(self) -> Path:
        """
        Where the sheets on the table are listed.

        `Sheets` is built with `_beside("openkerf-sheets", "openkerf-vellen")`
        (server.py:292), which is `library.path.with_name(...)`, and its index inside that
        directory is still called `vellen.json` (sheets.py:57) — the state file kept its
        name when the interface became English, so that live work was not thrown away.
        Only the new directory name is looked for: by the time anything here runs, the
        server has already moved the old one.
        """
        return self.path.with_name("openkerf-sheets") / "vellen.json"

    def _read_sheets(self) -> list[dict]:
        try:
            sheets = json.loads(self._sheets_index.read_text())
        except (OSError, ValueError):
            return []
        return sheets if isinstance(sheets, list) else []

    def _repoint_sheets(self, old_material_id: int, new_material_id: int | None) -> int:
        """
        The sheet on the table names its material by id, in a file the database cannot see.

        Without this, removing a material leaves the top bar naming a material that is
        gone, and merging two names leaves the sheet on the one that was merged away —
        which is how `drawing.py`'s comparison ends up saying "this sheet is this sheet".
        `Sheets` re-reads its index on every call, so writing it here is picked up at
        once.
        """
        sheets = self._read_sheets()
        touched = 0
        for sheet in sheets:
            if sheet.get("material_id") == old_material_id:
                sheet["material_id"] = new_material_id
                touched += 1
        if touched:
            self._sheets_index.write_text(
                json.dumps(sheets, indent=1, ensure_ascii=False)
            )
        return touched

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _one(db, table: str, row_id: int) -> dict:
        row = db.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()
        return dict(row)


def _fresh_grid_uid(db, wanted: str | None = None) -> str:
    """
    A board name nothing in this library carries yet.

    `wanted` is a name that came in from somewhere — a bundle being imported — and it is
    kept when it is free, because that name is on a plank somewhere and a photograph of
    that plank will decode it. Taken, and it is replaced rather than refused: two libraries
    merging must not fail on a name, and the board itself is still the same evidence.

    The retry is for the unique index rather than for the odds: forty bits from `secrets`
    against a library of tens of boards collides with a probability around 1 in 30 million,
    and going round again costs one indexed lookup.
    """
    from .boardcode import mint_uid, parse

    def free(candidate: str) -> bool:
        return (
            db.execute(
                "SELECT 1 FROM test_grid WHERE uid = ?", (candidate,)
            ).fetchone()
            is None
        )

    clean = parse(wanted)
    if clean and free(clean):
        return clean
    for _ in range(8):
        candidate = mint_uid()
        if free(candidate):
            return candidate
    raise LibraryError(
        "Could not find a free name for this board; try again.",
        code="library.grid.noFreeUid",
    )


def _grid_row(row) -> dict:
    data = dict(row)
    data["cells"] = json.loads(data["cells"])
    data["alignment"] = _alignment(data.get("alignment"))
    # SQLite has no booleans; the wizard does set ticks with them.
    for key in ("text_enabled", "border_enabled", "code_enabled", "cutout_enabled"):
        if key in data:
            data[key] = bool(data[key])
    return data


# The values of the quantities that are *not* on an axis. They belong to a recipe —
# otherwise "engrave birch at 40%" is not a recipe but half a recipe — but not to
# GRID_DEFAULTS, because there they appear as min == max in the series.
_FIXED_FIELDS = ("speed_mm_s", "power_percent", "interval_mm")


def _recipe_settings(raw: dict) -> dict:
    """
    Only the keys that describe a grid, in the right type.

    A recipe is a JSON blob in the database, and that is exactly where rubbish gets in. Here
    what does not belong goes out, so that the wizard can trust it blindly.
    """
    kept = {}
    for key in tuple(Library.GRID_DEFAULTS) + _FIXED_FIELDS:
        if key not in raw or raw[key] is None:
            continue
        value = raw[key]
        if key in ("text_enabled", "border_enabled", "code_enabled", "cutout_enabled"):
            kept[key] = bool(value)
        elif key in ("operation", "row_axis", "column_axis", "anchor"):
            kept[key] = str(value)
        else:
            try:
                kept[key] = float(value)
            except (TypeError, ValueError):
                continue
    return kept


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
        for cell in json.loads(cells):
            if cell.get("preset_id") == data["id"]:
                data["grid_cell"] = {"row": cell["row"], "column": cell["column"]}
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


def _union_synonyms(target, source) -> list[str]:
    """
    Both materials' other names, plus the name that is being merged away.

    The old name has to survive as a synonym or the merge quietly breaks the next import:
    a bundle calling the board `Multiplex berken` would create it again beside
    `Berkentriplex` and we would be back where we started. Compared without accents or
    capitals, but the first spelling is the one that is kept — it is what somebody typed.
    """
    words: list[str] = []
    seen = {_norm(target["name"])}
    for text in (
        *(target["synonyms"] or "").split("|"),
        source["name"],
        *(source["synonyms"] or "").split("|"),
    ):
        word = str(text).strip()
        if not word or _norm(word) in seen:
            continue
        seen.add(_norm(word))
        words.append(word)
    return words


# What a laser can plausibly be. Ours, not measured, so the numbers travel in
# X-OpenKerf-Error-Values and the sentence can be translated.
WATT_MIN, WATT_MAX = 1, 1000

# The three answers to the starting-values offer: not asked yet, waved away, and "I do not
# know what my tube is" — which is a legitimate answer and not a dead end, because
# `dev_info` carries no wattage anywhere to default from.
STARTER_STATES = ("", "dismissed", "power_unknown")


def _starter_state(value) -> str:
    state = str(value or "")
    if state not in STARTER_STATES:
        raise LibraryError(
            f"Unknown state for the starting-values offer: {state}",
            code="library.machine.unknownStarterState",
        )
    return state


def _watt(value):
    """A tube power, or nothing at all — but never a number no laser has."""
    number = _number(value, "power_watt", optional=True)
    if number is None:
        return None
    if not (WATT_MIN <= number <= WATT_MAX):
        raise LibraryError(
            f"A tube power between {WATT_MIN} and {WATT_MAX} watt, please.",
            code="library.machine.wattRange",
            values={"min": WATT_MIN, "max": WATT_MAX},
        )
    return number


def _percent(value):
    number = _number(value, "power_percent", positive=True)
    if number > 100:
        raise LibraryError(
            "power_percent cannot go above 100.",
            code="library.preset.powerRange",
            values={"max": 100},
        )
    return number


#: The three words the shared catalogue's schema allows for how badly the edge burned
#: (`result.charring`). English values, like everything this round writes: they are the
#: catalogue's own enum, and a Dutch word here would be a row nobody could merge.
CHARRING = ("none", "light", "heavy")


def _charring(value) -> str:
    """One of the catalogue's three words for the edge, or a refusal."""
    text = str(value or "").strip().lower()
    if text not in CHARRING:
        raise LibraryError(
            f"Charring is one of {', '.join(CHARRING)}, and not {value!r}.",
            code="library.preset.charring",
        )
    return text


def _kerf(value):
    """
    The width the beam took out, within the range the catalogue accepts.

    The bound is the schema's own (`kerf_mm`, minimum 0 and maximum 5), checked here
    rather than at the moment of offering: a kerf of 50 mm is a typo whichever way the
    row is later used, and finding out at the proposal is finding out too late.
    """
    number = _number(value, "result_kerf_mm", optional=True)
    if number is not None and not 0 <= number <= 5:
        raise LibraryError(
            "A kerf is measured in millimetres and this one is out of range.",
            code="library.preset.kerfRange",
            values={"kerf": number, "max": 5},
        )
    return number


def _number(value, name: str, positive: bool = False, optional: bool = False):
    if value is None or value == "":
        if optional:
            return None
        raise LibraryError(
            f"{name} is required.", code="library.value.required", values={"field": name}
        )
    try:
        number = float(value)
    except (TypeError, ValueError) as e:
        raise LibraryError(
            f"{name} has to be a number.",
            code="library.value.notANumber",
            values={"field": name},
        ) from e
    if positive and number <= 0:
        raise LibraryError(
            f"{name} has to be greater than zero.",
            code="library.value.notPositive",
            values={"field": name},
        )
    return number
