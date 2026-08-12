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


def test_throwing_it_away_does_not_leave_you_without_a_net(client, server):
    """
    "Beginnen met een leeg canvas" gooit het herstelbestand weg, en daarna werk
    je gewoon door. De rem meet vanaf de laatste schrijfbeurt, dus zonder deze
    reset zwijgt de autosave nog een hele interval — en als je in die tijd
    ophoudt met tekenen, staat er helemaal niets. Gemeten op een draaiende
    server: weggooien, vier vormen tekenen, dertig seconden wachten, geen
    herstelbestand.
    """
    a_rect(client)
    # Via touch(), niet save(): de rem gaat pas lopen als er langs de rem
    # geschreven is, en dat is precies de toestand waar het misgaat.
    assert server.autosave.touch() is True

    client.delete("/api/design/autosave")
    a_rect(client)

    assert server.autosave.touch() is True
    assert client.get("/api/design/autosave").json()["exists"] is True


def test_after_restoring_the_next_change_is_saved_again(client, server):
    """Hetzelfde na herstellen: wat je ná het terugzetten doet, hoort beschermd."""
    a_rect(client)
    assert server.autosave.touch() is True
    client.post("/api/design/clear")
    client.post("/api/design/autosave/restore")

    a_rect(client)

    assert server.autosave.touch() is True


def test_autosaving_does_not_rename_your_document(kernel, client, tmp_path):
    """
    Automatisch bewaren schrijft naar `herstel.svg`, en `save` zet die naam op
    `elements.basename`. Die naam kwam daarna terug als jobnaam: elke job in de
    wachtrij heette "herstel.svg", ook op een vers ontwerp waar niets hersteld
    was. Twee jobs die hetzelfde heten zijn bij een laser niet uit elkaar te
    houden.
    """

    client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 10, "y_mm": 10, "width_mm": 20, "height_mm": 20},
    )
    kernel.elements._filename = "/ergens/mijn-ontwerp.svg"

    _autosave(kernel, tmp_path).save()

    assert kernel.elements.basename == "mijn-ontwerp.svg"


def test_autosaving_leaves_an_unnamed_document_unnamed(kernel, client, tmp_path):
    """Zonder naam blijft het naamloos — dan verzint onze eigen jobnaam iets."""

    client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 10, "y_mm": 10, "width_mm": 20, "height_mm": 20},
    )
    voor = getattr(kernel.elements, "basename", None)

    _autosave(kernel, tmp_path).save()

    assert getattr(kernel.elements, "basename", None) == voor


def _autosave(kernel, tmp_path):
    """De autosave zoals de server hem maakt, met een eigen pad voor de test."""
    from openkerf_api.autosave import Autosave
    from openkerf_api.document import Document
    from openkerf_api.drawing import Drawing

    return Autosave(kernel, Drawing(kernel), Document(), tmp_path / "herstel.svg")
