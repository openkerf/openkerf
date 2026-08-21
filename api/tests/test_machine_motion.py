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
    The capabilities belong to the device, not to the app. Focusing is the proof
    of that: the Ruida knows `focusz`, the K40 board does not.
    """
    before = motion.capabilities()
    assert before["focus"] is False

    kernel.console("service device start ruida -i\n")
    after = motion.capabilities()

    # Movement stays, because the kernel provides it.
    for shared in ("home", "jog", "move", "unlock"):
        assert after[shared] == before[shared]
    assert after["focus"] is True, "the Ruida does know focusing"


def test_home_runs(kernel, motion):
    result = motion.home()

    assert "output" in result


def test_a_jog_of_nothing_is_refused(motion):
    """Nothing to do, and worth saying so rather than sending it on."""
    with pytest.raises(DesignError):
        motion.jog(0, 0)


def test_jog_validates_its_numbers(motion):
    for bad in ("left", None, float("inf")):
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
    response = client.post("/api/machine/jog", json={"dx_mm": "left", "dy_mm": 0})
    assert response.status_code == 409


def test_moving_is_refused_while_a_job_is_running(kernel, motion):
    """
    The UI turns the jog buttons off during a job, but the UI is advice: a second
    tab or a curl command gets past it easily. Moving the head while burning
    ruins the job.
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
        with pytest.raises(DesignError, match="A job is running"):
            call()


def test_focus_is_only_offered_when_the_device_knows_it(motion):
    """
    Focusing lives on the Ruida, not on every device. The same approach as for
    pausing and stopping: ask what this device knows instead of assuming.
    """
    caps = motion.capabilities()

    assert "focus" in caps
    # The test device does not know it, so it is not offered either.
    if not caps["focus"]:
        with pytest.raises(DesignError, match="focusz"):
            motion.focus(2)


def test_the_frame_traces_the_work(client):
    """
    Showing the frame is the last check before you burn: does it fit, is it
    square, is the clamp in the way. The laser stays off — only movement happens.
    """
    client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 20, "y_mm": 30, "width_mm": 60, "height_mm": 40},
    )

    response = client.post("/api/machine/frame")

    assert response.status_code == 200
    # Four corners plus back to the start, so you see the round close.
    assert response.json()["corners"] == 5


def test_every_corner_of_the_frame_is_queued_and_not_refused(client):
    """
    Measured on a real machine: the head went to the first corner and the other
    four got "Busy Error".

    `move_absolute` refuses as soon as the spooler is not standing still
    (`core/spoolers.py:243`) — and after the first corner the head is of course on
    its way. With `-f` the command goes into the queue instead of being refused,
    and that is exactly what you want: five movements that follow each other.
    Without a job around it there is nothing to push in front of; that no job is
    running has already been checked.
    """
    client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 20, "y_mm": 30, "width_mm": 60, "height_mm": 40},
    )

    response = client.post("/api/machine/frame")

    assert response.status_code == 200
    lines = response.json()["output"]
    commands = [r for r in lines if "move_absolute" in r]
    assert len(commands) == 5
    assert all("-f" in r for r in commands), lines
    assert not any("busy" in r.lower() for r in lines), lines
    assert response.json()["notice"] is None


def test_an_empty_bed_has_nothing_to_frame(client):
    client.post("/api/design/clear")

    response = client.post("/api/machine/frame")

    assert response.status_code == 409
    assert "nothing" in response.json()["detail"].lower()
