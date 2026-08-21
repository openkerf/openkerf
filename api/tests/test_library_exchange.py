"""
Decision B7: the library is exchangeable.

The only measurement that counts is at the bottom: export a filled library, wipe
everything, put it back, and then check that the provenance *and* the photos are
still there. Everything above it proves the parts of that.
"""

import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from openkerf_api.library import BUNDLE_INDEX, Library, LibraryError
from openkerf_api.server import ApiServer

PHOTO = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100"
    "05fe02fea7d4b2000000000049454e44ae426082"
)


ALIGNMENT = [
    {"x": 0.12, "y": 0.08},
    {"x": 0.91, "y": 0.14},
    {"x": 0.88, "y": 0.93},
    {"x": 0.09, "y": 0.87},
]


@pytest.fixture
def mine(tmp_path):
    return Library(tmp_path / "source" / "library.db")


@pytest.fixture
def empty(tmp_path):
    return Library(tmp_path / "target" / "library.db")


def fill(library: Library) -> dict:
    """A library the way it looks after a week of work."""
    machine = library.add_machine(name="5030 CO2", power_watt=80, lens_mm=63.5)
    birch = library.add_material("Birch plywood", ["birchply"])
    acrylic = library.add_material("Acrylic")
    grid = library.add_test_grid(
        {
            "material_id": birch["id"],
            "machine_id": machine["id"],
            "thickness_mm": 3,
            "operation": "snijden",
            "speed_min": 5, "speed_max": 25, "speed_steps": 3,
            "power_min": 40, "power_max": 80, "power_steps": 3,
            "cell_mm": 10, "gap_mm": 2, "origin_x_mm": 0, "origin_y_mm": 0,
        },
        [{"row": 1, "column": 2, "speed_mm_s": 12, "power_percent": 65, "operation_id": "op1"}],
    )
    library.set_grid_photo(grid["id"], ".png", PHOTO)
    # The alignment is handwork and so belongs with the evidence (T4).
    library.set_grid_alignment(grid["id"], ALIGNMENT)
    measured = library.add_preset(
        material_id=birch["id"],
        machine_id=machine["id"],
        thickness_mm=3,
        operation="snijden",
        speed_mm_s=12,
        power_percent=65,
        source="testraster",
        origin_id=f"testgrid:{grid['id']}",
        note="clean underside",
    )
    library.mark_cell(grid["id"], 1, 2, measured["id"])
    library.add_preset(
        material_id=acrylic["id"],
        machine_id=machine["id"],
        thickness_mm=3,
        operation="graveren-raster",
        speed_mm_s=200,
        power_percent=25,
        interval_mm=0.1,
        source="handmatig",
    )
    return {"machine": machine, "birch": birch, "grid": grid, "preset": measured}


# -------------------------------------------------------------------- exporting

def test_export_carries_data_and_photos(mine, tmp_path):
    fill(mine)

    bundle = mine.export_bundle()

    assert bundle.name.endswith(".openkerf-lib")
    with zipfile.ZipFile(bundle) as zip_:
        names = zip_.namelist()
        data = json.loads(zip_.read(BUNDLE_INDEX))
    assert len(data["materials"]) == 2
    assert len(data["presets"]) == 2
    assert len(data["machines"]) == 1
    assert len(data["test_grids"]) == 1
    # The evidence comes along, not only the reference to it.
    photos = [n for n in names if n.startswith("photos/")]
    assert photos and data["test_grids"][0]["photo_file"] == photos[0]


def test_a_file_that_is_not_a_library_is_refused(empty, tmp_path):
    fake = tmp_path / "holiday.zip"
    fake.write_bytes(b"this is not a zip")

    with pytest.raises(LibraryError) as error:
        empty.read_bundle(fake)
    assert "not an OpenKerf library" in str(error.value)


def test_a_zip_without_a_library_is_refused(empty, tmp_path):
    fake = tmp_path / "photos.openkerf-lib"
    with zipfile.ZipFile(fake, "w") as zip_:
        zip_.writestr("plaatje.png", PHOTO)

    with pytest.raises(LibraryError):
        empty.read_bundle(fake)


