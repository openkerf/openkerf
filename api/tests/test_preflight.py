"""
De pre-flight: wat gaat de machine dóén.

Time and the number of parts alone is theatre. Anybody who has worked with a laser for ten
years looks at speed, power, passes before starting — and where those numbers came from.
"""

import pytest
from fastapi.testclient import TestClient

from openkerf_api.server import ApiServer


@pytest.fixture
def client(kernel, tmp_path):
    with TestClient(ApiServer(kernel, library_path=tmp_path / "p.db").build_app()) as c:
        yield c


def a_job(client, speed=12, power=65):
    made = client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 20, "y_mm": 20, "width_mm": 50, "height_mm": 50},
    ).json()
    layer = client.post(
        "/api/design/operations",
        json={"type": "cut", "speed": speed, "power_percent": power},
    ).json()
    client.post(
        "/api/design/assign", json={"ids": made["ids"], "operation_id": layer["id"]}
    )
    return layer


def test_the_preflight_says_what_the_machine_will_do(client):
    a_job(client)

    estimate = client.get("/api/job/estimate").json()

    assert estimate["seconds"] > 0
    layers = [l for l in estimate["layers"] if l["label"] == "Cut"]
    assert layers, "the layer is not in the pre-flight"
    layer = layers[0]
    assert layer["speed_mm_s"] == 12
    assert layer["power_percent"] == 65
    assert layer["passes"] >= 1
    assert layer["elements"] == 1


def test_settings_that_came_from_a_test_grid_are_marked_as_measured(client):
    """Measured is a different conversation from guessed, and you should see that."""
    material = client.post("/api/library/materials", json={"name": "Berken"}).json()
    client.post(
        "/api/library/presets",
        json={
            "material_id": material["id"],
            "operation": "snijden",
            "speed_mm_s": 12,
            "power_percent": 65,
            "source": "testraster",
        },
    )
    a_job(client, speed=12, power=65)

    layer = next(
        l for l in client.get("/api/job/estimate").json()["layers"] if l["label"] == "Cut"
    )
    assert layer["source"] == "testraster"


def test_settings_nobody_measured_have_no_provenance(client):
    a_job(client, speed=37, power=42)

    layer = next(
        l for l in client.get("/api/job/estimate").json()["layers"] if l["label"] == "Cut"
    )
    assert layer["source"] is None


def test_a_layer_that_does_not_burn_is_left_out(client):
    """What does not burn does not belong in the list of what is going to happen."""
    layer = a_job(client)
    client.patch(f"/api/design/operations/{layer['id']}", json={"output": False})

    labels = [l["label"] for l in client.get("/api/job/estimate").json()["layers"]]
    assert "Cut" not in labels


# -------------------------------------------------------------- herkomst (B1)

def a_preset(client, material, **fields):
    body = {
        "material_id": material["id"],
        "operation": "snijden",
        "speed_mm_s": 12,
        "power_percent": 65,
        **fields,
    }
    return client.post("/api/library/presets", json=body).json()


def a_material(client, name):
    return client.post("/api/library/materials", json={"name": name}).json()


def layer_of(client, label="Cut"):
    estimate = client.get("/api/job/estimate").json()
    return next(l for l in estimate["layers"] if l["label"] == label)


def test_applying_a_preset_records_where_the_settings_came_from(client):
    """
    The pre-flight guessed the provenance from the numbers. 12 mm/s at 65% exists for more
    than one material, so that guessing has to become knowing.
    """
    berken = a_material(client, "Berken")
    preset = a_preset(client, berken, thickness_mm=3, source="testraster")
    layer = a_job(client, speed=1, power=1)
    client.post(
        f"/api/library/presets/{preset['id']}/apply", json={"operation_id": layer["id"]}
    )

    gevonden = layer_of(client)

    assert gevonden["preset_id"] == preset["id"]
    assert gevonden["material_name"] == "Berken"
    assert gevonden["thickness_mm"] == 3
    assert gevonden["source"] == "testraster"


def test_the_preflight_warns_when_a_layer_carries_another_materials_setting(client):
    """This is the question B1 is about: does this setting belong to this sheet?"""
    berken = a_material(client, "Berken")
    acryl = a_material(client, "Acryl")
    preset = a_preset(client, berken, thickness_mm=3)
    client.patch("/api/sheets/sheet-1", json={"material_id": acryl["id"], "thickness_mm": 3})
    layer = a_job(client, speed=1, power=1)
    client.post(
        f"/api/library/presets/{preset['id']}/apply", json={"operation_id": layer["id"]}
    )

    codes = [w["code"] for w in layer_of(client)["warnings"]]

    assert "ander-materiaal" in codes


