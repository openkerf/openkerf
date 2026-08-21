"""
Making an imported drawing workable.

Three actions that together solve one complaint: an OpenSCAD export arrives as
one path with dozens of subpaths (nothing to click separately), lands in a
raster layer through `classify_black_as_raster`, and next to that layer sit ten
empty layers that the engine creates on start-up.
"""

import pytest
from fastapi.testclient import TestClient

from openkerf_api.drawing import LABEL_LAYER, Drawing
from openkerf_api.edits import DesignEditor, DesignError
from openkerf_api.server import ApiServer


@pytest.fixture
def client(kernel, tmp_path):
    with TestClient(ApiServer(kernel, library_path=tmp_path / "d.db").build_app()) as c:
        yield c


@pytest.fixture
def drawing(kernel):
    return Drawing(kernel)


@pytest.fixture
def editor(kernel):
    return DesignEditor(kernel)


def one_path_of_two_rects(kernel, drawing) -> str:
    """What an OpenSCAD export is in miniature: one path, several subpaths."""
    a = drawing.create("rect", x_mm=10, y_mm=10, width_mm=20, height_mm=20)
    b = drawing.create("rect", x_mm=50, y_mm=10, width_mm=20, height_mm=20)
    kernel.elements.set_emphasis(
        [kernel.elements.find_node(a["ids"][0]), kernel.elements.find_node(b["ids"][0])]
    )
    kernel.console("element merge\n")
    kernel.elements.validate_ids()
    together = list(kernel.elements.elems())
    assert len(together) == 1
    return together[0].id


def only_these_layers(kernel, how_many: int) -> None:
    """
    Starting with a clean slate.

    The layer list at start-up is not fixed: the engine keeps the previous
    session's layers in a shared `operations.cfg` (not per profile, and read
    even with `ignore_settings`) and puts them back. So a test that counts on a
    number is counting on whatever ran here before.
    """
    for op in list(kernel.elements.ops()):
        op.remove_node()
    assert not list(kernel.elements.ops())


def layers_with_live_work(kernel) -> list:
    """Layers that really hold work — dead references do not count."""
    live = {id(node) for node in kernel.elements.elems()}
    return [
        op
        for op in kernel.elements.ops()
        if any(id(getattr(c, "node", None)) in live for c in op.children)
    ]


# -------------------------------------------------------------------- splitting


def test_splitting_a_path_makes_one_shape_per_subpath(kernel, drawing, editor):
    path = one_path_of_two_rects(kernel, drawing)

    result = editor.split(path)

    assert result["count"] == 2
    assert len(result["ids"]) == 2
    # And they are separately clickable: every id finds an element of its own.
    found = [kernel.elements.find_node(i) for i in result["ids"]]
    assert all(node is not None for node in found)
    assert len({id(node) for node in found}) == 2


def test_splitting_leaves_no_dead_reference_behind(kernel, drawing, editor):
    """
    After `subpath` the engine leaves a reference to the removed path behind.

    Measured in a bare kernel: an engrave layer with one reference goes to three
    after the split — the two new pieces plus the original, which is no longer
    in the tree but still hangs in the layer. That is not cosmetic: that layer
    would burn the whole path *and* the separate pieces.
    """
    path = one_path_of_two_rects(kernel, drawing)

    editor.split(path)

    live = {id(node) for node in kernel.elements.elems()}
    dead = [
        c
        for op in kernel.elements.ops()
        for c in op.children
        if id(getattr(c, "node", None)) not in live
    ]
    assert dead == []


def test_a_path_with_one_subpath_is_left_alone(kernel, drawing, editor):
    single = drawing.create("rect", x_mm=10, y_mm=10, width_mm=20, height_mm=20)

    result = editor.split(single["ids"][0])

    assert result["count"] == 0
    assert result["skipped"] == 1
    # The shape is still there, and not stuffed into a group.
    assert kernel.elements.find_node(single["ids"][0]) is not None


def test_splitting_needs_something_to_split(editor):
    with pytest.raises(DesignError):
        editor.split([])