# -------------------------------------------------------------------- preview

def test_preview_says_what_is_new_before_anything_happens(mine, empty):
    fill(mine)
    bundle = mine.export_bundle()

    preview = empty.preview_import(bundle)

    assert preview["contains"] == {
        "materials": 2, "presets": 2, "machines": 1, "test_grids": 1, "photos": 1
    }
    assert sorted(preview["merge"]["materials"]["new"]) == ["Acrylic", "Birch plywood"]
    assert preview["merge"]["presets"]["new"] == 2
    # And looking changed nothing.
    assert empty.materials() == []


def test_preview_separates_identical_from_conflicting(mine, empty):
    before = fill(mine)
    bundle = mine.export_bundle()
    empty.import_bundle(bundle)
    # Eén preset bijgesteld: dezelfde plank, dezelfde snede, andere getallen.
    ours = next(p for p in empty.presets() if p["operation"] == "snijden")
    empty.update_preset(ours["id"], speed_mm_s=10)

    preview = empty.preview_import(bundle)["merge"]["presets"]

    assert preview["new"] == 0
    assert preview["identical"] == 1
    assert len(preview["conflicts"]) == 1
    clash = preview["conflicts"][0]
    assert clash["material"] == "Birch plywood"
    # Both sides are there: without your own value there is nothing to weigh up.
    assert clash["mine"]["speed_mm_s"] == 10
    assert clash["theirs"]["speed_mm_s"] == before["preset"]["speed_mm_s"]


def test_a_colliding_name_is_offered_as_a_merge_not_done_silently(mine, empty):
    """
    The trap from M5: "Birchply board" and "Birch plywood" are one board.

    Merging by itself is not allowed — a wrong guess sticks somebody else's
    numbers on your material. Pointing at it has to work, or you end up with two.
    """
    fill(mine)
    empty.add_material("Birchply board")
    bundle = mine.export_bundle()

    preview = empty.preview_import(bundle)["merge"]["materials"]

    assert "Birch plywood" in preview["new"]
    suggestion = next(v for v in preview["similar"] if v["name"] == "Birch plywood")
    assert suggestion["match"] == "Birchply board"
    assert "birch" in suggestion["why"] and "plywood" in suggestion["why"]

    # Pointed at: then it is no longer a new material, not even after importing.
    choice = {"Birch plywood": suggestion["material_id"]}
    assert "Birch plywood" not in empty.preview_import(bundle, choice)["merge"]["materials"]["new"]
    empty.import_bundle(bundle, merge_materials=choice)
    assert [m["name"] for m in empty.materials()] == ["Acrylic", "Birchply board"]
    assert any(p["material_name"] == "Birchply board" for p in empty.presets())


def test_a_synonym_counts_as_the_same_material(mine, empty):
    fill(mine)
    empty.add_material("Birch 3mm", ["birchply"])
    bundle = mine.export_bundle()

    preview = empty.preview_import(bundle)["merge"]["materials"]

    assert "Birch plywood" not in preview["new"]
    assert any(v["as"] == "Birch 3mm" for v in preview["existing"])


# -------------------------------------------------------------------- importing

def test_merge_keeps_your_own_measurements(mine, empty):
    fill(mine)
    bundle = mine.export_bundle()
    empty.import_bundle(bundle)
    ours = next(p for p in empty.presets() if p["operation"] == "snijden")
    empty.update_preset(ours["id"], speed_mm_s=10)

    result = empty.import_bundle(bundle)

    assert result["presets"]["added"] == 0
    assert result["presets"]["updated"] == 0
    assert empty.preset(ours["id"])["speed_mm_s"] == 10
    assert len(empty.presets()) == 2


