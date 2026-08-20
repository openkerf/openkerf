"""
Besluit B7: de bibliotheek is uitwisselbaar.

De enige meting die telt staat onderaan: een gevulde bibliotheek exporteren,
alles wissen, terugzetten, en dan controleren dat de herkomst én de foto's er
nog zijn. Alles daarboven bewijst de onderdelen daarvan.
"""

import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from openkerf_api.library import BUNDLE_INDEX, Library, LibraryError
from openkerf_api.server import ApiServer

FOTO = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100"
    "05fe02fea7d4b2000000000049454e44ae426082"
)


UITLIJNING = [
    {"x": 0.12, "y": 0.08},
    {"x": 0.91, "y": 0.14},
    {"x": 0.88, "y": 0.93},
    {"x": 0.09, "y": 0.87},
]


@pytest.fixture
def bib(tmp_path):
    return Library(tmp_path / "bron" / "library.db")


@pytest.fixture
def leeg(tmp_path):
    return Library(tmp_path / "doel" / "library.db")


def vul(library: Library) -> dict:
    """Een bibliotheek zoals hij er na een werkweek uitziet."""
    machine = library.add_machine(name="5030 CO2", power_watt=80, lens_mm=63.5)
    berken = library.add_material("Multiplex berken", ["berkenmultiplex"])
    acryl = library.add_material("Acryl")
    raster = library.add_test_grid(
        {
            "material_id": berken["id"],
            "machine_id": machine["id"],
            "thickness_mm": 3,
            "operation": "snijden",
            "speed_min": 5, "speed_max": 25, "speed_steps": 3,
            "power_min": 40, "power_max": 80, "power_steps": 3,
            "cell_mm": 10, "gap_mm": 2, "origin_x_mm": 0, "origin_y_mm": 0,
        },
        [{"row": 1, "column": 2, "speed_mm_s": 12, "power_percent": 65, "operation_id": "op1"}],
    )
    library.set_grid_photo(raster["id"], ".png", FOTO)
    # De uitlijning is handwerk en hoort dus bij het bewijs (T4).
    library.set_grid_alignment(raster["id"], UITLIJNING)
    gemeten = library.add_preset(
        material_id=berken["id"],
        machine_id=machine["id"],
        thickness_mm=3,
        operation="snijden",
        speed_mm_s=12,
        power_percent=65,
        source="testraster",
        origin_id=f"testgrid:{raster['id']}",
        note="schone onderkant",
    )
    library.mark_cell(raster["id"], 1, 2, gemeten["id"])
    library.add_preset(
        material_id=acryl["id"],
        machine_id=machine["id"],
        thickness_mm=3,
        operation="graveren-raster",
        speed_mm_s=200,
        power_percent=25,
        interval_mm=0.1,
        source="handmatig",
    )
    return {"machine": machine, "berken": berken, "raster": raster, "preset": gemeten}


# ------------------------------------------------------------------ exporteren

def test_export_carries_data_and_photos(bib, tmp_path):
    vul(bib)

    bundel = bib.export_bundle()

    assert bundel.name.endswith(".openkerf-lib")
    with zipfile.ZipFile(bundel) as zip_:
        namen = zip_.namelist()
        data = json.loads(zip_.read(BUNDLE_INDEX))
    assert len(data["materials"]) == 2
    assert len(data["presets"]) == 2
    assert len(data["machines"]) == 1
    assert len(data["test_grids"]) == 1
    # Het bewijs gaat mee, niet alleen de verwijzing ernaar.
    fotos = [n for n in namen if n.startswith("fotos/")]
    assert fotos and data["test_grids"][0]["photo_file"] == fotos[0]


def test_a_file_that_is_not_a_library_is_refused(leeg, tmp_path):
    nep = tmp_path / "vakantie.zip"
    nep.write_bytes(b"dit is geen zip")

    with pytest.raises(LibraryError) as fout:
        leeg.read_bundle(nep)
    assert "not an OpenKerf library" in str(fout.value)


def test_a_zip_without_a_library_is_refused(leeg, tmp_path):
    nep = tmp_path / "fotos.openkerf-lib"
    with zipfile.ZipFile(nep, "w") as zip_:
        zip_.writestr("plaatje.png", FOTO)

    with pytest.raises(LibraryError):
        leeg.read_bundle(nep)


