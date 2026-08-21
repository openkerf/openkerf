"""
Automatic saving, with recovery after a crash or a closed tab.

xTool Studio saves nothing automatically and warns about that itself. That is exactly the
kind of work you lose while standing waiting for the laser, so here we do.

Two choices that make it usable:

- **Saving happens with a delay.** Every change to the element tree sends a signal; while
  dragging a shape that is dozens per second. So at most one per `INTERVAL` goes to disk.
- **The recovery file is never silently reloaded.** The app asks; somebody who wants to start
  with an empty canvas has to be able to.
"""

from __future__ import annotations

import time
from pathlib import Path

INTERVAL = 20.0


class Autosave:
    def __init__(self, kernel, drawing, document, path: Path | str):
        self.kernel = kernel
        self.drawing = drawing
        self.document = document
        self.path = Path(path)
        self._last = 0.0
        # Did a change come in while the brake was on? Then there is work in the tree that
        # does not come back anywhere on disk yet.
        self._wachtend = False

    def touch(self) -> bool:
        """
        Called on every change. Saves at most once per interval.

        Hands back whether anything was actually written — handy in tests, and it makes the
        brake visible.
        """
        if not any(True for _ in self.kernel.elements.elems()):
            # An empty design produces nothing to save (see `save`), so it must not use the
            # brake up either. It did: clearing sends a tree signal, that set the clock, and
            # `save` then wrote nothing. Measured: clear the design, immediately draw four
            # shapes
            # — no recovery file, until twenty seconds later another change happened to
            # come along. "New design" is precisely the moment you start drawing after.
            return False
        now = time.monotonic()
        if now - self._last < INTERVAL:
            # Not now, but it must not be left lying either: `flush` picks it up.
            self._wachtend = True
            return False
        self._last = now
        self._wachtend = False
        return self.save()

    def flush(self, *args) -> bool:
        """
        The tail: the last change before you go and stand at the machine.

        `touch` writes the first change straight away and then brakes. Anybody who draws
        another three shapes in those twenty seconds and then stops never got a write for
        those three — no further signal comes, after all. Measured: three shapes in three
        seconds, server killed hard, and the
        herstelbestand bevatte er één.

        Runs as a kernel job, so on the same thread as the tree signals. That is not a
        detail: a timer thread of its own would read the element tree while the kernel is
        moving it.
        """
        if not self._wachtend:
            return False
        if time.monotonic() - self._last < INTERVAL:
            return False
        self._last = time.monotonic()
        self._wachtend = False
        return self.save()

    def save(self) -> bool:
        if not any(True for _ in self.kernel.elements.elems()):
            # Saving an empty design would overwrite a good recovery file at the moment
            # somebody chooses "new".
            return False
        # `save` sets `elements.basename` to the file name, and that name then comes back as
        # the job name in the spooler — every job was called "herstel.svg", even on a fresh
        # design where nothing had been recovered. Two jobs with the same name cannot be told
        # apart at a laser, so we put the name back as it was.
        # `basename` is a property without a setter; it derives from `_filename`, and that is
        # what `save` sets.
        elements = self.kernel.elements
        bestand_voor = getattr(elements, "_filename", None)
        try:
            written = self.drawing.export_svg("herstel.svg")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_bytes(written.read_bytes())
            return True
        except Exception:
            # Automatisch bewaren mag nooit een bewerking laten mislukken.
            return False
        finally:
            try:
                elements._filename = bestand_voor
            except Exception:
                pass

    def state(self) -> dict:
        if not self.path.is_file():
            return {"exists": False, "when": None, "age_seconds": None}
        stamp = self.path.stat().st_mtime
        return {
            "exists": True,
            "when": time.strftime("%Y-%m-%d %H:%M", time.localtime(stamp)),
            "age_seconds": max(0, int(time.time() - stamp)),
        }

    def forget_if_saved(self) -> bool:
        """
        Cleaning up the safety net when nothing can fall into it any more.

        Otherwise the recovery file stays for ever, and the "Work from a previous session"
        dialog then comes past on *every* start of a new design. Measured: draw, press Export,
        start something new — and the next load asks whether you want to restore that
        just-exported drawing. That is not a previous session and there is nothing to recover;
        it is a dialog you learn to click away, and that is exactly what you do not want on
        the day there *is* something to recover.

        `document.dirty` is the right question here and not "has the user saved": it is False
        as soon as the design is identical to a file — after exporting, after opening, after a
        project file. If it is True there is unsecured work and the safety net stays, even
        when the user empties the canvas.

        Geeft terug of er werkelijk iets weggehaald is.
        """
        if self.document.dirty:
            return False
        bestond = self.path.is_file()
        self.discard()
        return bestond

    def _open_de_rem(self) -> None:
        """
        Releasing the brake, so that the very next change is saved straight away.

        The brake measures from the last write, and that holds as long as a recovery file is
        there. After discarding or restoring, something else is there
        op schijf dan wat de rem denkt, en dan is wachten fout. Gemeten vóór
        deze regel: herstelbestand weggooien, daarna vier vormen tekenen en
        dertig seconden wachten — en er stond nog steeds geen herstelbestand.
        Wie in het openingsvenster voor "leeg beginnen" kiest, werkte dus een
        hele sessie zonder vangnet.
        """
        self._last = 0.0
        self._wachtend = False

    def restore(self) -> dict:
        """Load the recovery file back, over an empty canvas."""
        from .edits import DesignError

        if not self.path.is_file():
            raise DesignError("There is no automatically saved design.")
        self.drawing.runner.run(f'load "{self.path}"')
        self.kernel.elements.validate_ids()
        self.kernel.elements.signal("rebuild_tree", "all")
        # Herstellen is geen opslaan: het werk staat nog steeds nergens waar de
        # gebruiker het zelf kan terugvinden.
        self.document.touch()
        self._open_de_rem()
        return {"restored": True, **self.state()}

    def discard(self) -> dict:
        self.path.unlink(missing_ok=True)
        self._open_de_rem()
        return {"exists": False}