def test_the_file_can_win_when_you_say_so(mine, empty):
    fill(mine)
    bundle = mine.export_bundle()
    empty.import_bundle(bundle)
    ours = next(p for p in empty.presets() if p["operation"] == "snijden")
    empty.update_preset(ours["id"], speed_mm_s=10)

    result = empty.import_bundle(bundle, on_conflict="file")

    assert result["presets"]["updated"] == 1
    assert empty.preset(ours["id"])["speed_mm_s"] == 12


def test_replace_throws_away_what_was_there(mine, empty):
    fill(mine)
    empty.add_material("Cardboard")
    bundle = mine.export_bundle()

    result = empty.import_bundle(bundle, mode="replace")

    assert result["removed"]["materials"] == 1
    assert "Cardboard" not in [m["name"] for m in empty.materials()]
    assert len(empty.presets()) == 2


def test_an_unknown_mode_is_refused(mine, empty):
    bundle = mine.export_bundle()
    with pytest.raises(LibraryError):
        empty.import_bundle(bundle, mode="wipe it all please")


def test_importing_twice_does_not_duplicate(mine, empty):
    fill(mine)
    bundle = mine.export_bundle()

    empty.import_bundle(bundle)
    empty.import_bundle(bundle)

    assert len(empty.materials()) == 2
    assert len(empty.presets()) == 2
    assert len(empty.test_grids()) == 1


# ------------------------------------- the measurement that counts: round trip

def test_a_full_round_trip_keeps_provenance_and_photos(mine, empty):
    """
    Export, wipe, put back. What comes back has to be able to point at *where* it
    came from — otherwise it is a list of numbers.
    """
    fill(mine)
    bundle = mine.export_bundle()
    mine.clear()
    assert mine.presets() == []

    mine.import_bundle(bundle, mode="replace")

    measured = next(p for p in mine.presets() if p["source"] == "testraster")
    assert measured["material_name"] == "Birch plywood"
    assert measured["machine_name"] == "5030 CO2"
    assert measured["note"] == "clean underside"
    # The provenance points at the grid that came along…
    grid = mine.test_grids()[0]
    assert measured["origin_id"] == f"testgrid:{grid['id']}"
    assert measured["grid_id"] == grid["id"]
    # …the square points back at this preset…
    assert measured["grid_cell"] == {"row": 1, "column": 2}
    # …and the photo is really there, with the same bytes.
    assert Path(grid["photo_path"]).read_bytes() == PHOTO
    # The alignment belongs to that photo: without it the evidence is still there
    # but no longer points at anything (T4).
    assert grid["alignment"] == ALIGNMENT
    # And a raster preset without a line spacing cannot be burned again (B12).
    their_grid = next(p for p in mine.presets() if p["operation"] == "graveren-raster")
    assert their_grid["interval_mm"] == 0.1


def test_the_burn_date_of_the_evidence_survives(mine, empty):
    fill(mine)
    with mine._connect() as db:
        db.execute("UPDATE test_grid SET created_at = '2026-03-01 09:15:00'")
    bundle = mine.export_bundle()

    empty.import_bundle(bundle)

    assert empty.test_grids()[0]["created_at"] == "2026-03-01 09:15:00"


def test_the_source_is_not_downgraded_on_your_own_backup(mine, empty):
    """
    Presetariat imports as "geimporteerd" — there it comes off a stranger's
    machine. Restoring your own backup is something else: then "testraster" is the
    truth, and throwing that away is throwing the evidence away.
    """
    fill(mine)
    bundle = mine.export_bundle()

    empty.import_bundle(bundle)

    assert {p["source"] for p in empty.presets()} == {"testraster", "handmatig"}


# ---------------------------------------------------------------------- routes

@pytest.fixture
def client(kernel, tmp_path):
    server = ApiServer(kernel, library_path=tmp_path / "api.db")
    with TestClient(server.build_app()) as web:
        yield web


