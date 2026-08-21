"""
Connecting and disconnecting.

The status bar could already read whether a machine was on the line, but there
was no way to do anything about it: "not connected" and no button. The engine does
have the commands, but every driver calls them something else (`ruida_connect` on
Ruida, `usb_connect` on lihuiyu/moshi/newly/balor) and they are `hidden=True`, so
we ask the active device what it knows instead of assuming it.
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
    """Says yes to every command and hands back the lines the engine would give."""

    def __init__(self, output=()):
        self.output = list(output)
        self.ran: list[str] = []

    def supports(self, name, input_type="None"):
        return True

    def run(self, command):
        self.ran.append(command)
        return list(self.output)


def control_for(connected, output=()) -> MachineControl:
    """A MachineControl around a made-up device, without a socket."""
    device = types.SimpleNamespace(connected=connected, spooler=None)
    kernel = types.SimpleNamespace(device=device)
    return MachineControl(kernel, FakeRunner(output))


# ---------------------------------------------------- what a device knows about


def test_a_device_without_a_connect_command_does_not_get_a_button(kernel):
    """The dummy device knows no connect command; then there should be no button."""
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

    with pytest.raises(DesignError) as error:
        control.connect()

    assert "connect" in str(error.value).lower()


# ------------------------------------------------------------- the outcome


def test_connecting_reports_the_state_the_machine_ended_up_in():
    control = control_for(connected=True)

    result = control.connect()

    assert result["connection"]["state"] == "connected"
    assert control.runner.ran == ["ruida_connect"]


def test_a_refused_connection_is_an_error_with_the_engines_own_words():
    """
    `ruida_connect` swallows its own error and writes it to a channel
    (`ruida/device.py:452`). Without this rule the button hands back HTTP 200 on a
    connection that is not there — exactly the lie the status bar was meant to take
    away.
    """
    control = control_for(
        connected=False,
        output=["Could not establish the connection: [Errno 51] Network unreachable"],
    )

    with pytest.raises(DesignError) as error:
        control.connect()

    assert "Errno 51" in str(error.value)


def test_a_connection_that_stays_shut_without_a_word_still_fails():
    control = control_for(connected=False)

    with pytest.raises(DesignError) as error:
        control.connect()

    assert str(error.value)


def test_disconnecting_wants_the_opposite_result():
    control = control_for(connected=False)

    result = control.disconnect()

    assert result["connection"]["state"] == "disconnected"
    assert control.runner.ran == ["ruida_disconnect"]

    hanging = control_for(connected=True, output=["Connection closed"])
    with pytest.raises(DesignError):
        hanging.disconnect()


def test_a_device_that_says_nothing_about_its_connection_is_taken_at_its_word():
    """
    Not every family reports a connection state. Then there is nothing to check
    and the output of the command is all we have — lying about success is not
    allowed, but refusing out of ignorance is not either.
    """
    device = types.SimpleNamespace(spooler=None)
    kernel = types.SimpleNamespace(device=device)
    control = MachineControl(kernel, FakeRunner(["USB Connected."]))

    result = control.connect()

    assert result["connection"]["state"] == "unknown"
    assert result["output"] == ["USB Connected."]


def test_the_echo_of_the_command_is_not_offered_as_a_reason():
    """
    Measured on the real KH-5030 with an address where nothing lives: the UDP
    session reports nothing and the console channel holds only its own echo. "The
    engine says: [11:51:29] ruida_connect" is not a reason; what belongs there is
    the question that gets somebody further.
    """
    control = control_for(connected=False, output=["[11:51:29] ruida_connect"])

    with pytest.raises(DesignError) as error:
        control.connect()

    message = str(error.value)
    assert "ruida_connect" not in message
    assert "address" in message
    # The second cause is there too, because it is just as likely and you never
    # look for it yourself: measured on the real machine, connecting breaks as soon
    # as you have switched machines in the same session.
    assert "switched" in message


def test_a_real_complaint_does_reach_the_user():
    control = control_for(
        connected=False,
        output=["[11:51:29] ruida_connect", "Could not establish the connection: [Errno 51]"],
    )

    with pytest.raises(DesignError) as error:
        control.connect()

    assert "Errno 51" in str(error.value)
    assert "ruida_connect" not in str(error.value)


# ---------------------------------------------------------------- routes


def test_the_routes_exist_and_report_what_the_device_can_do(client, kernel):
    caps = client.get("/api/capabilities").json()
    assert caps["connection"] == {"connect": False, "disconnect": False}

    # Without a command on this device: a clean refusal, no 500.
    answer = client.post("/api/machine/connect")
    assert answer.status_code == 409, answer.text
    assert answer.json()["detail"]

    kernel.console("service device start ruida -i\n")
    caps = client.get("/api/capabilities").json()
    assert caps["connection"] == {"connect": True, "disconnect": True}