# --------------------------------------------------------------- het voorbeeld

def test_preview_says_what_is_new_before_anything_happens(bib, leeg):
    vul(bib)
    bundel = bib.export_bundle()

    voorbeeld = leeg.preview_import(bundel)

    assert voorbeeld["bevat"] == {
        "materials": 2, "presets": 2, "machines": 1, "test_grids": 1, "photos": 1
    }
    assert sorted(voorbeeld["samenvoegen"]["materials"]["new"]) == ["Acryl", "Multiplex berken"]
    assert voorbeeld["samenvoegen"]["presets"]["new"] == 2
    # En kijken heeft niets veranderd.
    assert leeg.materials() == []


def test_preview_separates_identical_from_conflicting(bib, leeg):
    stand = vul(bib)
    bundel = bib.export_bundle()
    leeg.import_bundle(bundel)
    # Eén preset bijgesteld: dezelfde plank, dezelfde snede, andere getallen.
    mijne = next(p for p in leeg.presets() if p["operation"] == "snijden")
    leeg.update_preset(mijne["id"], speed_mm_s=10)

    voorbeeld = leeg.preview_import(bundel)["samenvoegen"]["presets"]

    assert voorbeeld["new"] == 0
    assert voorbeeld["identical"] == 1
    assert len(voorbeeld["conflicts"]) == 1
    botsing = voorbeeld["conflicts"][0]
    assert botsing["material"] == "Multiplex berken"
    # Beide kanten staan erbij: zonder de eigen waarde is er niets af te wegen.
    assert botsing["mine"]["speed_mm_s"] == 10
    assert botsing["theirs"]["speed_mm_s"] == stand["preset"]["speed_mm_s"]


def test_a_colliding_name_is_offered_as_a_merge_not_done_silently(bib, leeg):
    """
    De valkuil uit M5: "Berkentriplex" en "Multiplex berken" zijn één plank.

    Vanzelf samenvoegen mag niet — een verkeerde gok plakt andermans getallen
    op jouw materiaal. Aanwijzen moet wél, anders staan er twee.
    """
    vul(bib)
    leeg.add_material("Berkentriplex")
    bundel = bib.export_bundle()

    voorbeeld = leeg.preview_import(bundel)["samenvoegen"]["materials"]

    assert "Multiplex berken" in voorbeeld["new"]
    voorstel = next(v for v in voorbeeld["similar"] if v["name"] == "Multiplex berken")
    assert voorstel["match"] == "Berkentriplex"
    assert "berken" in voorstel["why"] and "multiplex" in voorstel["why"]

    # Aangewezen: dan is het geen nieuw materiaal meer, ook niet na importeren.
    keuze = {"Multiplex berken": voorstel["material_id"]}
    assert "Multiplex berken" not in leeg.preview_import(bundel, keuze)["samenvoegen"]["materials"]["new"]
    leeg.import_bundle(bundel, merge_materials=keuze)
    assert [m["name"] for m in leeg.materials()] == ["Acryl", "Berkentriplex"]
    assert any(p["material_name"] == "Berkentriplex" for p in leeg.presets())


def test_a_synonym_counts_as_the_same_material(bib, leeg):
    vul(bib)
    leeg.add_material("Berken 3mm", ["berkenmultiplex"])
    bundel = bib.export_bundle()

    voorbeeld = leeg.preview_import(bundel)["samenvoegen"]["materials"]

    assert "Multiplex berken" not in voorbeeld["new"]
    assert any(v["as"] == "Berken 3mm" for v in voorbeeld["existing"])


# ------------------------------------------------------------------ importeren

def test_merge_keeps_your_own_measurements(bib, leeg):
    vul(bib)
    bundel = bib.export_bundle()
    leeg.import_bundle(bundel)
    mijne = next(p for p in leeg.presets() if p["operation"] == "snijden")
    leeg.update_preset(mijne["id"], speed_mm_s=10)

    resultaat = leeg.import_bundle(bundel)

    assert resultaat["presets"]["added"] == 0
    assert resultaat["presets"]["updated"] == 0
    assert leeg.preset(mijne["id"])["speed_mm_s"] == 10
    assert len(leeg.presets()) == 2


