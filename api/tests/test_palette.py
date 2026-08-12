"""
Besluit B2: het palet met geheugen, en het verschil met een preset.

Twee dingen worden hier bewaakt. Ten eerste dat één klik op een kleur genoeg is
om een vorm van laag te laten wisselen — dat is de hele winst. Ten tweede dat
het geheugen en de herkomst gescheiden blijven: een onthouden getal mag nooit
als "gemeten" gaan gelden.
"""

import pytest
from fastapi.testclient import TestClient

from openkerf_api.palette import Palette, machine_key, normalise
from openkerf_api.server import ApiServer

ROOD = "#e5484d"
BLAUW = "#0090ff"


@pytest.fixture
def server(kernel, tmp_path):
    return ApiServer(kernel, library_path=tmp_path / "bibliotheek.db")


@pytest.fixture
def client(server):
    with TestClient(server.build_app()) as c:
        yield c


def _rect(client, x=10.0):
    response = client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": x, "y_mm": 10, "width_mm": 20, "height_mm": 20},
    )
    assert response.status_code == 201, response.text
    return response.json()["ids"][0]


def _layer_of(client, element_id):
    design = client.get("/api/design").json()
    element = next(e for e in design["elements"] if e["id"] == element_id)
    return element["operation_ids"]


def _op(client, operation_id):
    design = client.get("/api/design").json()
    return next(o for o in design["operations"] if o["id"] == operation_id)


# ------------------------------------------------------------------- opslag


def test_memory_survives_a_new_store_on_the_same_file(tmp_path):
    path = tmp_path / "palet.json"
    Palette(path).remember("machine-1", ROOD, speed=12, power_percent=65)

    assert Palette(path).recall("machine-1", ROOD)["speed_mm_s"] == 12


def test_memory_is_per_machine(tmp_path):
    palette = Palette(tmp_path / "palet.json")
    palette.remember("machine-1", ROOD, speed=12, power_percent=65)
    palette.remember("machine-2", ROOD, speed=300, power_percent=20)

    assert palette.recall("machine-1", ROOD)["speed_mm_s"] == 12
    assert palette.recall("machine-2", ROOD)["speed_mm_s"] == 300


def test_a_half_update_keeps_the_other_half(tmp_path):
    """Wie alleen de snelheid bijstelt, verliest het vermogen niet."""
    palette = Palette(tmp_path / "palet.json")
    palette.remember("m", ROOD, speed=12, power_percent=65)
    palette.remember("m", ROOD, speed=14)

    entry = palette.recall("m", ROOD)
    assert (entry["speed_mm_s"], entry["power_percent"]) == (14, 65)


def test_only_real_colours_are_stored(tmp_path):
    palette = Palette(tmp_path / "palet.json")
    assert palette.remember("m", "rood", speed=12) is None
    assert palette.recall("m", "rood") is None
    assert normalise("#E5484D") == ROOD
    assert normalise("#xyzxyz") is None


def test_no_machine_still_has_a_key():
    assert machine_key(None) == machine_key({})


# ------------------------------------------------------------------- routes


def test_palette_lists_ten_colours_with_their_memory(client):
    body = client.get("/api/design/palette").json()

    from openkerf_api.drawing import Drawing

    assert [c["color"] for c in body["colors"]] == [k.lower() for k in Drawing.PALETTE]
    assert all(c["memory"] is None for c in body["colors"])
    assert body["machine"]["key"]


def test_one_click_moves_a_shape_to_the_colour_layer(client):
    """
    De meting uit de opdracht: van drie handelingen naar één.

    Drie waren het via het lagenpaneel — tabblad Lagen, de laag opzoeken, "hierin".
    Hier is het één verzoek, en de vorm zit erna in precies één laag.
    """
    element = _rect(client)

    response = client.post("/api/design/palette", json={"color": BLAUW, "ids": [element]})

    assert response.status_code == 200, response.text
    operation_id = response.json()["operation_id"]
    assert _layer_of(client, element) == [operation_id]
    assert _op(client, operation_id)["color"] == BLAUW


def test_moving_does_not_leave_the_shape_in_its_old_layer(client):
    """Twee lagen betekent twee keer branden — daar is een verhuizing geen verhuizing."""
    element = _rect(client)
    first = client.post("/api/design/palette", json={"color": ROOD, "ids": [element]})
    tweede = client.post("/api/design/palette", json={"color": BLAUW, "ids": [element]})

    assert _layer_of(client, element) == [tweede.json()["operation_id"]]
    assert first.json()["operation_id"] not in _layer_of(client, element)


