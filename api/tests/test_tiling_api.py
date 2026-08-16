"""
De tegelroutes, en de dekkingstest die het hele ontwerp waarmaakt.
"""

import pytest
from fastapi.testclient import TestClient

from openkerf_api.server import ApiServer


@pytest.fixture
def client(kernel, tmp_path):
    with TestClient(ApiServer(kernel, library_path=tmp_path / "v.db").build_app()) as c:
        yield c


def wide_plate(client):
    """
    Een plaat die op het dummy-bed precies drie tegels wordt.

    Het dummy-apparaat meet 320 × 220 mm, dus het bruikbare venster is 300 mm
    breed en 800 mm plaat geeft drie tegels. Bij 900 worden het er vier.
    """
    vel = client.get("/api/sheets").json()["sheets"][0]
    client.patch(f"/api/sheets/{vel['id']}", json={"width_mm": 800.0, "height_mm": 150.0})
    client.patch(f"/api/sheets/{vel['id']}", json={"tiling": {"enabled": True}})
    for x in (10, 300, 600):
        client.post(
            "/api/design/elements",
            json={"type": "rect", "x_mm": x, "y_mm": 40, "width_mm": 40, "height_mm": 40},
        )
    return vel


def test_the_layout_is_readable_without_starting_anything(client):
    """Kijken wat het gaat worden hoort geen reeks te beginnen."""
    wide_plate(client)

    antwoord = client.get("/api/tiling")

    assert antwoord.status_code == 200
    assert len(antwoord.json()["tiles"]) == 3
    assert client.get("/api/status").json()["tiling"] is None


def test_burning_before_aligning_is_refused_in_a_sentence(client):
    wide_plate(client)
    client.post("/api/tiling/start")

    antwoord = client.post("/api/tiling/burn")

    assert antwoord.status_code == 409
    # Zie de gelijknamige test in test_tilerun.py: "uitlijn" staat niet in
    # "uitgelijnd" — er zit "ge" tussen.
    assert "uitgelijnd" in antwoord.json()["detail"].lower()


def test_the_series_shows_up_in_the_status_payload(client):
    """
    Bovenbalk, canvas en telefoon lezen alle drie dezelfde stand; een eigen
    verzoek per scherm zou ze uit elkaar laten lopen.
    """
    wide_plate(client)
    client.post("/api/tiling/start")

    stand = client.get("/api/status").json()["tiling"]

    assert stand["current"] == 0
    assert stand["tiles"] == 3
    assert stand["aligned"] is False


def test_cancelling_leaves_no_series_behind(client):
    wide_plate(client)
    client.post("/api/tiling/start")

    client.post("/api/tiling/cancel")

    assert client.get("/api/status").json()["tiling"] is None