def test_the_file_can_win_when_you_say_so(bib, leeg):
    vul(bib)
    bundel = bib.export_bundle()
    leeg.import_bundle(bundel)
    mijne = next(p for p in leeg.presets() if p["operation"] == "snijden")
    leeg.update_preset(mijne["id"], speed_mm_s=10)

    resultaat = leeg.import_bundle(bundel, on_conflict="bestand")

    assert resultaat["presets"]["updated"] == 1
    assert leeg.preset(mijne["id"])["speed_mm_s"] == 12


def test_replace_throws_away_what_was_there(bib, leeg):
    vul(bib)
    leeg.add_material("Karton")
    bundel = bib.export_bundle()

    resultaat = leeg.import_bundle(bundel, mode="vervangen")

    assert resultaat["removed"]["materials"] == 1
    assert "Karton" not in [m["name"] for m in leeg.materials()]
    assert len(leeg.presets()) == 2


def test_an_unknown_mode_is_refused(bib, leeg):
    bundel = bib.export_bundle()
    with pytest.raises(LibraryError):
        leeg.import_bundle(bundel, mode="alles wissen graag")


def test_importing_twice_does_not_duplicate(bib, leeg):
    vul(bib)
    bundel = bib.export_bundle()

    leeg.import_bundle(bundel)
    leeg.import_bundle(bundel)

    assert len(leeg.materials()) == 2
    assert len(leeg.presets()) == 2
    assert len(leeg.test_grids()) == 1


# ------------------------------------------------- de meting die telt: rondje

def test_a_full_round_trip_keeps_provenance_and_photos(bib, leeg):
    """
    Exporteren, wissen, terugzetten. Wat terugkomt moet nog steeds kunnen
    aanwijzen wáár het vandaan komt — anders is het een lijst getallen.
    """
    vul(bib)
    bundel = bib.export_bundle()
    bib.clear()
    assert bib.presets() == []

    bib.import_bundle(bundel, mode="vervangen")

    gemeten = next(p for p in bib.presets() if p["source"] == "testraster")
    assert gemeten["material_name"] == "Multiplex berken"
    assert gemeten["machine_name"] == "5030 CO2"
    assert gemeten["note"] == "schone onderkant"
    # De herkomst wijst naar het raster dat mee is gekomen…
    raster = bib.test_grids()[0]
    assert gemeten["origin_id"] == f"testgrid:{raster['id']}"
    assert gemeten["grid_id"] == raster["id"]
    # …het vakje wijst terug naar deze preset…
    assert gemeten["grid_cell"] == {"row": 1, "column": 2}
    # …en de foto staat er echt, met dezelfde bytes.
    assert Path(raster["photo_path"]).read_bytes() == FOTO
    # De uitlijning hoort bij die foto: zonder haar staat het bewijs er nog maar
    # wijst het niets meer aan (T4).
    assert raster["alignment"] == UITLIJNING
    # En een rasterpreset zonder lijnafstand is niet na te branden (B12).
    hun_raster = next(p for p in bib.presets() if p["operation"] == "graveren-raster")
    assert hun_raster["interval_mm"] == 0.1


def test_the_burn_date_of_the_evidence_survives(bib, leeg):
    vul(bib)
    with bib._connect() as db:
        db.execute("UPDATE test_grid SET created_at = '2026-03-01 09:15:00'")
    bundel = bib.export_bundle()

    leeg.import_bundle(bundel)

    assert leeg.test_grids()[0]["created_at"] == "2026-03-01 09:15:00"


def test_the_source_is_not_downgraded_on_your_own_backup(bib, leeg):
    """
    Presetariat importeert als "geimporteerd" — daar komt het van een vreemde
    machine. Je eigen back-up terugzetten is iets anders: dan is "testraster"
    de waarheid, en die weggooien is het bewijs weggooien.
    """
    vul(bib)
    bundel = bib.export_bundle()

    leeg.import_bundle(bundel)

    assert {p["source"] for p in leeg.presets()} == {"testraster", "handmatig"}


# ---------------------------------------------------------------------- routes

@pytest.fixture
def client(kernel, tmp_path):
    server = ApiServer(kernel, library_path=tmp_path / "api.db")
    with TestClient(server.build_app()) as web:
        yield web


