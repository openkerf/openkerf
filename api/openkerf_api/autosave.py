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
        # Kwam er een wijziging binnen terwijl de rem erop stond? Dan staat er
        # werk in de boom dat nog nergens op schijf terugkomt.
        self._wachtend = False

    def touch(self) -> bool:
        """
        Aangeroepen bij elke wijziging. Bewaart hooguit één keer per interval.

        Geeft terug of er daadwerkelijk geschreven is — handig in tests, en het
        maakt zichtbaar dat de rem werkt.
        """
        if not any(True for _ in self.kernel.elements.elems()):
            # Een leeg ontwerp levert niets om te bewaren (zie `save`), dus het
            # mag de rem ook niet opgebruiken. Dat deed het wél: leegmaken stuurt
            # een boomsignaal, dat zette de klok, en `save` schreef vervolgens
            # niets. Gemeten: ontwerp leegmaken, meteen daarna vier vormen
            # tekenen — geen herstelbestand, tot er twintig seconden later
            # toevallig nog een wijziging kwam. "Nieuw ontwerp" is precies het
            # moment waarop je daarna gaat tekenen.
            return False
        now = time.monotonic()
        if now - self._last < INTERVAL:
            # Niet nu, maar het mag ook niet blijven liggen: `flush` haalt het op.
            self._wachtend = True
            return False
        self._last = now
        self._wachtend = False
        return self.save()

    def flush(self, *args) -> bool:
        """
        De staart: de laatste wijziging vóór je bij de machine gaat staan.

        `touch` schrijft de eerste wijziging meteen en remt daarna. Wie in die
        twintig seconden nog drie vormen tekent en dan ophoudt, kreeg voor die
        drie nooit meer een schrijfbeurt — er komt immers geen signaal meer.
        Gemeten: drie vormen in drie seconden, server hard afgeschoten, en het
        herstelbestand bevatte er één.

        Draait als kerneljob, dus op dezelfde thread als de boomsignalen. Dat is
        geen detail: een eigen timerthread zou de elementenboom uitlezen terwijl
        de kernel hem verzet.
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

    def forget_if_saved(self) -> bool:
        """
        Het vangnet opruimen als er niets meer in kan vallen.

        Het herstelbestand blijft anders eeuwig staan, en het venster "Werk van
        een vorige sessie" komt dan bij élke start van een nieuw ontwerp langs.
        Gemeten: tekenen, op Exporteren drukken, aan iets nieuws beginnen — en
        de volgende laadbeurt vraagt of je die pas geëxporteerde tekening wilt
        terugzetten. Dat is geen vorige sessie en er valt niets te herstellen;
        het is een venster dat je leert wegklikken, en dat is precies wat je
        niet wil op de dag dat er wél iets te herstellen valt.

        `document.dirty` is hier de juiste vraag en niet "heeft de gebruiker
        opgeslagen": hij staat op False zodra het ontwerp gelijk is aan een
        bestand — na exporteren, na openen, na een projectbestand. Staat hij op
        True, dan is er ongeborgen werk en blijft het vangnet liggen, ook al
        gooit de gebruiker het canvas leeg.

        Geeft terug of er werkelijk iets weggehaald is.
        """
        if self.document.dirty:
            return False
        bestond = self.path.is_file()
        self.discard()
        return bestond

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
