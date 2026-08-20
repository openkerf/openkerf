"""
Lagen herordenen, sorteren, van soort wisselen, en air assist per laag.

De gaten die hier gedicht worden: L1 (slepen naar een plek), L2 (graveren vóór
snijden in één handeling), L3 (laagsoort wijzigen met behoud van de vormen), L4
met besluit B11 (air assist alleen als de driver hem kent) en C2 (wat er buiten
het bed of buiten het vel valt).
"""

import pytest
from fastapi.testclient import TestClient

from openkerf_api.drawing import Drawing
from openkerf_api.edits import DesignError
from openkerf_api.server import ApiServer


@pytest.fixture
def client(kernel, tmp_path):
    with TestClient(ApiServer(kernel, library_path=tmp_path / "d.db").build_app()) as c:
        yield c


@pytest.fixture
def drawing(kernel):
    # De engine zet bij het opstarten een hele reeks standaardbewerkingen in de
    # boom (bij ons filtert de snapshot die eruit zolang ze leeg zijn). Voor een
    # test over volgorde is dat ruis: dan is "plek 1" niet de eerste laag die je
    # ziet. Schone tak, dus.
    kernel.elements.clear_operations()
    return Drawing(kernel)


def types(kernel):
    """De brandvolgorde zoals de boom hem heeft, zonder de `op `-prefix."""
    return [
        str(op.type).replace("op ", "")
        for op in kernel.elements.op_branch.children
        if str(op.type).startswith("op ")
    ]


def maak(drawing, *soorten):
    return [drawing.create_operation(soort)["id"] for soort in soorten]


# ------------------------------------------------------- L1: naar een plek


def zichtbaar(drawing):
    """De lagen zoals het paneel ze toont — dus zonder de lege standaardlagen."""
    from openkerf_api.design import DesignReader

    reader = DesignReader(
        drawing.kernel,
        keep_operations=drawing.user_operations,
        grid_operations=drawing.grid_operations,
    )
    return [op.get("label") for op in reader.snapshot()["operations"]]


@pytest.fixture
def volle_boom(kernel):
    """
    Een boom zoals hij in het echt is: mét de standaardlagen van de engine.

    De fixture hierboven veegt die weg, en juist dáárdoor stond deze suite
    groen terwijl verschuiven in de app niets deed. Een verse boom heeft ruim
    tweehonderd lege `op`-knopen die het paneel niet toont; wie in knopen telt
    in plaats van in zichtbare lagen, schuift een laag langs een buur die
    niemand ziet. Deze fixture houdt ze dus expres staan.
    """
    return Drawing(kernel)


def test_moving_a_layer_down_moves_it_past_a_layer_you_can_see(volle_boom):
    drawing = volle_boom
    een = drawing.create_operation("engrave", label="Een")["id"]
    drawing.create_operation("cut", label="Twee")
    assert zichtbaar(drawing) == ["Een", "Twee"]

    uit = drawing.move_operation(een, direction="down")

    assert uit["moved"] is True
    assert zichtbaar(drawing) == ["Twee", "Een"]


def test_dragging_a_layer_lands_where_the_list_says(volle_boom):
    """Slepen telt in de lijst waaruit je sleept, niet in knopen van de boom."""
    drawing = volle_boom
    drawing.create_operation("engrave", label="Een")
    drawing.create_operation("cut", label="Twee")
    drie = drawing.create_operation("raster", label="Drie")["id"]

    drawing.move_operation(drie, index=0)

    assert zichtbaar(drawing) == ["Drie", "Een", "Twee"]


def test_a_layer_at_the_edge_does_not_pretend_to_move(volle_boom):
    """
    De bovenste laag omhoog is geen beweging, en mag dat ook niet melden.

    Meldde hij `moved: true`, dan verversde het paneel voor niets — en erger:
    dat was precies het signaal waarmee de kapotte versie deed alsof er iets
    gebeurd was.
    """
    drawing = volle_boom
    een = drawing.create_operation("engrave", label="Een")["id"]
    drawing.create_operation("cut", label="Twee")

    uit = drawing.move_operation(een, direction="up")

    assert uit["moved"] is False
    assert zichtbaar(drawing) == ["Een", "Twee"]