def test_the_routes_walk_the_same_road(client):
    client.post("/api/library/materials", json={"name": "Multiplex berken"})
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
    assert "bibliotheek.openkerf-lib" in download.headers["content-disposition"]

    upload = client.post(
        "/api/library/import/upload",
        files={"file": ("bibliotheek.openkerf-lib", download.content, "application/zip")},
    )
    assert upload.status_code == 200
    voorbeeld = upload.json()
    assert voorbeeld["bundle"]
    assert voorbeeld["samenvoegen"]["presets"]["identical"] == 1

    klaar = client.post(
        "/api/library/import",
        json={"bundle": voorbeeld["bundle"], "mode": "samenvoegen"},
    )
    assert klaar.status_code == 200
    assert len(client.get("/api/library/presets?all_machines=true").json()) == 1


def test_importing_without_a_file_is_a_clean_refusal(client):
    assert client.post("/api/library/import", json={}).status_code == 422


def test_uploading_something_else_is_a_clean_refusal(client):
    response = client.post(
        "/api/library/import/upload",
        files={"file": ("foto.png", FOTO, "image/png")},
    )
    assert response.status_code == 409
    assert "library" in json.dumps(response.json())


def test_the_alignment_survives_a_backup(bib, leeg):
    """
    De uitlijning is met de hand gedaan en hoort bij de foto. Ging hij bij een
    back-up verloren, dan stond het bewijs er nog maar wees het niets meer aan.
    """
    vul(bib)

    leeg.import_bundle(bib.export_bundle())

    teruggekomen = leeg.test_grids()[0]
    assert teruggekomen["alignment"] == UITLIJNING


def test_the_line_spacing_survives_a_backup(bib, leeg):
    """Een rasterpreset zonder lijnafstand is niet na te branden (B12)."""
    vul(bib)

    leeg.import_bundle(bib.export_bundle())

    raster = [p for p in leeg.presets() if p["operation"] == "graveren-raster"][0]
    assert raster["interval_mm"] == 0.1


def test_two_presets_that_differ_only_in_interval_are_a_conflict(bib, leeg):
    """
    Zonder de lijnafstand in de vergelijking zou de ene stilletjes de andere
    overschrijven: dezelfde snelheid en hetzelfde vermogen, ander resultaat.
    """
    vul(bib)
    vul(leeg)
    van_mij = [p for p in leeg.presets() if p["operation"] == "graveren-raster"][0]
    leeg.update_preset(van_mij["id"], interval_mm=0.2)

    voorstel = leeg.preview_import(bib.export_bundle())

    botsingen = voorstel["samenvoegen"]["presets"]["conflicts"]
    assert [b["operation"] for b in botsingen] == ["graveren-raster"]


# --------------------------------- benoemde rasterrecepten mee (gat T7)


def test_named_recipes_travel_with_the_library(bib, leeg):
    """
    Een recept is werk dat je zelf hebt uitgezocht. Een back-up die je
    materialen en metingen meeneemt maar je recepten laat staan, is een halve
    back-up — en dat merk je pas op de tweede computer.
    """
    berken = bib.add_material("Multiplex berken")
    bib.save_grid_recipe(
        "Berk snijden",
        {"operation": "snijden", "speed_min": 5, "speed_max": 25, "cell_mm": 8},
        berken["id"],
    )
    bib.save_grid_recipe("Snelle 4×4", {"operation": "snijden", "cell_mm": 6})

    leeg.import_bundle(bib.export_bundle())

    recepten = {r["name"]: r for r in leeg.grid_recipes()}
    assert set(recepten) == {"Berk snijden", "Snelle 4×4"}
    assert recepten["Berk snijden"]["material_name"] == "Multiplex berken"
    assert recepten["Snelle 4×4"]["material_id"] is None
    assert recepten["Berk snijden"]["settings"]["speed_max"] == 25


def test_your_own_recipe_wins_from_the_file(bib, leeg):
    """Zelfde regel als bij presets: wat jij hebt uitgezocht blijft staan."""
    bib.save_grid_recipe("Snel", {"operation": "snijden", "cell_mm": 6})
    leeg.save_grid_recipe("Snel", {"operation": "snijden", "cell_mm": 12})

    resultaat = leeg.import_bundle(bib.export_bundle())

    assert resultaat["grid_recipes"] == 0
    assert leeg.grid_recipes()[0]["settings"]["cell_mm"] == 12
