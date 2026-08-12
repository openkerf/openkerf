"""Automatisch bewaren en herstellen."""

import pytest
from fastapi.testclient import TestClient

from openkerf_api.autosave import INTERVAL
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


def test_a_new_design_after_exporting_is_not_haunted(client, server):
    """
    Tekenen, exporteren, aan iets nieuws beginnen — en de volgende laadbeurt
    vroeg of je die pas geëxporteerde tekening wilde terugzetten. Er valt daar
    niets te herstellen: het staat onder je eigen naam op schijf. Een venster
    dat bij elk nieuw ontwerp langskomt, leer je wegklikken, en dan mis je het
    op de dag dat het wél ergens over gaat.
    """
    a_rect(client)
    server.autosave.save()
    client.get("/api/design/export.svg")

    client.post("/api/design/clear")

    assert client.get("/api/design/autosave").json()["exists"] is False


def test_unsaved_work_keeps_its_net_even_when_you_clear_the_canvas(client, server):
    """
    De keerzijde, en die weegt zwaarder: wie tekent zonder op te slaan en dan
    het canvas leegt, moet het nog terug kunnen halen.
    """
    a_rect(client)
    server.autosave.save()

    client.post("/api/design/clear")

    assert client.get("/api/design/autosave").json()["exists"] is True


def test_the_last_change_before_you_walk_away_still_lands(client, server, monkeypatch):
    """
    `touch` schrijft de eerste wijziging en remt daarna. Wie in die interval nog
    twee vormen tekent en dan naar de machine loopt, kreeg voor die twee nooit
    meer een schrijfbeurt: er komt geen signaal meer om er een op te hangen.
    Gemeten op een draaiende server: drie vormen in drie seconden, proces
    afgeschoten, één vorm in het herstelbestand.

    `flush` hangt als kerneljob aan de scheduler en haalt de staart op.
    """
    a_rect(client)
    assert server.autosave.touch() is True

    a_rect(client)
    a_rect(client)
    assert server.autosave.touch() is False, "de rem hoort er nog op te staan"
    # Niets meer te doen zonder de staart: er komt geen wijziging meer.
    assert server.autosave.flush() is False, "binnen de interval blijft het wachten"

    # De interval loopt af terwijl er niemand meer tekent.
    monkeypatch.setattr(
        "openkerf_api.autosave.time.monotonic",
        lambda: server.autosave._last + INTERVAL + 1,
    )

    assert server.autosave.flush() is True
    assert server.autosave.flush() is False, "één keer is genoeg; niet blijven schrijven"


def test_clearing_the_design_does_not_use_up_the_throttle(client, server):
    """
    Leegmaken stuurt een boomsignaal, dus `touch()` komt langs — maar er is
    niets te bewaren. Zonder deze regel zette dat wél de klok, en stond de
    eerste twintig seconden van je volgende ontwerp buiten het vangnet.
    Gemeten op een draaiende server: leegmaken, vier vormen tekenen, geen
    herstelbestand.
    """
    a_rect(client)
    assert server.autosave.touch() is True

    client.delete("/api/design/autosave")
    client.post("/api/design/clear")
    assert server.autosave.touch() is False, "een leeg ontwerp schrijft niets"

    a_rect(client)

    assert server.autosave.touch() is True


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
