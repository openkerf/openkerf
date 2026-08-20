"""
Knippen, kopiëren en plakken.

De engine heeft een klembord (`core/elements/clipboard.py`); wij zetten er de
nadruk op en lezen de stand terug. Wat hier vastgepind wordt is niet dat de
engine werkt, maar de twee dingen die wij eraan toevoegen: plakken op een
gevraagde plek, en géén stilzwijgende groep om wat je plakt.
"""

import pytest
from fastapi.testclient import TestClient

from openkerf_api.server import ApiServer


@pytest.fixture
def client(kernel):
    with TestClient(ApiServer(kernel).build_app()) as c:
        yield c


def _ids(client):
    return [e["id"] for e in client.get("/api/design").json()["elements"]]


def _vak(client, element_id):
    element = next(e for e in client.get("/api/design").json()["elements"] if e["id"] == element_id)
    return element["bounds"]


@pytest.fixture
def twee(client):
    client.post("/api/design/elements", json={"type": "rect", "x_mm": 10, "y_mm": 10, "width_mm": 20, "height_mm": 10})
    client.post("/api/design/elements", json={"type": "rect", "x_mm": 50, "y_mm": 10, "width_mm": 20, "height_mm": 10})
    return _ids(client)


def test_a_fresh_clipboard_is_empty(client):
    state = client.get("/api/design/clipboard").json()

    assert state["count"] == 0
    assert state["bounds"] is None


def test_copy_fills_the_clipboard_without_touching_the_design(client, twee):
    state = client.post("/api/design/clipboard/copy", json={"ids": [twee[0]]}).json()

    assert state["count"] == 1
    assert state["bounds"]["width_mm"] == pytest.approx(20, abs=0.01)
    assert _ids(client) == twee


def test_cut_fills_the_clipboard_and_removes_the_shape(client, twee):
    state = client.post("/api/design/clipboard/cut", json={"ids": [twee[0]]}).json()

    assert state["count"] == 1
    assert len(_ids(client)) == 1


def test_paste_puts_the_work_back_after_a_cut(client, twee):
    client.post("/api/design/clipboard/cut", json={"ids": [twee[0]]})

    response = client.post("/api/design/clipboard/paste", json={})

    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert len(_ids(client)) == 2


def test_paste_without_a_target_lands_next_to_the_original(client, twee):
    """Precies op elkaar plakken ziet eruit als "er gebeurde niets"."""
    client.post("/api/design/clipboard/copy", json={"ids": [twee[0]]})
    voor = _vak(client, twee[0])

    nieuw = client.post("/api/design/clipboard/paste", json={}).json()["ids"][0]

    na = _vak(client, nieuw)
    assert na[0] > voor[0]
    assert na[1] > voor[1]


def test_paste_at_a_point_puts_the_top_left_corner_there(client, twee):
    client.post("/api/design/clipboard/copy", json={"ids": [twee[0]]})

    nieuw = client.post(
        "/api/design/clipboard/paste", json={"x_mm": 120, "y_mm": 80}
    ).json()["ids"][0]

    from meerk40t.core.units import UNITS_PER_MM

    vak = _vak(client, nieuw)
    assert vak[0] / UNITS_PER_MM == pytest.approx(120, abs=0.05)
    assert vak[1] / UNITS_PER_MM == pytest.approx(80, abs=0.05)


def test_pasting_more_than_one_shape_does_not_leave_a_group_behind(client, twee):
    """
    `clipboard paste` van de engine wikkelt meer dan één vorm in een groep.
    Plakken dat stilzwijgend groepeert merk je pas als je één vorm wil
    verslepen en er twee meekomen.
    """
    client.post("/api/design/clipboard/copy", json={"ids": twee})

    geplakt = client.post("/api/design/clipboard/paste", json={}).json()

    assert geplakt["count"] == 2
    snapshot = client.get("/api/design").json()["elements"]
    assert len(snapshot) == 4
    assert all(e["group_id"] is None for e in snapshot)


def test_pasting_a_real_group_keeps_that_group(client, twee):
    client.post("/api/design/group", json={"ids": twee})
    client.post("/api/design/clipboard/copy", json={"ids": twee})

    client.post("/api/design/clipboard/paste", json={})

    snapshot = client.get("/api/design").json()["elements"]
    assert len(snapshot) == 4
    assert sum(1 for e in snapshot if e["group_id"]) == 4


def test_pasting_an_empty_clipboard_says_so(client):
    response = client.post("/api/design/clipboard/paste", json={})

    assert response.status_code == 409
    assert "leeg" in response.json()["detail"].lower()
