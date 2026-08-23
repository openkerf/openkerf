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


def test_removing_a_material_with_everything_takes_its_presets(library, stocked):
    """
    The cascade is still the cascade — but only when the caller asked for it.

    This test used to call `remove_material(id)` bare and pin the silent cascade as
    intended. It was not: measured on a copy of the live library, removing Berkentriplex
    that way took six settings, two of them measured with photographs, orphaned two
    boards, and the route answered `{"removed": 6}`. So the flag is the word for "yes,
    all of it" and the sibling below pins what happens without it.
    """
    material, _ = stocked
    assert library.presets()

    gone = library.remove_material(material["id"], with_everything=True)

    assert library.presets() == []
    assert gone["presets"] == 1


def test_removing_a_material_that_carries_work_is_refused_and_names_the_count(library):
    """
    A bare remove of a material that carries work is a data-loss button with a label on
    it. The refusal has to say what would go, in the numbers the user can recognise.
    """
    material = library.add_material("Berkentriplex")
    for thickness in (3, 4, 6, 8, 10, 12):
        library.add_preset(
            material_id=material["id"],
            thickness_mm=thickness,
            operation="snijden",
            speed_mm_s=12,
            power_percent=65,
        )
    for _ in range(2):
        library.add_test_grid(_grid_plan(material["id"]), [])
    library.save_grid_recipe("cut birch", {"operation": "snijden"}, material["id"])

    with pytest.raises(LibraryError) as refusal:
        library.remove_material(material["id"])

    assert refusal.value.code == "library.material.inUse"
    assert "6 setting(s)" in str(refusal.value)
    assert "2 test board(s)" in str(refusal.value)
    assert "1 recipe(s)" in str(refusal.value)
    # Nothing went.
    assert len(library.presets()) == 6
    assert len(library.test_grids()) == 2


def _grid_plan(material_id):
    """The smallest board `add_test_grid` accepts, for tests that only count them."""
    return {
        "material_id": material_id,
        "operation": "snijden",
        "speed_min": 8, "speed_max": 20, "speed_steps": 2,
        "power_min": 40, "power_max": 100, "power_steps": 2,
        "cell_mm": 8, "gap_mm": 2, "origin_x_mm": 0, "origin_y_mm": 0,
    }


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

    updated = library.update_preset(preset["id"], speed_mm_s=14, power_percent=70, note="faster")

    assert updated["speed_mm_s"] == 14
    assert updated["power_percent"] == 70
    assert updated["note"] == "faster"


def test_identity_fields_cannot_be_changed(library, stocked):
    """A different material or operation is a different preset, not a change."""
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
    A preset is a statement about *this* laser on this material. So by default the
    library shows what belongs to the active machine.
    """
    # A machine somebody set up; the engine starts with an lhystudios stand-in
    # that nobody chose, and that one deliberately gets no profile (see
    # test_machine_profiles.py).
    client.post("/api/machines", json={"info": "ruida-beta", "label": "My 5030"})
    profile = client.get("/api/library/active-machine").json()
    assert profile["device_path"], "the profile hangs off a device of the engine"

    material = client.post("/api/library/materials", json={"name": "Birch"}).json()
    ours = client.post(
        "/api/library/presets",
        json={
            "material_id": material["id"],
            "operation": "snijden",
            "speed_mm_s": 12,
            "power_percent": 70,
        },
    ).json()
    assert ours["machine_id"] == profile["id"], "takes the active machine along"

    # One from another machine.
    other = client.post(
        "/api/library/machines", json={"name": "Ruida 60W"}
    ).json()
    client.post(
        "/api/library/presets",
        json={
            "material_id": material["id"],
            "operation": "snijden",
            "speed_mm_s": 30,
            "power_percent": 55,
            "machine_id": other["id"],
        },
    )

    van_ons = client.get("/api/library/presets").json()
    alles = client.get("/api/library/presets?all_machines=true").json()

    assert [p["id"] for p in van_ons] == [ours["id"]]
    assert len(alles) == 2


def test_a_machine_can_declare_a_z_axis_and_autofocus(client):
    """Wat de machine kán, bepaalt wat er in de jog verschijnt."""
    client.post("/api/machines", json={"info": "ruida-beta", "label": "My 5030"})
    profile = client.get("/api/library/active-machine").json()
    assert profile["has_z"] == 0 and profile["has_autofocus"] == 0

    bijgewerkt = client.patch(
        f"/api/library/machines/{profile['id']}",
        json={"has_z": True, "has_autofocus": True},
    ).json()

    assert bijgewerkt["has_z"] == 1
    assert bijgewerkt["has_autofocus"] == 1
    assert client.get("/api/library/active-machine").json()["has_z"] == 1
