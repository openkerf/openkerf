"""
The camera image of the bed, as a background under the design.

On top of MeerK40t's own camera plugin (`meerk40t/camera/`), not beside it: that already
does the hard work — a read thread of its own, fisheye correction with a chequerboard
pattern, and a perspective correction that pulls four corner points into a rectangle. We
only supply what the browser needs.

Three choices that make it smooth:

1. **MJPEG instead of polling.** The browser gets one answer that keeps running
   (`multipart/x-mixed-replace`) and decodes it itself. No JavaScript loop fetching an image
   every 200 ms, no stuttering refresh, and the image stops by itself when the tab closes.
2. **The plugin does the perspective correction, we do not.** The corrected image *is* the
   bed rectangle, so the frontend can lay it over the bed one to one without computing
   anything itself.
3. **The camera only runs while somebody is watching.** A read thread that runs on for hours
   while nobody sees the image costs power and keeps the device
   bezet voor andere programma's.
"""

from __future__ import annotations

import os
import platform
import subprocess
import threading
import time

# On macOS OpenCV asks for camera permission itself, but that is only possible from the main
# thread — and the engine opens the camera in a worker thread. The request then fails with
# "can not spin main run loop from other thread" and no dialog ever appears. This flag skips
# that request; the permission itself then has to be arranged already, and that is exactly
# what we explain in the error message.
os.environ.setdefault("OPENCV_AVFOUNDATION_SKIP_AUTH", "1")

from .edits import DesignError

# Without these two there is no camera; that deserves a decent message and not a
# stacktrace. OpenCV is not in MeerK40t's standard installation.
IMPORT_HINT = (
    "A camera image needs OpenCV. Install it beside the engine with "
    "'pip install opencv-python-headless'."
)

# This long the camera keeps running after the last viewer has gone. Short enough not to
# hang around, long enough to refresh a page without the camera having to start up again
# (which costs seconds).
LINGER = 20.0


