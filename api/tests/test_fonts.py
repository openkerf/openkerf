"""
Making your own fonts usable.

The engine reads only .ttf, .shx and .jhf and keeps its list in a cache. So a
freshly installed .otf is invisible — even when it simply holds TrueType
outlines, which it often does.
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
    With a font folder of its own. Without this the tests write into the engine's
    real folder: they then leak into each other *and* into the user's install.
    """
    shop = Fonts(kernel)
    kernel.root.setting(str, "font_directory", str(tmp_path / "fontmap"))
    kernel.root.font_directory = str(tmp_path / "fontmap")
    (tmp_path / "fontmap").mkdir()
    return shop


def a_font(path, cff=False):
    """A minimal font, in TrueType or PostScript flavour."""
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
        builder.setupCFF("Trial", {}, {".notdef": pen.getCharString(), "A": pen.getCharString()}, {})
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
    builder.setupNameTable({"familyName": "Trial", "styleName": "Regular"})
    builder.setupOS2()
    builder.setupPost()
    builder.save(str(path))
    return path


def test_an_otf_outside_a_font_folder_is_refused(fonts, tmp_path):
    """Letting the server read an arbitrary path is an open door."""
    with pytest.raises(DesignError, match="font folder"):
        fonts.import_font(str(a_font(tmp_path / "Trial.otf")))


def test_an_otf_with_truetype_outlines_is_just_copied(fonts, tmp_path, monkeypatch):
    """
    Plenty of .otf files simply hold TrueType outlines; then it is only an
    extension that differs. Exactly the case that started this.
    """
    import openkerf_api.fonts as module

    monkeypatch.setattr(module, "SEARCH", (str(tmp_path),))
    source = a_font(tmp_path / "Galaxy.otf")

    added = fonts.import_font(str(source))

    assert added["name"] == "Galaxy"
    assert added["file"].endswith(".ttf")

    from fontTools.ttLib import TTFont

    assert "glyf" in TTFont(added["file"])


def test_a_postscript_font_is_converted(fonts, tmp_path, monkeypatch):
    """If there is CFF in it, the outlines really have to be converted."""
    import openkerf_api.fonts as module

    monkeypatch.setattr(module, "SEARCH", (str(tmp_path),))
    source = a_font(tmp_path / "Curve.otf", cff=True)

    from fontTools.ttLib import TTFont

    assert "CFF " in TTFont(str(source))

    added = fonts.import_font(str(source))

    converted = TTFont(added["file"])
    assert "glyf" in converted
    assert "CFF " not in converted


def test_importing_the_same_font_twice_is_refused(fonts, tmp_path, monkeypatch):
    import openkerf_api.fonts as module

    monkeypatch.setattr(module, "SEARCH", (str(tmp_path),))
    source = a_font(tmp_path / "Once.otf")
    fonts.import_font(str(source))

    with pytest.raises(DesignError, match="already there"):
        fonts.import_font(str(source))


def test_an_imported_font_shows_up_in_the_list(client, tmp_path, monkeypatch):
    """
    Without a refresh it stays invisible: the list comes out of a cache file.
    """
    import openkerf_api.fonts as module

    monkeypatch.setattr(module, "SEARCH", (str(tmp_path),))
    source = a_font(tmp_path / "Apparition.otf")

    client.post("/api/design/fonts/import", json={"file": str(source)})

    names = [f["name"] for f in client.get("/api/design/fonts?refresh=true").json()]
    assert any("Trial" in name or "Apparition" in name for name in names)


def test_a_file_that_is_not_a_font_is_refused(fonts, tmp_path, monkeypatch):
    import openkerf_api.fonts as module

    monkeypatch.setattr(module, "SEARCH", (str(tmp_path),))
    fake = tmp_path / "Fake.otf"
    fake.write_bytes(b"this is not a font")

    with pytest.raises(DesignError, match="cannot be read"):
        fonts.import_font(str(fake))


def test_the_preview_endpoint_only_serves_fonts_the_engine_knows(client, tmp_path, monkeypatch):
    """
    Look a name up in the list, do not treat it as a path: otherwise this is a
    readable window onto the whole disk.
    """
    import openkerf_api.fonts as module

    monkeypatch.setattr(module, "SEARCH", (str(tmp_path),))
    secret = tmp_path / "secret.txt"
    secret.write_text("not for the browser")

    assert client.get("/api/design/fonts/file", params={"name": str(secret)}).status_code == 409
    assert client.get("/api/design/fonts/file", params={"name": "/etc/passwd"}).status_code == 409


def test_a_known_font_is_served_as_bytes(client, fonts, tmp_path, monkeypatch):
    """The picker can only show a name in its own letters once this works."""
    import openkerf_api.fonts as module

    monkeypatch.setattr(module, "SEARCH", (str(tmp_path),))
    a_font(tmp_path / "Exemplary.otf")
    added = client.post(
        "/api/design/fonts/import", json={"file": str(tmp_path / "Exemplary.otf")}
    ).json()

    response = client.get("/api/design/fonts/file", params={"name": added["file"]})

    assert response.status_code == 200
    # The signature of a TrueType file; an HTML error page does not have it.
    assert response.content[:4] in (b"\x00\x01\x00\x00", b"true", b"ttcf")
