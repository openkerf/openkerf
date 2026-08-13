"""
Machineprofielen: één per machine, met de naam die de gebruiker koos.

Jelle vond tien profielen in een lijst waar hij er één had aangemaakt, en de
namen erin waren de interne namen van MeerK40t ("lihuiyu-device") in plaats van
hoe hij zijn laser noemde. Drie oorzaken, drie groepen tests.
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


# ------------------------------------------------------------------ dubbelen


def test_simultaneous_readers_share_one_profile(library):
    """
    De bibliotheek vraagt drie routes tegelijk op en meerdere daarvan willen
    het actieve profiel. Zonder slot leverde dat één profiel per verzoek op —
    gemeten: acht aanroepen, acht profielen.
    """
    fouten = []

    def vraag():
        try:
            library.profile_for_device("ruida", "Mijn 5030")
        except Exception as e:  # pragma: no cover - alleen bij een regressie
            fouten.append(e)

    threads = [threading.Thread(target=vraag) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert fouten == []
    assert len(library.machines()) == 1


def test_a_second_profile_for_the_same_machine_is_refused(library):
    library.add_machine(name="Mijn 5030", device_path="ruida")

    with pytest.raises(sqlite3.IntegrityError):
        library.add_machine(name="Nog een", device_path="ruida")


def test_existing_duplicates_are_merged_on_open(tmp_path):
    """De bibliotheek van Jelle heeft twee regels 'lihuiyu-device'; die moeten
    samengaan, met hun presets erbij, zonder dat er bewijs verdwijnt."""
    path = tmp_path / "oud.db"
    library = Library(path)
    materiaal = library.add_material("Multiplex")
    with sqlite3.connect(path) as db:
        # Zoals de database eruitzag vóór het slot erop kwam.
        db.execute("DROP INDEX IF EXISTS machine_profile_device")
        db.execute(
            "INSERT INTO machine_profile (id, name, device_path) VALUES (1, 'A', 'ruida')"
        )
        db.execute(
            "INSERT INTO machine_profile (id, name, device_path) VALUES (2, 'A', 'ruida')"
        )
    for machine_id in (1, 2):
        library.add_preset(
            material_id=materiaal["id"],
            machine_id=machine_id,
            operation="snijden",
            speed_mm_s=12,
            power_percent=65,
        )

    heropend = Library(path)

    machines = heropend.machines()
    assert [m["id"] for m in machines] == [1]
    # Geen preset kwijt, en allebei bij het overgebleven profiel.
    presets = heropend.presets()
    assert len(presets) == 2
    assert {p["machine_id"] for p in presets} == {1}


# ------------------------------------------------------------------- de naam


def test_the_profile_follows_the_name_of_the_machine(library):
    """
    Bij Jelle heet het apparaat "KH-5030 50W" en het profiel nog "K50 CO2":
    de naam werd één keer overgenomen en daarna nooit meer.
    """
    eerst = library.profile_for_device("ruida", "K50 CO2")

    daarna = library.profile_for_device("ruida", "KH-5030 50W")

    assert daarna["id"] == eerst["id"]
    assert daarna["name"] == "KH-5030 50W"
    assert [m["name"] for m in library.machines()] == ["KH-5030 50W"]


def test_renaming_a_machine_renames_its_profile(client, kernel):
    client.post("/api/machines", json={"info": "ruida-beta", "label": "Berk-lasertje"})
    assert client.get("/api/library/active-machine").json()["name"] == "Berk-lasertje"
    pad = kernel.device.path

    client.post(f"/api/machines/{pad}/rename", json={"label": "Mijn 5030"})

    assert client.get("/api/library/active-machine").json()["name"] == "Mijn 5030"
    assert [m["name"] for m in client.get("/api/library/machines").json()] == ["Mijn 5030"]


# ----------------------------------------------------- machines die niemand koos


def test_reading_the_library_does_not_invent_a_machine(client):
    """
    Verse installatie: de engine heeft zijn eigen lhystudios-apparaat, niemand
    heeft iets ingesteld. Openen van de bibliotheek maakte daar een profiel
    voor aan — met de interne naam van dat apparaat.
    """
    assert client.get("/api/library/machines").json() == []

    client.get("/api/library/presets")
    assert client.get("/api/library/active-machine").status_code == 409

    assert client.get("/api/library/machines").json() == []


def test_a_machine_from_the_wizard_does_get_a_profile(client):
    client.post("/api/machines", json={"info": "ruida-beta", "label": "Mijn 5030"})
    assert client.get("/api/library/active-machine").status_code == 200

    profielen = client.get("/api/library/machines").json()

    assert [m["name"] for m in profielen] == ["Mijn 5030"]
    assert profielen[0]["orphaned"] is False


# --------------------------------------------------------------- verweesd


def test_a_profile_without_a_machine_is_marked(client, server):
    server.library.add_machine(name="Laser van vroeger", device_path="ruida7")

    profiel = client.get("/api/library/machines").json()[0]

    assert profiel["orphaned"] is True
    assert profiel["presets"] == 0


def test_a_profile_for_the_engines_placeholder_counts_as_orphaned(client, kernel):
    """
    Wat de oude versie achterliet: een profiel voor het lhystudios-apparaat dat
    MeerK40t zelf aanmaakt. Het apparaat bestáát, dus zonder deze regel staat
    het in de lijst als levende machine — terwijl niemand het koos, en dat is
    precies de naam die er niet hoort te staan.
    """
    kernel.device.setting(bool, "openkerf_configured", False)
    assert kernel.device.openkerf_configured is False

    client.post(
        "/api/library/machines",
        json={"name": "lihuiyu-device", "device_path": kernel.device.path},
    )

    assert client.get("/api/library/machines").json()[0]["orphaned"] is True


def test_an_orphan_can_be_cleaned_up(client, server):
    profiel = server.library.add_machine(name="Laser van vroeger", device_path="ruida7")

    response = client.delete(f"/api/library/machines/{profiel['id']}")

    assert response.status_code == 200
    assert client.get("/api/library/machines").json() == []


def test_a_profile_with_evidence_is_not_thrown_away(client, server):
    profiel = server.library.add_machine(name="Laser van vroeger", device_path="ruida7")
    materiaal = server.library.add_material("Multiplex")
    server.library.add_preset(
        material_id=materiaal["id"],
        machine_id=profiel["id"],
        operation="snijden",
        speed_mm_s=12,
        power_percent=65,
    )

    response = client.delete(f"/api/library/machines/{profiel['id']}")

    assert response.status_code == 409
    assert "1 instelling" in response.json()["detail"]
    assert len(client.get("/api/library/machines").json()) == 1


# ---------------------------------------------------- welke machine actief is


def test_the_chosen_machine_survives_a_restart(client, kernel):
    """
    MeerK40t schrijft `activated_device` pas bij een nette afsluiting en valt
    daarna terug op `preferred_device` — standaard de lhystudios-plaatsvervanger.
    Een headless engine die omvalt, draait na de herstart dus op een K40-driver
    en de bovenbalk zegt "lihuiyu-device".
    """
    client.post("/api/machines", json={"info": "ruida-beta", "label": "Mijn 5030"})
    pad = kernel.device.path

    assert kernel.read_persistent(str, "/", "activated_device", None) == pad

    # De testkernel start met het dummy-apparaat in de rol van MeerK40t's
    # lhystudios-plaatsvervanger: erbij gezet door de engine, niet door een mens.
    client.post("/api/machines/dummy/activate")
    assert kernel.read_persistent(str, "/", "activated_device", None) == "dummy"

    client.post(f"/api/machines/{pad}/activate")
    assert kernel.read_persistent(str, "/", "activated_device", None) == pad


def test_the_machine_you_are_working_on_keeps_its_profile(client, kernel):
    """
    Weg is hij toch niet: de eerstvolgende leesroute maakt hem opnieuw aan. Wat
    er wél verandert is dat elke preset die eraan hing losraakt.
    """
    client.post("/api/machines", json={"info": "ruida-beta", "label": "Mijn 5030"})
    profiel = client.get("/api/library/active-machine").json()

    response = client.delete(f"/api/library/machines/{profiel['id']}")

    assert response.status_code == 409
    assert len(client.get("/api/library/machines").json()) == 1


def test_the_list_shows_the_current_name_of_every_machine(client, kernel, server):
    """
    Niet alleen van de machine waarop je werkt. Bij Jelle staat in de lijst nog
    "K50 CO2" terwijl dat apparaat allang "KH-5030 50W" heet — hij werkt er nu
    even niet op, dus niets liep die naam ooit na.
    """
    client.post("/api/machines", json={"info": "ruida-beta", "label": "Berk 5030 CO2"})
    eerste = kernel.device.path
    profiel = client.get("/api/library/active-machine").json()
    client.post("/api/machines", json={"info": "ruida-beta", "label": "Tweede"})
    client.get("/api/library/active-machine")
    # De stand van vóór deze reparatie: het profiel draagt een naam van vroeger
    # en de machine waar hij bij hoort is niet de actieve.
    server.library.update_machine(profiel["id"], {"name": "K50 CO2"})
    assert kernel.device.path != eerste

    namen = {m["name"] for m in client.get("/api/library/machines").json()}

    assert namen == {"Berk 5030 CO2", "Tweede"}
