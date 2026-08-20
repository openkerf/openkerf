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


def test_the_frame_traces_the_work(client):
    """
    Kader tonen is de laatste controle vóór je brandt: past het, ligt het recht,
    zit de klem in de weg. De laser blijft uit — er wordt alleen bewogen.
    """
    client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 20, "y_mm": 30, "width_mm": 60, "height_mm": 40},
    )

    response = client.post("/api/machine/frame")

    assert response.status_code == 200
    # Vier hoeken plus terug naar het begin, zodat je de ronde ziet sluiten.
    assert response.json()["corners"] == 5


def test_every_corner_of_the_frame_is_queued_and_not_refused(client):
    """
    Gemeten op een echte machine: de kop ging naar de eerste hoek en de andere
    vier kregen "Busy Error".

    `move_absolute` weigert zodra de spooler niet stilstaat
    (`core/spoolers.py:243`) — en na de eerste hoek is de kop natuurlijk
    onderweg. Met `-f` gaat de opdracht in de wachtrij in plaats van geweigerd
    te worden, en dat is precies wat je wil: vijf bewegingen die op elkaar
    volgen. Zonder job eromheen is er niets om voor te dringen; dat er geen job
    loopt, is al gecontroleerd.
    """
    client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 20, "y_mm": 30, "width_mm": 60, "height_mm": 40},
    )

    response = client.post("/api/machine/frame")

    assert response.status_code == 200
    regels = response.json()["output"]
    opdrachten = [r for r in regels if "move_absolute" in r]
    assert len(opdrachten) == 5
    assert all("-f" in r for r in opdrachten), regels
    assert not any("busy" in r.lower() for r in regels), regels
    assert response.json()["notice"] is None


def test_an_empty_bed_has_nothing_to_frame(client):
    client.post("/api/design/clear")

    response = client.post("/api/machine/frame")

    assert response.status_code == 409
    assert "niets" in response.json()["detail"].lower()
