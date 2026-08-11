"""
Eigen lettertypen bruikbaar maken.

De engine leest alleen .ttf, .shx en .jhf en houdt zijn lijst in een cache. Een
net geïnstalleerde .otf is dus onzichtbaar — ook als er gewoon TrueType-
omtrekken in zitten, wat vaak zo is.
"""

import pytest
from fastapi.testclient import TestClient

from openkerf_api.edits import DesignError
from openkerf_api.fonts import Fonts
from openkerf_api.server import ApiServer

fontTools = pytest.importorskip("fontTools")


@pytest.fixture
def client(kernel, tmp_path, fonts):
    with TestClient(ApiServer(kernel, library_path=tmp_path / "f.db").build_app()) as c:
        yield c


@pytest.fixture
def fonts(kernel, tmp_path):
    """
    Met een eigen fontmap. Zonder dit schrijven de tests in de échte map van de
    engine: ze lekken dan in elkaar én in de installatie van de gebruiker.
    """
    shop = Fonts(kernel)
    kernel.root.setting(str, "font_directory", str(tmp_path / "fontmap"))
    kernel.root.font_directory = str(tmp_path / "fontmap")
    (tmp_path / "fontmap").mkdir()
    return shop


def a_font(path, cff=False):
    """Een minimaal lettertype, in TrueType- of PostScript-smaak."""
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.t2CharStringPen import T2CharStringPen
    from fontTools.pens.ttGlyphPen import TTGlyphPen

    builder = FontBuilder(1000, isTTF=not cff)
    order = [".notdef", "A"]
    builder.setupGlyphOrder(order)
    builder.setupCharacterMap({65: "A"})
    if cff:
        pen = T2CharStringPen(600, None)
        pen.moveTo((100, 0))
        pen.lineTo((500, 0))
        pen.lineTo((300, 700))
        pen.closePath()
        builder.setupCFF("Proef", {}, {".notdef": pen.getCharString(), "A": pen.getCharString()}, {})
    else:
        pen = TTGlyphPen(None)
        pen.moveTo((100, 0))
        pen.lineTo((500, 0))
        pen.lineTo((300, 700))
        pen.closePath()
        glyph = pen.glyph()
        builder.setupGlyf({".notdef": glyph, "A": glyph})
    builder.setupHorizontalMetrics({name: (600, 100) for name in order})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable({"familyName": "Proef", "styleName": "Regular"})
    builder.setupOS2()
    builder.setupPost()
    builder.save(str(path))
    return path


def test_an_otf_outside_a_font_folder_is_refused(fonts, tmp_path):
    """De server een willekeurig pad laten inlezen is een open deur."""
    with pytest.raises(DesignError, match="lettertypemap"):
        fonts.import_font(str(a_font(tmp_path / "Proef.otf")))


def test_an_otf_with_truetype_outlines_is_just_copied(fonts, tmp_path, monkeypatch):
    """
    Veel .otf-bestanden bevatten gewoon TrueType-omtrekken; dan scheelt het
    alleen een extensie. Precies het geval dat dit begon.
    """
    import openkerf_api.fonts as module

    monkeypatch.setattr(module, "SEARCH", (str(tmp_path),))
    source = a_font(tmp_path / "Sterrenstelsel.otf")

    added = fonts.import_font(str(source))

    assert added["name"] == "Sterrenstelsel"
    assert added["file"].endswith(".ttf")

    from fontTools.ttLib import TTFont

    assert "glyf" in TTFont(added["file"])


def test_a_postscript_font_is_converted(fonts, tmp_path, monkeypatch):
    """Zit er CFF in, dan moeten de omtrekken echt omgezet worden."""
    import openkerf_api.fonts as module

    monkeypatch.setattr(module, "SEARCH", (str(tmp_path),))
    source = a_font(tmp_path / "Kromme.otf", cff=True)

    from fontTools.ttLib import TTFont

    assert "CFF " in TTFont(str(source))

    added = fonts.import_font(str(source))

    converted = TTFont(added["file"])
    assert "glyf" in converted
    assert "CFF " not in converted


def test_importing_the_same_font_twice_is_refused(fonts, tmp_path, monkeypatch):
    import openkerf_api.fonts as module

    monkeypatch.setattr(module, "SEARCH", (str(tmp_path),))
    source = a_font(tmp_path / "Eenmalig.otf")
    fonts.import_font(str(source))

    with pytest.raises(DesignError, match="staat er al"):
        fonts.import_font(str(source))


def test_an_imported_font_shows_up_in_the_list(client, tmp_path, monkeypatch):
    """
    Zonder verversen blijft hij onzichtbaar: de lijst komt uit een cachebestand.
    """
    import openkerf_api.fonts as module

    monkeypatch.setattr(module, "SEARCH", (str(tmp_path),))
    source = a_font(tmp_path / "Verschijnsel.otf")

    client.post("/api/design/fonts/import", json={"file": str(source)})

    names = [f["name"] for f in client.get("/api/design/fonts?refresh=true").json()]
    assert any("Proef" in name or "Verschijnsel" in name for name in names)


def test_a_file_that_is_not_a_font_is_refused(fonts, tmp_path, monkeypatch):
    import openkerf_api.fonts as module

    monkeypatch.setattr(module, "SEARCH", (str(tmp_path),))
    fake = tmp_path / "Nep.otf"
    fake.write_bytes(b"dit is geen lettertype")

    with pytest.raises(DesignError, match="niet te lezen"):
        fonts.import_font(str(fake))