def test_move_to_index_places_the_layer_there(kernel, drawing):
    ids = maak(drawing, "cut", "engrave", "raster", "dots")

    uit = drawing.move_operation(ids[3], index=0)

    assert uit["moved"] is True
    assert types(kernel)[:4] == ["dots", "cut", "engrave", "raster"]


def test_move_to_index_downwards_lands_below_the_target(kernel, drawing):
    """
    Naar beneden slepen betekent: onder de laag komen die daar nu staat.

    Zonder dat onderscheid landt de laag er steeds één naast en loopt de lijst
    bij het slepen een plek achter op de aanwijzer.
    """
    ids = maak(drawing, "cut", "engrave", "raster")

    drawing.move_operation(ids[0], index=2)

    assert types(kernel)[:3] == ["engrave", "raster", "cut"]


def test_move_to_own_index_changes_nothing(kernel, drawing):
    ids = maak(drawing, "cut", "engrave")

    uit = drawing.move_operation(ids[1], index=1)

    assert uit["moved"] is False
    assert types(kernel)[:2] == ["cut", "engrave"]


def test_move_needs_exactly_one_of_direction_or_index(drawing):
    ids = maak(drawing, "cut", "engrave")

    with pytest.raises(DesignError):
        drawing.move_operation(ids[0])
    with pytest.raises(DesignError):
        drawing.move_operation(ids[0], "down", 1)


def test_move_to_index_out_of_range_is_refused(drawing):
    ids = maak(drawing, "cut", "engrave")

    with pytest.raises(DesignError):
        drawing.move_operation(ids[0], index=7)


def test_move_route_accepts_an_index(client, kernel, drawing):
    # Via de route aanmaken, niet via de fixture: de server houdt zijn eigen
    # `Drawing` en dus zijn eigen lijst van "door de gebruiker gemaakt". Maak
    # je de lagen ernaast, dan kent de route ze niet als zichtbare laag en
    # rangschik je iets wat voor de server niet in de lijst staat.
    ids = [
        client.post("/api/design/operations", json={"type": soort}).json()["id"]
        for soort in ("cut", "engrave")
    ]

    response = client.post(
        f"/api/design/operations/{ids[1]}/move", json={"index": 0}
    )

    assert response.status_code == 200
    assert types(kernel)[:2] == ["engrave", "cut"]


# ------------------------------------------- L2: graveren vóór snijden


def test_sort_puts_cutting_last(kernel, drawing):
    maak(drawing, "cut", "engrave", "raster")

    uit = drawing.sort_operations()

    assert uit["sorted"] is True
    assert types(kernel) == ["raster", "engrave", "cut"]


def test_sort_keeps_the_order_the_user_chose_within_one_kind(kernel, drawing):
    """Stabiel: twee snijlagen houden hun onderlinge volgorde."""
    eerste, tweede = maak(drawing, "cut", "cut")
    for op in kernel.elements.op_branch.children:
        if getattr(op, "id", None) == eerste:
            op.label = "Buitensnede"
        if getattr(op, "id", None) == tweede:
            op.label = "Binnensnede"
    maak(drawing, "engrave")

    drawing.sort_operations()

    labels = [
        op.label
        for op in kernel.elements.op_branch.children
        if str(op.type) == "op cut"
    ]
    assert labels == ["Buitensnede", "Binnensnede"]


def test_sort_puts_the_lightest_layer_of_a_kind_first(kernel, drawing):
    """
    Gat L7: binnen dezelfde soort telt de sterkte mee.

    Twee snijlagen zijn niet uitwisselbaar. Een scoreerlijn op 12 % en een
    doorsnede op 90 % horen in die volgorde: zodra het werkstuk los is, ligt het
    niet meer stil voor de rest. Eerder keek het sorteren alleen naar het soort,
    en dan ging een snijlaag op 5 % even hard naar achteren als een die er
    doorheen gaat.
    """
    diep = drawing.create_operation("cut", label="Doorsnijden", speed=8, power_percent=90)
    licht = drawing.create_operation("cut", label="Scoreren", speed=40, power_percent=12)
    drawing.create_operation("engrave", label="Tekst")

    drawing.sort_operations()

    volgorde = [
        getattr(op, "id", None)
        for op in kernel.elements.op_branch.children
        if str(op.type) == "op cut"
    ]
    assert volgorde == [licht["id"], diep["id"]]


