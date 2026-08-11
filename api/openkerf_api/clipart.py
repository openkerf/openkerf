"""
Clipart zoeken in openbare collecties.

Bewust géén eigen bibliotheek: verwijzen in plaats van hosten. Dat scheelt
onderhoud en, belangrijker, het legt de licentieverantwoordelijkheid waar hij
hoort — bij de bron, zichtbaar bij elk resultaat. Wie lasert, verkoopt vaak wat
hij snijdt, en dan is "gratis gevonden" niet hetzelfde als "vrij te gebruiken".

Drie dingen die dit bruikbaar maken:

1. **Zoeken loopt via onze server, niet vanuit de browser.** Anders lopen we
   tegen CORS aan en kunnen we niets filteren of samenvoegen.
2. **Elke bron heeft zijn eigen korte time-out en mag omvallen.** Openclipart
   ligt er met enige regelmaat uit. Eén trage bron mag het zoeken niet ophouden;
   de gebruiker ziet wat er wél is, plus welke bron niet antwoordde.
3. **Bij het invoegen wordt gecontroleerd, niet bij het zoeken.** Een tekening
   die er op het scherm goed uitziet kan op een laser waardeloos zijn: open
   paden, gradiënten, tekst die geen pad is. Dat hoort je te weten vóór je
   materiaal erin legt, niet erna.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
import threading

from .edits import DesignError

# Kort: een gebruiker die zoekt, wacht niet. Een bron die er langer over doet,
# is voor dit doel gewoon niet beschikbaar.
TIMEOUT = 5.0
DOWNLOAD_TIMEOUT = 10.0
MAX_BYTES = 4 * 1024 * 1024

WIKIMEDIA = "https://commons.wikimedia.org/w/api.php"
OPENCLIPART = "https://openclipart.org/search/json/"
ICONIFY = "https://api.iconify.design"

USER_AGENT = "OpenKerf/0.1 (https://github.com/openkerf/openkerf)"

SOURCES = ("iconify", "wikimedia", "openclipart")

# Iconen komen als 1em-vierkantjes in de kleur van de tekst; zonder een echte
# maat en een echte kleur weet de engine niet wat hij moet tekenen.
ICON_SIZE = 240

# Wat op een laser niet bestaat, of anders uitpakt dan je ziet. Geen weigering
# maar een melding: de engine laat ze vallen, en dan hoor je te weten wat er
# verdwijnt.
DROPPED = {
    "linearGradient": "kleurverlopen",
    "radialGradient": "kleurverlopen",
    "filter": "filters",
    "mask": "maskers",
    "text": "tekst (wordt geen pad)",
    "image": "ingesloten pixels",
}


def _fetch(url: str, timeout: float = TIMEOUT) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(MAX_BYTES + 1)


class Clipart:
    def __init__(self, kernel, drawing, fetch=_fetch):
        self.kernel = kernel
        self.drawing = drawing
        # Injecteerbaar, zodat tests niet het internet op hoeven.
        self.fetch = fetch

    # -------------------------------------------------------------- zoeken

    def search(self, query: str, sources=None, limit: int = 24, page: int = 1) -> dict:
        text = str(query or "").strip()
        if len(text) < 2:
            raise DesignError("Geef minstens twee letters om op te zoeken.")
        wanted = [s for s in (sources or SOURCES) if s in SOURCES]
        if not wanted:
            raise DesignError(f"Onbekende bron. Kies uit {', '.join(SOURCES)}.")
        try:
            number = int(page)
        except (TypeError, ValueError) as e:
            raise DesignError("De pagina moet een geheel getal zijn.") from e
        if not 1 <= number <= 50:
            raise DesignError("De pagina moet tussen 1 en 50 liggen.")
        per_source = max(4, int(limit) // len(wanted))
        offset = (number - 1) * per_source

        lookups = {
            "iconify": self._iconify,
            "wikimedia": self._wikimedia,
            "openclipart": self._openclipart,
        }
        results, problems = [], {}

        # Naast elkaar, met gewone threads: één trage bron mag de andere niet
        # ophouden. Geen ThreadPoolExecutor — die weigert dienst zodra ergens in
        # het proces de atexit-haak van `concurrent.futures` is afgegaan, en in
        # een engine die zelf threads beheert gebeurt dat.
        found = {}

        def run(name):
            try:
                found[name] = lookups[name](text, per_source, offset)
            except Exception as error:  # noqa: BLE001 - de reden is het antwoord
                problems[name] = self._reason(error)

        threads = [
            threading.Thread(target=run, args=(name,), daemon=True) for name in wanted
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            # Iets ruimer dan de time-out van het ophalen zelf, zodat een bron
            # die netjes afbreekt zijn eigen melding kan achterlaten.
            thread.join(timeout=TIMEOUT + 2)
        for name in wanted:
            if name in found:
                results.extend(found[name])
            elif name not in problems:
                problems[name] = "reageerde niet op tijd"

        # Meer te halen zolang minstens één bron zijn pagina helemaal vulde.
        # Geen van beide API's zegt hoeveel resultaten er in totaal zijn, dus
        # dit is het eerlijkste teken: een halfvolle pagina is het einde.
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
            return "reageerde niet op tijd"
        if isinstance(error, urllib.error.HTTPError):
            return f"gaf een foutmelding ({error.code})"
        if isinstance(error, urllib.error.URLError):
            return "was niet bereikbaar"
        if isinstance(error, (json.JSONDecodeError, UnicodeDecodeError)):
            # Openclipart geeft bij storing een HTML-pagina of niets terug. De
            # gebruiker heeft niets aan een parse-fout.
            return "gaf een onverwacht antwoord"
        return str(error)[:120] or "gaf een onverwacht antwoord"

    def _iconify(self, query: str, limit: int, offset: int = 0) -> list[dict]:
        """
        Open-source iconensets, gebundeld door Iconify.

        Voor een laser is dit het meest bruikbare materiaal dat er is: gesloten
        paden, geen kleurverlopen, geen tekst, weinig knooppunten. Precies alles
        wat bij andere bronnen uit de tekening valt, ontbreekt hier gewoon.
        """
        params = urllib.parse.urlencode(
            {"query": query, "limit": str(max(32, limit)), "start": str(offset)}
        )
        payload = json.loads(self.fetch(f"{ICONIFY}/search?{params}").decode("utf-8"))
        # De licentie per set zit in hetzelfde antwoord; dat scheelt een tweede
        # verzoek per resultaat.
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
                    "license": licence or "zie de iconenset",
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
            # Op het mime-type filteren, niet op de bestandsnaam: Commons hangt
            # er een `?utm_source=` achter, waardoor een test op ".svg" alles
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
        # Openclipart telt in pagina's, niet in een beginpositie.
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
                    # Openclipart is volledig publiek domein; dat staat niet
                    # altijd in het antwoord, maar geldt voor de hele collectie.
                    "license": item.get("license") or "CC0 (publiek domein)",
                    "author": item.get("uploader"),
                }
            )
        return found

    # ------------------------------------------------------------ invoegen

    def insert(self, url: str, width_mm=60.0, x_mm=10.0, y_mm=10.0) -> dict:
        """
        Een gevonden tekening in het ontwerp zetten, op ware grootte.

        De controle zit hier en niet bij het zoeken: pas als je hem echt wilt
        gebruiken, is het de moeite om te weten wat er op een laser van
        overblijft.
        """
        from meerk40t.core.units import UNITS_PER_MM

        address = str(url or "").strip()
        if not address.lower().startswith("https://"):
            # Alleen https, en alleen van de bronnen die we zelf aanbieden:
            # een willekeurige URL laten ophalen door de server is een open deur.
            raise DesignError(
                "Alleen beveiligde adressen (https) worden opgehaald. Kies een "
                "tekening uit het zoekvenster in plaats van een adres te plakken."
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
                "Dit adres hoort niet bij Iconify, Wikimedia Commons of "
                "Openclipart. Kies een tekening uit het zoekvenster; alleen die "
                "bronnen worden opgehaald."
            )
        width = float(width_mm)
        if not 1 <= width <= 2000:
            raise DesignError("De breedte moet tussen 1 en 2000 mm liggen.")

        try:
            body = self.fetch(address, timeout=DOWNLOAD_TIMEOUT)
        except Exception as error:
            raise DesignError(f"Ophalen mislukte: {self._reason(error)}") from error
        if len(body) > MAX_BYTES:
            raise DesignError("Deze tekening is te groot om te verwerken.")

        notes = self._inspect(body)

        import tempfile
        from pathlib import Path

        target = Path(tempfile.mkdtemp(prefix="openkerf-clipart-")) / "clipart.svg"
        target.write_bytes(body)

        before = {id(node) for node in self.elements.elems()}
        with self.elements.undoscope("Clipart invoegen"):
            self.drawing.runner.run(f'load "{target}"')
            added = [n for n in self.elements.elems() if id(n) not in before]
            if not added:
                raise DesignError(
                    "Hier viel niets uit te tekenen. "
                    + (" ".join(notes) if notes else "De engine kon de SVG niet lezen.")
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
        """Wat er op een laser niet overkomt. Meldingen, geen weigering."""
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
                f"Deze tekening bestaat uit {paths} losse paden; dat wordt een "
                "lange job. Overweeg een eenvoudiger afbeelding."
            )
        return notes

    def _place(self, nodes, width_units: float, x_mm, y_mm) -> None:
        """Op maat schalen en neerleggen, zodat hij niet ergens buiten het bed valt."""
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
    """Commons hangt tracking achter zijn bestands-URL's; die willen we niet."""
    return url.split("?", 1)[0]


def _plain_text(field) -> str | None:
    """Wikimedia levert HTML in zijn metadata; daar wil de gebruiker niets van zien."""
    import re

    if not field:
        return None
    value = field.get("value") if isinstance(field, dict) else field
    if not value:
        return None
    return re.sub(r"<[^>]+>", "", str(value)).strip() or None