def test_the_same_material_in_another_thickness_is_also_worth_a_word(client):
    berken = a_material(client, "Berken")
    preset = a_preset(client, berken, thickness_mm=3)
    client.patch("/api/sheets/sheet-1", json={"material_id": berken["id"], "thickness_mm": 6})
    layer = a_job(client, speed=1, power=1)
    client.post(
        f"/api/library/presets/{preset['id']}/apply", json={"operation_id": layer["id"]}
    )

    gevonden = layer_of(client)

    assert [w["code"] for w in gevonden["warnings"]] == ["andere-dikte"]
    assert "6" in gevonden["warnings"][0]["text"]


def test_an_extrapolated_setting_says_it_was_never_burned(client):
    """
    The task this has to improve: do you see before starting that these values have never
    been burned?
    """
    berken = a_material(client, "Berken")
    preset = a_preset(client, berken, thickness_mm=3, source="geextrapoleerd")
    client.patch("/api/sheets/sheet-1", json={"material_id": berken["id"], "thickness_mm": 3})
    layer = a_job(client, speed=1, power=1)
    client.post(
        f"/api/library/presets/{preset['id']}/apply", json={"operation_id": layer["id"]}
    )

    gevonden = layer_of(client)

    assert [w["code"] for w in gevonden["warnings"]] == ["nooit-gebrand"]
    assert gevonden["source"] == "geextrapoleerd"


def test_a_matching_material_and_thickness_says_nothing(client):
    """Whoever has nothing to report keeps quiet: otherwise the user learns to look away."""
    berken = a_material(client, "Berken")
    preset = a_preset(client, berken, thickness_mm=3, source="testraster")
    client.patch("/api/sheets/sheet-1", json={"material_id": berken["id"], "thickness_mm": 3})
    layer = a_job(client, speed=1, power=1)
    client.post(
        f"/api/library/presets/{preset['id']}/apply", json={"operation_id": layer["id"]}
    )

    assert layer_of(client)["warnings"] == []


def test_hand_edited_values_lose_their_claimed_provenance(client):
    """
    A note that no longer holds is worse than no note: then it says "3 mm birch, measured"
    above numbers somebody has turned themselves.
    """
    berken = a_material(client, "Berken")
    preset = a_preset(client, berken, thickness_mm=3, source="testraster")
    layer = a_job(client, speed=1, power=1)
    client.post(
        f"/api/library/presets/{preset['id']}/apply", json={"operation_id": layer["id"]}
    )
    client.patch(f"/api/design/operations/{layer['id']}", json={"speed": 40})

    gevonden = layer_of(client)

    assert gevonden["preset_id"] is None
    assert gevonden["material_name"] is None


def test_the_estimate_names_the_sheet_it_burns_on(client):
    berken = a_material(client, "Berken")
    client.patch("/api/sheets/sheet-1", json={"material_id": berken["id"], "thickness_mm": 3})
    a_job(client)

    sheet = client.get("/api/job/estimate").json()["sheet"]

    assert sheet["material_name"] == "Berken"
    assert sheet["thickness_mm"] == 3


def test_a_removed_sheet_does_not_bequeath_its_provenance(client):
    """
    Sheet numbers are reused: delete sheet-2 and the next new sheet is called sheet-2 again.
    Without cleaning up, that sheet inherits its predecessor's provenance, and then a material
    appears beside a layer that never saw it.
    """
    berken = a_material(client, "Berken")
    preset = a_preset(client, berken, thickness_mm=3, source="testraster")
    client.post("/api/sheets", json={"name": "Tweede"})
    client.post("/api/sheets/sheet-2/activate")
    layer = a_job(client, speed=1, power=1)
    client.post(
        f"/api/library/presets/{preset['id']}/apply", json={"operation_id": layer["id"]}
    )
    assert layer_of(client)["preset_id"] == preset["id"]

    client.delete("/api/sheets/sheet-2")
    client.post("/api/sheets", json={"name": "Derde"})
    client.post("/api/sheets/sheet-2/activate")
    opnieuw = a_job(client, speed=1, power=1)

    hergebruikt = [l for l in client.get("/api/job/estimate").json()["layers"] if l["id"] == opnieuw["id"]]
    assert hergebruikt and hergebruikt[0]["preset_id"] is None


