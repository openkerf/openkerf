"""
Verbinden en verbreken.

De statusbalk kon al lezen of er een machine aan de lijn hing, maar er was geen
manier om er iets aan te doen: "niet verbonden" en geen knop. De engine heeft de
opdrachten wel, maar elke driver noemt ze anders (`ruida_connect` bij Ruida,
`usb_connect` bij lihuiyu/moshi/newly/balor) en ze staan op `hidden=True`, dus
we vragen het actieve apparaat wat het kent in plaats van het aan te nemen.
"""

import types

import pytest
from fastapi.testclient import TestClient

from openkerf_api.edits import DesignError
from openkerf_api.machine import MachineControl
from openkerf_api.server import ApiServer


@pytest.fixture
def client(kernel, tmp_path):
    with TestClient(ApiServer(kernel, library_path=tmp_path / "d.db").build_app()) as c:
        yield c


class FakeRunner:
    """Zegt ja tegen elk commando en levert de regels die de engine zou geven."""

    def __init__(self, output=()):
        self.output = list(output)
        self.ran: list[str] = []

    def supports(self, name, input_type="None"):
        return True

    def run(self, command):
        self.ran.append(command)
        return list(self.output)


def besturing(connected, output=()) -> MachineControl:
    """Een MachineControl om een nagemaakt apparaat, zonder socket."""
    device = types.SimpleNamespace(connected=connected, spooler=None)
    kernel = types.SimpleNamespace(device=device)
    return MachineControl(kernel, FakeRunner(output))


# ------------------------------------------------------- wat een apparaat kent


def test_a_device_without_a_connect_command_does_not_get_a_button(kernel):
    """Het dummy-apparaat kent geen verbindopdracht; dan hoort er geen knop."""
    control = MachineControl(kernel)

    caps = control.connection_capabilities()

    assert caps["connect"] is False
    assert caps["disconnect"] is False


def test_a_ruida_offers_connecting(kernel):
    kernel.console("service device start ruida -i\n")
    control = MachineControl(kernel)

    caps = control.connection_capabilities()

    assert caps["connect"] is True
    assert caps["disconnect"] is True


def test_connecting_without_a_command_says_so_instead_of_failing_silently(kernel):
    control = MachineControl(kernel)

    with pytest.raises(DesignError) as fout:
        control.connect()

    assert "verbind" in str(fout.value).lower()


# ------------------------------------------------------------- de uitkomst


def test_connecting_reports_the_state_the_machine_ended_up_in():
    control = besturing(connected=True)

    result = control.connect()

    assert result["connection"]["state"] == "connected"
    assert control.runner.ran == ["ruida_connect"]


def test_a_refused_connection_is_an_error_with_the_engines_own_words():
    """
    `ruida_connect` slikt zijn eigen fout op en schrijft die naar een kanaal
    (`ruida/device.py:452`). Zonder deze regel geeft de knop HTTP 200 terug op
    een verbinding die er niet is — precies de leugen die de statusbalk juist
    moest wegnemen.
    """
    control = besturing(
        connected=False,
        output=["Could not establish the connection: [Errno 51] Network unreachable"],
    )

    with pytest.raises(DesignError) as fout:
        control.connect()

    assert "Errno 51" in str(fout.value)


def test_a_connection_that_stays_shut_without_a_word_still_fails():
    control = besturing(connected=False)

    with pytest.raises(DesignError) as fout:
        control.connect()

    assert str(fout.value)


def test_disconnecting_wants_the_opposite_result():
    control = besturing(connected=False)

    result = control.disconnect()

    assert result["connection"]["state"] == "disconnected"
    assert control.runner.ran == ["ruida_disconnect"]

    hangt = besturing(connected=True, output=["Connection closed"])
    with pytest.raises(DesignError):
        hangt.disconnect()


def test_a_device_that_says_nothing_about_its_connection_is_taken_at_its_word():
    """
    Niet elke familie meldt een verbindingstoestand. Dan is er niets te
    controleren en is de uitvoer van de opdracht het enige dat we hebben —
    liegen over succes mag niet, maar weigeren op onwetendheid ook niet.
    """
    device = types.SimpleNamespace(spooler=None)
    kernel = types.SimpleNamespace(device=device)
    control = MachineControl(kernel, FakeRunner(["USB Connected."]))

    result = control.connect()

    assert result["connection"]["state"] == "unknown"
    assert result["output"] == ["USB Connected."]


def test_the_echo_of_the_command_is_not_offered_as_a_reason():
    """
    Gemeten op de echte KH-5030 met een adres waar niets staat: de UDP-sessie
    meldt niets en het console-kanaal bevat alleen zijn eigen echo. "De engine
    meldt: [11:51:29] ruida_connect" is geen reden; dan hoort er de vraag te
    staan die iemand verder helpt.
    """
    control = besturing(connected=False, output=["[11:51:29] ruida_connect"])

    with pytest.raises(DesignError) as fout:
        control.connect()

    bericht = str(fout.value)
    assert "ruida_connect" not in bericht
    assert "adres" in bericht
    # De tweede oorzaak staat er ook, want die is even waarschijnlijk en je
    # zoekt hem nooit zelf: gemeten op de echte machine gaat verbinden stuk
    # zodra je in dezelfde sessie van machine gewisseld hebt.
    assert "gewisseld" in bericht


def test_a_real_complaint_does_reach_the_user():
    control = besturing(
        connected=False,
        output=["[11:51:29] ruida_connect", "Could not establish the connection: [Errno 51]"],
    )

    with pytest.raises(DesignError) as fout:
        control.connect()

    assert "Errno 51" in str(fout.value)
    assert "ruida_connect" not in str(fout.value)


# ---------------------------------------------------------------- routes


def test_the_routes_exist_and_report_what_the_device_can_do(client, kernel):
    caps = client.get("/api/capabilities").json()
    assert caps["connection"] == {"connect": False, "disconnect": False}

    # Zonder opdracht op dit apparaat: een nette weigering, geen 500.
    antwoord = client.post("/api/machine/connect")
    assert antwoord.status_code == 409, antwoord.text
    assert antwoord.json()["detail"]

    kernel.console("service device start ruida -i\n")
    caps = client.get("/api/capabilities").json()
    assert caps["connection"] == {"connect": True, "disconnect": True}