def test_sort_reports_nothing_to_do_when_already_in_order(drawing):
    maak(drawing, "raster", "engrave", "cut")

    assert drawing.sort_operations()["sorted"] is False


def test_sort_route(client, kernel, drawing):
    for soort in ("cut", "raster"):
        client.post("/api/design/operations", json={"type": soort})

    response = client.post("/api/design/operations/sort")

    assert response.status_code == 200
    assert types(kernel) == ["raster", "cut"]


# ----------------------------------------------- L3: soort van een laag


def test_retype_keeps_the_shapes_and_the_place(kernel, drawing):
    ids = maak(drawing, "engrave", "cut", "raster")
    vorm = drawing.create("rect", x_mm=10, y_mm=10, width_mm=20, height_mm=20)
    from openkerf_api.edits import DesignEditor

    DesignEditor(kernel).assign(vorm["ids"], ids[1])

    uit = drawing.change_operation_type(ids[1], "engrave")

    assert uit["changed"] is True
    assert uit["elements"] == 1
    # Op de plek van de oude laag: de brandvolgorde mag niet verspringen omdat je
    # het soort bijstelt. (De engine hangt bij het tekenen zelf ook een
    # classificatielaag in de boom, dus we toetsen de plek en niet de hele lijst.)
    kinderen = [op.id for op in kernel.elements.op_branch.children]
    assert kinderen.index(uit["id"]) == uit["index"]
    assert types(kernel)[uit["index"]] == "engrave"
    nieuw = kernel.elements.find_node(uit["id"])
    verwezen = [
        getattr(child, "node", None) for child in nieuw.children
    ]
    assert kernel.elements.find_node(vorm["ids"][0]) in verwezen


def test_retype_keeps_settings_and_colour(kernel, drawing):
    (laag,) = maak(drawing, "cut")
    drawing.update_operation(laag, speed=12, power_percent=80, passes=3, color="#8E4EC6")

    uit = drawing.change_operation_type(laag, "engrave")

    nieuw = kernel.elements.find_node(uit["id"])
    assert float(nieuw.speed) == 12
    assert float(nieuw.power) == 800
    assert int(nieuw.passes) == 3
    assert str(nieuw.color.hexrgb).lower() == "#8e4ec6"


def test_retype_renames_a_default_label_but_keeps_a_chosen_one(kernel, drawing):
    standaard, eigen = maak(drawing, "cut", "cut")
    drawing.update_operation(eigen, label="Buitensnede")

    een = drawing.change_operation_type(standaard, "engrave")
    twee = drawing.change_operation_type(eigen, "engrave")

    assert kernel.elements.find_node(een["id"]).label == "Engrave"
    assert kernel.elements.find_node(twee["id"]).label == "Buitensnede"


def test_retype_to_the_same_kind_is_a_no_op(drawing):
    (laag,) = maak(drawing, "cut")

    assert drawing.change_operation_type(laag, "cut")["changed"] is False


def test_retype_refuses_an_unknown_kind(drawing):
    (laag,) = maak(drawing, "cut")

    with pytest.raises(DesignError):
        drawing.change_operation_type(laag, "vaporise")


def test_retype_refuses_a_test_grid_cell(kernel, drawing):
    (laag,) = maak(drawing, "cut")
    drawing.update_operation(laag, speed=25, power_percent=40)
    drawing.grid_operations = lambda: {
        laag: {"grid_id": 1, "row": 0, "column": 0, "speed_mm_s": 25, "power_percent": 40}
    }

    with pytest.raises(DesignError):
        drawing.change_operation_type(laag, "engrave")


def test_retype_route(client, kernel, drawing):
    (laag,) = maak(drawing, "cut")

    response = client.post(
        f"/api/design/operations/{laag}/type", json={"type": "raster"}
    )

    assert response.status_code == 200
    assert types(kernel) == ["raster"]


# --------------------------------------------- L4 / B11: air assist


