"""
Clipart zoeken in openbare collecties.

Geen netwerk in de tests: de ophaalfunctie is injecteerbaar. Dat is niet alleen
handig maar ook nodig — een test die van Wikimedia afhangt, faalt op een dag
zonder dat er iets stuk is.
"""

import json

import pytest
from fastapi.testclient import TestClient

from openkerf_api.clipart import Clipart
from openkerf_api.drawing import Drawing
from openkerf_api.edits import DesignError
from openkerf_api.server import ApiServer

WIKI_ANSWER = {
    "query": {
        "pages": {
            "1": {
                "pageid": 1,
                "title": "File:Hart.svg",
                "imageinfo": [
                    {
                        "mime": "image/svg+xml",
                        "url": "https://upload.wikimedia.org/hart.svg?utm_source=x",
                        "thumburl": "https://upload.wikimedia.org/thumb/hart.png",
                        "descriptionurl": "https://commons.wikimedia.org/wiki/File:Hart.svg",
                        "extmetadata": {
                            "LicenseShortName": {"value": "CC0"},
                            "Artist": {"value": '<a href="x">Iemand</a>'},
                        },
                    }
                ],
            },
            "2": {
                "pageid": 2,
                "title": "File:Foto.jpg",
                "imageinfo": [
                    {"mime": "image/jpeg", "url": "https://upload.wikimedia.org/foto.jpg"}
                ],
            },
        }
    }
}

CLIPART_ANSWER = {
    "payload": [
        {
            "id": 77,
            "title": "ster",
            "uploader": "iemand",
            "detail_link": "https://openclipart.org/detail/77",
            "svg": {
                "url": "https://openclipart.org/download/77/ster.svg",
                "png_thumb": "https://openclipart.org/image/64px/77",
            },
        }
    ]
}

ICONIFY_ANSWER = {
    "icons": ["mdi:heart", "tabler:heart-filled"],
    "total": 2,
    "collections": {
        "mdi": {
            "name": "Material Design Icons",
            "author": {"name": "Pictogrammers"},
            "license": {"title": "Apache 2.0", "spdx": "Apache-2.0"},
        }
    },
}

A_DRAWING = b"""<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100">
  <path d="M 10 10 L 90 10 L 90 90 L 10 90 Z" fill="none" stroke="black"/>
</svg>"""

A_MESSY_DRAWING = b"""<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100">
  <linearGradient id="g"><stop offset="0"/></linearGradient>
  <text x="10" y="20">hallo</text>
  <path d="M 10 10 L 90 10 L 90 90 Z" fill="url(#g)"/>
</svg>"""


def answers(**by_fragment):
    """Een neppe ophaalfunctie: kiest een antwoord op wat er in de URL staat."""

    def fetch(url, timeout=None):
        for fragment, payload in by_fragment.items():
            if fragment in url:
                if isinstance(payload, Exception):
                    raise payload
                if isinstance(payload, bytes):
                    return payload
                return json.dumps(payload).encode()
        raise AssertionError(f"onverwachte url: {url}")

    return fetch


@pytest.fixture
def shop(kernel):
    return Clipart(
        kernel,
        Drawing(kernel),
        fetch=answers(
            commons=WIKI_ANSWER,
            openclipart=CLIPART_ANSWER,
            iconify=ICONIFY_ANSWER,
        ),
    )


def test_all_sources_come_back(shop):
    found = shop.search("hart")

    sources = {r["source"] for r in found["results"]}
    assert sources == {"Iconify", "Wikimedia Commons", "Openclipart"}
    assert found["unavailable"] == {}


def test_only_vectors_from_wikimedia(shop):
    """Een JPEG uit Commons is voor een laser een heel ander gesprek."""
    titles = [r["title"] for r in shop.search("hart", sources=["wikimedia"])["results"]]

    assert titles == ["Hart.svg"]


def test_the_tracking_tail_is_stripped(shop):
    """
    Commons hangt `?utm_source=` achter zijn URL's. Daar struikelde de filter
    op bestandsnaam over, en het hoort ook niet in ons ontwerp terecht te komen.
    """
    first = shop.search("hart", sources=["wikimedia"])["results"][0]

    assert first["svg_url"] == "https://upload.wikimedia.org/hart.svg"


