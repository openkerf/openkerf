"""The local material library and applying a preset to a layer."""

import pytest
from fastapi.testclient import TestClient

from openkerf_api.design import DesignReader
from openkerf_api.library import Library, LibraryError
from openkerf_api.server import ApiServer


@pytest.fixture
def library(tmp_path):
    return Library(tmp_path / "library.db")


@pytest.fixture
def client(kernel, tmp_path):
    server = ApiServer(kernel, library_path=tmp_path / "api.db")
    with TestClient(server.build_app()) as c:
        yield c


@pytest.fixture
def stocked(library):
    material = library.add_material("Multiplex berken", ["plywood", "multiplex"])
    preset = library.add_preset(
        material_id=material["id"],
        thickness_mm=3.0,
        operation="snijden",
        speed_mm_s=12,
        power_percent=65,
    )
    return material, preset


# -------------------------------------------------------------- materials

def test_material_round_trip(library):
    library.add_material("MDF", ["vezelplaat"])

    materials = library.materials()

    assert [m["name"] for m in materials] == ["MDF"]
    assert materials[0]["synonyms"] == ["vezelplaat"]


def test_material_names_are_unique(library):
    library.add_material("Acrylaat")
    with pytest.raises(LibraryError):
        library.add_material("Acrylaat")


def test_material_needs_a_name(library):
    for empty in ("", "   ", None):
        with pytest.raises(LibraryError):
            library.add_material(empty)


def test_removing_a_material_takes_its_presets(library, stocked):
    material, _ = stocked
    assert library.presets()

    library.remove_material(material["id"])

    assert library.presets() == []


# ---------------------------------------------------------------- presets

def test_preset_round_trip(library, stocked):
    _, preset = stocked

    stored = library.presets()[0]

    assert stored["id"] == preset["id"]
    assert stored["material_name"] == "Multiplex berken"
    assert stored["speed_mm_s"] == 12
    assert stored["power_percent"] == 65
    assert stored["source"] == "handmatig"
    assert stored["air_assist"] is True


def test_presets_filter_by_material_and_operation(library, stocked):
    material, _ = stocked
    library.add_preset(
        material_id=material["id"],
        operation="graveren-raster",
        speed_mm_s=300,
        power_percent=18,
    )

    assert len(library.presets()) == 2
    assert len(library.presets(operation="snijden")) == 1
    assert len(library.presets(material_id=material["id"])) == 2
    assert library.presets(material_id=9999) == []


def test_preset_rejects_impossible_values(library, stocked):
    material, _ = stocked
    base = {"material_id": material["id"], "operation": "snijden"}

    for bad in (
        {**base, "speed_mm_s": 0, "power_percent": 50},
        {**base, "speed_mm_s": 10, "power_percent": 0},
        {**base, "speed_mm_s": 10, "power_percent": 150},
        {**base, "speed_mm_s": "snel", "power_percent": 50},
        {**base, "operation": "verzonnen", "speed_mm_s": 10, "power_percent": 50},
    ):
        with pytest.raises(LibraryError):
            library.add_preset(**bad)


def test_preset_needs_an_existing_material(library):
    with pytest.raises(LibraryError):
        library.add_preset(
            material_id=4242, operation="snijden", speed_mm_s=10, power_percent=50
        )


def test_source_records_where_a_preset_came_from(library, stocked):
    material, _ = stocked
    preset = library.add_preset(
        material_id=material["id"],
        operation="snijden",
        speed_mm_s=10,
        power_percent=40,
        source="geextrapoleerd",
        note="afgeleid van 60W",
    )

    assert preset["source"] == "geextrapoleerd"
    assert preset["note"] == "afgeleid van 60W"

    with pytest.raises(LibraryError):
        library.add_preset(
            material_id=material["id"],
            operation="snijden",
            speed_mm_s=10,
            power_percent=40,
            source="verzonnen",
        )


def test_library_survives_a_reopen(tmp_path):
    path = tmp_path / "persist.db"
    first = Library(path)
    material = first.add_material("Leer")
    first.add_preset(
        material_id=material["id"], operation="markeren", speed_mm_s=200, power_percent=15
    )

    reopened = Library(path)

    assert [m["name"] for m in reopened.materials()] == ["Leer"]
    assert len(reopened.presets()) == 1


