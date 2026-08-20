"""
De pre-flight: wat gaat de machine dóén.

Tijd en aantal onderdelen alleen is theater. Wie tien jaar met een laser werkt
kijkt vóór het starten naar snelheid, vermogen, passes — en waar die getallen
vandaan komen.
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
    assert layers, "de laag staat niet in de pre-flight"
    layer = layers[0]
    assert layer["speed_mm_s"] == 12
    assert layer["power_percent"] == 65
    assert layer["passes"] >= 1
    assert layer["elements"] == 1


def test_settings_that_came_from_a_test_grid_are_marked_as_measured(client):
    """Gemeten is een ander gesprek dan gegokt, en dat hoor je te zien."""
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
    """Wat niet meebrandt hoort niet in de opsomming van wat er gaat gebeuren."""
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
    De pre-flight raadde de herkomst aan de getallen. 12 mm/s op 65% bestaat
    voor meer dan één materiaal, dus dat raden moet een weten worden.
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
    """Dit is de vraag waar B1 over gaat: hoort deze instelling bij dit vel?"""
    berken = a_material(client, "Berken")
    acryl = a_material(client, "Acryl")
    preset = a_preset(client, berken, thickness_mm=3)
    client.patch("/api/sheets/vel-1", json={"material_id": acryl["id"], "thickness_mm": 3})
    layer = a_job(client, speed=1, power=1)
    client.post(
        f"/api/library/presets/{preset['id']}/apply", json={"operation_id": layer["id"]}
    )

    codes = [w["code"] for w in layer_of(client)["warnings"]]

    assert "ander-materiaal" in codes


def test_the_same_material_in_another_thickness_is_also_worth_a_word(client):
    berken = a_material(client, "Berken")
    preset = a_preset(client, berken, thickness_mm=3)
    client.patch("/api/sheets/vel-1", json={"material_id": berken["id"], "thickness_mm": 6})
    layer = a_job(client, speed=1, power=1)
    client.post(
        f"/api/library/presets/{preset['id']}/apply", json={"operation_id": layer["id"]}
    )

    gevonden = layer_of(client)

    assert [w["code"] for w in gevonden["warnings"]] == ["andere-dikte"]
    assert "6" in gevonden["warnings"][0]["text"]


def test_an_extrapolated_setting_says_it_was_never_burned(client):
    """
    De taak die dit moet verbeteren: zie je vóór het starten dat deze waarden
    nooit gebrand zijn?
    """
    berken = a_material(client, "Berken")
    preset = a_preset(client, berken, thickness_mm=3, source="geextrapoleerd")
    client.patch("/api/sheets/vel-1", json={"material_id": berken["id"], "thickness_mm": 3})
    layer = a_job(client, speed=1, power=1)
    client.post(
        f"/api/library/presets/{preset['id']}/apply", json={"operation_id": layer["id"]}
    )

    gevonden = layer_of(client)

    assert [w["code"] for w in gevonden["warnings"]] == ["nooit-gebrand"]
    assert gevonden["source"] == "geextrapoleerd"


def test_a_matching_material_and_thickness_says_nothing(client):
    """Wie niets te melden heeft, zwijgt: anders leert de gebruiker wegkijken."""
    berken = a_material(client, "Berken")
    preset = a_preset(client, berken, thickness_mm=3, source="testraster")
    client.patch("/api/sheets/vel-1", json={"material_id": berken["id"], "thickness_mm": 3})
    layer = a_job(client, speed=1, power=1)
    client.post(
        f"/api/library/presets/{preset['id']}/apply", json={"operation_id": layer["id"]}
    )

    assert layer_of(client)["warnings"] == []


def test_hand_edited_values_lose_their_claimed_provenance(client):
    """
    Een briefje dat niet meer klopt is erger dan geen briefje: dan staat er
    "3 mm berken, gemeten" boven getallen die iemand zelf heeft bijgedraaid.
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
    client.patch("/api/sheets/vel-1", json={"material_id": berken["id"], "thickness_mm": 3})
    a_job(client)

    sheet = client.get("/api/job/estimate").json()["sheet"]

    assert sheet["material_name"] == "Berken"
    assert sheet["thickness_mm"] == 3