def test_a_source_that_answers_nonsense_says_so_plainly(kernel):
    """Openclipart geeft bij storing HTML terug; een parse-fout helpt niemand."""
    from openkerf_api.drawing import Drawing

    def fetch(url, timeout=None):
        if "commons" in url:
            return json.dumps(WIKI_ANSWER).encode()
        return b"<html>onderhoud</html>"

    shop = Clipart(kernel, Drawing(kernel), fetch=fetch)

    assert shop.search("hart", sources=["wikimedia", "openclipart"])[
        "unavailable"
    ] == {"openclipart": "gaf een onverwacht antwoord"}


def test_the_licence_travels_along(shop):
    """Wie lasert verkoopt wat hij snijdt; dan moet je de licentie kunnen zien."""
    first = shop.search("hart", sources=["wikimedia"])["results"][0]

    assert first["license"] == "CC0"
    # Wikimedia levert HTML in zijn metadata; dat wil niemand zien.
    assert first["author"] == "Iemand"


def test_a_source_that_is_down_does_not_hold_up_the_rest(kernel):
    """
    Openclipart ligt er met enige regelmaat uit. Dan hoor je te zien wat er wél
    is, plus welke bron niet antwoordde.
    """
    shop = Clipart(
        kernel,
        Drawing(kernel),
        fetch=answers(commons=WIKI_ANSWER, openclipart=TimeoutError()),
    )

    found = shop.search("hart", sources=["wikimedia", "openclipart"])

    assert [r["source"] for r in found["results"]] == ["Wikimedia Commons"]
    assert found["unavailable"] == {"openclipart": "reageerde niet op tijd"}


def test_both_down_is_reported_not_pretended_empty(kernel):
    shop = Clipart(
        kernel,
        Drawing(kernel),
        fetch=answers(commons=TimeoutError(), openclipart=TimeoutError()),
    )

    found = shop.search("hart", sources=["wikimedia", "openclipart"])

    assert found["results"] == []
    assert set(found["unavailable"]) == {"wikimedia", "openclipart"}


def test_a_one_letter_search_is_refused(shop):
    with pytest.raises(DesignError):
        shop.search("a")


# ------------------------------------------------------------------ invoegen


@pytest.fixture
def inserter(kernel):
    return Clipart(
        kernel,
        Drawing(kernel),
        fetch=answers(
            **{"hart.svg": A_DRAWING, "rommel.svg": A_MESSY_DRAWING}
        ),
    )


def test_inserting_places_it_at_the_size_you_asked_for(kernel, inserter):
    from meerk40t.core.units import UNITS_PER_MM

    result = inserter.insert(
        "https://upload.wikimedia.org/hart.svg", width_mm=50, x_mm=20, y_mm=30
    )

    assert result["count"] >= 1
    nodes = [n for n in kernel.elements.elems() if getattr(n, "bounds", None)]
    x0 = min(n.bounds[0] for n in nodes) / UNITS_PER_MM
    y0 = min(n.bounds[1] for n in nodes) / UNITS_PER_MM
    x1 = max(n.bounds[2] for n in nodes) / UNITS_PER_MM
    assert (x1 - x0) == pytest.approx(50, abs=0.5)
    assert x0 == pytest.approx(20, abs=0.5)
    assert y0 == pytest.approx(30, abs=0.5)


def test_what_a_laser_cannot_do_is_reported(inserter):
    """
    Gradiënten en tekst komen niet mee. Dat hoor je te weten voordat je
    materiaal in de machine legt, niet erna.
    """
    result = inserter.insert("https://upload.wikimedia.org/rommel.svg")

    assert any("kleurverlopen" in note for note in result["notes"])
    assert any("tekst" in note for note in result["notes"])


def test_a_random_address_is_not_fetched(inserter):
    """De server iets willekeurigs laten ophalen is een open deur."""
    for url in (
        "https://voorbeeld.nl/iets.svg",
        "http://upload.wikimedia.org/hart.svg",
        "file:///etc/passwd",
    ):
        with pytest.raises(DesignError):
            inserter.insert(url)


def test_an_absurd_width_is_refused(inserter):
    with pytest.raises(DesignError):
        inserter.insert("https://upload.wikimedia.org/hart.svg", width_mm=9000)


