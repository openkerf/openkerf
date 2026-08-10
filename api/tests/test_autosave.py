"""Automatisch bewaren en herstellen."""

import pytest
from fastapi.testclient import TestClient

from openkerf_api.server import ApiServer


@pytest.fixture
def server(kernel, tmp_path):
    return ApiServer(kernel, library_path=tmp_path / "a.db")


@pytest.fixture
def client(server):
    with TestClient(server.build_app()) as c:
        yield c


def a_rect(client):
    return client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 10, "y_mm": 10, "width_mm": 20, "height_mm": 10},
    ).json()["ids"][0]


def test_nothing_to_restore_at_first(client):
    assert client.get("/api/design/autosave").json()["exists"] is False


def test_a_design_is_saved_and_can_come_back(client, server):
    a_rect(client)
    assert server.autosave.save() is True

    state = client.get("/api/design/autosave").json()
    assert state["exists"] is True
    assert state["when"]

    client.post("/api/design/clear")
    response = client.post("/api/design/autosave/restore")

    assert response.status_code == 200
    assert len(client.get("/api/design").json()["elements"]) == 1


def test_an_empty_design_never_overwrites_a_good_one(client, server):
    """
    Anders wist "nieuw ontwerp" precies het bestand dat je nodig hebt zodra er
    iets misgaat.
    """
    a_rect(client)
    server.autosave.save()
    client.post("/api/design/clear")

    assert server.autosave.save() is False
    assert client.get("/api/design/autosave").json()["exists"] is True


def test_saving_is_throttled(client, server):
    """Eén vorm verslepen stuurt tientallen signalen; die gaan niet allemaal naar schijf."""
    a_rect(client)

    assert server.autosave.touch() is True
    assert server.autosave.touch() is False


def test_restoring_over_existing_work_is_refused(client, server):
    a_rect(client)
    server.autosave.save()

    response = client.post("/api/design/autosave/restore")

    assert response.status_code == 409


def test_it_can_be_thrown_away(client, server):
    a_rect(client)
    server.autosave.save()

    client.delete("/api/design/autosave")

    assert client.get("/api/design/autosave").json()["exists"] is False