def test_the_heaviest_objection_comes_first(client):
    """
    A measured setting for the wrong material weighs more than a calculated one for the
    right material: those numbers *are* true, but about something else. Showing both with
    equal weight leaves the user to work out what has to come first — exactly when there is no
    time for it.
    """
    berken = a_material(client, "Berken")
    zacht = a_preset(client, berken, thickness_mm=6, source="geextrapoleerd")
    client.patch("/api/sheets/sheet-1", json={"material_id": berken["id"], "thickness_mm": 3})
    layer = a_job(client, speed=1, power=1)
    client.post(
        f"/api/library/presets/{zacht['id']}/apply", json={"operation_id": layer["id"]}
    )

    codes = [w["code"] for w in layer_of(client)["warnings"]]
    ernst = [w["ernst"] for w in layer_of(client)["warnings"]]

    assert codes == ["andere-dikte", "nooit-gebrand"]
    assert ernst == sorted(ernst, reverse=True)


def test_what_will_be_burned_can_be_read_without_building_the_plan(client):
    """
    The time estimate builds the whole cut plan and takes minutes on a heavy design (gap
    J1). The warning that a layer belongs to another material must not queue behind it — that
    is precisely what you have to know before starting.
    """
    berken = a_material(client, "Berken")
    preset = a_preset(client, berken, thickness_mm=3, source="testraster")
    client.patch("/api/sheets/sheet-1", json={"material_id": berken["id"], "thickness_mm": 3})
    layer = a_job(client, speed=1, power=1)
    client.post(
        f"/api/library/presets/{preset['id']}/apply", json={"operation_id": layer["id"]}
    )

    overview = client.get("/api/job/layers").json()

    assert overview["sheet"]["material_name"] == "Berken"
    gevonden = next(l for l in overview["layers"] if l["label"] == "Cut")
    assert gevonden["preset_id"] == preset["id"]
    # The same layers as the pre-flight, only without the clock.
    assert "seconds" not in overview


def test_bounds_travel_with_the_layers_not_only_with_the_clock(client):
    """
    Off the bed is a blockage, not a clock fact.

    The pre-flight reads its layer overview from `/api/job/layers` and the time after that —
    deliberately separated (see the test above). If `bounds` were only in
    `/api/job/estimate`, "falls off the bed" would only appear once the estimate was back, and
    that is precisely the message that must not wait.
    """
    a_job(client)

    overview = client.get("/api/job/layers").json()

    vel = client.get("/api/sheets").json()["sheets"][0]
    assert overview["bounds"]["sheet"] == {
        "width_mm": vel["width_mm"],
        "height_mm": vel["height_mm"],
    }
    assert overview["bounds"]["outside_bed"] == 0
    # The same measurement the clock route gives; two sources could disagree about the
    # edge.
    assert overview["bounds"] == client.get("/api/job/estimate").json()["bounds"]


def test_shapes_outside_the_bed_are_named_with_the_ids_the_design_uses(client):
    """
    The drawing colours by id, so the ids have to be `/api/design`'s.

    Without `validate_ids()`, `bounds_report` handed back empty strings for everything that
    came from an SVG — and then the drawing colours nothing.
    """
    ver = client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 900, "y_mm": 20, "width_mm": 50, "height_mm": 50},
    ).json()

    bounds = client.get("/api/job/layers").json()["bounds"]

    assert bounds["outside_bed"] == 1
    assert bounds["outside_bed_ids"] == ver["ids"]
    bekend = {e["id"] for e in client.get("/api/design").json()["elements"]}
    assert set(bounds["outside_bed_ids"]) <= bekend


