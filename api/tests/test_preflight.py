"""
De pre-flight: wat gaat de machine dóén.

Tijd en aantal onderdelen alleen is theater. Wie tien jaar met een laser werkt
kijkt vóór het starten naar snelheid, vermogen, passes — en waar die getallen
vandaan komen.
"""

import pytest
from fastapi.testclient import TestClient

from openkerf_api.server import ApiServer


@pytest.fixture
def client(kernel, tmp_path):
    with TestClient(ApiServer(kernel, library_path=tmp_path / "p.db").build_app()) as c:
        yield c


def a_job(client, speed=12, power=65):
    made = client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 20, "y_mm": 20, "width_mm": 50, "height_mm": 50},
    ).json()
    layer = client.post(
        "/api/design/operations",
        json={"type": "cut", "speed": speed, "power_percent": power},
    ).json()
    client.post(
        "/api/design/assign", json={"ids": made["ids"], "operation_id": layer["id"]}
    )
    return layer


def test_the_preflight_says_what_the_machine_will_do(client):
    a_job(client)

    estimate = client.get("/api/job/estimate").json()

    assert estimate["seconds"] > 0
    layers = [l for l in estimate["layers"] if l["label"] == "Snijden"]
    assert layers, "de laag staat niet in de pre-flight"
    layer = layers[0]
    assert layer["speed_mm_s"] == 12
    assert layer["power_percent"] == 65
    assert layer["passes"] >= 1
    assert layer["elements"] == 1


def test_settings_that_came_from_a_test_grid_are_marked_as_measured(client):
    """Gemeten is een ander gesprek dan gegokt, en dat hoor je te zien."""
    material = client.post("/api/library/materials", json={"name": "Berken"}).json()
    client.post(
        "/api/library/presets",
        json={
            "material_id": material["id"],
            "operation": "snijden",
            "speed_mm_s": 12,
            "power_percent": 65,
            "source": "testraster",
        },
    )
    a_job(client, speed=12, power=65)

    layer = next(
        l for l in client.get("/api/job/estimate").json()["layers"] if l["label"] == "Snijden"
    )
    assert layer["source"] == "testraster"


def test_settings_nobody_measured_have_no_provenance(client):
    a_job(client, speed=37, power=42)

    layer = next(
        l for l in client.get("/api/job/estimate").json()["layers"] if l["label"] == "Snijden"
    )
    assert layer["source"] is None


def test_a_layer_that_does_not_burn_is_left_out(client):
    """Wat niet meebrandt hoort niet in de opsomming van wat er gaat gebeuren."""
    layer = a_job(client)
    client.patch(f"/api/design/operations/{layer['id']}", json={"output": False})

    labels = [l["label"] for l in client.get("/api/job/estimate").json()["layers"]]
    assert "Snijden" not in labels


# -------------------------------------------------------------- herkomst (B1)

def a_preset(client, material, **fields):
    body = {
        "material_id": material["id"],
        "operation": "snijden",
        "speed_mm_s": 12,
        "power_percent": 65,
        **fields,
    }
    return client.post("/api/library/presets", json=body).json()


def a_material(client, name):
    return client.post("/api/library/materials", json={"name": name}).json()


def layer_of(client, label="Snijden"):
    estimate = client.get("/api/job/estimate").json()
    return next(l for l in estimate["layers"] if l["label"] == label)


def test_applying_a_preset_records_where_the_settings_came_from(client):
    """
    De pre-flight raadde de herkomst aan de getallen. 12 mm/s op 65% bestaat
    voor meer dan één materiaal, dus dat raden moet een weten worden.
    """
    berken = a_material(client, "Berken")
    preset = a_preset(client, berken, thickness_mm=3, source="testraster")
    layer = a_job(client, speed=1, power=1)
    client.post(
        f"/api/library/presets/{preset['id']}/apply", json={"operation_id": layer["id"]}
    )

    gevonden = layer_of(client)

    assert gevonden["preset_id"] == preset["id"]
    assert gevonden["material_name"] == "Berken"
    assert gevonden["thickness_mm"] == 3
    assert gevonden["source"] == "testraster"


def test_the_preflight_warns_when_a_layer_carries_another_materials_setting(client):
    """Dit is de vraag waar B1 over gaat: hoort deze instelling bij dit vel?"""
    berken = a_material(client, "Berken")
    acryl = a_material(client, "Acryl")
    preset = a_preset(client, berken, thickness_mm=3)
    client.patch("/api/sheets/vel-1", json={"material_id": acryl["id"], "thickness_mm": 3})
    layer = a_job(client, speed=1, power=1)
    client.post(
        f"/api/library/presets/{preset['id']}/apply", json={"operation_id": layer["id"]}
    )

    codes = [w["code"] for w in layer_of(client)["warnings"]]

    assert "ander-materiaal" in codes


def test_the_same_material_in_another_thickness_is_also_worth_a_word(client):
    berken = a_material(client, "Berken")
    preset = a_preset(client, berken, thickness_mm=3)
    client.patch("/api/sheets/vel-1", json={"material_id": berken["id"], "thickness_mm": 6})
    layer = a_job(client, speed=1, power=1)
    client.post(
        f"/api/library/presets/{preset['id']}/apply", json={"operation_id": layer["id"]}
    )

    gevonden = layer_of(client)

    assert [w["code"] for w in gevonden["warnings"]] == ["andere-dikte"]
    assert "6" in gevonden["warnings"][0]["text"]


