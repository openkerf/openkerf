"""
Eigen lettertypen bruikbaar maken.

The engine only reads `.ttf`, `.shx` and `.jhf`, and keeps the list it found in a cache
file. Two consequences a user experiences as "my font does not work":

1. **An `.otf` never appears**, not even when it simply contains TrueType outlines — which
   is the case for many `.otf` files. Then it is only an extension that stands in the way.
2. **A freshly installed typeface only appears after clearing the cache**, and nothing tells
   you so.

Here we solve both: importing puts a copy as `.ttf` in the engine's font directory — with a
real conversion when the file has CFF outlines — and then refreshes the list.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from .edits import DesignError

# Where macOS, Windows and Linux keep their typefaces. The engine looks here too, but only
# for the extensions it knows.
SEARCH = (
    "~/Library/Fonts",
    "/Library/Fonts",
    "/System/Library/Fonts",
    "~/.fonts",
    "~/.local/share/fonts",
    "/usr/share/fonts",
    "C:/Windows/Fonts",
)

# What the engine does not read but we can convert.
CONVERTIBLE = (".otf", ".ttc", ".otc")
MAX_FONT_BYTES = 40 * 1024 * 1024


class Fonts:
    def __init__(self, kernel):
        self.kernel = kernel

    @property
    def registry(self):
        registry = getattr(self.kernel.root, "fonts", None)
        if registry is None:
            raise DesignError("The engine's font plugin is not loaded.")
        return registry

    def directory(self) -> Path:
        return Path(self.registry.font_directory)

    # ------------------------------------------------------------ verversen

    def refresh(self) -> None:
        """
        De engine again laten kijken.

        Without this a freshly installed typeface stays invisible until MeerK40t restarts —
        the list comes from a cache file.
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

    # -------------------------------------------------------------- tonen

    # What a browser can load as a web font. `.shx` and `.jhf` are plotter fonts without a
    # browser equivalent; those get no preview.
    PREVIEWABLE = (".ttf", ".otf", ".woff", ".woff2")

    def preview_file(self, name: str) -> Path:
        """
        The file behind a typeface, to serve as a web font.

        Only files the engine already knows come past here: the name is looked up in the
        list, not treated as a path. Otherwise this is a readable window onto the whole disk.
        """
        wanted = str(name or "")
        for entry in self.registry.available_fonts() or []:
            path = Path(str(entry[0]))
            if wanted not in (str(path), path.name):
                continue
            if path.suffix.lower() not in self.PREVIEWABLE:
                raise DesignError("A browser can show nothing of this font.")
            if not path.is_file():
                raise DesignError("That font is no longer there.")
            return path
        raise DesignError("Onbekend lettertype.")

    # ---------------------------------------------------------- importeren

    def importable(self) -> list[dict]:
        """
        Typefaces on this system the engine does not see but we can use.
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
        Putting a typeface in the engine's font directory, as a `.ttf`.

        Many `.otf` files simply contain TrueType outlines; then copying is enough. If there
        is PostScript (CFF) in it, the outlines are converted to quadratic curves — which is
        what TrueType knows.
        """
        path = Path(os.path.expanduser(str(source or ""))).resolve()
        if not path.is_file():
            raise DesignError(
                f"'{source}' does not exist. Choose a font from the list in "
                "the text window; it shows what is on this computer."
            )
        if path.suffix.lower() not in CONVERTIBLE + (".ttf",):
            raise DesignError(
                f"'{path.suffix}' is not possible; choose a .ttf or .otf file."
            )
        if not any(
            str(path).lower().startswith(str(Path(os.path.expanduser(w)).resolve()).lower())
            for w in SEARCH
        ):
            # Only from the system's font directories: having the server read an arbitrary
            # path is an open door.
            raise DesignError("This file is not in a font folder.")
        if path.stat().st_size > MAX_FONT_BYTES:
            raise DesignError("This file is too large for a font.")

        target = self.directory() / f"{path.stem}.ttf"
        if target.exists():
            raise DesignError(f"'{target.name}' is already there.")

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
                "Converting needs the 'fonttools' package; install it beside the API."
            ) from e

        try:
            font = TTFont(str(source), fontNumber=0)
        except Exception as e:
            raise DesignError(f"This font cannot be read: {e}") from e

        if "glyf" in font:
            # Already TrueType inside; only the extension said otherwise.
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
        """Hang the converted outlines in the font as TrueType tables."""
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