def test_the_routes_work_end_to_end(kernel, tmp_path):
    server = ApiServer(kernel, library_path=tmp_path / "cl.db")
    server.clipart.fetch = answers(
        commons=WIKI_ANSWER,
        openclipart=CLIPART_ANSWER,
        **{"hart.svg": A_DRAWING},
    )
    with TestClient(server.build_app()) as client:
        found = client.get("/api/clipart/search", params={"q": "hart"})
        assert found.status_code == 200
        assert found.json()["results"]

        made = client.post(
            "/api/clipart/insert",
            json={"url": "https://upload.wikimedia.org/hart.svg", "width_mm": 40},
        )
        assert made.status_code == 201
        assert client.get("/api/design").json()["elements"]


def test_a_very_busy_drawing_is_flagged(kernel):
    """
    Een tekening uit een encyclopedie heeft zo duizend paden. Dat brandt niet
    fout, maar het duurt uren — en dat weet je liever voordat je begint.
    """
    from openkerf_api.drawing import Drawing

    busy = (
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        + b'<path d="M 1 1 L 9 9"/>' * 500
        + b"</svg>"
    )
    shop = Clipart(kernel, Drawing(kernel), fetch=answers(**{"druk.svg": busy}))

    result = shop.insert("https://upload.wikimedia.org/druk.svg")

    assert any("losse paden" in note for note in result["notes"])


def watcher(kernel):
    """Een neppe bron die onthoudt welke URL's er gevraagd zijn."""
    from openkerf_api.drawing import Drawing

    asked = []

    def fetch(url, timeout=None):
        asked.append(url)
        if "commons" in url:
            return json.dumps(WIKI_ANSWER).encode()
        if "iconify" in url:
            return json.dumps(ICONIFY_ANSWER).encode()
        return json.dumps(CLIPART_ANSWER).encode()

    return Clipart(kernel, Drawing(kernel), fetch=fetch), asked


def test_paging_asks_the_sources_for_the_next_batch(kernel):
    """
    Twaalf resultaten is vaak te weinig om te vinden wat je zoekt. De twee
    bronnen tellen anders: Commons in een beginpositie, Openclipart in
    pagina's.
    """
    shop, asked = watcher(kernel)

    shop.search("hart", limit=24, page=3)

    assert "gsroffset=16" in next(u for u in asked if "commons" in u)
    assert "page=3" in next(u for u in asked if "openclipart" in u)
    assert "start=16" in next(u for u in asked if "iconify" in u)


def test_the_first_page_starts_at_the_beginning(kernel):
    shop, asked = watcher(kernel)

    shop.search("hart")

    assert "gsroffset=0" in next(u for u in asked if "commons" in u)
    assert "page=1" in next(u for u in asked if "openclipart" in u)
    assert "start=0" in next(u for u in asked if "iconify" in u)


def test_a_half_empty_page_means_the_end(shop):
    """
    Geen van beide API's zegt hoeveel resultaten er in totaal zijn. Een pagina
    die niet vol raakt, is dus het eerlijkste teken dat we er zijn.
    """
    found = shop.search("hart", limit=24)

    assert found["page"] == 1
    assert found["has_more"] is False


def test_an_absurd_page_is_refused(shop):
    for page in (0, -3, 500, "twee"):
        with pytest.raises(DesignError):
            shop.search("hart", page=page)


def test_iconify_carries_its_set_licence(shop):
    """De licentie verschilt per iconenset en staat in hetzelfde antwoord."""
    icon = next(r for r in shop.search("hart")["results"] if r["source"] == "Iconify")

    assert icon["license"] == "Apache 2.0"
    assert icon["author"] == "Pictogrammers"


def test_an_icon_gets_a_real_size_and_colour(shop):
    """
    Iconify levert standaard een vierkantje van 1em in de tekstkleur. Zonder
    echte maat en kleur weet de engine niet wat hij moet tekenen.
    """
    icon = next(r for r in shop.search("hart")["results"] if r["source"] == "Iconify")

    assert "height=240" in icon["svg_url"]
    assert "color=%23000000" in icon["svg_url"]


def test_an_icon_can_be_inserted(kernel):
    from openkerf_api.drawing import Drawing

    shop = Clipart(
        kernel, Drawing(kernel), fetch=answers(**{"iconify": A_DRAWING})
    )

    result = shop.insert("https://api.iconify.design/mdi/heart.svg?height=240")

    assert result["count"] >= 1
