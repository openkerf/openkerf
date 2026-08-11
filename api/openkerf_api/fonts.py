"""
Eigen lettertypen bruikbaar maken.

De engine leest alleen `.ttf`, `.shx` en `.jhf`, en houdt de gevonden lijst in
een cachebestand. Twee gevolgen die een gebruiker als "mijn font doet het niet"
ervaart:

1. **Een `.otf` verschijnt nooit**, ook niet als hij gewoon TrueType-omtrekken
   bevat — wat bij veel `.otf`-bestanden zo is. Dan scheelt het alleen een
   extensie.
2. **Een net geïnstalleerd lettertype verschijnt pas na het legen van de
   cache**, en niets vertelt je dat.

Hier lossen we beide op: importeren zet een kopie als `.ttf` in de fontmap van
de engine — met een echte omzetting als het bestand CFF-omtrekken heeft — en
ververst daarna de lijst.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from .edits import DesignError

# Waar macOS, Windows en Linux hun lettertypen bewaren. De engine kijkt hier
# ook, maar alleen naar de uitbreidingen die hij kent.
SEARCH = (
    "~/Library/Fonts",
    "/Library/Fonts",
    "/System/Library/Fonts",
    "~/.fonts",
    "~/.local/share/fonts",
    "/usr/share/fonts",
    "C:/Windows/Fonts",
)

# Wat de engine niet leest maar wij wel kunnen omzetten.
CONVERTIBLE = (".otf", ".ttc", ".otc")
MAX_FONT_BYTES = 40 * 1024 * 1024


class Fonts:
    def __init__(self, kernel):
        self.kernel = kernel

    @property
    def registry(self):
        registry = getattr(self.kernel.root, "fonts", None)
        if registry is None:
            raise DesignError("De lettertype-plugin van de engine is niet geladen.")
        return registry

    def directory(self) -> Path:
        return Path(self.registry.font_directory)

    # ------------------------------------------------------------ verversen

    def refresh(self) -> None:
        """
        De engine opnieuw laten kijken.

        Zonder dit blijft een net geïnstalleerd lettertype onzichtbaar tot
        MeerK40t herstart — de lijst komt uit een cachebestand.
        """
        registry = self.registry
        try:
            cache = Path(registry.cache_file)
            cache.unlink(missing_ok=True)
        except (OSError, AttributeError):
            pass
        registry._available_fonts = None
        try:
            registry.get_font_information.cache_clear()
        except AttributeError:
            pass

    # ---------------------------------------------------------- importeren

    def importable(self) -> list[dict]:
        """
        Lettertypen op dit systeem die de engine niet ziet maar wij wel kunnen
        gebruiken.
        """
        known = {
            str(entry[0]).lower()
            for entry in (self.registry.available_fonts() or [])
            if entry
        }
        found, seen = [], set()
        for where in SEARCH:
            root = Path(os.path.expanduser(where))
            if not root.is_dir():
                continue
            for path in sorted(root.rglob("*")):
                if path.suffix.lower() not in CONVERTIBLE or not path.is_file():
                    continue
                if str(path).lower() in known or path.name.lower() in seen:
                    continue
                seen.add(path.name.lower())
                found.append({"file": str(path), "name": path.stem})
        return found

    def import_font(self, source: str) -> dict:
        """
        Een lettertype in de fontmap van de engine zetten, als `.ttf`.

        Veel `.otf`-bestanden bevatten gewoon TrueType-omtrekken; dan is
        kopiëren genoeg. Zit er PostScript (CFF) in, dan worden de omtrekken
        omgezet naar kwadratische krommen — dat is wat TrueType kent.
        """
        path = Path(os.path.expanduser(str(source or ""))).resolve()
        if not path.is_file():
            raise DesignError(
                f"'{source}' bestaat niet. Kies een lettertype uit de lijst in "
                "het tekstvenster; die toont wat er op deze computer staat."
            )
        if path.suffix.lower() not in CONVERTIBLE + (".ttf",):
            raise DesignError(
                f"'{path.suffix}' kan niet; kies een .ttf of .otf-bestand."
            )
        if not any(
            str(path).lower().startswith(str(Path(os.path.expanduser(w)).resolve()).lower())
            for w in SEARCH
        ):
            # Alleen uit de fontmappen van het systeem: een willekeurig pad laten
            # inlezen door de server is een open deur.
            raise DesignError("Dit bestand staat niet in een lettertypemap.")
        if path.stat().st_size > MAX_FONT_BYTES:
            raise DesignError("Dit bestand is te groot voor een lettertype.")

        target = self.directory() / f"{path.stem}.ttf"
        if target.exists():
            raise DesignError(f"'{target.name}' staat er al.")

        if path.suffix.lower() == ".ttf":
            shutil.copyfile(path, target)
        else:
            self._convert(path, target)

        self.refresh()
        return {"file": str(target), "name": target.stem}

    def _convert(self, source: Path, target: Path) -> None:
        try:
            from fontTools.pens.cu2quPen import Cu2QuPen
            from fontTools.pens.ttGlyphPen import TTGlyphPen
            from fontTools.ttLib import TTFont
        except ImportError as e:  # pragma: no cover - alleen zonder fonttools
            raise DesignError(
                "Omzetten vraagt het pakket 'fonttools'; installeer dat naast de API."
            ) from e

        try:
            font = TTFont(str(source), fontNumber=0)
        except Exception as e:
            raise DesignError(f"Dit lettertype is niet te lezen: {e}") from e

        if "glyf" in font:
            # Al TrueType van binnen; alleen de extensie zei iets anders.
            font.save(str(target))
            return

        try:
            glyph_set = font.getGlyphSet()
            pens = {}
            for name in font.getGlyphOrder():
                pen = TTGlyphPen(None)
                glyph_set[name].draw(Cu2QuPen(pen, 1.0))
                pens[name] = pen.glyph()
            self._build_glyf(font, pens)
            font.save(str(target))
        except Exception as e:
            target.unlink(missing_ok=True)
            raise DesignError(f"Omzetten mislukte: {e}") from e

    @staticmethod
    def _build_glyf(font, pens) -> None:
        """De omgezette omtrekken als TrueType-tabellen in het font hangen."""
        from fontTools.ttLib import newTable

        glyf = newTable("glyf")
        glyf.glyphOrder = font.getGlyphOrder()
        glyf.glyphs = pens
        font["glyf"] = glyf

        loca = newTable("loca")
        font["loca"] = loca

        head = font["head"]
        head.indexToLocFormat = 0
        head.glyphDataFormat = 0

        maxp = font["maxp"]
        maxp.tableVersion = 0x00010000
        maxp.numGlyphs = len(pens)
        for attribute, value in (
            ("maxPoints", 0),
            ("maxContours", 0),
            ("maxCompositePoints", 0),
            ("maxCompositeContours", 0),
            ("maxZones", 2),
            ("maxTwilightPoints", 0),
            ("maxStorage", 0),
            ("maxFunctionDefs", 0),
            ("maxInstructionDefs", 0),
            ("maxStackElements", 0),
            ("maxSizeOfInstructions", 0),
            ("maxComponentElements", 0),
            ("maxComponentDepth", 0),
        ):
            setattr(maxp, attribute, value)

        for gone in ("CFF ", "CFF2", "VORG"):
            if gone in font:
                del font[gone]
