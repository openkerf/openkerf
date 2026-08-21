"""
Machine profiles: one per machine, with the name the user chose.

Jelle found ten profiles in a list where he had created one, and the names in it
were MeerK40t's internal names ("lihuiyu-device") instead of what he called his
laser. Three causes, three groups of tests.
"""

import sqlite3
import threading

import pytest
from fastapi.testclient import TestClient

from openkerf_api.library import Library
from openkerf_api.server import ApiServer


@pytest.fixture
def library(tmp_path):
    return Library(tmp_path / "lib.db")


@pytest.fixture
def server(kernel, tmp_path):
    return ApiServer(kernel, library_path=tmp_path / "lib.db")


@pytest.fixture
def client(server):
    with TestClient(server.build_app()) as c:
        yield c


# ----------------------------------------------------------------- duplicates


def test_simultaneous_readers_share_one_profile(library):
    """
    The library asks for three routes at once and several of them want the active
    profile. Without a lock that gave one profile per request — measured: eight
    calls, eight profiles.
    """
    errors = []

    def ask():
        try:
            library.profile_for_device("ruida", "My 5030")
        except Exception as e:  # pragma: no cover - only on a regression
            errors.append(e)

    threads = [threading.Thread(target=ask) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert len(library.machines()) == 1


def test_a_second_profile_for_the_same_machine_is_refused(library):
    library.add_machine(name="My 5030", device_path="ruida")

    with pytest.raises(sqlite3.IntegrityError):
        library.add_machine(name="Another one", device_path="ruida")


def test_existing_duplicates_are_merged_on_open(tmp_path):
    """Jelle's library has two rows 'lihuiyu-device'; those have to be merged,
    presets and all, without any evidence disappearing."""
    path = tmp_path / "oud.db"
    library = Library(path)
    material = library.add_material("Multiplex")
    with sqlite3.connect(path) as db:
        # The way the database looked before the lock went on it.
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

    reopened = Library(path)

    machines = reopened.machines()
    assert [m["id"] for m in machines] == [1]
    # No preset lost, and both on the profile that stayed.
    presets = reopened.presets()
    assert len(presets) == 2
    assert {p["machine_id"] for p in presets} == {1}


# -------------------------------------------------------------------- the name


def test_the_profile_follows_the_name_of_the_machine(library):
    """
    On Jelle's machine the device is called "KH-5030 50W" and the profile is
    still "K50 CO2": the name was taken over once and never again.
    """
    first_time = library.profile_for_device("ruida", "K50 CO2")

    after = library.profile_for_device("ruida", "KH-5030 50W")

    assert after["id"] == first_time["id"]
    assert after["name"] == "KH-5030 50W"
    assert [m["name"] for m in library.machines()] == ["KH-5030 50W"]


def test_renaming_a_machine_renames_its_profile(client, kernel):
    client.post("/api/machines", json={"info": "ruida-beta", "label": "Little birch laser"})
    assert client.get("/api/library/active-machine").json()["name"] == "Little birch laser"
    path = kernel.device.path

    client.post(f"/api/machines/{path}/rename", json={"label": "My 5030"})

    assert client.get("/api/library/active-machine").json()["name"] == "My 5030"
    assert [m["name"] for m in client.get("/api/library/machines").json()] == ["My 5030"]


# ------------------------------------------------------- machines nobody chose


def test_reading_the_library_does_not_invent_a_machine(client):
    """
    A fresh install: the engine has its own lhystudios device, nobody has set
    anything up. Opening the library used to create a profile for it — with that
    device's internal name.
    """
    assert client.get("/api/library/machines").json() == []

    client.get("/api/library/presets")
    assert client.get("/api/library/active-machine").status_code == 409

    assert client.get("/api/library/machines").json() == []


def test_a_machine_from_the_wizard_does_get_a_profile(client):
    client.post("/api/machines", json={"info": "ruida-beta", "label": "My 5030"})
    assert client.get("/api/library/active-machine").status_code == 200

    profiles = client.get("/api/library/machines").json()

    assert [m["name"] for m in profiles] == ["My 5030"]
    assert profiles[0]["orphaned"] is False


# --------------------------------------------------------------- orphaned


def test_a_profile_without_a_machine_is_marked(client, server):
    server.library.add_machine(name="Laser from the old days", device_path="ruida7")

    profile = client.get("/api/library/machines").json()[0]

    assert profile["orphaned"] is True
    assert profile["presets"] == 0


def test_a_profile_for_the_engines_placeholder_counts_as_orphaned(client, kernel):
    """
    What the old version left behind: a profile for the lhystudios device that
    MeerK40t creates itself. The device *does* exist, so without this rule it sits
    in the list as a live machine — while nobody chose it, and that is exactly the
    name that should not be there.
    """
    kernel.device.setting(bool, "openkerf_configured", False)
    assert kernel.device.openkerf_configured is False

    client.post(
        "/api/library/machines",
        json={"name": "lihuiyu-device", "device_path": kernel.device.path},
    )

    assert client.get("/api/library/machines").json()[0]["orphaned"] is True


def test_an_orphan_can_be_cleaned_up(client, server):
    profile = server.library.add_machine(name="Laser from the old days", device_path="ruida7")

    response = client.delete(f"/api/library/machines/{profile['id']}")

    assert response.status_code == 200
    assert client.get("/api/library/machines").json() == []


def test_a_profile_with_evidence_is_not_thrown_away(client, server):
    profile = server.library.add_machine(name="Laser from the old days", device_path="ruida7")
    material = server.library.add_material("Multiplex")
    server.library.add_preset(
        material_id=material["id"],
        machine_id=profile["id"],
        operation="snijden",
        speed_mm_s=12,
        power_percent=65,
    )

    response = client.delete(f"/api/library/machines/{profile['id']}")

    assert response.status_code == 409
    assert "1 setting" in response.json()["detail"]
    assert len(client.get("/api/library/machines").json()) == 1


# ------------------------------------------------- which machine is active


def test_the_chosen_machine_survives_a_restart(client, kernel):
    """
    MeerK40t only writes `activated_device` on a clean shutdown and otherwise
    falls back on `preferred_device` — the lhystudios stand-in by default. So a
    headless engine that falls over runs on a K40 driver after the restart and the
    top bar says "lihuiyu-device".
    """
    client.post("/api/machines", json={"info": "ruida-beta", "label": "My 5030"})
    path = kernel.device.path

    assert kernel.read_persistent(str, "/", "activated_device", None) == path

    # The test kernel starts with the dummy device in the role of MeerK40t's
    # lhystudios stand-in: put there by the engine, not by a human.
    client.post("/api/machines/dummy/activate")
    assert kernel.read_persistent(str, "/", "activated_device", None) == "dummy"

    client.post(f"/api/machines/{path}/activate")
    assert kernel.read_persistent(str, "/", "activated_device", None) == path


def test_the_machine_you_are_working_on_keeps_its_profile(client, kernel):
    """
    It is not gone anyway: the very next read route creates it again. What *does*
    change is that every preset hanging off it comes loose.
    """
    client.post("/api/machines", json={"info": "ruida-beta", "label": "My 5030"})
    profile = client.get("/api/library/active-machine").json()

    response = client.delete(f"/api/library/machines/{profile['id']}")

    assert response.status_code == 409
    assert len(client.get("/api/library/machines").json()) == 1


def test_the_list_shows_the_current_name_of_every_machine(client, kernel, server):
    """
    Not only of the machine you are working on. Jelle's list still says "K50 CO2"
    while that device has long been called "KH-5030 50W" — he is not working on it
    at the moment, so nothing ever went back to check that name.
    """
    client.post("/api/machines", json={"info": "ruida-beta", "label": "Birch 5030 CO2"})
    first = kernel.device.path
    profile = client.get("/api/library/active-machine").json()
    client.post("/api/machines", json={"info": "ruida-beta", "label": "Second"})
    client.get("/api/library/active-machine")
    # The state before this repair: the profile carries a name from the past and
    # the machine it belongs to is not the active one.
    server.library.update_machine(profile["id"], {"name": "K50 CO2"})
    assert kernel.device.path != first

    names = {m["name"] for m in client.get("/api/library/machines").json()}

    assert names == {"Birch 5030 CO2", "Second"}
