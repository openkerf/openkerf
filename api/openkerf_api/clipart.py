"""
Clipart zoeken in openbare collecties.

Deliberately no library of our own: referring instead of hosting. That saves maintenance
and, more importantly, it puts the licence responsibility where it belongs — with the
source, visible at every result. Anybody who lasers often sells what they cut, and then
"found for free" is not the same as "free to use".

Three things that make this usable:

1. **Searching goes through our server, not from the browser.** Otherwise we run into CORS
   and can filter or merge nothing.
2. **Every source has its own short time-out and may fall over.** Openclipart is down with
   some regularity. One slow source must not hold the search up; the user sees what *is*
   there, plus which source did not answer.
3. **Checking happens on insertion, not on searching.** A drawing that looks good on screen
   can be worthless on a laser: open paths, gradients, text that is not a path. You should
   know that before you put material in, not after.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
import threading

from .edits import DesignError

# Short: a user who is searching does not wait. A source that takes longer is simply not
# available for this purpose.
TIMEOUT = 5.0
DOWNLOAD_TIMEOUT = 10.0
MAX_BYTES = 4 * 1024 * 1024

WIKIMEDIA = "https://commons.wikimedia.org/w/api.php"
OPENCLIPART = "https://openclipart.org/search/json/"
ICONIFY = "https://api.iconify.design"

USER_AGENT = "OpenKerf/0.1 (https://github.com/openkerf/openkerf)"

SOURCES = ("iconify", "wikimedia", "openclipart")

# Icons come as 1em squares in the text colour; without a real size and a real colour the
# engine does not know what to draw.
ICON_SIZE = 240

# What does not exist on a laser, or turns out differently from what you see. Not
# a refusal but a note: the engine drops them, and then you ought to know what
# disappears.
DROPPED = {
    "linearGradient": "gradients",
    "radialGradient": "gradients",
    "filter": "filters",
    "mask": "masks",
    "text": "text (does not become a path)",
    "image": "embedded pixels",
}


def _fetch(url: str, timeout: float = TIMEOUT) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(MAX_BYTES + 1)


class Clipart:
    def __init__(self, kernel, drawing, fetch=_fetch):
        self.kernel = kernel
        self.drawing = drawing
        # Injectable, so that tests do not have to go on the internet.
        self.fetch = fetch

    # -------------------------------------------------------------- zoeken

    def search(self, query: str, sources=None, limit: int = 24, page: int = 1) -> dict:
        text = str(query or "").strip()
        if len(text) < 2:
            raise DesignError("Give at least two letters to search for.")
        wanted = [s for s in (sources or SOURCES) if s in SOURCES]
        if not wanted:
            raise DesignError(f"Unknown source. Choose from {', '.join(SOURCES)}.")
        try:
            number = int(page)
        except (TypeError, ValueError) as e:
            raise DesignError("The page has to be a whole number.") from e
        if not 1 <= number <= 50:
            raise DesignError("The page has to be between 1 and 50.")
        per_source = max(4, int(limit) // len(wanted))
        offset = (number - 1) * per_source

        lookups = {
            "iconify": self._iconify,
            "wikimedia": self._wikimedia,
            "openclipart": self._openclipart,
        }
        results, problems = [], {}

        # Side by side, with ordinary threads: one slow source must not hold the others up.
        # Not a ThreadPoolExecutor — that refuses service as soon as `concurrent.futures`'s
        # atexit hook has fired somewhere in the process, and in an engine that manages
        # threads itself that happens.
        found = {}

        def run(name):
            try:
                found[name] = lookups[name](text, per_source, offset)
            except Exception as error:  # noqa: BLE001 - the reason is the answer
                problems[name] = self._reason(error)

        threads = [
            threading.Thread(target=run, args=(name,), daemon=True) for name in wanted
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            # Slightly more generous than the fetch's own time-out, so that a source
            # breaking off neatly can leave its own message behind.
            thread.join(timeout=TIMEOUT + 2)
        for name in wanted:
            if name in found:
                results.extend(found[name])
            elif name not in problems:
                problems[name] = "did not answer in time"

        # More to fetch as long as at least one source filled its page completely. Neither
        # API says how many results there are in total, so this is the most honest sign: a
        # half-full page is the end.
        more = any(len(found.get(name, [])) >= per_source for name in wanted)
        return {
            "query": text,
            "page": number,
            "has_more": more,
            "results": results[: int(limit)],
            "unavailable": problems,
        }

    @staticmethod
    def _reason(error: Exception) -> str:
        if isinstance(error, TimeoutError) or isinstance(
            getattr(error, "reason", None), TimeoutError
        ):
            return "did not answer in time"
        if isinstance(error, urllib.error.HTTPError):
            return f"returned an error ({error.code})"
        if isinstance(error, urllib.error.URLError):
            return "was unreachable"
        if isinstance(error, (json.JSONDecodeError, UnicodeDecodeError)):
            # On a fault Openclipart hands back an HTML page or nothing. A parse error is no
            # use to the user.
            return "gave an unexpected answer"
        return str(error)[:120] or "gave an unexpected answer"

    def _iconify(self, query: str, limit: int, offset: int = 0) -> list[dict]:
        """
        Open-source iconensets, gebundeld door Iconify.

        For a laser this is the most usable material there is: closed paths, no gradients,
        no text, few nodes. Precisely everything that falls out of the drawing with other
        sources is simply absent here.
        """
        params = urllib.parse.urlencode(
            {"query": query, "limit": str(max(32, limit)), "start": str(offset)}
        )
        payload = json.loads(self.fetch(f"{ICONIFY}/search?{params}").decode("utf-8"))
        # The licence per set is in the same answer; that saves a second request per
        # result.
        sets = payload.get("collections") or {}

        found = []
        for name in (payload.get("icons") or [])[:limit]:
            prefix, _, icon = str(name).partition(":")
            if not icon:
                continue
            collection = sets.get(prefix) or {}
            licence = (collection.get("license") or {}).get("title")
            image = f"{ICONIFY}/{prefix}/{icon}.svg"
            found.append(
                {
                    "id": f"iconify:{name}",
                    "source": "Iconify",
                    "title": icon.replace("-", " "),
                    "svg_url": f"{image}?height={ICON_SIZE}&color=%23000000",
                    "thumbnail_url": f"{image}?height=64&color=%23000000",
                    "page_url": f"https://icon-sets.iconify.design/{prefix}/{icon}/",
                    "license": licence or "see the icon set",
                    "author": (collection.get("author") or {}).get("name")
                    or collection.get("name"),
                }
            )
        return found

    def _wikimedia(self, query: str, limit: int, offset: int = 0) -> list[dict]:
        params = urllib.parse.urlencode(
            {
                "action": "query",
                "format": "json",
                "generator": "search",
                "gsrsearch": f"filetype:drawing {query}",
                "gsrnamespace": "6",
                "gsrlimit": str(limit),
                "gsroffset": str(offset),
                "prop": "imageinfo",
                "iiprop": "url|mime|extmetadata",
                "iiurlwidth": "160",
            }
        )
        payload = json.loads(self.fetch(f"{WIKIMEDIA}?{params}").decode("utf-8"))
        pages = (payload.get("query") or {}).get("pages") or {}

        found = []
        for page in pages.values():
            info = (page.get("imageinfo") or [{}])[0]
            # Filter on the mime type, not on the file name: Commons hangs a `?utm_source=`
            # on the end, which makes a test on ".svg" throw everything
            # wegfiltert.
            if info.get("mime") != "image/svg+xml":
                continue
            url = _without_query(info.get("url") or "")
            if not url:
                continue
            meta = info.get("extmetadata") or {}
            found.append(
                {
                    "id": f"wikimedia:{page.get('pageid')}",
                    "source": "Wikimedia Commons",
                    "title": str(page.get("title", "")).removeprefix("File:"),
                    "svg_url": url,
                    "thumbnail_url": info.get("thumburl") or url,
                    "page_url": info.get("descriptionurl"),
                    "license": _plain_text(meta.get("LicenseShortName")),
                    "author": _plain_text(meta.get("Artist")),
                }
            )
        return found

    def _openclipart(self, query: str, limit: int, offset: int = 0) -> list[dict]:
        # Openclipart counts in pages, not in a start position.
        params = urllib.parse.urlencode(
            {
                "query": query,
                "amount": str(limit),
                "page": str(offset // max(1, limit) + 1),
            }
        )
        payload = json.loads(self.fetch(f"{OPENCLIPART}?{params}").decode("utf-8"))

        found = []
        for item in payload.get("payload") or []:
            svg = (item.get("svg") or {}).get("url")
            if not svg:
                continue
            found.append(
                {
                    "id": f"openclipart:{item.get('id')}",
                    "source": "Openclipart",
                    "title": item.get("title") or "zonder titel",
                    "svg_url": svg,
                    "thumbnail_url": (item.get("svg") or {}).get("png_thumb") or svg,
                    "page_url": item.get("detail_link"),
                    # Openclipart is entirely public domain; that is not always in the
                    # answer, but it holds for the whole collection.
                    "license": item.get("license") or "CC0 (public domain)",
                    "author": item.get("uploader"),
                }
            )
        return found

    # ------------------------------------------------------------ invoegen

    def insert(self, url: str, width_mm=60.0, x_mm=10.0, y_mm=10.0) -> dict:
        """
        Een gevonden tekening in het ontwerp zetten, op ware grootte.

        The check is here and not at the search: only when you really want to use it is it
        worth knowing what is left of it on a laser.
        """
        from meerk40t.core.units import UNITS_PER_MM

        address = str(url or "").strip()
        if not address.lower().startswith("https://"):
            # Only https, and only from the sources we offer ourselves: having the server
            # fetch an arbitrary URL is an open door.
            raise DesignError(
                "Only secure addresses (https) are fetched. Choose a "
                "drawing from the search window instead of pasting an address."
            )
        if not any(
            address.lower().startswith(prefix)
            for prefix in (
                "https://upload.wikimedia.org/",
                "https://openclipart.org/",
                f"{ICONIFY}/",
            )
        ):
            raise DesignError(
                "This address does not belong to Iconify, Wikimedia Commons or "
                "Openclipart. Choose a drawing from the search window; only those "
                "bronnen worden opgehaald."
            )
        width = float(width_mm)
        if not 1 <= width <= 2000:
            raise DesignError("The width has to be between 1 and 2000 mm.")

        try:
            body = self.fetch(address, timeout=DOWNLOAD_TIMEOUT)
        except Exception as error:
            raise DesignError(f"Ophalen mislukte: {self._reason(error)}") from error
        if len(body) > MAX_BYTES:
            raise DesignError("This drawing is too large to process.")

        notes = self._inspect(body)

        import tempfile
        from pathlib import Path

        target = Path(tempfile.mkdtemp(prefix="openkerf-clipart-")) / "clipart.svg"
        target.write_bytes(body)

        before = {id(node) for node in self.elements.elems()}
        with self.elements.undoscope("Insert clipart"):
            self.drawing.runner.run(f'load "{target}"')
            added = [n for n in self.elements.elems() if id(n) not in before]
            if not added:
                raise DesignError(
                    "There was nothing to draw out of this. "
                    + (" ".join(notes) if notes else "The engine could not read the SVG.")
                )
            self.elements.validate_ids()
            self._place(added, width * UNITS_PER_MM, x_mm, y_mm)

        self.elements.signal("rebuild_tree", "all")
        self.elements.signal("refresh_scene", "Scene")
        return {
            "ids": [n.id for n in added if n.id],
            "count": len(added),
            "notes": notes,
        }

    @property
    def elements(self):
        return self.kernel.elements

    def _inspect(self, body: bytes) -> list[str]:
        """What does not come across on a laser. Notes, not a refusal."""
        try:
            text = body.decode("utf-8", errors="ignore")
        except Exception:
            return []
        found = []
        for tag, what in DROPPED.items():
            if f"<{tag}" in text or f":{tag} " in text:
                if what not in found:
                    found.append(what)
        notes = []
        if found:
            notes.append(
                "Deze tekening bevat " + ", ".join(found) + "; dat komt niet mee."
            )
        paths = text.count("<path")
        if paths > 400:
            # Een tekening uit een encyclopedie heeft er zo duizend. Dat brandt
            # niet fout, maar het duurt uren en dat weet je liever vooraf.
            notes.append(
                f"This drawing consists of {paths} loose paths; that makes a "
                "long job. Consider a simpler image."
            )
        return notes

    def _place(self, nodes, width_units: float, x_mm, y_mm) -> None:
        """Scale it to size and put it down, so it does not land outside the bed."""
        from meerk40t.core.units import UNITS_PER_MM

        boxes = [n.bounds for n in nodes if getattr(n, "bounds", None)]
        if not boxes:
            return
        x0 = min(b[0] for b in boxes)
        y0 = min(b[1] for b in boxes)
        x1 = max(b[2] for b in boxes)
        y1 = max(b[3] for b in boxes)
        if x1 - x0 <= 0:
            return

        scale = width_units / (x1 - x0)
        target_x = float(x_mm) * UNITS_PER_MM
        target_y = float(y_mm) * UNITS_PER_MM
        for node in nodes:
            matrix = getattr(node, "matrix", None)
            if matrix is None:
                continue
            matrix.post_translate(-x0, -y0)
            matrix.post_scale(scale, scale)
            matrix.post_translate(target_x, target_y)
            if hasattr(node, "modified"):
                node.modified()


def _without_query(url: str) -> str:
    """Commons hangs tracking behind its file URLs; we do not want that."""
    return url.split("?", 1)[0]


def _plain_text(field) -> str | None:
    """Wikimedia delivers HTML in its metadata; the user wants to see none of it."""
    import re

    if not field:
        return None
    value = field.get("value") if isinstance(field, dict) else field
    if not value:
        return None
    return re.sub(r"<[^>]+>", "", str(value)).strip() or None
