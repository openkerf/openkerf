"""De gedeelde catalogus: ophalen, filteren, importeren en aandragen."""

import json

import pytest
from fastapi.testclient import TestClient

from openkerf_api.library import Library, LibraryError
from openkerf_api.presetariat import Presetariat
from openkerf_api.server import ApiServer

CATALOGUE = {
    "schema_version": 1,
    "version": "abc123",
    "count": 3,
    "presets": [
        {
            "id": "berken-3mm-snijden-co2-80w",
            "material": "Berkentriplex",
            "synonyms": ["birch plywood"],
            "thickness_mm": 3,
            "operation": "snijden",
            "machine": {"laser_type": "co2-glass", "power_watt": 80},
            "speed_mm_s": 12,
            "power_percent": 65,
            "passes": 1,
            "air_assist": True,
            "focus_offset_mm": 0,
            "note": "Startwaarde",
            "source": {"kind": "handmatig"},
            "verified": False,
        },
        {
            "id": "mdf-3mm-snijden-co2-80w",
            "material": "MDF",
            "thickness_mm": 3,
            "operation": "snijden",
            "machine": {"laser_type": "co2-glass", "power_watt": 80},
            "speed_mm_s": 10,
            "power_percent": 70,
            "source": {"kind": "testraster", "by": "iemand"},
            "verified": True,
        },
        {
            "id": "acryl-3mm-snijden-diode-10w",
            "material": "Acrylaat",
            "thickness_mm": 3,
            "operation": "snijden",
            "machine": {"laser_type": "diode", "power_watt": 10},
            "speed_mm_s": 3,
            "power_percent": 100,
            "source": {"kind": "handmatig"},
        },
    ],
}


@pytest.fixture
def catalogue_file(tmp_path):
    path = tmp_path / "presets.json"
    path.write_text(json.dumps(CATALOGUE))
    return path


@pytest.fixture
def shop(tmp_path, catalogue_file):
    library = Library(tmp_path / "lib.db")
    return Presetariat(
        library, tmp_path / "cache.json", url=catalogue_file.as_uri()
    )


@pytest.fixture
def co2(shop):
    return shop.library.add_machine(
        name="5030", laser_type="co2-glass", power_watt=80
    )["id"]


def test_browsing_returns_everything_without_a_machine(shop):
    result = shop.browse()

    assert result["count"] == 3
    assert result["version"] == "abc123"
    assert result["stale"] is False


def test_a_diode_preset_is_hidden_from_a_co2_machine(shop, co2):
    """
    Letting the settings of a 10 W diode loose on an 80 W CO2 gives nonsense, so
    filtering is not cosmetic.
    """
    ids = [p["id"] for p in shop.browse(machine_id=co2)["presets"]]

    assert "acryl-3mm-snijden-diode-10w" not in ids
    assert "mdf-3mm-snijden-co2-80w" in ids


def test_measured_and_verified_presets_come_first(shop):
    presets = shop.browse()["presets"]

    assert presets[0]["id"] == "mdf-3mm-snijden-co2-80w"


def test_searching_matches_synonyms(shop):
    result = shop.browse(material="birch")

    assert [p["id"] for p in result["presets"]] == ["berken-3mm-snijden-co2-80w"]


def test_importing_creates_a_preset_and_its_material(shop, co2):
    result = shop.import_presets(["mdf-3mm-snijden-co2-80w"], machine_id=co2)

    assert len(result["imported"]) == 1
    preset = shop.library.presets()[0]
    assert preset["material_name"] == "MDF"
    # Never as a test grid: nothing was measured on this machine.
    assert preset["source"] == "geimporteerd"
    assert preset["origin_id"] == "mdf-3mm-snijden-co2-80w"
    assert "testraster" in preset["note"]


def test_importing_twice_does_not_duplicate(shop, co2):
    shop.import_presets(["mdf-3mm-snijden-co2-80w"], machine_id=co2)

    again = shop.import_presets(["mdf-3mm-snijden-co2-80w"], machine_id=co2)

    assert again["imported"] == []
    assert again["skipped"] == ["mdf-3mm-snijden-co2-80w"]
    assert len(shop.library.presets()) == 1


def test_browsing_marks_what_is_already_imported(shop, co2):
    shop.import_presets(["mdf-3mm-snijden-co2-80w"], machine_id=co2)

    presets = {p["id"]: p for p in shop.browse()["presets"]}

    assert presets["mdf-3mm-snijden-co2-80w"]["imported"] is True
    assert presets["berken-3mm-snijden-co2-80w"]["imported"] is False


def test_an_unknown_id_is_reported_not_silently_dropped(shop):
    result = shop.import_presets(["bestaat-niet"])

    assert result["missing"] == ["bestaat-niet"]


def test_a_dead_network_falls_back_to_the_cache(shop, tmp_path):
    shop.browse()  # vult de cache
    shop.url = (tmp_path / "weg.json").as_uri()

    result = shop.browse(refresh=True)

    assert result["count"] == 3
    assert result["stale"] is True
    assert result["error"]


def test_without_cache_a_dead_network_is_an_honest_error(tmp_path):
    shop = Presetariat(
        Library(tmp_path / "l.db"),
        tmp_path / "c.json",
        url=(tmp_path / "weg.json").as_uri(),
    )

    with pytest.raises(LibraryError):
        shop.browse()


def test_sharing_produces_a_catalogue_entry(shop, co2):
    material = shop.library.add_material("Berkentriplex")["id"]
    preset = shop.library.add_preset(
        material_id=material,
        machine_id=co2,
        thickness_mm=3,
        operation="snijden",
        speed_mm_s=12,
        power_percent=65,
        source="testraster",
    )

    shared = shop.as_contribution(preset["id"])

    assert shared["preset"]["id"] == "berkentriplex-3mm-snijden-co2-80w"
    assert shared["preset"]["machine"]["power_watt"] == 80
    assert shared["preset"]["source"]["kind"] == "testraster"
    # Contributing is not verifying; a second person does that.
    assert shared["preset"]["verified"] is False
    assert shared["filename"] == "berkentriplex-3mm-snijden-co2-80w.json"
    assert shared["issue_url"].startswith("https://github.com/openkerf/presetariat/issues/new?")


def test_sharing_without_a_machine_profile_is_refused(shop):
    """Without knowing what machine it was measured on, it is useless."""
    material = shop.library.add_material("Cardboard")["id"]
    preset = shop.library.add_preset(
        material_id=material,
        operation="snijden",
        speed_mm_s=30,
        power_percent=35,
    )

    with pytest.raises(LibraryError):
        shop.as_contribution(preset["id"])


def test_the_routes_work_end_to_end(kernel, tmp_path, catalogue_file):
    server = ApiServer(kernel, library_path=tmp_path / "api.db")
    server.presetariat.url = catalogue_file.as_uri()
    with TestClient(server.build_app()) as client:
        listing = client.get("/api/presetariat")
        assert listing.status_code == 200
        assert listing.json()["count"] == 3

        response = client.post(
            "/api/presetariat/import", json={"ids": ["mdf-3mm-snijden-co2-80w"]}
        )
        assert response.status_code == 200
        assert len(client.get("/api/library/presets").json()) == 1