# ------------------------------------------------------ applying to a layer

def test_apply_preset_writes_speed_and_power_onto_the_operation(kernel, client):
    kernel.console("rect 20mm 15mm 60mm 40mm\n")
    kernel.console("element* cut -s 5 -p 10\n")
    operation_id = DesignReader(kernel).snapshot()["operations"][0]["id"]
    material = client.post("/api/library/materials", json={"name": "Multiplex"}).json()
    preset = client.post(
        "/api/library/presets",
        json={
            "material_id": material["id"],
            "operation": "snijden",
            "speed_mm_s": 12,
            "power_percent": 65,
            "passes": 2,
        },
    ).json()

    response = client.post(
        f"/api/library/presets/{preset['id']}/apply", json={"operation_id": operation_id}
    )

    assert response.status_code == 200
    node = kernel.elements.find_node(operation_id)
    assert node.speed == 12
    # MeerK40t stores power on a 0-1000 scale: 65% is 650, not 65.
    assert node.power == 650
    assert node.passes == 2


def test_apply_refuses_a_non_operation(kernel, client):
    kernel.console("rect 20mm 15mm 60mm 40mm\n")
    element_id = DesignReader(kernel).snapshot()["elements"][0]["id"]
    material = client.post("/api/library/materials", json={"name": "MDF"}).json()
    preset = client.post(
        "/api/library/presets",
        json={
            "material_id": material["id"],
            "operation": "snijden",
            "speed_mm_s": 10,
            "power_percent": 50,
        },
    ).json()

    response = client.post(
        f"/api/library/presets/{preset['id']}/apply", json={"operation_id": element_id}
    )

    assert response.status_code == 409


def test_apply_without_an_operation_is_a_422(client):
    material = client.post("/api/library/materials", json={"name": "Acryl"}).json()
    preset = client.post(
        "/api/library/presets",
        json={
            "material_id": material["id"],
            "operation": "snijden",
            "speed_mm_s": 10,
            "power_percent": 50,
        },
    ).json()

    assert client.post(f"/api/library/presets/{preset['id']}/apply", json={}).status_code == 422


def test_unknown_preset_is_a_409(kernel, client):
    kernel.console("rect 20mm 15mm 60mm 40mm\n")
    kernel.console("element* cut -s 5 -p 10\n")
    operation_id = DesignReader(kernel).snapshot()["operations"][0]["id"]

    response = client.post(
        "/api/library/presets/9999/apply", json={"operation_id": operation_id}
    )

    assert response.status_code == 409


# ------------------------------------------------------------------- HTTP

def test_materials_over_http(client):
    assert client.get("/api/library/materials").json() == []

    created = client.post(
        "/api/library/materials", json={"name": "Leer", "synonyms": ["leather"]}
    )

    assert created.status_code == 201
    assert client.get("/api/library/materials").json()[0]["name"] == "Leer"


def test_duplicate_material_over_http_is_a_409(client):
    client.post("/api/library/materials", json={"name": "Kurk"})
    assert client.post("/api/library/materials", json={"name": "Kurk"}).status_code == 409


def test_machine_profile_round_trip(client):
    created = client.post(
        "/api/library/machines",
        json={"name": "5030 CO2", "power_watt": 60, "lens_mm": 63.5},
    )

    assert created.status_code == 201
    assert client.get("/api/library/machines").json()[0]["power_watt"] == 60


# ------------------------------------------------------- preset bijstellen

def test_update_a_preset(library, stocked):
    _, preset = stocked

    updated = library.update_preset(preset["id"], speed_mm_s=14, power_percent=70, note="sneller")

    assert updated["speed_mm_s"] == 14
    assert updated["power_percent"] == 70
    assert updated["note"] == "sneller"


def test_identity_fields_cannot_be_changed(library, stocked):
    """Ander materiaal of andere bewerking is een andere preset, geen wijziging."""
    _, preset = stocked

    for bad in ({"material_id": 99}, {"operation": "graveren-raster"}, {"source": "testraster"}):
        with pytest.raises(LibraryError):
            library.update_preset(preset["id"], **bad)


def test_update_validates_like_creation(library, stocked):
    _, preset = stocked
    for bad in ({"speed_mm_s": 0}, {"power_percent": 150}, {"speed_mm_s": "snel"}):
        with pytest.raises(LibraryError):
            library.update_preset(preset["id"], **bad)