def test_an_extrapolated_setting_says_it_was_never_burned(client):
    """
    De taak die dit moet verbeteren: zie je vóór het starten dat deze waarden
    nooit gebrand zijn?
    """
    berken = a_material(client, "Berken")
    preset = a_preset(client, berken, thickness_mm=3, source="geextrapoleerd")
    client.patch("/api/sheets/vel-1", json={"material_id": berken["id"], "thickness_mm": 3})
    layer = a_job(client, speed=1, power=1)
    client.post(
        f"/api/library/presets/{preset['id']}/apply", json={"operation_id": layer["id"]}
    )

    gevonden = layer_of(client)

    assert [w["code"] for w in gevonden["warnings"]] == ["nooit-gebrand"]
    assert gevonden["source"] == "geextrapoleerd"


def test_a_matching_material_and_thickness_says_nothing(client):
    """Wie niets te melden heeft, zwijgt: anders leert de gebruiker wegkijken."""
    berken = a_material(client, "Berken")
    preset = a_preset(client, berken, thickness_mm=3, source="testraster")
    client.patch("/api/sheets/vel-1", json={"material_id": berken["id"], "thickness_mm": 3})
    layer = a_job(client, speed=1, power=1)
    client.post(
        f"/api/library/presets/{preset['id']}/apply", json={"operation_id": layer["id"]}
    )

    assert layer_of(client)["warnings"] == []


def test_hand_edited_values_lose_their_claimed_provenance(client):
    """
    Een briefje dat niet meer klopt is erger dan geen briefje: dan staat er
    "3 mm berken, gemeten" boven getallen die iemand zelf heeft bijgedraaid.
    """
    berken = a_material(client, "Berken")
    preset = a_preset(client, berken, thickness_mm=3, source="testraster")
    layer = a_job(client, speed=1, power=1)
    client.post(
        f"/api/library/presets/{preset['id']}/apply", json={"operation_id": layer["id"]}
    )
    client.patch(f"/api/design/operations/{layer['id']}", json={"speed": 40})

    gevonden = layer_of(client)

    assert gevonden["preset_id"] is None
    assert gevonden["material_name"] is None


def test_the_estimate_names_the_sheet_it_burns_on(client):
    berken = a_material(client, "Berken")
    client.patch("/api/sheets/vel-1", json={"material_id": berken["id"], "thickness_mm": 3})
    a_job(client)

    sheet = client.get("/api/job/estimate").json()["sheet"]

    assert sheet["material_name"] == "Berken"
    assert sheet["thickness_mm"] == 3


def test_a_removed_sheet_does_not_bequeath_its_provenance(client):
    """
    Vel-nummers worden hergebruikt: verwijder vel-2 en het volgende nieuwe vel
    heet weer vel-2. Zonder opruimen erft dat vel de herkomst van zijn
    voorganger, en dan staat er een materiaal bij een laag die het nooit zag.
    """
    berken = a_material(client, "Berken")
    preset = a_preset(client, berken, thickness_mm=3, source="testraster")
    client.post("/api/sheets", json={"name": "Tweede"})
    client.post("/api/sheets/vel-2/activate")
    layer = a_job(client, speed=1, power=1)
    client.post(
        f"/api/library/presets/{preset['id']}/apply", json={"operation_id": layer["id"]}
    )
    assert layer_of(client)["preset_id"] == preset["id"]

    client.delete("/api/sheets/vel-2")
    client.post("/api/sheets", json={"name": "Derde"})
    client.post("/api/sheets/vel-2/activate")
    opnieuw = a_job(client, speed=1, power=1)

    hergebruikt = [l for l in client.get("/api/job/estimate").json()["layers"] if l["id"] == opnieuw["id"]]
    assert hergebruikt and hergebruikt[0]["preset_id"] is None


def test_the_heaviest_objection_comes_first(client):
    """
    Een gemeten instelling van het verkeerde materiaal weegt zwaarder dan een
    uitgerekende op het juiste: die getallen zijn wél waar, maar over iets
    anders. Wie beide even zwaar toont, laat de gebruiker uitzoeken wat er
    eerst moet — precies op het moment dat daar geen tijd voor is.
    """
    berken = a_material(client, "Berken")
    zacht = a_preset(client, berken, thickness_mm=6, source="geextrapoleerd")
    client.patch("/api/sheets/vel-1", json={"material_id": berken["id"], "thickness_mm": 3})
    layer = a_job(client, speed=1, power=1)
    client.post(
        f"/api/library/presets/{zacht['id']}/apply", json={"operation_id": layer["id"]}
    )

    codes = [w["code"] for w in layer_of(client)["warnings"]]
    ernst = [w["ernst"] for w in layer_of(client)["warnings"]]

    assert codes == ["andere-dikte", "nooit-gebrand"]
    assert ernst == sorted(ernst, reverse=True)


def test_what_will_be_burned_can_be_read_without_building_the_plan(client):
    """
    De tijdschatting bouwt het hele snijplan en duurt op een zwaar ontwerp
    minuten (gat J1). De waarschuwing dat een laag bij een ander materiaal
    hoort, mag daar niet achteraan staan — dat is juist wat je vóór het starten
    moet weten.
    """
    berken = a_material(client, "Berken")
    preset = a_preset(client, berken, thickness_mm=3, source="testraster")
    client.patch("/api/sheets/vel-1", json={"material_id": berken["id"], "thickness_mm": 3})
    layer = a_job(client, speed=1, power=1)
    client.post(
        f"/api/library/presets/{preset['id']}/apply", json={"operation_id": layer["id"]}
    )

    overzicht = client.get("/api/job/layers").json()

    assert overzicht["sheet"]["material_name"] == "Berken"
    gevonden = next(l for l in overzicht["layers"] if l["label"] == "Snijden")
    assert gevonden["preset_id"] == preset["id"]
    # Dezelfde lagen als de pre-flight, alleen zonder klok.
    assert "seconds" not in overzicht