def test_a_raster_layer_promises_no_time_on_an_engine_that_cannot_burn_it(client, kernel):
    """
    Do not promise seconds for work the engine does not execute.

    During planning `op raster` turns its shapes into a bitmap through
    `render-op/make_raster`. Our plugin registers that service itself, so normally a raster
    layer simply burns — but if somebody runs an older installation or the registration drops
    away, `preprocess` takes the `strip_rasters` branch: the layer throws its own children
    away and produces no cutcode. Our sum *did* compute time for it. Measured on one filled
    area of 60x40 mm: 385.5 s promised against 70.0 s in the real plan.
    """
    made = client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 20, "y_mm": 20, "width_mm": 60, "height_mm": 40},
    ).json()
    # A raster layer burns the area, and a shape without a fill has none; without this line
    # the test measures a layer that costs zero anyway.
    from meerk40t.svgelements import Color

    node = list(kernel.elements.elems())[-1]
    node.fill = Color("#333333")
    node.set_dirty_bounds()
    layer = client.post(
        "/api/design/operations",
        json={"type": "raster", "speed": 150, "power_percent": 40},
    ).json()
    client.post(
        "/api/design/assign", json={"ids": made["ids"], "operation_id": layer["id"]}
    )
    # The engine also classifies a new shape into a default layer itself; that
    # would keep delivering time here and then this test measures two things at once.
    for other in client.get("/api/design").json()["operations"]:
        if other["id"] != layer["id"]:
            client.post(
                "/api/design/unassign",
                json={"ids": made["ids"], "operation_id": other["id"]},
            )
    assert client.get("/api/job/estimate").json()["seconds"] > 0

    # Taking the rasteriser away: this is the engine as it was, and as it becomes
    # again on a failed registration. Putting it back afterwards — the kernel is
    # shared within this test, and the suite runs in random order: leave it out and
    # another test that has nothing to do with it falls over. That cost half a hunt.
    previous = kernel.root.lookup("render-op/make_raster")
    kernel.root.register("render-op/make_raster", None)
    try:
        overview = client.get("/api/job/layers").json()
        estimate = client.get("/api/job/estimate").json()
    finally:
        kernel.root.register("render-op/make_raster", previous)

    assert overview["engine"]["raster"] is False
    raster = next(l for l in overview["layers"] if l["type"] == "op raster")
    assert raster["burns"] is False
    assert estimate["seconds"] == 0
    # The shape *is* there: the pre-flight has to be able to talk about it instead
    # of showing "there is nothing to burn".
    assert estimate["parts"] == 1


def test_a_raster_layer_keeps_its_time_now_that_we_have_a_rasteriser(client):
    """The ordinary situation: our plugin provides the rasteriser, so something burns."""
    made = client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 20, "y_mm": 20, "width_mm": 60, "height_mm": 40},
    ).json()
    layer = client.post(
        "/api/design/operations",
        json={"type": "raster", "speed": 150, "power_percent": 40},
    ).json()
    client.post(
        "/api/design/assign", json={"ids": made["ids"], "operation_id": layer["id"]}
    )

    overview = client.get("/api/job/layers").json()

    assert overview["engine"]["raster"] is True
    assert next(l for l in overview["layers"] if l["type"] == "op raster")["burns"]


def test_a_layer_that_does_burn_keeps_its_estimate(client):
    """Het vangnet mag geen gewone laag raken."""
    a_job(client)

    estimate = client.get("/api/job/estimate").json()

    assert estimate["seconds"] > 0
    assert all(l["burns"] for l in estimate["layers"])


def test_a_shape_whose_length_the_engine_cannot_compute_still_counts(kernel):
    """
    Found in a real project: text in Chalkduster, 474 contours and 10,026
    segments, on which the engine's `Geomstr.length()` falls over with "expected a
    positive input, got -inf". We caught that with a 0 — the `except` was there for
    images, which have no path — and so the estimate counted zero seconds for
    exactly the shape that takes longest.

    Measured with the fallback over the points: 0.68 m of line.
    """
    from openkerf_api.drawing import Drawing

    class BrokenGeometry:
        """The way the engine behaves on that text."""

        def length(self):
            raise ValueError("expected a positive input, got -inf")

        def as_interpolated_points(self, interpolate=20):
            # A square of 10 mm: 40 mm of line.
            from meerk40t.core.units import UNITS_PER_MM

            mm = UNITS_PER_MM
            return [
                complex(0, 0),
                complex(10 * mm, 0),
                complex(10 * mm, 10 * mm),
                complex(0, 10 * mm),
                complex(0, 0),
            ]

    class FakeNode:
        type = "elem path"

        def as_geometry(self):
            return BrokenGeometry()

    assert Drawing._length_mm(FakeNode()) == pytest.approx(40.0, rel=0.01)


def test_something_without_geometry_is_still_zero(kernel):
    """An image has no path; that falls under the raster calculation."""
    from openkerf_api.drawing import Drawing

    class AnImage:
        type = "elem image"

    assert Drawing._length_mm(AnImage()) == 0.0