# ------------------------------------------------------------- one cut layer


def test_the_selection_ends_up_in_a_cut_layer_and_nowhere_else(kernel, drawing):
    design = Drawing(kernel)
    first = design.create("rect", x_mm=10, y_mm=10, width_mm=20, height_mm=20)
    second = design.create("rect", x_mm=50, y_mm=10, width_mm=20, height_mm=20)
    ids = first["ids"] + second["ids"]
    # The way an import arrives: in a layer that does not cut.
    assert [op.type for op in layers_with_live_work(kernel)] != ["op cut"]

    result = design.single_layer(ids, kind="cut")

    layers = layers_with_live_work(kernel)
    assert [op.type for op in layers] == ["op cut"]
    assert layers[0].id == result["operation_id"]
    assert result["assigned"] == 2


def test_one_cut_layer_reuses_the_layer_that_is_already_there(kernel, drawing):
    shape = drawing.create("rect", x_mm=10, y_mm=10, width_mm=20, height_mm=20)
    before = len(list(kernel.elements.ops()))

    result = drawing.single_layer(shape["ids"], kind="cut")

    assert len(list(kernel.elements.ops())) == before
    assert result["created"] is False


def test_one_cut_layer_makes_one_when_the_design_has_none(kernel, drawing):
    """Every cut layer gone, and yet 'to cut layer' has to land somewhere."""
    for op in [o for o in kernel.elements.ops() if str(o.type) == "op cut"]:
        op.remove_node()
    shape = drawing.create("rect", x_mm=10, y_mm=10, width_mm=20, height_mm=20)

    result = drawing.single_layer(shape["ids"], kind="cut")

    assert result["created"] is True
    layer = kernel.elements.find_node(result["operation_id"])
    assert str(layer.type) == "op cut"


def test_one_layer_can_also_engrave(kernel, drawing):
    shape = drawing.create("rect", x_mm=10, y_mm=10, width_mm=20, height_mm=20)

    result = drawing.single_layer(shape["ids"], kind="engrave")

    assert str(kernel.elements.find_node(result["operation_id"]).type) == "op engrave"


def test_one_layer_refuses_a_layer_type_it_does_not_know(drawing):
    shape = drawing.create("rect", x_mm=10, y_mm=10, width_mm=20, height_mm=20)

    with pytest.raises(DesignError):
        drawing.single_layer(shape["ids"], kind="folding")


def test_one_layer_can_be_pointed_at_an_existing_layer(kernel, drawing):
    target = drawing.create_operation("cut", label="Outline")
    shape = drawing.create("rect", x_mm=10, y_mm=10, width_mm=20, height_mm=20)

    result = drawing.single_layer(shape["ids"], operation_id=target["id"])

    assert result["operation_id"] == target["id"]
    assert [op.id for op in layers_with_live_work(kernel)] == [target["id"]]


def test_the_shape_takes_the_colour_of_the_layer_it_moves_to(kernel, drawing):
    """
    Without the stroke colour the shape jumps back at the next classification.

    In MeerK40t the stroke colour *is* what classification works on. The same
    rule as in the colour strip (`Drawing.paint`), and just as necessary here:
    an imported black path would otherwise stay 'black = raster'.
    """
    shape = drawing.create("rect", x_mm=10, y_mm=10, width_mm=20, height_mm=20)
    layer = drawing.create_operation("cut", label="Outline")
    target = kernel.elements.find_node(layer["id"])

    drawing.single_layer(shape["ids"], operation_id=layer["id"])

    node = kernel.elements.find_node(shape["ids"][0])
    assert str(node.stroke).lower() == str(target.color).lower()


# ----------------------------------------------------------------- tidying up


def test_pruning_removes_the_empty_layers_and_keeps_the_filled_one(kernel, drawing):
    only_these_layers(kernel, 0)
    for _ in range(3):
        drawing.create_operation("cut")
    shape = drawing.create("rect", x_mm=10, y_mm=10, width_mm=20, height_mm=20)
    filled = drawing.single_layer(shape["ids"], kind="cut")["operation_id"]
    assert len(list(kernel.elements.ops())) > 1

    result = drawing.prune_operations()

    assert result["removed"] >= 1
    assert [op.id for op in kernel.elements.ops()] == [filled]