def test_the_routes_walk_the_same_road(client):
    client.post("/api/library/materials", json={"name": "Birch plywood"})
    client.post(
        "/api/library/presets",
        json={
            "material_id": client.get("/api/library/materials").json()[0]["id"],
            "operation": "snijden",
            "thickness_mm": 3,
            "speed_mm_s": 12,
            "power_percent": 65,
        },
    )

    download = client.get("/api/library/export.openkerf-lib")
    assert download.status_code == 200
    assert "library.openkerf-lib" in download.headers["content-disposition"]

    upload = client.post(
        "/api/library/import/upload",
        files={"file": ("library.openkerf-lib", download.content, "application/zip")},
    )
    assert upload.status_code == 200
    preview = upload.json()
    assert preview["bundle"]
    assert preview["merge"]["presets"]["identical"] == 1

    done = client.post(
        "/api/library/import",
        json={"bundle": preview["bundle"], "mode": "merge"},
    )
    assert done.status_code == 200
    assert len(client.get("/api/library/presets?all_machines=true").json()) == 1


def test_importing_without_a_file_is_a_clean_refusal(client):
    assert client.post("/api/library/import", json={}).status_code == 422


def test_uploading_something_else_is_a_clean_refusal(client):
    response = client.post(
        "/api/library/import/upload",
        files={"file": ("foto.png", PHOTO, "image/png")},
    )
    assert response.status_code == 409
    assert "library" in json.dumps(response.json())


def test_the_alignment_survives_a_backup(mine, empty):
    """
    The alignment was done by hand and belongs to the photo. If it got lost in a
    backup, the evidence would still be there but point at nothing.
    """
    fill(mine)

    empty.import_bundle(mine.export_bundle())

    returned = empty.test_grids()[0]
    assert returned["alignment"] == ALIGNMENT


def test_the_line_spacing_survives_a_backup(mine, empty):
    """A raster preset without a line spacing cannot be burned again (B12)."""
    fill(mine)

    empty.import_bundle(mine.export_bundle())

    grid = [p for p in empty.presets() if p["operation"] == "graveren-raster"][0]
    assert grid["interval_mm"] == 0.1


def test_two_presets_that_differ_only_in_interval_are_a_conflict(mine, empty):
    """
    Without the line spacing in the comparison one would quietly overwrite the
    other: the same speed and the same power, a different result.
    """
    fill(mine)
    fill(empty)
    ours = [p for p in empty.presets() if p["operation"] == "graveren-raster"][0]
    empty.update_preset(ours["id"], interval_mm=0.2)

    suggestion = empty.preview_import(mine.export_bundle())

    clashes = suggestion["merge"]["presets"]["conflicts"]
    assert [b["operation"] for b in clashes] == ["graveren-raster"]


# ------------------------------ named grid recipes come along (gap T7)


def test_named_recipes_travel_with_the_library(mine, empty):
    """
    A recipe is work you sorted out yourself. A backup that takes your materials
    and measurements along but leaves your recipes behind is half a backup — and
    you only notice that on the second computer.
    """
    birch = mine.add_material("Birch plywood")
    mine.save_grid_recipe(
        "Birch cut",
        {"operation": "snijden", "speed_min": 5, "speed_max": 25, "cell_mm": 8},
        birch["id"],
    )
    mine.save_grid_recipe("Quick 4×4", {"operation": "snijden", "cell_mm": 6})

    empty.import_bundle(mine.export_bundle())

    recipes = {r["name"]: r for r in empty.grid_recipes()}
    assert set(recipes) == {"Birch cut", "Quick 4×4"}
    assert recipes["Birch cut"]["material_name"] == "Birch plywood"
    assert recipes["Quick 4×4"]["material_id"] is None
    assert recipes["Birch cut"]["settings"]["speed_max"] == 25


def test_your_own_recipe_wins_from_the_file(mine, empty):
    """The same rule as for presets: what you sorted out yourself stays."""
    mine.save_grid_recipe("Quick", {"operation": "snijden", "cell_mm": 6})
    empty.save_grid_recipe("Quick", {"operation": "snijden", "cell_mm": 12})

    result = empty.import_bundle(mine.export_bundle())

    assert result["grid_recipes"] == 0
    assert empty.grid_recipes()[0]["settings"]["cell_mm"] == 12