def test_updating_an_unknown_preset_is_refused(library):
    with pytest.raises(LibraryError):
        library.update_preset(999, speed_mm_s=10)


# ------------------------------------------------------ bereik voorstellen

def test_suggestion_without_presets_is_a_sane_default(library):
    suggestion = library.suggest_range()

    assert suggestion["based_on"] == 0
    assert suggestion["speed_min"] < suggestion["speed_max"]
    assert 0 < suggestion["power_min"] < suggestion["power_max"] <= 100


def test_suggestion_brackets_the_presets_it_knows(library, stocked):
    material, _ = stocked  # 12 mm/s @ 65%

    suggestion = library.suggest_range(material_id=material["id"], operation="snijden")

    assert suggestion["based_on"] == 1
    assert suggestion["speed_min"] < 12 < suggestion["speed_max"]
    assert suggestion["power_min"] < 65 < suggestion["power_max"]


def test_suggestion_stays_within_a_hundred_percent(library):
    material = library.add_material("Dun papier")
    library.add_preset(
        material_id=material["id"], operation="snijden", speed_mm_s=100, power_percent=95
    )

    suggestion = library.suggest_range(material_id=material["id"])

    assert suggestion["power_max"] <= 100


def test_suggestion_prefers_the_same_thickness(library):
    material = library.add_material("Multiplex")
    library.add_preset(
        material_id=material["id"], operation="snijden", thickness_mm=3,
        speed_mm_s=12, power_percent=60,
    )
    library.add_preset(
        material_id=material["id"], operation="snijden", thickness_mm=9,
        speed_mm_s=3, power_percent=95,
    )

    thin = library.suggest_range(material_id=material["id"], thickness_mm=3)

    assert thin["based_on"] == 1
    assert thin["speed_max"] < 30


def test_presets_follow_the_active_machine(client):
    """
    Een preset is een uitspraak over déze laser op dit materiaal. Standaard
    toont de bibliotheek dus wat bij de actieve machine hoort.
    """
    # Een machine die iemand heeft ingesteld; de engine start met een
    # lhystudios-plaatsvervanger die niemand koos, en die krijgt bewust geen
    # profiel (zie test_machine_profiles.py).
    client.post("/api/machines", json={"info": "ruida-beta", "label": "Mijn 5030"})
    profiel = client.get("/api/library/active-machine").json()
    assert profiel["device_path"], "het profiel hangt aan een device van de engine"

    materiaal = client.post("/api/library/materials", json={"name": "Berk"}).json()
    eigen = client.post(
        "/api/library/presets",
        json={
            "material_id": materiaal["id"],
            "operation": "snijden",
            "speed_mm_s": 12,
            "power_percent": 70,
        },
    ).json()
    assert eigen["machine_id"] == profiel["id"], "krijgt de actieve machine mee"

    # Eentje van een andere machine.
    ander = client.post(
        "/api/library/machines", json={"name": "Ruida 60W"}
    ).json()
    client.post(
        "/api/library/presets",
        json={
            "material_id": materiaal["id"],
            "operation": "snijden",
            "speed_mm_s": 30,
            "power_percent": 55,
            "machine_id": ander["id"],
        },
    )

    van_ons = client.get("/api/library/presets").json()
    alles = client.get("/api/library/presets?all_machines=true").json()

    assert [p["id"] for p in van_ons] == [eigen["id"]]
    assert len(alles) == 2


def test_a_machine_can_declare_a_z_axis_and_autofocus(client):
    """Wat de machine kán, bepaalt wat er in de jog verschijnt."""
    client.post("/api/machines", json={"info": "ruida-beta", "label": "Mijn 5030"})
    profiel = client.get("/api/library/active-machine").json()
    assert profiel["has_z"] == 0 and profiel["has_autofocus"] == 0

    bijgewerkt = client.patch(
        f"/api/library/machines/{profiel['id']}",
        json={"has_z": True, "has_autofocus": True},
    ).json()

    assert bijgewerkt["has_z"] == 1
    assert bijgewerkt["has_autofocus"] == 1
    assert client.get("/api/library/active-machine").json()["has_z"] == 1
