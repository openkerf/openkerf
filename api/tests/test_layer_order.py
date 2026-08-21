"""
Reordering layers, sorting them, changing their kind, and air assist per layer.

The gaps closed here: L1 (dragging to a place), L2 (engraving before cutting in one
action), L3 (changing a layer's kind while keeping the shapes), L4 with decision B11 (air
assist only when the driver knows it) and C2 (what falls off the bed or off the sheet).
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
    # At startup the engine puts a whole series of default operations in the tree (with us
    # the snapshot filters those out while they are empty). For a test about order that is
    # noise: then "place 1" is not the first layer you see. So: a clean branch.
    kernel.elements.clear_operations()
    return Drawing(kernel)


def types(kernel):
    """The burn order as the tree has it, without the `op ` prefix."""
    return [
        str(op.type).replace("op ", "")
        for op in kernel.elements.op_branch.children
        if str(op.type).startswith("op ")
    ]


def make(drawing, *kinds):
    return [drawing.create_operation(kind)["id"] for kind in kinds]


# ---------------------------------------------------------- L1: to a place


def visible(drawing):
    """The layers as the panel shows them — so without the empty default layers."""
    from openkerf_api.design import DesignReader

    reader = DesignReader(
        drawing.kernel,
        keep_operations=drawing.user_operations,
        grid_operations=drawing.grid_operations,
    )
    return [op.get("label") for op in reader.snapshot()["operations"]]


@pytest.fixture
def full_tree(kernel):
    """
    A tree as it really is: *with* the engine's default layers.

    The fixture above sweeps those away, and that is exactly why this suite stood green while
    moving did nothing in the app. A fresh tree has well over two hundred empty `op` nodes the
    panel does not show; anybody counting in nodes rather than in visible layers moves a layer
    past a neighbour nobody sees. So this fixture deliberately keeps them.
    """
    return Drawing(kernel)


def test_moving_a_layer_down_moves_it_past_a_layer_you_can_see(full_tree):
    drawing = full_tree
    one = drawing.create_operation("engrave", label="One")["id"]
    drawing.create_operation("cut", label="Two")
    assert visible(drawing) == ["One", "Two"]

    out = drawing.move_operation(one, direction="down")

    assert out["moved"] is True
    assert visible(drawing) == ["Two", "One"]


def test_dragging_a_layer_lands_where_the_list_says(full_tree):
    """Dragging counts in the list you drag from, not in nodes of the tree."""
    drawing = full_tree
    drawing.create_operation("engrave", label="One")
    drawing.create_operation("cut", label="Two")
    drie = drawing.create_operation("raster", label="Three")["id"]

    drawing.move_operation(drie, index=0)

    assert visible(drawing) == ["Three", "One", "Two"]


def test_a_layer_at_the_edge_does_not_pretend_to_move(full_tree):
    """
    The top layer upwards is not a movement, and must not report one either.

    If it reported `moved: true`, the panel refreshed for nothing — and worse: that was
    precisely the signal with which the broken version pretended something had happened.
    """
    drawing = full_tree
    one = drawing.create_operation("engrave", label="One")["id"]
    drawing.create_operation("cut", label="Two")

    out = drawing.move_operation(one, direction="up")

    assert out["moved"] is False
    assert visible(drawing) == ["One", "Two"]


def test_move_to_index_places_the_layer_there(kernel, drawing):
    ids = make(drawing, "cut", "engrave", "raster", "dots")

    out = drawing.move_operation(ids[3], index=0)

    assert out["moved"] is True
    assert types(kernel)[:4] == ["dots", "cut", "engrave", "raster"]


def test_move_to_index_downwards_lands_below_the_target(kernel, drawing):
    """
    Dragging down means: coming below the layer that is there now.

    Without that distinction the layer keeps landing one place beside it and while dragging
    the list runs a place behind the pointer.
    """
    ids = make(drawing, "cut", "engrave", "raster")

    drawing.move_operation(ids[0], index=2)

    assert types(kernel)[:3] == ["engrave", "raster", "cut"]


def test_move_to_own_index_changes_nothing(kernel, drawing):
    ids = make(drawing, "cut", "engrave")

    out = drawing.move_operation(ids[1], index=1)

    assert out["moved"] is False
    assert types(kernel)[:2] == ["cut", "engrave"]


def test_move_needs_exactly_one_of_direction_or_index(drawing):
    ids = make(drawing, "cut", "engrave")

    with pytest.raises(DesignError):
        drawing.move_operation(ids[0])
    with pytest.raises(DesignError):
        drawing.move_operation(ids[0], "down", 1)


def test_move_to_index_out_of_range_is_refused(drawing):
    ids = make(drawing, "cut", "engrave")

    with pytest.raises(DesignError):
        drawing.move_operation(ids[0], index=7)


def test_move_route_accepts_an_index(client, kernel, drawing):
    # Create them through the route, not through the fixture: the server keeps its own
    # `Drawing` and therefore its own list of "made by the user". Make the layers beside it and
    # the route does not know them as a visible layer and you are ordering something that is
    # not in the server's list.
    ids = [
        client.post("/api/design/operations", json={"type": kind}).json()["id"]
        for kind in ("cut", "engrave")
    ]

    response = client.post(
        f"/api/design/operations/{ids[1]}/move", json={"index": 0}
    )

    assert response.status_code == 200
    assert types(kernel)[:2] == ["engrave", "cut"]


# ------------------------------------------- L2: graveren vóór snijden


def test_sort_puts_cutting_last(kernel, drawing):
    make(drawing, "cut", "engrave", "raster")

    out = drawing.sort_operations()

    assert out["sorted"] is True
    assert types(kernel) == ["raster", "engrave", "cut"]


def test_sort_keeps_the_order_the_user_chose_within_one_kind(kernel, drawing):
    """Stabiel: twee snijlagen houden hun onderlinge volgorde."""
    eerste, tweede = make(drawing, "cut", "cut")
    for op in kernel.elements.op_branch.children:
        if getattr(op, "id", None) == eerste:
            op.label = "Buitensnede"
        if getattr(op, "id", None) == tweede:
            op.label = "Binnensnede"
    make(drawing, "engrave")

    drawing.sort_operations()

    labels = [
        op.label
        for op in kernel.elements.op_branch.children
        if str(op.type) == "op cut"
    ]
    assert labels == ["Buitensnede", "Binnensnede"]


def test_sort_puts_the_lightest_layer_of_a_kind_first(kernel, drawing):
    """
    Gap L7: within the same kind the strength counts too.

    Two cut layers are not interchangeable. A score line at 12% and a through-cut at 90%
    belong in that order: as soon as the workpiece is loose it no longer lies still for the
    rest. The sorting used to look only at the kind, and then a cut layer at 5% went to the
    back just as hard as one that goes through.
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
    make(drawing, "raster", "engrave", "cut")

    assert drawing.sort_operations()["sorted"] is False


