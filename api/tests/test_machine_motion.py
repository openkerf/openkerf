"""Moving the machine: home, jog, unlock."""

import pytest
from fastapi.testclient import TestClient

from openkerf_api.edits import DesignError
from openkerf_api.machine import MachineControl
from openkerf_api.server import ApiServer


@pytest.fixture
def client(kernel, tmp_path):
    with TestClient(ApiServer(kernel, library_path=tmp_path / "m.db").build_app()) as c:
        yield c


@pytest.fixture
def motion(kernel):
    return MachineControl(kernel)


def test_motion_commands_are_kernel_level(kernel, motion):
    """
    Unlike pause and estop, movement is registered by core/spoolers.py on the
    kernel, not by the device service — so it exists whatever is selected. It
    still goes through the active device's spooler, so a dummy device simply
    does nothing with it.
    """
    caps = motion.capabilities()

    assert caps["home"] is True
    assert caps["jog"] is True
    assert caps["unlock"] is True


def test_capability_reporting_follows_the_device(kernel, motion):
    """
    De mogelijkheden horen bij het apparaat, niet bij de app. Scherpstellen is
    daar het bewijs van: de Ruida kent `focusz`, het K40-bord niet.
    """
    before = motion.capabilities()
    assert before["focus"] is False

    kernel.console("service device start ruida -i\n")
    after = motion.capabilities()

    # Bewegen blijft bestaan, want dat levert de kernel.
    for shared in ("home", "jog", "move", "unlock"):
        assert after[shared] == before[shared]
    assert after["focus"] is True, "de Ruida kent scherpstellen wel"


def test_home_runs(kernel, motion):
    result = motion.home()

    assert "output" in result


def test_a_jog_of_nothing_is_refused(motion):
    """Nothing to do, and worth saying so rather than sending it on."""
    with pytest.raises(DesignError):
        motion.jog(0, 0)


def test_jog_validates_its_numbers(motion):
    for bad in ("links", None, float("inf")):
        with pytest.raises(DesignError):
            motion.jog(bad, 0)


def test_motion_capabilities_over_http(kernel, client):
    body = client.get("/api/capabilities").json()

    assert "motion" in body
    assert set(body["motion"]) >= {"home", "jog", "move", "unlock"}


def test_motion_over_http(client):
    assert client.post("/api/machine/home", json={}).status_code == 200
    assert client.post("/api/machine/jog", json={"dx_mm": 1, "dy_mm": 0}).status_code == 200


def test_a_nonsense_jog_over_http_is_a_409(client):
    response = client.post("/api/machine/jog", json={"dx_mm": "links", "dy_mm": 0})
    assert response.status_code == 409


def test_moving_is_refused_while_a_job_is_running(kernel, motion):
    """
    De UI zet de jogknoppen uit tijdens een job, maar de UI is een advies: een
    tweede tabblad of een curl-opdracht komt er zo langs. De kop verzetten
    tijdens het branden verpest de job.
    """

    class RunningJob:
        def is_running(self):
            return True

    class Busy:
        is_idle = False
        queue = [RunningJob()]

    kernel.device.spooler = Busy()

    for call in (
        lambda: motion.jog(5, 0),
        lambda: motion.home(),
        lambda: motion.move_to(10, 10),
    ):
        with pytest.raises(DesignError, match="loopt een job"):
            call()


def test_focus_is_only_offered_when_the_device_knows_it(motion):
    """
    Scherpstellen zit op de Ruida, niet op elk apparaat. Zelfde aanpak als bij
    pauzeren en stoppen: vragen wat dit apparaat kent in plaats van aannemen.
    """
    caps = motion.capabilities()

    assert "focus" in caps
    # Het testapparaat kent het niet, dus dan wordt het ook niet aangeboden.
    if not caps["focus"]:
        with pytest.raises(DesignError, match="focusz"):
            motion.focus(2)
