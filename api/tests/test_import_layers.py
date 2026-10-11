"""
An import puts every new shape in exactly one layer, and reuses the user's layers.

Found on a real project ("Monitor Lijst", sheet "Laag 1 Vel 2"): after an import the
layer list read "Standard-Raster" twice and "Cut" twice, and 31 of the 59 shapes sat in
two layers — engraved twice. The drawing below has the structure of that file
(`laag1_vel2.svg` from the monitor-greebles project): blue filled rectangles in one
`<g fill="#0000ff">`, red outlines in one `<g stroke="#ff0000">`, plus one blue label as
`<text>`, which comes in as vector text.

The cause is the engine's classification (`Elements.classify`): it classifies the `<g>`
groups as well as their shapes. A group matches no layer, so it gets a fresh one from the
defaults — unless a layer of the same type, colour *and speed* exists. Once the user has
set their own speed, that check fails, a default layer is added beside theirs, and every
filled (red) shape lands in both raster (cut) layers. `Drawing.settle_import` repairs it.
"""

from collections import Counter

import pytest
from fastapi.testclient import TestClient

from openkerf_api.server import ApiServer

PLATE = b"""<svg xmlns="http://www.w3.org/2000/svg" width="500mm" height="300mm" viewBox="0 0 500 300">
<g fill="#0000ff" stroke="none">
<rect x="224.12" y="27.35" width="2.70" height="0.90"/>
<rect x="223.22" y="28.25" width="0.90" height="0.90"/>
<rect x="226.82" y="28.25" width="0.90" height="0.90"/>
<rect x="174.25" y="82.25" width="4.50" height="0.90"/>
<text x="100" y="150" font-family="Helvetica, Arial, sans-serif" font-size="6">L1-02</text>
</g>
<g fill="none" stroke="#ff0000" stroke-width="0.1">
<polygon points="5.00,56.00 451.33,56.00 451.33,5.00 5.00,5.00"/>
<circle cx="421.33" cy="51.00" r="1.9"/>
<circle cx="389.21" cy="16.16" r="3.25"/>
</g>
</svg>"""

# Five blue shapes (four rectangles and the label) and three red ones per import.
BLUE, RED = 5, 3

USER_RASTER = {"speed": 350, "power_percent": 25}
USER_CUT = {"speed": 10, "power_percent": 85}


@pytest.fixture
def client(kernel, tmp_path):
    with TestClient(ApiServer(kernel, library_path=tmp_path / "d.db").build_app()) as c:
        yield c


def _import(client, svg=PLATE, name="plate.svg") -> dict:
    response = client.post("/api/job/load", files={"file": (name, svg, "image/svg+xml")})
    assert response.status_code == 200, response.text
    return response.json()


def _set_up_layers(client) -> None:
    """What the user did: their own speed and power on the black and the red layer."""
    for layer in client.get("/api/design").json()["operations"]:
        body = USER_RASTER if layer["type"] == "op raster" else USER_CUT
        response = client.patch(f"/api/design/operations/{layer['id']}", json=body)
        assert response.status_code == 200, response.text


def _membership(design) -> Counter:
    """How many shapes sit in 0, 1, 2 … layers."""
    return Counter(len(e["operation_ids"]) for e in design["elements"])


def _layers(design) -> list[tuple]:
    return sorted(
        (o["type"], round(o["speed"]), round(float(o["power"])), len(o["element_ids"]))
        for o in design["operations"]
    )


def _switch_away_and_back(client) -> str:
    """Save the sheet and load it again, the way every sheet switch does."""
    sheets = client.post("/api/sheets", json={})
    assert sheets.status_code == 201, sheets.text
    other = sheets.json()["sheets"][-1]["id"]
    first = sheets.json()["active"]
    assert client.post(f"/api/sheets/{other}/activate").status_code == 200
    assert client.post(f"/api/sheets/{first}/activate").status_code == 200
    return other


def test_a_second_import_after_a_sheet_switch_reuses_the_users_layers(client):
    """
    The user's sequence: import, set the layers, switch sheets away and back, import.

    Before: 4 layers — the user's raster (350 mm/s, power 250) and cut (10 mm/s, 850)
    plus a default raster (150 mm/s, 1000) and cut (1 mm/s, 1000) — and the 8 new shapes
    each in 2 of them. After: 2 layers, every shape in exactly 1.
    """
    _import(client)
    _set_up_layers(client)
    _switch_away_and_back(client)

    result = _import(client)

    design = client.get("/api/design").json()
    assert result["count"] == BLUE + RED
    assert result["unassigned"] == []
    assert _membership(design) == {1: 2 * (BLUE + RED)}
    assert _layers(design) == [
        ("op cut", 10, 850, 2 * RED),
        ("op raster", 350, 250, 2 * BLUE),
    ]


