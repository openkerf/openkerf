"""
A camera image of the bed.

There is no real camera in this environment (macOS gives a terminal process no
permission), so the tests use a video file as their source. OpenCV opens that by
the same road as a real camera, so the whole chain — starting the service,
fetching a frame, calibrating, correcting — *is* walked.
"""

import time

import platform

import numpy as np
import pytest
from fastapi.testclient import TestClient

from openkerf_api.camera import Camera
from openkerf_api.commands import CommandRunner
from openkerf_api.edits import DesignError
from openkerf_api.server import ApiServer

cv2 = pytest.importorskip("cv2")

# The corners of the "bed" in the fake image, photographed at an angle.
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
    # Never leave a read thread behind: it keeps the device occupied and the
    # test run open.
    device.stop()


@pytest.fixture
def client(kernel, tmp_path):
    server = ApiServer(kernel, library_path=tmp_path / "c.db")
    with TestClient(server.build_app()) as c:
        c.server = server
        yield c
    server.camera.stop()


def test_the_plugin_is_available(camera):
    """Without OpenCV the camera plugin withdraws itself; then this is False."""
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
    with pytest.raises(DesignError, match="no camera image"):
        camera.frame_png()


def test_a_camera_that_does_not_exist_is_reported_not_hung(camera):
    """Better a clean message than a window that keeps spinning on black."""
    with pytest.raises(DesignError, match="No image"):
        camera.start(uri="/does/not/exist.mp4")


def test_calibration_changes_the_picture(camera, source):
    """
    Pulling the four corners into a rectangle is the whole trick: only then does
    the image lie on the bed and only then is where you put your design right.
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
        pytest.fail("the image did not change after calibrating")


def test_three_corners_is_not_a_bed(camera, source):
    camera.start(uri=source)

    with pytest.raises(DesignError, match="four corners"):
        camera.calibrate(CORNERS[:3])


def test_corners_on_top_of_each_other_are_refused(camera, source):
    camera.start(uri=source)

    with pytest.raises(DesignError, match="on top of each other"):
        camera.calibrate([[10, 10], [10, 10], [100, 100], [0, 100]])


def test_calibration_can_be_reset(camera, source):
    camera.start(uri=source)
    camera.calibrate(CORNERS)

    state = camera.reset_calibration()

    assert state["corrected"] is False


def test_the_raw_picture_can_be_shown_while_calibrating(camera, source):
    """You point out corners in the raw image, not in the corrected one."""
    camera.start(uri=source)
    camera.calibrate(CORNERS)

    assert camera.set_corrected(False)["corrected"] is False
    assert camera.set_corrected(True)["corrected"] is True


def test_the_camera_closes_when_nobody_is_watching(camera, source, monkeypatch):
    import openkerf_api.camera as module

    monkeypatch.setattr(module, "LINGER", 0.0)
    camera.start(uri=source)
    with camera.viewer():
        assert camera.reap() is False, "somebody is still watching"

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
    assert b"\xff\xd8" in part  # start of a JPEG
    assert index is not None


def test_the_same_frame_is_not_sent_twice(camera, source):
    """Sending the same image again costs bandwidth and gives nothing."""
    camera.start(uri=source)

    _, index = camera.next_part(None)
    again, _ = camera.next_part(index)

    assert again is None


# Whether a browser clicking away really counts cannot be tested here: Starlette's
# TestClient does not play back a broken connection, so `request.is_disconnected()`
# never becomes true. That was checked with a running server and curl — see the PR.
# What *is* pinned down here is that the counter runs back down as soon as the
# viewer is gone (the test above), because that was the bug.


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


def test_the_failure_says_what_to_do_about_it(camera, monkeypatch):
    """
    "There is no image" helps nobody. The difference between "there is no camera
    attached" and "this program is not allowed near the camera" entirely decides
    what you have to do about it.
    """
    monkeypatch.setattr(camera, "detected", lambda: [])
    without_one = camera._why_no_picture("0")

    monkeypatch.setattr(camera, "detected", lambda: ["MacBook Pro camera"])
    with_one = camera._why_no_picture("0")

    assert "no camera at all" in without_one
    assert "MacBook Pro camera" in with_one
    assert without_one != with_one
    if platform.system() == "Darwin":
        # There is no + button under Camera in System Settings, so "tick your
        # terminal" is dead-end advice. The command that provokes the dialog
        # belongs with it.
        assert "cv2.VideoCapture(0)" in with_one


def test_opencvs_broken_permission_request_is_skipped():
    """
    On macOS OpenCV asks for permission itself, but that can only be done from the
    main thread — and the engine opens the camera in a worker thread. Without this
    flag the request fails and no dialog ever appears.
    """
    import os

    assert os.environ.get("OPENCV_AVFOUNDATION_SKIP_AUTH") == "1"


def test_the_state_says_which_cameras_the_machine_sees(client):
    assert isinstance(client.get("/api/camera").json().get("detected", []), list)
