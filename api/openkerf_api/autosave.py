"""
Automatisch bewaren, met herstel na een crash of een gesloten tabblad.

xTool Studio slaat niets automatisch op en waarschuwt daar zelf voor. Dat is
precies het soort werk dat je kwijtraakt terwijl je op de laser staat te
wachten, dus hier wél.

Twee keuzes die het bruikbaar maken:

- **Bewaren gebeurt vertraagd.** Elke wijziging aan de elementenboom stuurt een
  signaal; bij het slepen van een vorm zijn dat er tientallen per seconde. Er
  gaat er dus hooguit één per `INTERVAL` naar schijf.
- **Het herstelbestand wordt nooit stilletjes teruggeladen.** De app vraagt het;
  iemand die met een leeg canvas wil beginnen, moet dat kunnen.
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

    def touch(self) -> bool:
        """
        Aangeroepen bij elke wijziging. Bewaart hooguit één keer per interval.

        Geeft terug of er daadwerkelijk geschreven is — handig in tests, en het
        maakt zichtbaar dat de rem werkt.
        """
        now = time.monotonic()
        if now - self._last < INTERVAL:
            return False
        self._last = now
        return self.save()

    def save(self) -> bool:
        if not any(True for _ in self.kernel.elements.elems()):
            # Een leeg ontwerp bewaren zou een goed herstelbestand overschrijven
            # op het moment dat iemand "nieuw" kiest.
            return False
        # `save` zet `elements.basename` op de bestandsnaam, en die naam komt
        # daarna terug als jobnaam in de spooler — elke job heette "herstel.svg",
        # ook op een vers ontwerp waar niets hersteld was. Twee jobs die
        # hetzelfde heten zijn bij een laser niet uit elkaar te houden, dus we
        # zetten de naam terug zoals hij was.
        # `basename` is een property zonder setter; hij leidt af van
        # `_filename`, en dát is wat `save` zet.
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

    def _open_de_rem(self) -> None:
        """
        De rem lostrekken, zodat de eerstvolgende wijziging meteen bewaard wordt.

        De rem meet vanaf de laatste schrijfbeurt, en dat klopt zolang er een
        herstelbestand staat. Na weggooien of terugzetten staat er iets anders
        op schijf dan wat de rem denkt, en dan is wachten fout. Gemeten vóór
        deze regel: herstelbestand weggooien, daarna vier vormen tekenen en
        dertig seconden wachten — en er stond nog steeds geen herstelbestand.
        Wie in het openingsvenster voor "leeg beginnen" kiest, werkte dus een
        hele sessie zonder vangnet.
        """
        self._last = 0.0

    def restore(self) -> dict:
        """Het herstelbestand terugladen, over een leeg canvas."""
        from .edits import DesignError

        if not self.path.is_file():
            raise DesignError("Er is geen automatisch bewaard ontwerp.")
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