def test_a_second_import_on_the_same_sheet_reuses_the_users_layers(client):
    """
    Without the sheet switch the engine does the same. Before: 4 layers and the 8 new
    shapes in 2 each; after: 2 layers, every shape in 1.
    """
    _import(client)
    _set_up_layers(client)

    result = _import(client)

    design = client.get("/api/design").json()
    assert result["unassigned"] == []
    assert _membership(design) == {1: 2 * (BLUE + RED)}
    assert _layers(design) == [
        ("op cut", 10, 850, 2 * RED),
        ("op raster", 350, 250, 2 * BLUE),
    ]


def test_the_imported_shapes_stay_selected_and_the_label_becomes_a_shape(client):
    """What an import did before stays: ids reported and selected, text outlined."""
    _import(client)
    _set_up_layers(client)
    result = _import(client)

    design = client.get("/api/design").json()
    texts = [e for e in design["elements"] if e["text"]]
    assert len(texts) == 2
    assert all(len(t["operation_ids"]) == 1 for t in texts)
    assert result["unreadable_texts"] == []
    assert len(result["added"]) == BLUE + RED
    assert set(result["added"]) <= {e["id"] for e in design["elements"]}


def test_a_new_sheet_starts_with_the_layers_of_the_sheet_it_was_added_from(client):
    """
    Before: a new sheet had no layers, and an import there got the engine's defaults —
    raster 150 mm/s @ power 1000 and cut 1 mm/s @ 1000. After: the two layers come along
    empty with the user's values, and the import fills those, one layer per shape.
    """
    _import(client)
    _set_up_layers(client)
    added = client.post("/api/sheets", json={}).json()["sheets"][-1]["id"]
    assert client.post(f"/api/sheets/{added}/activate").status_code == 200

    empty = client.get("/api/design").json()
    assert empty["elements"] == []
    assert _layers(empty) == [("op cut", 10, 850, 0), ("op raster", 350, 250, 0)]

    result = _import(client)

    design = client.get("/api/design").json()
    assert result["unassigned"] == []
    assert _membership(design) == {1: BLUE + RED}
    assert _layers(design) == [("op cut", 10, 850, RED), ("op raster", 350, 250, BLUE)]


def test_the_kept_layers_survive_saving_the_project(client):
    """An empty new sheet in a saved project still opens with its layers."""
    _import(client)
    _set_up_layers(client)
    added = client.post("/api/sheets", json={}).json()["sheets"][-1]["id"]
    saved = client.post("/api/projects/Kept layers")
    assert saved.status_code == 200, saved.text
    assert client.post("/api/project/new").status_code == 200
    opened = client.post("/api/projects/Kept layers/open")
    assert opened.status_code == 200, opened.text
    assert client.post(f"/api/sheets/{added}/activate").status_code == 200

    assert _layers(client.get("/api/design").json()) == [
        ("op cut", 10, 850, 0),
        ("op raster", 350, 250, 0),
    ]


def test_a_colour_nobody_has_a_layer_for_still_gets_one(client):
    """A green outline on a sheet with the user's layers: one new layer, not none."""
    _import(client)
    _set_up_layers(client)
    green = (
        b'<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" '
        b'viewBox="0 0 100 100"><g fill="none" stroke="#00ff00">'
        b'<rect x="10" y="10" width="20" height="20"/></g></svg>'
    )

    result = _import(client, green, "green.svg")

    design = client.get("/api/design").json()
    assert result["unassigned"] == []
    assert _membership(design) == {1: BLUE + RED + 1}
    assert len(design["operations"]) == 3


# ------------------------------------------------------------------ groups

INKSCAPE = b"""<svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" width="100mm" height="100mm" viewBox="0 0 100 100">
<g inkscape:groupmode="layer" inkscape:label="Layer 1" id="layer1">
<g id="g12"><rect x="10" y="10" width="20" height="20" fill="none" stroke="#ff0000"/><circle cx="20" cy="20" r="3" fill="none" stroke="#ff0000"/></g>
<rect x="50" y="10" width="20" height="20" fill="none" stroke="#ff0000"/>
</g></svg>"""


def test_a_group_that_only_gives_its_shapes_a_colour_is_not_kept(client):
    """
    The user's files wrap every blue shape in one `<g fill="#0000ff">` and every red one
    in one `<g stroke="#ff0000">`. Before: `laag1_vel2.svg` came in as two groups of 38
    and 21, so one click on a letter selected all 38. After: every shape on its own.
    """
    result = _import(client)

    design = client.get("/api/design").json()
    assert [e["group_id"] for e in design["elements"]] == [None] * (BLUE + RED)
    assert set(result["added"]) == {e["id"] for e in design["elements"]}


def test_an_inkscape_layer_goes_and_a_part_group_stays(client):
    """
    Before: the layer `layer1` was a group around everything (1 shape directly, the part
    `g12` with 2). After: the layer is gone, the part `g12` (no colour of its own, two
    shapes) is still one group, and the loose rectangle is loose.
    """
    _import(client, INKSCAPE, "inkscape.svg")

    groups = Counter(e["group_id"] for e in client.get("/api/design").json()["elements"])
    assert groups == {"g12": 2, None: 1}
