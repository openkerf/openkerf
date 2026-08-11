"""
Camerabeeld van het bed, als achtergrond onder het ontwerp.

Bovenop MeerK40t's eigen cameraplugin (`meerk40t/camera/`), niet ernaast: die
doet het lastige werk al — een eigen leesthread, fisheye-correctie met een
schaakbordpatroon, en een perspectiefcorrectie die vier hoekpunten naar een
rechthoek trekt. Wij leveren alleen wat de browser nodig heeft.

Drie keuzes die het soepel maken:

1. **MJPEG in plaats van pollen.** De browser krijgt één antwoord dat blijft
   doorlopen (`multipart/x-mixed-replace`) en decodeert dat zelf. Geen
   JavaScript-lus die elke 200 ms een plaatje ophaalt, geen haperende
   verversing, en het beeld stopt vanzelf als het tabblad dichtgaat.
2. **De plugin doet de perspectiefcorrectie, wij niet.** Het gecorrigeerde
   beeld ís de bedrechthoek, dus de frontend kan het één-op-één over het bed
   leggen zonder zelf te rekenen.
3. **De camera draait alleen als er iemand kijkt.** Een leesthread die uren
   doorloopt terwijl niemand het beeld ziet, kost stroom en houdt het apparaat
   bezet voor andere programma's.
"""

from __future__ import annotations

import threading
import time

from .edits import DesignError

# Zonder deze twee is er geen camera; dat is een nette melding waard en geen
# stacktrace. OpenCV zit niet in de standaardinstallatie van MeerK40t.
IMPORT_HINT = (
    "Camerabeeld vraagt OpenCV. Installeer het naast de engine met "
    "'pip install opencv-python-headless'."
)

# Zo lang blijft de camera nog draaien nadat de laatste kijker weg is. Kort
# genoeg om niet te blijven hangen, lang genoeg om een pagina te verversen
# zonder dat de camera opnieuw hoeft op te starten (dat kost seconden).
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
        """Of er überhaupt een camera te openen valt."""
        try:
            import cv2  # noqa: F401
        except ImportError:
            return False
        # De plugin registreert dit pas als cv2 én numpy er zijn; hij trekt
        # zichzelf anders bij "invalidate" helemaal terug. Dat is een
        # betrouwbaarder teken dan zoeken naar het commando, dat met een regex
        # geregistreerd staat.
        return self.kernel.lookup("camera-enabled") is not None

    def service(self, start: bool = False):
        camera = getattr(self.kernel, "camera", None)
        if camera is None and start:
            # `camera0` maakt de service aan én activeert hem; zonder cijfer
            # pakt het commando alleen de bestaande.
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
            "perspective": [list(map(float, point)) for point in camera.perspective or []],
            "corrected": bool(camera.correction_perspective),
            "frame": self._size(camera),
        }

    def cameras(self) -> list[dict]:
        """De camera's die de engine kent, plus hun omschrijving."""
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
            raise DesignError("De cameraservice liet zich niet starten.")
        if uri is not None and str(uri).strip():
            camera.set_uri(str(uri).strip())
        camera.open_camera()
        # De leesthread heeft even nodig om het apparaat te openen; zonder deze
        # wachtlus levert het eerste verzoek een leeg beeld op en lijkt het stuk.
        deadline = time.monotonic() + 6.0
        while time.monotonic() < deadline and camera.get_display_frame() is None:
            time.sleep(0.1)
        if camera.get_display_frame() is None:
            raise DesignError(
                f"Geen beeld van camera '{camera.uri}'. Staat hij aan, en heeft dit "
                "programma toestemming om de camera te gebruiken?"
            )
        self._idle_since = None
        return self.state()

    def stop(self) -> dict:
        camera = self.service()
        if camera is not None:
            camera.close_camera()
        self._viewers = 0
        self._idle_since = None
        return self.state()

    # ---------------------------------------------------------------- beeld

    def frame_png(self) -> bytes:
        """Eén beeld, voor een stilstaande weergave of om op te meten."""
        frame = self._frame()
        return self._encode(frame, "png")

    def viewer(self):
        """Telt zolang er iemand kijkt; de camera sluit pas als de teller nul is."""
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
        Het volgende MJPEG-deel, of None als er nog geen nieuw beeld is.

        Blokkeert niet: de aanroeper bepaalt hoe lang hij wacht. Dat is wat het
        mogelijk maakt om tussendoor te kijken of de browser nog luistert —
        zonder die controle blijft de camera draaien voor een kijker die er
        allang niet meer is.
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
        De camera sluiten als er al even niemand kijkt.

        Wordt vanuit de statuslus aangeroepen. Een leesthread die uren
        doorloopt terwijl niemand kijkt, kost stroom en houdt het apparaat
        bezet voor andere programma's.
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

        Volgorde is linksboven, rechtsboven, rechtsonder, linksonder — dezelfde
        als de plugin gebruikt, want die trekt ze in die volgorde naar een
        rechthoek. Door elkaar gooien geeft een gespiegeld of gedraaid beeld.
        """
        camera = self.service()
        if camera is None:
            raise DesignError("Er draait geen camera om te ijken.")
        cleaned = []
        for point in points or []:
            if not isinstance(point, (list, tuple)) or len(point) != 2:
                raise DesignError("Elk hoekpunt is [x, y] in beeldpixels.")
            cleaned.append([float(point[0]), float(point[1])])
        if len(cleaned) != 4:
            raise DesignError("Een bed heeft vier hoeken; geef er precies vier.")
        if len({tuple(p) for p in cleaned}) != 4:
            raise DesignError("Twee hoeken liggen op elkaar.")

        camera.perspective = cleaned
        camera.correction_perspective = True if corrected is None else bool(corrected)
        return self.state()

    def reset_calibration(self) -> dict:
        camera = self.service()
        if camera is None:
            raise DesignError("Er draait geen camera.")
        camera.reset_perspective()
        camera.correction_perspective = False
        return self.state()

    def set_corrected(self, corrected: bool) -> dict:
        """Tijdens het ijken wil je juist het ónbewerkte beeld zien."""
        camera = self.service()
        if camera is None:
            raise DesignError("Er draait geen camera.")
        camera.correction_perspective = bool(corrected)
        return self.state()

    # --------------------------------------------------------------- intern

    def _frame(self):
        camera = self.service()
        frame = None if camera is None else camera.get_display_frame()
        if frame is None:
            raise DesignError("Er is geen camerabeeld; start de camera eerst.")
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

        # De plugin levert RGB; PIL verwacht dat ook, dus geen omzetting.
        buffer = io.BytesIO()
        Image.fromarray(frame).convert("RGB").save(
            buffer, "JPEG" if kind == "jpeg" else "PNG", quality=80
        )
        return buffer.getvalue()
