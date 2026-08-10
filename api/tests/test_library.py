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