def test_a_fresh_layer_starts_on_what_the_colour_did_before(client, server):
    """
    Het hele punt van B2. Zet een kleur op 42 mm/s, gooi de laag weg, klik de
    kleur opnieuw: de nieuwe laag begint op 42, niet blanco.
    """
    element = _rect(client)
    eerste = client.post(
        "/api/design/palette", json={"color": BLAUW, "ids": [element]}
    ).json()["operation_id"]
    client.patch(
        f"/api/design/operations/{eerste}", json={"speed": 42, "power_percent": 33}
    )
    client.delete(f"/api/design/operations/{eerste}")

    tweede = client.post(
        "/api/design/palette", json={"color": BLAUW, "ids": [element]}
    ).json()["operation_id"]

    layer = _op(client, tweede)
    assert layer["speed"] == 42
    assert layer["power"] == 330


def test_the_strip_reports_the_memory_it_will_use(client):
    element = _rect(client)
    operation = client.post(
        "/api/design/palette", json={"color": BLAUW, "ids": [element]}
    ).json()["operation_id"]
    client.patch(f"/api/design/operations/{operation}", json={"speed": 42})

    onthouden = {
        c["color"]: c["memory"] for c in client.get("/api/design/palette").json()["colors"]
    }
    assert onthouden[BLAUW]["speed_mm_s"] == 42
    assert onthouden[ROOD] is None


def test_clicking_without_a_selection_sets_the_colour_for_new_work(client, server):
    response = client.post("/api/design/palette", json={"color": BLAUW})

    assert response.status_code == 200, response.text
    assert response.json()["operation_id"] is None
    assert server.drawing.default_color() == BLAUW
    assert client.get("/api/design/palette").json()["default_color"] == BLAUW

    # En een verse vorm komt er dan ook in terecht.
    element = _rect(client)
    design = client.get("/api/design").json()
    stroke = next(e for e in design["elements"] if e["id"] == element)["stroke"]
    assert stroke.lower() == BLAUW


def test_drawing_in_a_remembered_colour_seeds_the_layer_the_engine_makes(client):
    """
    De andere helft van de belofte.

    Kies je een kleur zonder laag en teken je daarna, dan maakt de engine zelf
    de laag aan — niet wij. Zonder ingreep begon die op de fabriekswaarde,
    terwijl de gebruiker net een kleur koos waarvan hij weet wat hij ermee deed.
    """
    element = _rect(client)
    operation = client.post(
        "/api/design/palette", json={"color": BLAUW, "ids": [element]}
    ).json()["operation_id"]
    client.patch(
        f"/api/design/operations/{operation}", json={"speed": 77, "power_percent": 22}
    )
    client.post("/api/design/elements/delete", json={"ids": [element]})
    client.delete(f"/api/design/operations/{operation}")

    client.post("/api/design/palette", json={"color": BLAUW})
    verse = _rect(client, x=60)

    design = client.get("/api/design").json()
    laag = next(
        o
        for o in design["operations"]
        if verse in o["element_ids"] and (o["color"] or "").lower() == BLAUW
    )
    assert laag["speed"] == 77
    assert laag["power"] == 220


def test_a_bad_colour_is_refused(client):
    assert client.post("/api/design/palette", json={"color": "rood"}).status_code == 409


def test_the_memory_is_not_a_provenance(client, server):
    """
    Het onderscheid dat B2 expliciet maakt.

    Het palet onthoudt wat je deed; de herkomst zegt dat er iets gebrand is.
    Een laag die zijn waarden uit het geheugen kreeg, mag dus geen herkomst
    hebben — anders leest gewoonte als bewijs.
    """
    element = _rect(client)
    operation = client.post(
        "/api/design/palette", json={"color": BLAUW, "ids": [element]}
    ).json()["operation_id"]
    client.patch(f"/api/design/operations/{operation}", json={"speed": 42})
    client.delete(f"/api/design/operations/{operation}")
    opnieuw = client.post(
        "/api/design/palette", json={"color": BLAUW, "ids": [element]}
    ).json()["operation_id"]

    assert server.provenance.lookup(server.sheets.active_id, opnieuw, 42, None) is None
