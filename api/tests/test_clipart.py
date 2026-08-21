"""
Searching clipart in public collections.

No network in the tests: the fetch function is injectable. That is not only handy
but necessary — a test that depends on Wikimedia fails one day without anything
being broken.
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
                "title": "File:Heart.svg",
                "imageinfo": [
                    {
                        "mime": "image/svg+xml",
                        "url": "https://upload.wikimedia.org/heart.svg?utm_source=x",
                        "thumburl": "https://upload.wikimedia.org/thumb/heart.png",
                        "descriptionurl": "https://commons.wikimedia.org/wiki/File:Heart.svg",
                        "extmetadata": {
                            "LicenseShortName": {"value": "CC0"},
                            "Artist": {"value": '<a href="x">Somebody</a>'},
                        },
                    }
                ],
            },
            "2": {
                "pageid": 2,
                "title": "File:Photo.jpg",
                "imageinfo": [
                    {"mime": "image/jpeg", "url": "https://upload.wikimedia.org/photo.jpg"}
                ],
            },
        }
    }
}

CLIPART_ANSWER = {
    "payload": [
        {
            "id": 77,
            "title": "star",
            "uploader": "somebody",
            "detail_link": "https://openclipart.org/detail/77",
            "svg": {
                "url": "https://openclipart.org/download/77/star.svg",
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
  <text x="10" y="20">hello</text>
  <path d="M 10 10 L 90 10 L 90 90 Z" fill="url(#g)"/>
</svg>"""


def answers(**by_fragment):
    """A fake fetch function: picks an answer on what the URL holds."""

    def fetch(url, timeout=None):
        for fragment, payload in by_fragment.items():
            if fragment in url:
                if isinstance(payload, Exception):
                    raise payload
                if isinstance(payload, bytes):
                    return payload
                return json.dumps(payload).encode()
        raise AssertionError(f"unexpected url: {url}")

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
    found = shop.search("heart")

    sources = {r["source"] for r in found["results"]}
    assert sources == {"Iconify", "Wikimedia Commons", "Openclipart"}
    assert found["unavailable"] == {}


def test_only_vectors_from_wikimedia(shop):
    """A JPEG out of Commons is a very different conversation for a laser."""
    titles = [r["title"] for r in shop.search("heart", sources=["wikimedia"])["results"]]

    assert titles == ["Heart.svg"]


def test_the_tracking_tail_is_stripped(shop):
    """
    Commons hangs `?utm_source=` on the end of its URLs. The file-name filter
    tripped over that, and it does not belong in our design either.
    """
    first = shop.search("heart", sources=["wikimedia"])["results"][0]

    assert first["svg_url"] == "https://upload.wikimedia.org/heart.svg"


def test_a_source_that_answers_nonsense_says_so_plainly(kernel):
    """On a fault Openclipart hands back HTML; a parse error helps nobody."""
    from openkerf_api.drawing import Drawing

    def fetch(url, timeout=None):
        if "commons" in url:
            return json.dumps(WIKI_ANSWER).encode()
        return b"<html>maintenance</html>"

    shop = Clipart(kernel, Drawing(kernel), fetch=fetch)

    assert shop.search("heart", sources=["wikimedia", "openclipart"])[
        "unavailable"
    ] == {"openclipart": "gave an unexpected answer"}


def test_the_licence_travels_along(shop):
    """People who laser sell what they cut, so the licence has to be visible."""
    first = shop.search("heart", sources=["wikimedia"])["results"][0]

    assert first["license"] == "CC0"
    # Wikimedia hands HTML in its metadata; nobody wants to see that.
    assert first["author"] == "Somebody"


def test_a_source_that_is_down_does_not_hold_up_the_rest(kernel):
    """
    Openclipart is down fairly regularly. Then you should see what there *is*,
    plus which source did not answer.
    """
    shop = Clipart(
        kernel,
        Drawing(kernel),
        fetch=answers(commons=WIKI_ANSWER, openclipart=TimeoutError()),
    )

    found = shop.search("heart", sources=["wikimedia", "openclipart"])

    assert [r["source"] for r in found["results"]] == ["Wikimedia Commons"]
    assert found["unavailable"] == {"openclipart": "did not answer in time"}


def test_both_down_is_reported_not_pretended_empty(kernel):
    shop = Clipart(
        kernel,
        Drawing(kernel),
        fetch=answers(commons=TimeoutError(), openclipart=TimeoutError()),
    )

    found = shop.search("heart", sources=["wikimedia", "openclipart"])

    assert found["results"] == []
    assert set(found["unavailable"]) == {"wikimedia", "openclipart"}


def test_a_one_letter_search_is_refused(shop):
    with pytest.raises(DesignError):
        shop.search("a")


# ------------------------------------------------------------------ inserting