def test_sort_route(client, kernel, drawing):
    for kind in ("cut", "raster"):
        client.post("/api/design/operations", json={"type": kind})

    response = client.post("/api/design/operations/sort")

    assert response.status_code == 200
    assert types(kernel) == ["raster", "cut"]


# -------------------------------------------------- L3: a layer's kind


def test_retype_keeps_the_shapes_and_the_place(kernel, drawing):
    ids = make(drawing, "engrave", "cut", "raster")
    vorm = drawing.create("rect", x_mm=10, y_mm=10, width_mm=20, height_mm=20)
    from openkerf_api.edits import DesignEditor

    DesignEditor(kernel).assign(vorm["ids"], ids[1])

    out = drawing.change_operation_type(ids[1], "engrave")

    assert out["changed"] is True
    assert out["elements"] == 1
    # In the old layer's place: the burn order must not jump because you adjust the kind.
    # (While drawing, the engine also hangs a classification layer in the tree itself, so we
    # test the place and not the whole list.)
    kinderen = [op.id for op in kernel.elements.op_branch.children]
    assert kinderen.index(out["id"]) == out["index"]
    assert types(kernel)[out["index"]] == "engrave"
    nieuw = kernel.elements.find_node(out["id"])
    verwezen = [
        getattr(child, "node", None) for child in nieuw.children
    ]
    assert kernel.elements.find_node(vorm["ids"][0]) in verwezen


def test_retype_keeps_settings_and_colour(kernel, drawing):
    (layer,) = make(drawing, "cut")
    drawing.update_operation(layer, speed=12, power_percent=80, passes=3, color="#8E4EC6")

    out = drawing.change_operation_type(layer, "engrave")

    nieuw = kernel.elements.find_node(out["id"])
    assert float(nieuw.speed) == 12
    assert float(nieuw.power) == 800
    assert int(nieuw.passes) == 3
    assert str(nieuw.color.hexrgb).lower() == "#8e4ec6"


def test_retype_renames_a_default_label_but_keeps_a_chosen_one(kernel, drawing):
    standaard, eigen = make(drawing, "cut", "cut")
    drawing.update_operation(eigen, label="Buitensnede")

    one = drawing.change_operation_type(standaard, "engrave")
    twee = drawing.change_operation_type(eigen, "engrave")

    assert kernel.elements.find_node(one["id"]).label == "Engrave"
    assert kernel.elements.find_node(twee["id"]).label == "Buitensnede"


def test_retype_to_the_same_kind_is_a_no_op(drawing):
    (layer,) = make(drawing, "cut")

    assert drawing.change_operation_type(layer, "cut")["changed"] is False


def test_retype_refuses_an_unknown_kind(drawing):
    (layer,) = make(drawing, "cut")

    with pytest.raises(DesignError):
        drawing.change_operation_type(layer, "vaporise")