def test_a_removed_sheet_does_not_bequeath_its_provenance(client):
    """
    Vel-nummers worden hergebruikt: verwijder vel-2 en het volgende nieuwe vel
    heet weer vel-2. Zonder opruimen erft dat vel de herkomst van zijn
    voorganger, en dan staat er een materiaal bij een laag die het nooit zag.
    """
    berken = a_material(client, "Berken")
    preset = a_preset(client, berken, thickness_mm=3, source="testraster")
    client.post("/api/sheets", json={"name": "Tweede"})
    client.post("/api/sheets/vel-2/activate")
    layer = a_job(client, speed=1, power=1)
    client.post(
        f"/api/library/presets/{preset['id']}/apply", json={"operation_id": layer["id"]}
    )
    assert layer_of(client)["preset_id"] == preset["id"]

    client.delete("/api/sheets/vel-2")
    client.post("/api/sheets", json={"name": "Derde"})
    client.post("/api/sheets/vel-2/activate")
    opnieuw = a_job(client, speed=1, power=1)

    hergebruikt = [l for l in client.get("/api/job/estimate").json()["layers"] if l["id"] == opnieuw["id"]]
    assert hergebruikt and hergebruikt[0]["preset_id"] is None


def test_the_heaviest_objection_comes_first(client):
    """
    Een gemeten instelling van het verkeerde materiaal weegt zwaarder dan een
    uitgerekende op het juiste: die getallen zijn wél waar, maar over iets
    anders. Wie beide even zwaar toont, laat de gebruiker uitzoeken wat er
    eerst moet — precies op het moment dat daar geen tijd voor is.
    """
    berken = a_material(client, "Berken")
    zacht = a_preset(client, berken, thickness_mm=6, source="geextrapoleerd")
    client.patch("/api/sheets/vel-1", json={"material_id": berken["id"], "thickness_mm": 3})
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
    De tijdschatting bouwt het hele snijplan en duurt op een zwaar ontwerp
    minuten (gat J1). De waarschuwing dat een laag bij een ander materiaal
    hoort, mag daar niet achteraan staan — dat is juist wat je vóór het starten
    moet weten.
    """
    berken = a_material(client, "Berken")
    preset = a_preset(client, berken, thickness_mm=3, source="testraster")
    client.patch("/api/sheets/vel-1", json={"material_id": berken["id"], "thickness_mm": 3})
    layer = a_job(client, speed=1, power=1)
    client.post(
        f"/api/library/presets/{preset['id']}/apply", json={"operation_id": layer["id"]}
    )

    overzicht = client.get("/api/job/layers").json()

    assert overzicht["sheet"]["material_name"] == "Berken"
    gevonden = next(l for l in overzicht["layers"] if l["label"] == "Cut")
    assert gevonden["preset_id"] == preset["id"]
    # Dezelfde lagen als de pre-flight, alleen zonder klok.
    assert "seconds" not in overzicht


def test_bounds_travel_with_the_layers_not_only_with_the_clock(client):
    """
    Buiten het bed is een blokkade, geen klokgegeven.

    De pre-flight leest zijn laagoverzicht uit `/api/job/layers` en de tijd
    daarná — bewust gescheiden (zie de test hierboven). Stond `bounds` alleen
    in `/api/job/estimate`, dan verscheen "valt buiten het bed" pas als de
    schatting terug was, en dat is precies de melding die niet mag wachten.
    """
    a_job(client)

    overzicht = client.get("/api/job/layers").json()

    vel = client.get("/api/sheets").json()["sheets"][0]
    assert overzicht["bounds"]["sheet"] == {
        "width_mm": vel["width_mm"],
        "height_mm": vel["height_mm"],
    }
    assert overzicht["bounds"]["outside_bed"] == 0
    # Dezelfde meting als de klokroute geeft; twee bronnen zouden het over de
    # rand oneens kunnen worden.
    assert overzicht["bounds"] == client.get("/api/job/estimate").json()["bounds"]


def test_shapes_outside_the_bed_are_named_with_the_ids_the_design_uses(client):
    """
    De weergave kleurt op id, dus de id's moeten die van `/api/design` zijn.

    Zonder `validate_ids()` gaf `bounds_report` lege strings terug voor alles
    wat uit een SVG kwam — en dan kleurt de weergave niets.
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
    Geen seconden beloven voor werk dat de engine niet uitvoert.

    `op raster` zet zijn vormen tijdens het plannen om in een bitmap via
    `render-op/make_raster`. Onze plugin registreert die dienst zelf, dus
    normaal brandt een rasterlaag gewoon — maar draait iemand met een oudere
    installatie of valt de registratie weg, dan neemt `preprocess` de
    `strip_rasters`-tak: de laag gooit zijn eigen kinderen weg en levert nul
    cutcode. Onze som rekende daar wél tijd voor. Gemeten op één gevuld vlak
    van 60x40 mm: 385,5 s beloofd tegen 70,0 s in het echte plan.
    """
    made = client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 20, "y_mm": 20, "width_mm": 60, "height_mm": 40},
    ).json()
    # Een rasterlaag brandt het vlak, en een vorm zonder vulling heeft dat niet;
    # zonder deze regel meet de test een laag die sowieso nul kost.
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
    # De engine classificeert een nieuwe vorm ook zelf in een standaardlaag; die
    # zou hier tijd blijven leveren en dan meet deze test twee dingen tegelijk.
    for andere in client.get("/api/design").json()["operations"]:
        if andere["id"] != layer["id"]:
            client.post(
                "/api/design/unassign",
                json={"ids": made["ids"], "operation_id": andere["id"]},
            )
    assert client.get("/api/job/estimate").json()["seconds"] > 0

    # De rasteraar weghalen: dit is de engine zoals hij was, en zoals hij bij
    # een mislukte registratie weer wordt. Daarna terugzetten — de kernel is
    # gedeeld binnen deze test, en de suite draait in willekeurige volgorde:
    # laat je hem weg, dan valt een andere test om die er niets mee te maken
    # heeft. Dat kostte een halve zoektocht.
    terug = kernel.root.lookup("render-op/make_raster")
    kernel.root.register("render-op/make_raster", None)
    try:
        overzicht = client.get("/api/job/layers").json()
        schatting = client.get("/api/job/estimate").json()
    finally:
        kernel.root.register("render-op/make_raster", terug)

    assert overzicht["engine"]["raster"] is False
    raster = next(l for l in overzicht["layers"] if l["type"] == "op raster")
    assert raster["burns"] is False
    assert schatting["seconds"] == 0
    # De vorm ligt er wel: de pre-flight moet erover kunnen praten in plaats van
    # "er is niets om te branden" te tonen.
    assert schatting["parts"] == 1


def test_a_raster_layer_keeps_its_time_now_that_we_have_a_rasteriser(client):
    """De gewone situatie: onze plugin levert de rasteraar, dus er brandt iets."""
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

    overzicht = client.get("/api/job/layers").json()

    assert overzicht["engine"]["raster"] is True
    assert next(l for l in overzicht["layers"] if l["type"] == "op raster")["burns"]


def test_a_layer_that_does_burn_keeps_its_estimate(client):
    """Het vangnet mag geen gewone laag raken."""
    a_job(client)

    schatting = client.get("/api/job/estimate").json()

    assert schatting["seconds"] > 0
    assert all(l["burns"] for l in schatting["layers"])


def test_a_shape_whose_length_the_engine_cannot_compute_still_counts(kernel):
    """
    Gevonden in een echt project: tekst in Chalkduster, 474 contouren en
    10 026 segmenten, waarop `Geomstr.length()` van de engine omvalt met
    "expected a positive input, got -inf". Wij vingen dat op met een 0 — de
    `except` stond er voor afbeeldingen, die geen pad hebben — en dus rekende de
    schatting nul seconden voor precies de vorm die het langst duurt.

    Gemeten met de terugval over de punten: 0,68 m lijn.
    """
    from openkerf_api.drawing import Drawing

    class KapotteGeometrie:
        """Zoals de engine zich gedraagt op die tekst."""

        def length(self):
            raise ValueError("expected a positive input, got -inf")

        def as_interpolated_points(self, interpolate=20):
            # Een vierkant van 10 mm: 40 mm lijn.
            from meerk40t.core.units import UNITS_PER_MM

            mm = UNITS_PER_MM
            return [
                complex(0, 0),
                complex(10 * mm, 0),
                complex(10 * mm, 10 * mm),
                complex(0, 10 * mm),
                complex(0, 0),
            ]

    class NepKnoop:
        type = "elem path"

        def as_geometry(self):
            return KapotteGeometrie()

    assert Drawing._length_mm(NepKnoop()) == pytest.approx(40.0, rel=0.01)


def test_something_without_geometry_is_still_zero(kernel):
    """Een afbeelding heeft geen pad; die hoort onder de rasterrekensom."""
    from openkerf_api.drawing import Drawing

    class Beeld:
        type = "elem image"

    assert Drawing._length_mm(Beeld()) == 0.0