def test_air_assist_is_not_offered_without_a_driver_command(client, drawing):
    """
    Besluit B11: wat de machine niet kan, hoort niet als schakelaar op het
    scherm. Het dummy-apparaat heeft geen coolant-methode geclaimd.
    """
    assert drawing.air_assist_supported() is False
    # Dezelfde regel geldt voor de Z-stap per pass: het dummy-apparaat heeft
    # geen Z-as, dus staat er geen veld voor op het scherm.
    assert client.get("/api/design/capabilities").json() == {
        "air_assist": False,
        "z_step": False,
    }


def test_air_assist_is_refused_while_the_machine_has_none(drawing):
    (laag,) = maak(drawing, "cut")

    with pytest.raises(DesignError):
        drawing.update_operation(laag, air_assist=True)


def test_air_assist_sets_the_engine_field_when_the_machine_has_one(kernel, drawing):
    """
    De engine kent drie standen in `coolant`: 0 laat staan, 1 aan, 2 uit. Uit
    moet expliciet uit zijn, anders blijft de blazer aan terwijl de schakelaar
    zegt dat hij uitstaat.
    """
    drawing.air_assist_supported = lambda: True
    (laag,) = maak(drawing, "cut")

    drawing.update_operation(laag, air_assist=True)
    assert int(kernel.elements.find_node(laag).coolant) == 1

    drawing.update_operation(laag, air_assist=False)
    assert int(kernel.elements.find_node(laag).coolant) == 2


def test_air_assist_shows_up_in_the_snapshot(kernel, drawing):
    drawing.air_assist_supported = lambda: True
    (laag,) = maak(drawing, "cut")
    drawing.create("rect", x_mm=10, y_mm=10, width_mm=10, height_mm=10)

    from openkerf_api.design import DesignReader

    drawing.update_operation(laag, air_assist=True)
    snapshot = DesignReader(kernel, keep_operations={laag}).snapshot()
    aan = [op for op in snapshot["operations"] if op["id"] == laag]

    assert aan and aan[0]["air_assist"] is True


def test_air_assist_survives_a_change_of_kind(kernel, drawing):
    drawing.air_assist_supported = lambda: True
    (laag,) = maak(drawing, "cut")
    drawing.update_operation(laag, air_assist=True)

    uit = drawing.change_operation_type(laag, "engrave")

    assert int(kernel.elements.find_node(uit["id"]).coolant) == 1


# ------------------------------------------- C2: buiten bed en buiten vel


def test_bounds_report_counts_what_falls_off_the_bed(drawing):
    bed = drawing.bed_mm()
    assert bed is not None
    drawing.create("rect", x_mm=10, y_mm=10, width_mm=20, height_mm=20)
    drawing.create("rect", x_mm=bed[0] - 5, y_mm=10, width_mm=40, height_mm=20)

    uit = drawing.bounds_report()

    assert uit["outside_bed"] == 1
    assert uit["outside_sheet"] == 0  # geen vel meegegeven
    assert uit["work"]["x_mm"] == 10.0


def test_bounds_report_counts_what_falls_off_the_sheet(drawing):
    drawing.create("rect", x_mm=10, y_mm=10, width_mm=20, height_mm=20)
    drawing.create("rect", x_mm=10, y_mm=190, width_mm=20, height_mm=40)

    uit = drawing.bounds_report({"width_mm": 310, "height_mm": 210})

    assert uit["outside_sheet"] == 1
    assert uit["sheet"] == {"width_mm": 310, "height_mm": 210}


def test_a_shape_exactly_on_the_edge_is_not_a_warning(drawing):
    """Een vorm die het vel precies vult, is geen fout maar goed genesteld."""
    drawing.create("rect", x_mm=0, y_mm=0, width_mm=310, height_mm=210)

    uit = drawing.bounds_report({"width_mm": 310, "height_mm": 210})

    assert uit["outside_sheet"] == 0


def test_estimate_carries_the_bounds(client, drawing):
    drawing.create("rect", x_mm=10, y_mm=10, width_mm=20, height_mm=20)

    bounds = client.get("/api/job/estimate").json()["bounds"]

    assert bounds["bed"]["width_mm"] > 0
    assert bounds["outside_bed"] == 0
    assert bounds["work"]["width_mm"] == 20.0