def test_pruning_counts_a_layer_with_only_dead_references_as_empty(
    kernel, drawing, editor
):
    """
    After a split a layer keeps a reference to the path that disappeared.

    Without this rule such a layer would count as 'filled' and stay put — a
    layer that no longer stands for anything and is still in the list.
    """
    path = one_path_of_two_rects(kernel, drawing)
    layer = drawing.create_operation("cut", label="Rest")
    kernel.elements.find_node(layer["id"]).add_reference(kernel.elements.find_node(path))
    editor.split(path)

    drawing.prune_operations()

    assert kernel.elements.find_node(layer["id"]) is None


def test_pruning_leaves_a_test_board_layer_alone(kernel, drawing):
    layer = kernel.elements.find_node(drawing.create_operation("cut")["id"])
    layer.label = LABEL_LAYER

    drawing.prune_operations()

    assert kernel.elements.find_node(layer.id) is not None


def test_pruning_an_already_tidy_design_changes_nothing(kernel, drawing):
    shape = drawing.create("rect", x_mm=10, y_mm=10, width_mm=20, height_mm=20)
    drawing.single_layer(shape["ids"], kind="cut")
    drawing.prune_operations()
    before = [op.id for op in kernel.elements.ops()]

    result = drawing.prune_operations()

    assert result["removed"] == 0
    assert [op.id for op in kernel.elements.ops()] == before


# -------------------------------------------------------------------- routes


def test_the_three_routes_do_what_the_methods_do(client, kernel):
    a = client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 10, "y_mm": 10, "width_mm": 20, "height_mm": 20},
    ).json()["ids"][0]
    b = client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 50, "y_mm": 10, "width_mm": 20, "height_mm": 20},
    ).json()["ids"][0]
    kernel.elements.set_emphasis(
        [kernel.elements.find_node(a), kernel.elements.find_node(b)]
    )
    kernel.console("element merge\n")
    kernel.elements.validate_ids()
    path = list(kernel.elements.elems())[0].id

    split = client.post("/api/design/split", json={"ids": [path]})
    assert split.status_code == 200, split.text
    pieces = split.json()["ids"]
    assert len(pieces) == 2

    moved = client.post(
        "/api/design/single-layer", json={"ids": pieces, "type": "cut"}
    )
    assert moved.status_code == 200, moved.text
    assert [op.type for op in layers_with_live_work(kernel)] == ["op cut"]

    pruned = client.post("/api/design/operations/prune")
    assert pruned.status_code == 200, pruned.text
    assert pruned.json()["removed"] >= 1
    # What is left holds work. One exception stays: the label layer of a test
    # board, which belongs to the board and not to the user.
    with_work = {op.id for op in layers_with_live_work(kernel)}
    empty = [
        op.label for op in kernel.elements.ops() if op.id not in with_work
    ]
    assert all(label == LABEL_LAYER for label in empty), empty
    assert len(with_work) == 1


def test_a_bad_request_says_what_is_wrong(client):
    answer = client.post("/api/design/split", json={"ids": []})
    assert answer.status_code == 409
    assert answer.json()["detail"]


def test_the_snapshot_says_how_many_pieces_a_path_holds(kernel, drawing, client):
    """
    The panel has to be able to put on its button what splitting will yield.

    That number comes out of the path data the snapshot sends along anyway (every
    piece starts with an `M`), so it costs no extra work per snapshot.
    """
    path = one_path_of_two_rects(kernel, drawing)

    elements = client.get("/api/design").json()["elements"]
    piece = next(e for e in elements if e["id"] == path)

    assert piece["subpaths"] == 2

    loose = drawing.create("rect", x_mm=90, y_mm=10, width_mm=10, height_mm=10)
    elements = client.get("/api/design").json()["elements"]
    single = next(e for e in elements if e["id"] == loose["ids"][0])
    assert single["subpaths"] == 1
