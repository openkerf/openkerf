"""
Editing the library, and the schema that had to make room for it.

Two halves, in this order because the second depends on the first.

The **schema** half is about a migration that runs against somebody's real 204 KB file
the first time they start. It was column-sniffing with no version stamp, and the step at
the end of it — `_dedupe_machines`, which DELETEs rows and rewrites foreign keys — ran on
every single construction of `Library`. Proved on the author's own library, wound back to
the shape it had before this round: 7 profiles, 20 materials, 35 presets, 32 boards and
1 recipe in, the same counts out, speed/power/passes sums identical at 3373.0 / 1940.0 /
36, and 26 Dutch notes turned into 26 English ones.

The **verbs** half is about a window that could add a material and never rename, merge or
remove one — which is why the live library holds both `Multiplex berken` and
`Berkentriplex` for one board, and why fourteen materials an import invented could not be
taken out again.
"""

import json
import sqlite3
from pathlib import Path

import pytest

from openkerf_api.library import Library, LibraryError

# A one-pixel PNG, so a board can have a photo file that really exists on disk.
PHOTO = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100"
    "05fe02fea7d4b2000000000049454e44ae426082"
)

# The library before any of the columns `_migrate` adds — the oldest shape that can still
# be sitting on somebody's disk, and the one this migration has to be able to carry.
# `PRAGMA user_version` on it is 0, and so it is on the author's real file: measured.
ANCIENT_SCHEMA = """
CREATE TABLE machine_profile (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    laser_type TEXT NOT NULL DEFAULT 'co2-glass',
    power_watt REAL, lens_mm REAL, bed_width_mm REAL, bed_height_mm REAL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE material (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    synonyms TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE preset (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id INTEGER NOT NULL REFERENCES material(id) ON DELETE CASCADE,
    machine_id INTEGER REFERENCES machine_profile(id) ON DELETE SET NULL,
    thickness_mm REAL, operation TEXT NOT NULL,
    speed_mm_s REAL NOT NULL, power_percent REAL NOT NULL,
    passes INTEGER NOT NULL DEFAULT 1,
    air_assist INTEGER NOT NULL DEFAULT 1,
    focus_offset_mm REAL NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'handmatig',
    origin_id TEXT, note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE test_grid (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id INTEGER REFERENCES material(id) ON DELETE SET NULL,
    machine_id INTEGER REFERENCES machine_profile(id) ON DELETE SET NULL,
    thickness_mm REAL, operation TEXT NOT NULL,
    speed_min REAL NOT NULL, speed_max REAL NOT NULL, speed_steps INTEGER NOT NULL,
    power_min REAL NOT NULL, power_max REAL NOT NULL, power_steps INTEGER NOT NULL,
    cell_mm REAL NOT NULL, gap_mm REAL NOT NULL,
    origin_x_mm REAL NOT NULL, origin_y_mm REAL NOT NULL,
    cells TEXT NOT NULL, photo_path TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE grid_recipe (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    material_id INTEGER REFERENCES material(id) ON DELETE CASCADE,
    settings TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

# The note `presetariat._note` wrote, verbatim in all 26 imported rows of the live
# library. Dutch, in an interface that has been English since the language round.
DUTCH_NOTE = (
    "Uit Presetariat (handmatig), door presetariat-prefill — Startwaarde, niet "
    "gemeten. Brand een testraster voordat je hier op vertrouwt."
)


@pytest.fixture
def library(tmp_path):
    return Library(tmp_path / "library.db")


def ancient(path: Path, rows: bool = True) -> Path:
    """A database from before the migration, optionally with work already in it."""
    db = sqlite3.connect(path)
    db.executescript(ANCIENT_SCHEMA)
    if rows:
        db.execute("INSERT INTO machine_profile (name) VALUES ('5030 CO2')")
        db.execute("INSERT INTO material (name) VALUES ('Berkentriplex')")
        db.execute(
            """INSERT INTO preset (material_id, operation, speed_mm_s, power_percent,
                                   source, origin_id, note)
               VALUES (1, 'snijden', 12, 65, 'geimporteerd', 'birch-3mm-cut', ?)""",
            (DUTCH_NOTE,),
        )
        db.execute(
            """INSERT INTO test_grid (material_id, operation, speed_min, speed_max,
                    speed_steps, power_min, power_max, power_steps, cell_mm, gap_mm,
                    origin_x_mm, origin_y_mm, cells)
               VALUES (1, 'snijden', 8, 20, 4, 40, 100, 4, 8, 2, 0, 0, '[]')"""
        )
    db.commit()
    db.close()
    return path


def columns_of(path: Path) -> dict:
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    tables = [
        row["name"]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%'"
        )
    ]
    found = {
        table: {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
        for table in tables
    }
    db.close()
    return found


def plan_for(material_id, machine_id=None) -> dict:
    """The smallest board `add_test_grid` accepts."""
    return {
        "material_id": material_id,
        "machine_id": machine_id,
        "thickness_mm": 3,
        "operation": "snijden",
        "speed_min": 8, "speed_max": 20, "speed_steps": 2,
        "power_min": 40, "power_max": 100, "power_steps": 2,
        "cell_mm": 8, "gap_mm": 2, "origin_x_mm": 0, "origin_y_mm": 0,
    }


# ============================================================== the schema ====


def test_a_migrated_database_has_the_same_columns_as_a_fresh_one(tmp_path):
    """
    Every column has to be written twice — in `SCHEMA` and in `_migrate` — and forgetting
    one is silent: the fresh-database suite stays green and only somebody with an existing
    library ever meets the missing column. This is the only check that notices.
    """
    old = ancient(tmp_path / "old.db")

    Library(old)
    fresh = Library(tmp_path / "fresh.db").path

    assert columns_of(old) == columns_of(fresh)
    # And the columns this round adds are actually in there, not just equal to each other.
    assert {
        "import_batch", "origin_laser_type", "origin_power_watt", "verified_at"
    } <= columns_of(old)["preset"]
    assert {"machine_uid", "starter_state"} <= columns_of(old)["machine_profile"]
    assert "import_batch" in columns_of(old)["material"]


def test_no_column_is_not_null_without_a_default(tmp_path):
    """
    Measured on SQLite 3.50.4: `ALTER TABLE ... ADD COLUMN x TEXT NOT NULL` with no
    default is *accepted* on an empty table and refused on a populated one. Such a
    migration therefore passes a suite that builds fresh databases and breaks the first
    user who has data in theirs — which is everybody with a library.
    """
    fresh = Library(tmp_path / "fresh.db").path

    db = sqlite3.connect(fresh)
    db.row_factory = sqlite3.Row
    trap = [
        f"{table}.{row['name']}"
        for table in columns_of(fresh)
        for row in db.execute(f"PRAGMA table_info({table})")
        # A primary key needs no default: SQLite fills it in.
        if row["notnull"] and row["dflt_value"] is None and not row["pk"]
    ]
    db.close()

    # The columns that were already like this before this round, and that no migration
    # adds — they were in the CREATE TABLE from the start, so no ALTER ever meets them.
    already = {
        "machine_profile.name", "material.name", "grid_recipe.name",
        "grid_recipe.settings",
        "preset.material_id", "preset.operation", "preset.speed_mm_s",
        "preset.power_percent",
        "test_grid.operation", "test_grid.speed_min", "test_grid.speed_max",
        "test_grid.speed_steps", "test_grid.power_min", "test_grid.power_max",
        "test_grid.power_steps", "test_grid.cell_mm", "test_grid.gap_mm",
        "test_grid.origin_x_mm", "test_grid.origin_y_mm", "test_grid.cells",
    }
    assert set(trap) == already


def test_an_old_populated_database_migrates_and_still_takes_inserts(tmp_path):
    """
    The other half of the SQLite trap: the migration has to survive rows being there, and
    the table has to be writable afterwards. Proved on the author's real library wound
    back to its pre-round shape — 7/20/35/32/1 rows in, the same out.
    """
    old = ancient(tmp_path / "old.db")

    library = Library(old)

    assert len(library.materials()) == 1
    assert len(library.presets()) == 1
    assert len(library.test_grids()) == 1
    fresh = library.add_preset(
        material_id=library.materials()[0]["id"],
        operation="graveren-raster",
        speed_mm_s=300,
        power_percent=20,
    )
    assert fresh["import_batch"] == ""
    assert fresh["verified_at"] is None
    # `rows`/`columns` came later and are back-filled from the axes, not left NULL.
    assert library.test_grids()[0]["rows"] == 4


def test_the_migration_is_stamped_and_does_not_run_again(tmp_path):
    """
    `PRAGMA user_version` was 0 for ever, so `_migrate` ran on every construction — and
    with it `_dedupe_machines`, which DELETEs rows and rewrites foreign keys. On a library
    the interface opens three times per page load that is a destructive step on a hot
    path.
    """
    old = ancient(tmp_path / "old.db")
    calls = []
    original = Library._dedupe_machines
    Library._dedupe_machines = staticmethod(
        lambda db: calls.append(1) or original(db)
    )
    try:
        Library(old)
        assert calls == [1], "the first open has to migrate"
        Library(old)
        Library(old)
    finally:
        Library._dedupe_machines = staticmethod(original)

    assert calls == [1], "an at-head database must not be deduped again"
    db = sqlite3.connect(old)
    assert db.execute("PRAGMA user_version").fetchone()[0] == 1
    db.close()


def test_the_dedupe_still_runs_when_the_device_lock_is_gone(tmp_path):
    """
    The gate is a version number, but the thing `_dedupe_machines` guarantees is an index.
    A database whose unique index on `machine_profile(device_path)` is missing can hold two
    profiles for one laser however new its version stamp says it is — and the author's
    library holds two `lihuiyu-device` rows with the same second on them. So the index,
    not the stamp, decides whether the repair is still needed.
    """
    library = Library(tmp_path / "library.db")
    material = library.add_material("Multiplex")
    with sqlite3.connect(library.path) as db:
        db.execute("DROP INDEX IF EXISTS machine_profile_device")
        db.execute(
            "INSERT INTO machine_profile (id, name, device_path) VALUES (1, 'A', 'ruida')"
        )
        db.execute(
            "INSERT INTO machine_profile (id, name, device_path) VALUES (2, 'A', 'ruida')"
        )
    for machine_id in (1, 2):
        library.add_preset(
            material_id=material["id"],
            machine_id=machine_id,
            operation="snijden",
            speed_mm_s=12,
            power_percent=65,
        )

    reopened = Library(library.path)

    assert [m["id"] for m in reopened.machines()] == [1]
    assert {p["machine_id"] for p in reopened.presets()} == {1}


def test_the_prefill_notes_are_said_in_english_and_nothing_else_moves(tmp_path):
    """
    Twenty-six rows of the live library carry a Dutch note in an English interface. They
    cannot be back-filled — the note records `presetariat-prefill` and no machine — so
    they are relabelled and kept. What must *not* happen is a relabel that also touches a
    number: these are usable values.
    """
    old = ancient(tmp_path / "old.db")

    library = Library(old)

    preset = library.presets()[0]
    assert preset["note"] == (
        "From the Presetariat (handmatig), by presetariat-prefill — Starting value, not "
        "measured. Burn a test grid before you rely on it."
    )
    assert preset["speed_mm_s"] == 12 and preset["power_percent"] == 65
    # NULL beside source='geimporteerd' is how "origin machine unknown" is written, and
    # the new column gives every existing row exactly that without a statement of its own.
    assert preset["origin_power_watt"] is None
    assert preset["origin_laser_type"] is None


def test_the_relabel_leaves_a_note_somebody_typed_alone(library):
    """
    The rewrite matches one shape and one only. A note a user wrote is theirs, even when
    it happens to be in Dutch.
    """
    material = library.add_material("Berkentriplex")
    library.add_preset(
        material_id=material["id"],
        operation="snijden",
        speed_mm_s=12,
        power_percent=65,
        source="geimporteerd",
        note="Werkt goed met perslucht",
    )

    Library._relabel_prefill(sqlite3.connect(library.path))

    assert library.presets()[0]["note"] == "Werkt goed met perslucht"


def test_the_schema_is_what_this_suite_thinks_it_is(tmp_path):
    """
    The column set, written down, so that adding one is a line in a review rather than a
    surprise in somebody's database.

    This test began life pinning the columns *against* `SCHEMA_VERSION`, on the grounds
    that a column added without bumping the constant would reach a fresh database and
    never an existing one — measured, and true at the time. That fault is now closed at
    the source instead: `Library._add_missing_columns` runs on every open, so a forgotten
    version bump can no longer hide a missing column, and
    `test_a_column_added_later_reaches_a_database_that_is_already_at_head` pins that.

    What is left worth pinning is this: the shape of the database is a decision, and a
    column that arrives without anybody noticing is how a library grows fields nothing
    reads. Turning this red is the point; making it green again is one name in a list, in
    the commit that adds the column.
    """
    fresh = Library(tmp_path / "fresh.db").path

    assert columns_of(fresh) == {
        "machine_profile": {
            "id", "name", "laser_type", "power_watt", "lens_mm", "bed_width_mm",
            "bed_height_mm", "device_path", "has_z", "has_autofocus", "machine_uid",
            "starter_state", "created_at",
        },
        "material": {"id", "name", "synonyms", "import_batch", "created_at"},
        "preset": {
            "id", "material_id", "machine_id", "thickness_mm", "operation", "speed_mm_s",
            "power_percent", "passes", "interval_mm", "air_assist", "focus_offset_mm",
            "source", "origin_id", "note", "last_used_at", "import_batch",
            "origin_laser_type", "origin_power_watt", "origin_by", "verified_at",
            "created_at",
        },
        "test_grid": {
            "id", "material_id", "machine_id", "thickness_mm", "operation", "passes",
            "speed_min", "speed_max", "speed_steps", "power_min", "power_max",
            "power_steps", "interval_min", "interval_max", "interval_steps", "row_axis",
            "column_axis", "rows", "columns", "cell_mm", "gap_mm", "origin_x_mm",
            "origin_y_mm", "cells", "photo_path", "alignment", "group_id", "anchor",
            "text_enabled", "border_enabled", "label_speed_mm_s", "label_power_percent",
            "created_at",
        },
        "grid_recipe": {
            "id", "name", "material_id", "settings", "created_at", "updated_at",
        },
    }


def test_no_test_opens_the_library_the_developer_uses(kernel, tmp_path):
    """
    A test run must not be the first thing that touches somebody's real database.

    Measured: eleven fixtures in this suite built `ApiServer(kernel)` with no
    `library_path`, and `default_path` is keyed to `kernel.name` and never to the profile
    — so a `pytest api/tests` run opened
    `~/Library/Application Support/MeerK40t/openkerf-library.db`, took it from
    `PRAGMA user_version` 0 to 1 and relabelled its 26 imported notes. Nothing was lost
    that time. The fence is `_library_of_its_own` in conftest.py; this is what notices if
    it goes away, and it also covers the sheets, provenance, palette and tile-series
    files, which `ApiServer._beside` puts next to whatever path the library got.
    """
    from openkerf_api.library import default_path
    from openkerf_api.server import ApiServer

    server = ApiServer(kernel)

    real = default_path(kernel)
    assert Path(server.library.path) != real
    assert tmp_path in Path(server.library.path).parents
    # And the state files that ride along on the library's directory.
    assert tmp_path in Path(server.sheets.directory).parents


def test_every_refusal_carries_a_code(library):
    """
    A refusal without a code can only ever be shown in English, whatever language the
    reader chose — `refuse()` turns `code` into the `X-OpenKerf-Error` header and the
    interface picks the translation from it (server.py:146-152). All 41 raises in this
    module had none.
    """
    import openkerf_api.library as module

    text = Path(module.__file__).read_text()

    # 41 raises before the sweep, none of them coded; 58 now, all of them coded. The
    # equality is the check — a new refusal without a code fails here and nowhere else.
    assert text.count("raise LibraryError") == text.count('code="library.')
    assert text.count("raise LibraryError") >= 41


def test_no_refusal_code_answers_to_two_different_sentences():
    """
    A code is what picks the translation, so two sentences under one code means the
    interface shows one of them for both — and the reader gets an answer to a question
    they did not ask.

    Found twice in this round's own work: `library.material.nameTaken` carried both
    "Material 'x' already exists." (adding) and "There is already a material called 'x'.
    Merge the two instead…" (renaming), and `library.starter.noMachine` carried both
    "nothing to put away" (dismissing) and "nothing to fetch settings for" (staging).
    Both are split now. The allow-list below is the debt this check found in code that
    predates the rule; it is a list of names, not an approval, and it must not grow.
    """
    import ast

    import openkerf_api

    def sentence(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.JoinedStr):
            return "".join(
                part.value if isinstance(part, ast.Constant) else "{}"
                for part in node.values
            )
        if isinstance(node, ast.BinOp):
            return sentence(node.left) + sentence(node.right)
        return "<built at run time>"

    wordings: dict[str, set[str]] = {}
    for path in sorted(Path(openkerf_api.__file__).parent.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Raise) or not isinstance(node.exc, ast.Call):
                continue
            for keyword in node.exc.keywords:
                if keyword.arg == "code" and isinstance(keyword.value, ast.Constant):
                    wordings.setdefault(keyword.value.value, set()).add(
                        sentence(node.exc.args[0]) if node.exc.args else ""
                    )

    doubled = {code for code, said in wordings.items() if len(said) > 1}
    older_debt = {
        "bridges.needsCount", "draw.needsTwo", "focus.notANumber",
        "focus.powerTooHigh", "nodes.needsNumber", "plate.noSize",
    }
    assert doubled == older_debt
    # And the codes this round introduced are on the right side of it.
    assert "library.material.nameTaken" in wordings
    assert "library.material.exists" in wordings
    assert not {code for code in doubled if code.startswith(("library.", "presetariat."))}


def test_no_refusal_still_speaks_dutch():
    """
    English is the source language of this layer, and a refusal is the one string in it
    that a person reads (CLAUDE.md, "Taal"). Nine were still Dutch or half-Dutch after
    the language round: `library.py`'s "{name} is verplicht.", three
    `'…' ontbreekt.` 422s in server.py, `Ophalen mislukte`, `Omzetten mislukte`, camera's
    "Elk hoekpunt is [x, y] in beeldpixels.", `machine.py`'s "…by the device-service
    geleverd." and tilerun's "Tussen tile 1 and 2".

    Only what a user can be shown is checked — the message of a raise, and an
    `HTTPException` detail. Docstrings are for whoever reads the code and a dozen of them
    are still Dutch; that is the language round's remaining debt and a different job from
    this one.
    """
    import ast

    import openkerf_api

    dutch = (
        " niet ", " geen ", " met de ", " van de ", " voor de ", " naar de ", " deze ",
        " het ", " een ", " zijn ", " wordt ", " kan niet", " moet ", "ontbreekt",
        "mislukt", " verplicht", "hoekpunt", " tussen ", "geleverd",
    )
    found = []
    for path in sorted(Path(openkerf_api.__file__).parent.glob("*.py")):
        tree = ast.parse(path.read_text())
        said = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
                said += node.exc.args[:1]
                said += [k.value for k in node.exc.keywords if k.arg == "detail"]
        for node in said:
            for text in ast.walk(node):
                if isinstance(text, ast.Constant) and isinstance(text.value, str):
                    lowered = f" {text.value.lower()} "
                    if any(word in lowered for word in dutch):
                        found.append(f"{path.name}:{text.lineno}: {text.value}")

    assert found == []


# =============================================================== the verbs ====


def test_a_material_can_be_renamed_and_given_other_names(library):
    """
    There was no way to rename a material at all, which is how the live library came to
    hold both `Multiplex berken` and `Berkentriplex` for one board.
    """
    material = library.add_material("Multiplex berken")

    renamed = library.update_material(
        material["id"], name="Birch plywood", synonyms=["berkentriplex", "multiplex"]
    )

    assert renamed["name"] == "Birch plywood"
    assert renamed["synonyms"] == ["berkentriplex", "multiplex"]
    assert [m["name"] for m in library.materials()] == ["Birch plywood"]


def test_renaming_onto_a_taken_name_is_refused_rather_than_merged(library):
    """
    Silently joining two materials because they now share a name would join two sets of
    measurements nobody asked to join. And the check has to ignore case, where the UNIQUE
    constraint on the column does not: `Acrylaat` beside `acrylaat` is the same rot.
    """
    library.add_material("Berkentriplex")
    other = library.add_material("Acrylaat")

    with pytest.raises(LibraryError) as refusal:
        library.update_material(other["id"], name="berkentriplex")

    assert refusal.value.code == "library.material.nameTaken"
    assert len(library.materials()) == 2


def test_merging_two_names_for_one_board_keeps_every_setting(library, tmp_path):
    """
    A merge written as remove-then-add throws away exactly what the library is for. Both
    sides' presets, boards and recipes have to arrive on one material, the old name has to
    survive as a synonym so the next import still lands on the right board, and the sheet
    on the table has to follow.
    """
    birch = library.add_material("Berkentriplex", ["birch ply"])
    ply = library.add_material("Multiplex berken", ["plywood"])
    for material in (birch, ply):
        library.add_preset(
            material_id=material["id"],
            thickness_mm=3,
            operation="snijden",
            speed_mm_s=12,
            power_percent=65,
        )
        library.add_test_grid(plan_for(material["id"]), [])
        library.save_grid_recipe(
            f"cut {material['id']}", {"operation": "snijden"}, material["id"]
        )
    write_sheets(library, ply["id"])

    result = library.merge_material(ply["id"], birch["id"])

    assert [m["name"] for m in library.materials()] == ["Berkentriplex"]
    assert len(library.presets(material_id=birch["id"])) == 2
    assert len([g for g in library.test_grids() if g["material_id"] == birch["id"]]) == 2
    assert len(library.grid_recipes(birch["id"])) == 2
    assert result["material"]["synonyms"] == ["birch ply", "Multiplex berken", "plywood"]
    assert read_sheets(library)[0]["material_id"] == birch["id"]


def test_a_material_cannot_be_merged_into_itself(library):
    """A no-op that reads as success would look like a merge that lost everything."""
    material = library.add_material("Berkentriplex")

    with pytest.raises(LibraryError) as refusal:
        library.merge_material(material["id"], material["id"])

    assert refusal.value.code == "library.material.mergeSelf"


def test_removing_a_material_with_everything_leaves_no_danglers(library, tmp_path):
    """
    Four things the foreign keys cannot reach, each of them measured on a copy of the live
    library. The squares in `test_grid.cells` name presets by id inside a JSON string;
    `preset.origin_id` names a board as the text "testgrid:12"; the photographs are files
    beside the database, which only `clear()` ever unlinked; and the sheet on the table
    names its material in a JSON file.

    The cross-material case is not contrived: a board burned on `Berkentriplex` and a
    winning square filed under `Multiplex berken` is precisely what two names for one
    board does to you.
    """
    birch = library.add_material("Berkentriplex")
    ply = library.add_material("Multiplex berken")
    board = library.add_test_grid(plan_for(birch["id"]), [])
    library.set_grid_photo(board["id"], ".png", PHOTO)
    photo = Path(library.test_grid(board["id"])["photo_path"])
    assert photo.exists()

    mine = library.add_preset(
        material_id=birch["id"], operation="snijden", speed_mm_s=12, power_percent=65,
        source="testraster", origin_id=f"testgrid:{board['id']}",
    )
    theirs = library.add_preset(
        material_id=ply["id"], operation="snijden", speed_mm_s=13, power_percent=66,
        source="testraster", origin_id=f"testgrid:{board['id']}",
    )
    # A board of the *other* material, whose square names the preset that is about to go.
    survivor = library.add_test_grid(
        plan_for(ply["id"]),
        [{"row": 0, "column": 0, "speed_mm_s": 12, "power_percent": 65,
          "preset_id": mine["id"]}],
    )
    library.save_grid_recipe("cut birch", {"operation": "snijden"}, birch["id"])
    write_sheets(library, birch["id"])

    gone = library.remove_material(birch["id"], with_everything=True)

    assert gone == {
        "removed": birch["id"], "presets": 1, "test_grids": 1, "grid_recipes": 1,
        "photos": 1, "sheets": 1,
    }
    assert not photo.exists(), "the photograph is a file and nothing else unlinks it"
    assert library.preset(theirs["id"])["origin_id"] is None
    assert library.test_grid(survivor["id"])["cells"][0]["preset_id"] is None
    assert read_sheets(library)[0]["material_id"] is None
    # And the material that was not named is untouched.
    assert [m["name"] for m in library.materials()] == ["Multiplex berken"]


def test_usage_counts_what_the_confirmation_is_going_to_promise(library):
    """
    The dialog and the refusal read the same numbers from the same place, or the sentence
    on screen and the sentence in the log disagree about how much is at stake.
    """
    material = library.add_material("Berkentriplex")
    library.add_preset(
        material_id=material["id"], operation="snijden", speed_mm_s=12, power_percent=65
    )
    board = library.add_test_grid(plan_for(material["id"]), [])
    library.set_grid_photo(board["id"], ".png", PHOTO)
    library.save_grid_recipe("cut birch", {"operation": "snijden"}, material["id"])
    write_sheets(library, material["id"])

    usage = library.material_usage(material["id"])

    assert usage == {
        "material_id": material["id"], "name": "Berkentriplex", "presets": 1,
        "test_grids": 1, "grid_recipes": 1, "photos": 1, "sheets": 1,
    }


def test_an_unknown_material_is_named_in_the_refusal(library):
    with pytest.raises(LibraryError) as refusal:
        library.material_usage(4242)
    assert refusal.value.code == "library.material.unknown"


# ------------------------------------------------------------- import batches --


def test_an_import_can_be_taken_back_in_one_call(tmp_path):
    """
    The state the author is stuck in: one bulk tick-list produced 14 of 20 materials and
    26 of 35 presets, all bound to a machine nobody had described, and not one of them
    could be removed again. Taking the batch back has to remove what the import brought
    and leave what was already there — including a material the import merely *used*.
    """
    theirs = Library(tmp_path / "theirs" / "library.db")
    for name in ("Berkentriplex", "MDF", "Acrylaat", "Vilt"):
        material = theirs.add_material(name)
        theirs.add_preset(
            material_id=material["id"], thickness_mm=3, operation="snijden",
            speed_mm_s=12, power_percent=65,
        )
    bundle = theirs.export_bundle("theirs")

    mine = Library(tmp_path / "mine" / "library.db")
    already = mine.add_material("Berkentriplex")
    keeper = mine.add_preset(
        material_id=already["id"], thickness_mm=6, operation="graveren-raster",
        speed_mm_s=300, power_percent=20,
    )

    mine.import_bundle(bundle, import_batch="starter-2026-08-23")

    assert len(mine.materials()) == 4
    assert {p["import_batch"] for p in mine.presets()} == {"", "starter-2026-08-23"}

    result = mine.remove_import_batch("starter-2026-08-23")

    assert result["presets"] == 4
    assert len(result["materials"]) == 3
    assert [m["name"] for m in mine.materials()] == ["Berkentriplex"]
    assert [p["id"] for p in mine.presets()] == [keeper["id"]]


def test_taking_back_an_import_keeps_a_material_that_grew_its_own_work(tmp_path):
    """
    A material an import created, that the user has since measured something on, is theirs
    now. Removing it because of where its name came from would take the measurement with
    it.
    """
    library = Library(tmp_path / "library.db")
    material = library.add_material("MDF", import_batch="starter")
    library.add_preset(
        material_id=material["id"], operation="snijden", speed_mm_s=12,
        power_percent=65, import_batch="starter",
    )
    library.add_preset(
        material_id=material["id"], operation="snijden", speed_mm_s=14,
        power_percent=70, source="testraster",
    )

    result = library.remove_import_batch("starter")

    assert result["materials"] == []
    assert result["kept_materials"] == [material["id"]]
    assert [m["name"] for m in library.materials()] == ["MDF"]
    assert len(library.presets()) == 1


def test_an_import_that_is_not_there_is_refused_rather_than_reported_as_done(library):
    """A typo answering "nothing removed, all good" is how you learn to distrust undo."""
    with pytest.raises(LibraryError) as refusal:
        library.remove_import_batch("never-happened")
    assert refusal.value.code == "library.import.unknownBatch"

    with pytest.raises(LibraryError) as empty:
        library.remove_import_batch("  ")
    assert empty.value.code == "library.import.needsBatch"


# ---------------------------------------------------------------- the machine --


def test_a_profile_without_a_device_can_be_moved_into_the_active_machine(library):
    """
    The case `_dedupe_machines` structurally cannot reach: it only merges rows that share
    a device path, and the unique index it creates stops that case from arising. Live, the
    author has a device-less `5030 CO2` carrying 60 W and 27 presets beside a device-bound
    `KH-5030` with no wattage and 3 — one physical laser, two rows, and the wattage on the
    wrong one.
    """
    phantom = library.add_machine(name="5030 CO2", power_watt=60, lens_mm=63.5)
    real = library.add_machine(name="KH-5030", device_path="ruida")
    material = library.add_material("Berkentriplex")
    for machine, speed in ((phantom, 12), (real, 14)):
        library.add_preset(
            material_id=material["id"], machine_id=machine["id"], operation="snijden",
            speed_mm_s=speed, power_percent=65,
        )
    library.add_test_grid(plan_for(material["id"], phantom["id"]), [])

    result = library.merge_machine(
        phantom["id"], real["id"], live_paths=["ruida"], active_path="ruida"
    )

    assert [m["name"] for m in library.machines()] == ["KH-5030"]
    assert result["moved"] == {"presets": 1, "test_grids": 1}
    assert len(library.presets(machine_id=real["id"])) == 2
    # The 60 W finally reaches the profile the engine actually uses.
    assert result["machine"]["power_watt"] == 60
    assert result["machine"]["device_path"] == "ruida"
    assert sorted(result["filled"]) == ["lens_mm", "power_watt"]


def test_a_merge_never_overwrites_what_the_target_already_says(library):
    """
    A merge that copied the source's numbers over the target's would quietly replace a
    figure the user typed with one from a row they wanted rid of.
    """
    source = library.add_machine(name="Guess", power_watt=60, lens_mm=63.5)
    target = library.add_machine(name="KH-5030", power_watt=80, device_path="ruida")

    result = library.merge_machine(source["id"], target["id"])

    assert result["machine"]["power_watt"] == 80
    assert result["machine"]["lens_mm"] == 63.5
    assert result["filled"] == ["lens_mm"]


def test_two_machines_that_both_exist_are_not_one_machine(library):
    """
    Merging two profiles that each belong to a live device files one laser's measurements
    under the other. Two Ruidas on one bench read as `ruida` and `ruida1`, so this is not
    hypothetical.
    """
    one = library.add_machine(name="Bench A", device_path="ruida")
    two = library.add_machine(name="Bench B", device_path="ruida1")

    with pytest.raises(LibraryError) as refusal:
        library.merge_machine(one["id"], two["id"], live_paths=["ruida", "ruida1"])

    assert refusal.value.code == "library.machine.mergeTwoReal"
    assert len(library.machines()) == 2


def test_the_machine_you_are_working_on_is_not_the_one_that_gets_merged_away(library):
    """
    Mirrors the refusal `remove_machine` already has: the direction matters, because the
    row that survives is the row the engine will keep writing to.
    """
    active = library.add_machine(name="KH-5030", device_path="ruida")
    phantom = library.add_machine(name="5030 CO2")

    with pytest.raises(LibraryError) as refusal:
        library.merge_machine(active["id"], phantom["id"], active_path="ruida")

    assert refusal.value.code == "library.machine.mergeActive"

    with pytest.raises(LibraryError) as itself:
        library.merge_machine(active["id"], active["id"])
    assert itself.value.code == "library.machine.mergeSelf"


def test_strays_are_adopted_only_when_a_machine_is_named(library):
    """
    Four presets and eleven boards in the live library carry `machine_id IS NULL` — the
    fingerprint of the lhystudios-fallback state, measured on a machine nobody can name.
    `presets()` shows them on every machine, which is visible but wrong; adopting them
    claims they were measured here, which is a different wrong. So it is a button, and
    without a machine it refuses instead of guessing.
    """
    machine = library.add_machine(name="KH-5030", device_path="ruida")
    material = library.add_material("Berkentriplex")
    library.add_preset(
        material_id=material["id"], operation="snijden", speed_mm_s=12, power_percent=65
    )
    library.add_test_grid(plan_for(material["id"]), [])

    with pytest.raises(LibraryError) as refusal:
        library.adopt_presets(None)
    assert refusal.value.code == "library.adopt.noMachine"

    result = library.adopt_presets(machine["id"])

    assert result == {"machine_id": machine["id"], "presets": 1, "test_grids": 1}
    assert library.presets()[0]["machine_id"] == machine["id"]


def test_a_recycled_device_path_does_not_inherit_the_old_machines_evidence(library):
    """
    The kernel hands out device paths first-free-slot (kernel.py:3433-3437), so removing a
    laser and adding another gives the newcomer `ruida` back — and `profile_for_device`
    then found the dead machine's row, renamed it after the newcomer and handed over every
    preset and every board. The uid catches it whatever route the removal took, including
    a crash or a console `service device` teardown that never passes through our own code.
    """
    old = library.profile_for_device("ruida", "KH-5030", machine_uid="MK1AAAAAAAA")
    material = library.add_material("Berkentriplex")
    library.add_preset(
        material_id=material["id"], machine_id=old["id"], operation="snijden",
        speed_mm_s=12, power_percent=65,
    )

    new = library.profile_for_device("ruida", "Second laser", machine_uid="MK1BBBBBBBB")

    assert new["id"] != old["id"]
    assert library.presets(machine_id=new["id"]) == []
    detached = next(m for m in library.machines() if m["id"] == old["id"])
    assert detached["device_path"] is None
    assert detached["name"] == "KH-5030", "the old row keeps its own name and evidence"
    assert len(library.presets(machine_id=old["id"])) == 1


def test_a_profile_from_before_the_uid_still_matches_on_its_slot(library):
    """
    Every profile in an existing library has an empty uid, and there is nothing to compare
    it against. Those keep matching on the device path alone — the alternative is minting
    a second profile for every machine the moment this ships.
    """
    before = library.add_machine(name="KH-5030", device_path="ruida")

    same = library.profile_for_device("ruida", "KH-5030", machine_uid="MK1AAAAAAAA")

    assert same["id"] == before["id"]
    assert same["machine_uid"] == "MK1AAAAAAAA", "and it adopts the uid on the way past"


def test_a_machine_that_moved_slots_takes_its_evidence_with_it(library):
    """
    The mirror of the recycled slot: same laser, different path, because the kernel
    started it in another order. Matching on the uid first is what keeps its presets.
    """
    first = library.profile_for_device("ruida", "KH-5030", machine_uid="MK1AAAAAAAA")

    moved = library.profile_for_device("ruida1", "KH-5030", machine_uid="MK1AAAAAAAA")

    assert moved["id"] == first["id"]
    assert moved["device_path"] == "ruida1"
    assert len(library.machines()) == 1


def test_a_tube_power_no_laser_has_is_refused_with_the_bounds(library):
    """
    The wizard now asks for a wattage, so a typo reaches the database and then the match:
    a 6000 W profile hides every preset ever made. The numbers are ours, so they travel in
    the header and the sentence can be translated.
    """
    machine = library.add_machine(name="KH-5030")

    with pytest.raises(LibraryError) as refusal:
        library.update_machine(machine["id"], {"power_watt": 6000})

    assert refusal.value.code == "library.machine.wattRange"
    assert refusal.value.values == {"min": 1, "max": 1000}
    # And "I do not know" stays a legal answer: nothing at all is allowed.
    assert library.update_machine(machine["id"], {"power_watt": None})["power_watt"] is None


def test_the_starter_state_is_one_of_three_answers(library):
    """
    'I do not know what my tube is' is a legitimate answer and needs somewhere to live, or
    the offer is a dead end for anybody who does not know their wattage. One column, three
    values — not a boolean beside a boolean.
    """
    machine = library.add_machine(name="KH-5030")

    assert library.update_machine(
        machine["id"], {"starter_state": "power_unknown"}
    )["starter_state"] == "power_unknown"
    assert library.update_machine(
        machine["id"], {"starter_state": "dismissed"}
    )["starter_state"] == "dismissed"

    with pytest.raises(LibraryError) as refusal:
        library.update_machine(machine["id"], {"starter_state": "maybe"})
    assert refusal.value.code == "library.machine.unknownStarterState"


# ----------------------------------------------------------------- the board --


def test_removing_a_board_lets_go_of_its_photo_and_its_presets(library):
    """
    `preset.origin_id` is the text "testgrid:12", so no foreign key nulls it: the setting
    would go on claiming a board that is gone and the card would offer a photograph that
    is not there. And until now only `clear()` ever unlinked a photo file, so every board
    ever removed left its picture on disk.
    """
    material = library.add_material("Berkentriplex")
    board = library.add_test_grid(plan_for(material["id"]), [])
    library.set_grid_photo(board["id"], ".png", PHOTO)
    photo = Path(library.test_grid(board["id"])["photo_path"])
    preset = library.add_preset(
        material_id=material["id"], operation="snijden", speed_mm_s=12,
        power_percent=65, source="testraster", origin_id=f"testgrid:{board['id']}",
    )

    result = library.remove_test_grid(board["id"])

    assert result == {"removed": board["id"], "photos": 1}
    assert not photo.exists()
    survivor = library.preset(preset["id"])
    assert survivor["origin_id"] is None
    # The source stays: it *was* measured, and rewriting that is a bigger lie than a
    # missing photograph.
    assert survivor["source"] == "testraster"


def test_removing_a_preset_takes_it_out_of_the_square_that_made_it(library):
    """
    `test_grid.cells` is JSON, so a removed preset leaves its id sitting in a square and
    the result window offers a setting that does not exist.
    """
    material = library.add_material("Berkentriplex")
    preset = library.add_preset(
        material_id=material["id"], operation="snijden", speed_mm_s=12, power_percent=65
    )
    board = library.add_test_grid(
        plan_for(material["id"]),
        [{"row": 0, "column": 0, "speed_mm_s": 12, "power_percent": 65}],
    )
    library.mark_cell(board["id"], 0, 0, preset["id"])
    assert library.test_grid(board["id"])["cells"][0]["preset_id"] == preset["id"]

    library.remove_preset(preset["id"])

    assert library.test_grid(board["id"])["cells"][0]["preset_id"] is None


def test_burning_a_setting_again_is_recorded_and_is_not_a_gate(library):
    """
    Re-burning is the only claim about a shared setting that one maintainer can check, so
    it is worth recording — and deliberately not a condition on sharing, because a share
    button that demands a re-burn is a share button nobody presses.
    """
    material = library.add_material("Berkentriplex")
    preset = library.add_preset(
        material_id=material["id"], operation="snijden", speed_mm_s=12, power_percent=65
    )
    assert preset["verified_at"] is None

    again = library.verify_preset(preset["id"])

    assert again["verified_at"]
    assert again["speed_mm_s"] == 12


# ------------------------------------------------------------------- helpers --


def write_sheets(library: Library, material_id) -> Path:
    """
    A sheet index where `Sheets` keeps one: beside the database, in `openkerf-sheets`, in
    a file still called `vellen.json` (sheets.py:57 — the state file kept its Dutch name
    when the interface became English, so that live work was not thrown away).
    """
    index = library.path.with_name("openkerf-sheets") / "vellen.json"
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text(
        json.dumps(
            [{"id": "sheet-1", "name": "Sheet 1", "material_id": material_id}], indent=1
        )
    )
    return index


def read_sheets(library: Library) -> list[dict]:
    return json.loads((library.path.with_name("openkerf-sheets") / "vellen.json").read_text())


def test_a_column_added_later_reaches_a_database_that_is_already_at_head(tmp_path):
    """
    The trap the version gate introduced, and the reason the column sniffing runs on every
    open rather than behind that gate.

    A column has to be written twice — in `SCHEMA` and in `_add_missing_columns` — and a
    version gate over the pair makes forgetting to raise `SCHEMA_VERSION` silent in the
    worst possible way: the column reaches every *fresh* database, so the whole suite
    stays green, and no *existing* one, so only somebody with a library ever meets it.
    Measured before this: a database stamped at head did not get the new column when
    reopened, while a fresh one did.

    Simulated here by taking a column away from a database that is already stamped, which
    is exactly the shape a forgotten version bump leaves behind.
    """
    import sqlite3

    path = tmp_path / "at-head.db"
    Library(path)

    with sqlite3.connect(path) as db:
        # SQLite can drop a column since 3.35, which is what makes this test possible.
        db.execute("ALTER TABLE preset DROP COLUMN verified_at")
        assert db.execute("PRAGMA user_version").fetchone()[0] >= 1
        gone = {row[1] for row in db.execute("PRAGMA table_info(preset)")}
    assert "verified_at" not in gone

    Library(path)

    with sqlite3.connect(path) as db:
        back = {row[1] for row in db.execute("PRAGMA table_info(preset)")}
    assert "verified_at" in back, "a database at head never got the column back"