@pytest.fixture
def inserter(kernel):
    return Clipart(
        kernel,
        Drawing(kernel),
        fetch=answers(
            **{"heart.svg": A_DRAWING, "mess.svg": A_MESSY_DRAWING}
        ),
    )


def test_inserting_places_it_at_the_size_you_asked_for(kernel, inserter):
    from meerk40t.core.units import UNITS_PER_MM

    result = inserter.insert(
        "https://upload.wikimedia.org/heart.svg", width_mm=50, x_mm=20, y_mm=30
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
    Gradients and text do not come along. You should know that before you put
    material in the machine, not after.
    """
    result = inserter.insert("https://upload.wikimedia.org/mess.svg")

    assert any("gradients" in note for note in result["notes"])
    assert any("text" in note for note in result["notes"])


def test_a_random_address_is_not_fetched(inserter):
    """Letting the server fetch something arbitrary is an open door."""
    for url in (
        "https://example.com/something.svg",
        "http://upload.wikimedia.org/heart.svg",
        "file:///etc/passwd",
    ):
        with pytest.raises(DesignError):
            inserter.insert(url)


def test_an_absurd_width_is_refused(inserter):
    with pytest.raises(DesignError):
        inserter.insert("https://upload.wikimedia.org/heart.svg", width_mm=9000)


def test_the_routes_work_end_to_end(kernel, tmp_path):
    server = ApiServer(kernel, library_path=tmp_path / "cl.db")
    server.clipart.fetch = answers(
        commons=WIKI_ANSWER,
        openclipart=CLIPART_ANSWER,
        **{"heart.svg": A_DRAWING},
    )
    with TestClient(server.build_app()) as client:
        found = client.get("/api/clipart/search", params={"q": "heart"})
        assert found.status_code == 200
        assert found.json()["results"]

        made = client.post(
            "/api/clipart/insert",
            json={"url": "https://upload.wikimedia.org/heart.svg", "width_mm": 40},
        )
        assert made.status_code == 201
        assert client.get("/api/design").json()["elements"]


def test_a_very_busy_drawing_is_flagged(kernel):
    """
    A drawing out of an encyclopedia easily has a thousand paths. That does not
    burn wrong, but it takes hours — and you would rather know before you start.
    """
    from openkerf_api.drawing import Drawing

    busy = (
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        + b'<path d="M 1 1 L 9 9"/>' * 500
        + b"</svg>"
    )
    shop = Clipart(kernel, Drawing(kernel), fetch=answers(**{"busy.svg": busy}))

    result = shop.insert("https://upload.wikimedia.org/busy.svg")

    assert any("loose paths" in note for note in result["notes"])


def watcher(kernel):
    """A fake source that remembers which URLs were asked for."""
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
    Twelve results is often too few to find what you are after. The two sources
    count differently: Commons in a start offset, Openclipart in pages.
    """
    shop, asked = watcher(kernel)

    shop.search("heart", limit=24, page=3)

    assert "gsroffset=16" in next(u for u in asked if "commons" in u)
    assert "page=3" in next(u for u in asked if "openclipart" in u)
    assert "start=16" in next(u for u in asked if "iconify" in u)


def test_the_first_page_starts_at_the_beginning(kernel):
    shop, asked = watcher(kernel)

    shop.search("heart")

    assert "gsroffset=0" in next(u for u in asked if "commons" in u)
    assert "page=1" in next(u for u in asked if "openclipart" in u)
    assert "start=0" in next(u for u in asked if "iconify" in u)


def test_a_half_empty_page_means_the_end(shop):
    """
    Neither API says how many results there are in total. So a page that does not
    fill up is the most honest sign that we are at the end.
    """
    found = shop.search("heart", limit=24)

    assert found["page"] == 1
    assert found["has_more"] is False


def test_an_absurd_page_is_refused(shop):
    for page in (0, -3, 500, "two"):
        with pytest.raises(DesignError):
            shop.search("heart", page=page)


def test_iconify_carries_its_set_licence(shop):
    """The licence differs per icon set and sits in the same answer."""
    icon = next(r for r in shop.search("heart")["results"] if r["source"] == "Iconify")

    assert icon["license"] == "Apache 2.0"
    assert icon["author"] == "Pictogrammers"


def test_an_icon_gets_a_real_size_and_colour(shop):
    """
    By default Iconify hands back a 1em square in the text colour. Without a real
    size and colour the engine does not know what to draw.
    """
    icon = next(r for r in shop.search("heart")["results"] if r["source"] == "Iconify")

    assert "height=240" in icon["svg_url"]
    assert "color=%23000000" in icon["svg_url"]


def test_an_icon_can_be_inserted(kernel):
    from openkerf_api.drawing import Drawing

    shop = Clipart(
        kernel, Drawing(kernel), fetch=answers(**{"iconify": A_DRAWING})
    )

    result = shop.insert("https://api.iconify.design/mdi/heart.svg?height=240")

    assert result["count"] >= 1