def test_retype_refuses_a_test_grid_cell(kernel, drawing):
    (layer,) = make(drawing, "cut")
    drawing.update_operation(layer, speed=25, power_percent=40)
    drawing.grid_operations = lambda: {
        layer: {"grid_id": 1, "row": 0, "column": 0, "speed_mm_s": 25, "power_percent": 40}
    }

    with pytest.raises(DesignError):
        drawing.change_operation_type(layer, "engrave")


def test_retype_route(client, kernel, drawing):
    (layer,) = make(drawing, "cut")

    response = client.post(
        f"/api/design/operations/{layer}/type", json={"type": "raster"}
    )

    assert response.status_code == 200
    assert types(kernel) == ["raster"]


# --------------------------------------------- L4 / B11: air assist


def test_air_assist_is_not_offered_without_a_driver_command(client, drawing):
    """
    Decision B11: what the machine cannot do does not belong on the screen as a switch. The
    dummy device has claimed no coolant method.
    """
    assert drawing.air_assist_supported() is False
    # The same rule holds for the Z step per pass: the dummy device has no Z
    # axis, so there is no field for it on the screen.
    assert client.get("/api/design/capabilities").json() == {
        "air_assist": False,
        "z_step": False,
    }


def test_air_assist_is_refused_while_the_machine_has_none(drawing):
    (layer,) = make(drawing, "cut")

    with pytest.raises(DesignError):
        drawing.update_operation(layer, air_assist=True)


def test_air_assist_sets_the_engine_field_when_the_machine_has_one(kernel, drawing):
    """
    The engine knows three states in `coolant`: 0 leave it, 1 on, 2 off. Off has
    to be explicitly off, or the blower stays on while the switch says it is off.
    """
    drawing.air_assist_supported = lambda: True
    (layer,) = make(drawing, "cut")

    drawing.update_operation(layer, air_assist=True)
    assert int(kernel.elements.find_node(layer).coolant) == 1

    drawing.update_operation(layer, air_assist=False)
    assert int(kernel.elements.find_node(layer).coolant) == 2


def test_air_assist_shows_up_in_the_snapshot(kernel, drawing):
    drawing.air_assist_supported = lambda: True
    (layer,) = make(drawing, "cut")
    drawing.create("rect", x_mm=10, y_mm=10, width_mm=10, height_mm=10)

    from openkerf_api.design import DesignReader

    drawing.update_operation(layer, air_assist=True)
    snapshot = DesignReader(kernel, keep_operations={layer}).snapshot()
    aan = [op for op in snapshot["operations"] if op["id"] == layer]

    assert aan and aan[0]["air_assist"] is True


def test_air_assist_survives_a_change_of_kind(kernel, drawing):
    drawing.air_assist_supported = lambda: True
    (layer,) = make(drawing, "cut")
    drawing.update_operation(layer, air_assist=True)

    out = drawing.change_operation_type(layer, "engrave")

    assert int(kernel.elements.find_node(out["id"]).coolant) == 1


# --------------------------------- C2: off the bed and off the sheet


def test_bounds_report_counts_what_falls_off_the_bed(drawing):
    bed = drawing.bed_mm()
    assert bed is not None
    drawing.create("rect", x_mm=10, y_mm=10, width_mm=20, height_mm=20)
    drawing.create("rect", x_mm=bed[0] - 5, y_mm=10, width_mm=40, height_mm=20)

    out = drawing.bounds_report()

    assert out["outside_bed"] == 1
    assert out["outside_sheet"] == 0  # no sheet passed in
    assert out["work"]["x_mm"] == 10.0


def test_bounds_report_counts_what_falls_off_the_sheet(drawing):
    drawing.create("rect", x_mm=10, y_mm=10, width_mm=20, height_mm=20)
    drawing.create("rect", x_mm=10, y_mm=190, width_mm=20, height_mm=40)

    out = drawing.bounds_report({"width_mm": 310, "height_mm": 210})

    assert out["outside_sheet"] == 1
    assert out["sheet"] == {"width_mm": 310, "height_mm": 210}


def test_a_shape_exactly_on_the_edge_is_not_a_warning(drawing):
    """A shape that fills the sheet exactly is not a mistake but well nested."""
    drawing.create("rect", x_mm=0, y_mm=0, width_mm=310, height_mm=210)

    out = drawing.bounds_report({"width_mm": 310, "height_mm": 210})

    assert out["outside_sheet"] == 0


def test_estimate_carries_the_bounds(client, drawing):
    drawing.create("rect", x_mm=10, y_mm=10, width_mm=20, height_mm=20)

    bounds = client.get("/api/job/estimate").json()["bounds"]

    assert bounds["bed"]["width_mm"] > 0
    assert bounds["outside_bed"] == 0
    assert bounds["work"]["width_mm"] == 20.0