class Camera:
    def __init__(self, kernel, runner):
        self.kernel = kernel
        self.runner = runner
        self._viewers = 0
        self._idle_since = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------ toestand

    @property
    def available(self) -> bool:
        """Whether a camera can be opened at all."""
        try:
            import cv2  # noqa: F401
        except ImportError:
            return False
        # The plugin only registers this when cv2 *and* numpy are there; otherwise it
        # withdraws itself entirely at "invalidate". That is a more reliable sign than looking
        # for the command, which is registered with a regex.
        return self.kernel.lookup("camera-enabled") is not None

    def service(self, start: bool = False):
        camera = getattr(self.kernel, "camera", None)
        if camera is None and start:
            # `camera0` creates the service *and* activates it; without a digit the command
            # only takes the existing one.
            self.runner.run("camera0")
            camera = getattr(self.kernel, "camera", None)
        return camera

    def state(self) -> dict:
        if not self.available:
            return {"available": False, "reason": IMPORT_HINT, "running": False}
        camera = self.service()
        if camera is None:
            return {"available": True, "running": False, "uri": None, "calibrated": False}
        return {
            "available": True,
            "running": camera.camera_thread is not None and not camera.quit_thread,
            "uri": str(camera.uri),
            "viewers": self._viewers,
            "calibrated": bool(camera.perspective),
            "detected": self.detected(),
            "perspective": [list(map(float, point)) for point in camera.perspective or []],
            "corrected": bool(camera.correction_perspective),
            "frame": self._size(camera),
        }

    def cameras(self) -> list[dict]:
        """The cameras the engine knows, plus what the device itself sees."""
        if not self.available:
            raise DesignError(IMPORT_HINT)
        found = []
        for path in self.kernel.section_startswith("camera/"):
            found.append(
                {
                    "path": path,
                    "uri": self.kernel.read_persistent(str, path, "uri", path[7:]),
                    "label": self.kernel.read_persistent(str, path, "desc", ""),
                }
            )
        return found

    # ------------------------------------------------------------- bedienen

    def start(self, uri=None) -> dict:
        if not self.available:
            raise DesignError(IMPORT_HINT)
        camera = self.service(start=True)
        if camera is None:
            raise DesignError("The camera service would not start.")
        if uri is not None and str(uri).strip():
            camera.set_uri(str(uri).strip())
        camera.open_camera()
        # The read thread needs a moment to open the device; without this wait loop the
        # first request produces an empty image and it looks broken.
        deadline = time.monotonic() + 6.0
        while time.monotonic() < deadline and camera.get_display_frame() is None:
            time.sleep(0.1)
        if camera.get_display_frame() is None:
            raise DesignError(self._why_no_picture(camera.uri))
        self._idle_since = None
        return self.state()

    def _why_no_picture(self, uri) -> str:
        """
        Een bruikbare uitleg in plaats van "there is no image".

        The difference between "there is no camera attached" and "this program is not
        allowed near the camera" entirely decides what you have to do about it, and that
        difference we can look up.
        """
        found = self.detected()
        base = f"No image from camera '{uri}'."
        if not found:
            return (
                f"{base} This device sees no camera at all. Is it plugged in "
                "en aan?"
            )
        names = ", ".join(found)
        if platform.system() == "Darwin":
            # Bij Camera in Systeeminstellingen zit géén +-knop: alleen
            # programs that ever asked for permission appear in that list. Our engine
            # cannot ask (the request has to come from the main thread), so the user has to
            # provoke it once themselves.
            return (
                f"{base} There is a camera ({names}), so this is a "
                "permissions matter. macOS does not let you add a program to the "
                "camera list yourself — it has to ask for it once. "
                "So run in your own Terminal:\n\n"
                "    python3 -c \"import cv2; cv2.VideoCapture(0)\"\n\n"
                "The permission dialog then appears and your terminal ends up in "
                "System Settings › Privacy & Security › Camera. Then start the "
                "engine from that same terminal."
            )
        return (
            f"{base} There is a camera ({names}); it may be in use "
            "by another program, or the camera number may be wrong."
        )

    def detected(self) -> list[str]:
        """Which cameras this device sees itself, outside OpenCV."""
        system = platform.system()
        try:
            if system == "Darwin":
                out = subprocess.run(
                    ["system_profiler", "SPCameraDataType"],
                    capture_output=True,
                    text=True,
                    timeout=8,
                ).stdout
                return [
                    line.strip().rstrip(":")
                    for line in out.splitlines()
                    if line.strip().endswith(":") and not line.startswith("Camera")
                    and line.startswith("    ")
                ]
            if system == "Linux":
                from pathlib import Path

                return sorted(p.name for p in Path("/dev").glob("video*"))
        except Exception:
            # Working out *which* cameras exist must never block the start.
            return []
        return []

    def stop(self) -> dict:
        camera = self.service()
        if camera is not None:
            camera.close_camera()
        self._viewers = 0
        self._idle_since = None
        return self.state()

    # ---------------------------------------------------------------- beeld

    def frame_png(self) -> bytes:
        """One frame, for a still view or to measure on."""
        frame = self._frame()
        return self._encode(frame, "png")

    def viewer(self):
        """Counts as long as somebody is watching; the camera only closes at zero."""
        from contextlib import contextmanager

        @contextmanager
        def scope():
            with self._lock:
                self._viewers += 1
                self._idle_since = None
            try:
                yield
            finally:
                with self._lock:
                    self._viewers = max(0, self._viewers - 1)
                    if self._viewers == 0:
                        self._idle_since = time.monotonic()

        return scope()

    def next_part(self, last):
        """
        The next MJPEG part, or None when there is no new image yet.

        Does not block: the caller decides how long it waits. That is what makes it possible
        to check in between whether the browser is still listening — without that check the
        camera keeps running for a viewer who left long ago.
        """
        camera = self.service()
        if camera is None:
            return None, last
        frame = camera.get_display_frame()
        if frame is None:
            return None, last
        index = getattr(camera, "frame_index", None)
        if index is not None and index == last:
            return None, last
        body = self._encode(frame, "jpeg")
        part = (
            b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
            + str(len(body)).encode()
            + b"\r\n\r\n"
            + body
            + b"\r\n"
        )
        return part, index

    def reap(self) -> bool:
        """
        Closing the camera when nobody has been watching for a while.

        Called from the status loop. A read thread that runs on for hours while nobody is
        watching costs power and keeps the device busy for other programs.
        """
        if self._viewers or self._idle_since is None:
            return False
        if time.monotonic() - self._idle_since < LINGER:
            return False
        self._idle_since = None
        camera = self.service()
        if camera is None:
            return False
        camera.close_camera()
        return True

    # ------------------------------------------------------------ ijken

    def calibrate(self, points, corrected: bool | None = None) -> dict:
        """
        De vier bedhoeken in het camerabeeld vastleggen.

        The order is top left, top right, bottom right, bottom left — the same as the plugin
        uses, because it pulls them into a rectangle in that order. Shuffling them gives a
        mirrored or rotated image.
        """
        camera = self.service()
        if camera is None:
            raise DesignError("No camera is running to calibrate.")
        cleaned = []
        for point in points or []:
            if not isinstance(point, (list, tuple)) or len(point) != 2:
                raise DesignError("Elk hoekpunt is [x, y] in beeldpixels.")
            cleaned.append([float(point[0]), float(point[1])])
        if len(cleaned) != 4:
            raise DesignError("A bed has four corners; give exactly four.")
        if len({tuple(p) for p in cleaned}) != 4:
            raise DesignError("Two corners lie on top of each other.")

        camera.perspective = cleaned
        camera.correction_perspective = True if corrected is None else bool(corrected)
        return self.state()

    def reset_calibration(self) -> dict:
        camera = self.service()
        if camera is None:
            raise DesignError("No camera is running.")
        camera.reset_perspective()
        camera.correction_perspective = False
        return self.state()

    def set_corrected(self, corrected: bool) -> dict:
        """While calibrating you want to see the *unprocessed* image."""
        camera = self.service()
        if camera is None:
            raise DesignError("No camera is running.")
        camera.correction_perspective = bool(corrected)
        return self.state()

    # --------------------------------------------------------------- intern

    def _frame(self):
        camera = self.service()
        frame = None if camera is None else camera.get_display_frame()
        if frame is None:
            raise DesignError("There is no camera image; start the camera first.")
        return frame

    def _size(self, camera) -> dict | None:
        frame = camera.get_display_frame()
        if frame is None:
            return None
        height, width = frame.shape[:2]
        return {"width": int(width), "height": int(height)}

    @staticmethod
    def _encode(frame, kind: str) -> bytes:
        import io

        from PIL import Image

        # The plugin supplies RGB; PIL expects that too, so no conversion.
        buffer = io.BytesIO()
        Image.fromarray(frame).convert("RGB").save(
            buffer, "JPEG" if kind == "jpeg" else "PNG", quality=80
        )
        return buffer.getvalue()
