"""
Decision B2: the palette with a memory, and the difference from a preset.

Two things are guarded here. First that one click on a colour is enough to move a
shape to another layer — that is the whole gain. Second that the memory and the
provenance stay apart: a remembered number must never come to count as
"measured".
"""

import pytest
from fastapi.testclient import TestClient

from openkerf_api.palette import Palette, machine_key, normalise
from openkerf_api.server import ApiServer

RED = "#e5484d"
BLUE = "#0090ff"


@pytest.fixture
def server(kernel, tmp_path):
    return ApiServer(kernel, library_path=tmp_path / "library.db")


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


# ------------------------------------------------------------------- storage


def test_memory_survives_a_new_store_on_the_same_file(tmp_path):
    path = tmp_path / "palette.json"
    Palette(path).remember("machine-1", RED, speed=12, power_percent=65)

    assert Palette(path).recall("machine-1", RED)["speed_mm_s"] == 12


def test_memory_is_per_machine(tmp_path):
    palette = Palette(tmp_path / "palette.json")
    palette.remember("machine-1", RED, speed=12, power_percent=65)
    palette.remember("machine-2", RED, speed=300, power_percent=20)

    assert palette.recall("machine-1", RED)["speed_mm_s"] == 12
    assert palette.recall("machine-2", RED)["speed_mm_s"] == 300


def test_a_half_update_keeps_the_other_half(tmp_path):
    """Adjusting only the speed does not lose the power."""
    palette = Palette(tmp_path / "palette.json")
    palette.remember("m", RED, speed=12, power_percent=65)
    palette.remember("m", RED, speed=14)

    entry = palette.recall("m", RED)
    assert (entry["speed_mm_s"], entry["power_percent"]) == (14, 65)


def test_only_real_colours_are_stored(tmp_path):
    palette = Palette(tmp_path / "palette.json")
    assert palette.remember("m", "red", speed=12) is None
    assert palette.recall("m", "red") is None
    assert normalise("#E5484D") == RED
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
    The measurement from the brief: from three actions to one.

    Three it was through the layers panel — the Layers tab, find the layer, "into
    this". Here it is one request, and afterwards the shape is in exactly one layer.
    """
    element = _rect(client)

    response = client.post("/api/design/palette", json={"color": BLUE, "ids": [element]})

    assert response.status_code == 200, response.text
    operation_id = response.json()["operation_id"]
    assert _layer_of(client, element) == [operation_id]
    assert _op(client, operation_id)["color"] == BLUE


def test_moving_does_not_leave_the_shape_in_its_old_layer(client):
    """Two layers means burning twice — then a move is not a move."""
    element = _rect(client)
    first = client.post("/api/design/palette", json={"color": RED, "ids": [element]})
    second = client.post("/api/design/palette", json={"color": BLUE, "ids": [element]})

    assert _layer_of(client, element) == [second.json()["operation_id"]]
    assert first.json()["operation_id"] not in _layer_of(client, element)


def test_a_fresh_layer_starts_on_what_the_colour_did_before(client, server):
    """
    The whole point of B2. Put a colour at 42 mm/s, throw the layer away, click
    the colour again: the new layer starts at 42, not blank.
    """
    element = _rect(client)
    first = client.post(
        "/api/design/palette", json={"color": BLUE, "ids": [element]}
    ).json()["operation_id"]
    client.patch(
        f"/api/design/operations/{first}", json={"speed": 42, "power_percent": 33}
    )
    client.delete(f"/api/design/operations/{first}")

    second = client.post(
        "/api/design/palette", json={"color": BLUE, "ids": [element]}
    ).json()["operation_id"]

    layer = _op(client, second)
    assert layer["speed"] == 42
    assert layer["power"] == 330


def test_the_strip_reports_the_memory_it_will_use(client):
    element = _rect(client)
    operation = client.post(
        "/api/design/palette", json={"color": BLUE, "ids": [element]}
    ).json()["operation_id"]
    client.patch(f"/api/design/operations/{operation}", json={"speed": 42})

    remembered = {
        c["color"]: c["memory"] for c in client.get("/api/design/palette").json()["colors"]
    }
    assert remembered[BLUE]["speed_mm_s"] == 42
    assert remembered[RED] is None


def test_clicking_without_a_selection_sets_the_colour_for_new_work(client, server):
    response = client.post("/api/design/palette", json={"color": BLUE})

    assert response.status_code == 200, response.text
    assert response.json()["operation_id"] is None
    assert server.drawing.default_color() == BLUE
    assert client.get("/api/design/palette").json()["default_color"] == BLUE

    # And a fresh shape does land in it.
    element = _rect(client)
    design = client.get("/api/design").json()
    stroke = next(e for e in design["elements"] if e["id"] == element)["stroke"]
    assert stroke.lower() == BLUE


def test_drawing_in_a_remembered_colour_seeds_the_layer_the_engine_makes(client):
    """
    The other half of the promise.

    If you pick a colour with no layer and then draw, the engine creates the layer
    itself — not us. Without an intervention that started on the factory value,
    while the user has just picked a colour they know what they did with.
    """
    element = _rect(client)
    operation = client.post(
        "/api/design/palette", json={"color": BLUE, "ids": [element]}
    ).json()["operation_id"]
    client.patch(
        f"/api/design/operations/{operation}", json={"speed": 77, "power_percent": 22}
    )
    client.post("/api/design/elements/delete", json={"ids": [element]})
    client.delete(f"/api/design/operations/{operation}")

    client.post("/api/design/palette", json={"color": BLUE})
    fresh = _rect(client, x=60)

    design = client.get("/api/design").json()
    layer = next(
        o
        for o in design["operations"]
        if fresh in o["element_ids"] and (o["color"] or "").lower() == BLUE
    )
    assert layer["speed"] == 77
    assert layer["power"] == 220


def test_a_bad_colour_is_refused(client):
    assert client.post("/api/design/palette", json={"color": "red"}).status_code == 409


def test_the_memory_is_not_a_provenance(client, server):
    """
    The distinction B2 makes explicitly.

    The palette remembers what you did; the provenance says something was burned.
    So a layer that got its values out of the memory must not have a provenance —
    otherwise habit reads as evidence.
    """
    element = _rect(client)
    operation = client.post(
        "/api/design/palette", json={"color": BLUE, "ids": [element]}
    ).json()["operation_id"]
    client.patch(f"/api/design/operations/{operation}", json={"speed": 42})
    client.delete(f"/api/design/operations/{operation}")
    again = client.post(
        "/api/design/palette", json={"color": BLUE, "ids": [element]}
    ).json()["operation_id"]

    assert server.provenance.lookup(server.sheets.active_id, again, 42, None) is None
