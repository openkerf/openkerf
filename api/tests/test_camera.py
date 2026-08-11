"""
Camerabeeld van het bed.

Er is geen echte camera in deze omgeving (macOS geeft een terminalproces geen
toestemming), dus de tests gebruiken een videobestand als bron. OpenCV opent
dat via dezelfde weg als een echte camera, dus de hele keten — service starten,
frame ophalen, ijken, corrigeren — wordt wél doorlopen.
"""

import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from openkerf_api.camera import Camera
from openkerf_api.commands import CommandRunner
from openkerf_api.edits import DesignError
from openkerf_api.server import ApiServer

cv2 = pytest.importorskip("cv2")

# De hoeken van het "bed" in het nepbeeld, scheef gefotografeerd.
CORNERS = [[80, 60], [560, 40], [600, 430], [40, 400]]


@pytest.fixture(scope="module")
def source(tmp_path_factory):
    path = tmp_path_factory.mktemp("camera") / "bed.mp4"
    frame = np.full((480, 640, 3), 40, np.uint8)
    cv2.fillPoly(frame, [np.array(CORNERS, np.int32)], (200, 200, 190))
    cv2.putText(frame, "BED", (250, 250), cv2.FONT_HERSHEY_SIMPLEX, 2, (30, 30, 30), 4)
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (640, 480)
    )
    for _ in range(40):
        writer.write(frame)
    writer.release()
    return str(path)


@pytest.fixture
def camera(kernel):
    device = Camera(kernel, CommandRunner(kernel))
    yield device
    # Nooit een leesthread laten staan: die houdt het apparaat bezet en de
    # testrun open.
    device.stop()


@pytest.fixture
def client(kernel, tmp_path):
    server = ApiServer(kernel, library_path=tmp_path / "c.db")
    with TestClient(server.build_app()) as c:
        c.server = server
        yield c
    server.camera.stop()


def test_the_plugin_is_available(camera):
    """Zonder OpenCV trekt de cameraplugin zichzelf terug; dan is dit False."""
    assert camera.available is True


def test_nothing_runs_until_asked(client):
    state = client.get("/api/camera").json()
    assert state["available"] is True
    assert state["running"] is False


def test_starting_gives_a_frame(camera, source):
    state = camera.start(uri=source)

    assert state["running"] is True
    assert state["frame"] == {"width": 640, "height": 480}
    assert camera.frame_png()[:4] == b"\x89PNG"


def test_asking_for_a_frame_before_starting_is_refused(camera):
    with pytest.raises(DesignError, match="geen camerabeeld"):
        camera.frame_png()


def test_a_camera_that_does_not_exist_is_reported_not_hung(camera):
    """Beter een nette melding dan een venster dat blijft draaien op zwart."""
    with pytest.raises(DesignError, match="Geen beeld"):
        camera.start(uri="/bestaat/niet.mp4")


def test_calibration_changes_the_picture(camera, source):
    """
    De vier hoeken naar een rechthoek trekken is de hele truc: pas daarna ligt
    het beeld op het bed en klopt waar je je ontwerp neerlegt.
    """
    camera.start(uri=source)
    before = camera.frame_png()

    state = camera.calibrate(CORNERS)

    assert state["corrected"] is True
    assert state["perspective"] == [[float(x), float(y)] for x, y in CORNERS]
    for _ in range(40):
        if camera.frame_png() != before:
            break
        time.sleep(0.1)
    else:
        pytest.fail("het beeld veranderde niet na het ijken")


def test_three_corners_is_not_a_bed(camera, source):
    camera.start(uri=source)

    with pytest.raises(DesignError, match="vier hoeken"):
        camera.calibrate(CORNERS[:3])


def test_corners_on_top_of_each_other_are_refused(camera, source):
    camera.start(uri=source)

    with pytest.raises(DesignError, match="op elkaar"):
        camera.calibrate([[10, 10], [10, 10], [100, 100], [0, 100]])


def test_calibration_can_be_reset(camera, source):
    camera.start(uri=source)
    camera.calibrate(CORNERS)

    state = camera.reset_calibration()

    assert state["corrected"] is False


def test_the_raw_picture_can_be_shown_while_calibrating(camera, source):
    """Hoeken aanwijzen doe je in het onbewerkte beeld, niet in het rechtgetrokken."""
    camera.start(uri=source)
    camera.calibrate(CORNERS)

    assert camera.set_corrected(False)["corrected"] is False
    assert camera.set_corrected(True)["corrected"] is True


def test_the_camera_closes_when_nobody_is_watching(camera, source, monkeypatch):
    import openkerf_api.camera as module

    monkeypatch.setattr(module, "LINGER", 0.0)
    camera.start(uri=source)
    with camera.viewer():
        assert camera.reap() is False, "er kijkt nog iemand"

    assert camera.reap() is True
    assert camera.state()["running"] is False


def test_a_running_camera_is_not_reaped(camera, source):
    camera.start(uri=source)

    assert camera.reap() is False
    assert camera.state()["running"] is True


def test_the_stream_serves_jpeg_parts(camera, source):
    camera.start(uri=source)

    part, index = camera.next_part(None)

    assert b"image/jpeg" in part
    assert b"\xff\xd8" in part  # JPEG-begin
    assert index is not None


def test_the_same_frame_is_not_sent_twice(camera, source):
    """Hetzelfde beeld nog eens versturen kost bandbreedte en levert niets op."""
    camera.start(uri=source)

    _, index = camera.next_part(None)
    again, _ = camera.next_part(index)

    assert again is None


# Of een wegklikkende browser echt meetelt, is hier niet te testen: de
# TestClient van Starlette speelt geen verbroken verbinding na, dus
# `request.is_disconnected()` wordt nooit waar. Dat is met een draaiende server
# en curl nagelopen — zie de PR. Wat hier wél vastligt, is dat de teller
# terugloopt zodra de kijker weg is (test hierboven), want dat was de fout.


def test_the_routes_work_end_to_end(client, source):
    assert client.post("/api/camera/start", json={"uri": source}).status_code == 200

    frame = client.get("/api/camera/frame.png")
    assert frame.status_code == 200
    assert frame.headers["cache-control"] == "no-store"
    assert frame.content[:4] == b"\x89PNG"

    assert client.post("/api/camera/calibrate", json={"points": CORNERS}).status_code == 200
    assert client.get("/api/camera").json()["calibrated"] is True
    assert client.delete("/api/camera/calibrate").json()["corrected"] is False
    assert client.post("/api/camera/stop").json()["running"] is False


def test_a_frame_without_a_camera_is_a_409(client):
    assert client.get("/api/camera/frame.png").status_code == 409
