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
