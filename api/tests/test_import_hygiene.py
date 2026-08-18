"""
Een geïmporteerde tekening bruikbaar maken.

Drie handelingen die samen één klacht oplossen: een OpenSCAD-export komt binnen
als één pad met tientallen subpaden (niets los aan te klikken), landt door
`classify_black_as_raster` in een rasterlaag, en naast die laag staan tien lege
lagen die de engine bij het opstarten aanmaakt.
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
    """Wat een OpenSCAD-export in het klein is: één pad, meerdere subpaden."""
    a = drawing.create("rect", x_mm=10, y_mm=10, width_mm=20, height_mm=20)
    b = drawing.create("rect", x_mm=50, y_mm=10, width_mm=20, height_mm=20)
    kernel.elements.set_emphasis(
        [kernel.elements.find_node(a["ids"][0]), kernel.elements.find_node(b["ids"][0])]
    )
    kernel.console("element merge\n")
    kernel.elements.validate_ids()
    samen = list(kernel.elements.elems())
    assert len(samen) == 1
    return samen[0].id


def only_these_layers(kernel, hoeveel: int) -> None:
    """
    Met een schone lei beginnen.

    De lagenlijst bij het opstarten is niet vast: de engine bewaart de lagen van
    de vorige sessie in een gedeelde `operations.cfg` (niet per profiel, en ook
    met `ignore_settings` gelezen) en zet die terug. Een test die op een aantal
    rekent, rekent dus op wat er hier eerder liep.
    """
    for op in list(kernel.elements.ops()):
        op.remove_node()
    assert not list(kernel.elements.ops())


def layers_with_live_work(kernel) -> list:
    """Lagen die echt werk bevatten — dode verwijzingen tellen niet mee."""
    levend = {id(node) for node in kernel.elements.elems()}
    return [
        op
        for op in kernel.elements.ops()
        if any(id(getattr(c, "node", None)) in levend for c in op.children)
    ]


# ------------------------------------------------------------------- splitsen


def test_splitting_a_path_makes_one_shape_per_subpath(kernel, drawing, editor):
    pad = one_path_of_two_rects(kernel, drawing)

    result = editor.split(pad)

    assert result["count"] == 2
    assert len(result["ids"]) == 2
    # En ze zijn los aan te klikken: elk id vindt een eigen element terug.
    gevonden = [kernel.elements.find_node(i) for i in result["ids"]]
    assert all(node is not None for node in gevonden)
    assert len({id(node) for node in gevonden}) == 2


def test_splitting_leaves_no_dead_reference_behind(kernel, drawing, editor):
    """
    De engine laat na `subpath` een verwijzing naar het weggehaalde pad staan.

    Gemeten in de kale kernel: een graveerlaag met één verwijzing gaat na het
    splitsen naar drie — de twee nieuwe stukken plus het origineel, dat niet
    meer in de boom staat maar nog wel in de laag hangt. Dat is niet cosmetisch:
    die laag zou het hele pad én de losse stukken branden.
    """
    pad = one_path_of_two_rects(kernel, drawing)

    editor.split(pad)

    levend = {id(node) for node in kernel.elements.elems()}
    dood = [
        c
        for op in kernel.elements.ops()
        for c in op.children
        if id(getattr(c, "node", None)) not in levend
    ]
    assert dood == []


def test_a_path_with_one_subpath_is_left_alone(kernel, drawing, editor):
    enkel = drawing.create("rect", x_mm=10, y_mm=10, width_mm=20, height_mm=20)

    result = editor.split(enkel["ids"][0])

    assert result["count"] == 0
    assert result["skipped"] == 1
    # De vorm staat er nog, en niet in een groep gestopt.
    assert kernel.elements.find_node(enkel["ids"][0]) is not None


def test_splitting_needs_something_to_split(editor):
    with pytest.raises(DesignError):
        editor.split([])


# ------------------------------------------------------------- één snijlaag


def test_the_selection_ends_up_in_a_cut_layer_and_nowhere_else(kernel, drawing):
    tekening = Drawing(kernel)
    eerste = tekening.create("rect", x_mm=10, y_mm=10, width_mm=20, height_mm=20)
    tweede = tekening.create("rect", x_mm=50, y_mm=10, width_mm=20, height_mm=20)
    ids = eerste["ids"] + tweede["ids"]
    # Zoals een import binnenkomt: in een laag die niet snijdt.
    assert [op.type for op in layers_with_live_work(kernel)] != ["op cut"]

    result = tekening.single_layer(ids, kind="cut")

    lagen = layers_with_live_work(kernel)
    assert [op.type for op in lagen] == ["op cut"]
    assert lagen[0].id == result["operation_id"]
    assert result["assigned"] == 2


def test_one_cut_layer_reuses_the_layer_that_is_already_there(kernel, drawing):
    vorm = drawing.create("rect", x_mm=10, y_mm=10, width_mm=20, height_mm=20)
    voor = len(list(kernel.elements.ops()))

    result = drawing.single_layer(vorm["ids"], kind="cut")

    assert len(list(kernel.elements.ops())) == voor
    assert result["created"] is False


def test_one_cut_layer_makes_one_when_the_design_has_none(kernel, drawing):
    """Alle snijlagen weg, en toch moet 'naar snijlaag' ergens landen."""
    for op in [o for o in kernel.elements.ops() if str(o.type) == "op cut"]:
        op.remove_node()
    vorm = drawing.create("rect", x_mm=10, y_mm=10, width_mm=20, height_mm=20)

    result = drawing.single_layer(vorm["ids"], kind="cut")

    assert result["created"] is True
    laag = kernel.elements.find_node(result["operation_id"])
    assert str(laag.type) == "op cut"


def test_one_layer_can_also_engrave(kernel, drawing):
    vorm = drawing.create("rect", x_mm=10, y_mm=10, width_mm=20, height_mm=20)

    result = drawing.single_layer(vorm["ids"], kind="engrave")

    assert str(kernel.elements.find_node(result["operation_id"]).type) == "op engrave"


def test_one_layer_refuses_a_layer_type_it_does_not_know(drawing):
    vorm = drawing.create("rect", x_mm=10, y_mm=10, width_mm=20, height_mm=20)

    with pytest.raises(DesignError):
        drawing.single_layer(vorm["ids"], kind="vouwen")


def test_one_layer_can_be_pointed_at_an_existing_layer(kernel, drawing):
    doel = drawing.create_operation("cut", label="Buitenrand")
    vorm = drawing.create("rect", x_mm=10, y_mm=10, width_mm=20, height_mm=20)

    result = drawing.single_layer(vorm["ids"], operation_id=doel["id"])

    assert result["operation_id"] == doel["id"]
    assert [op.id for op in layers_with_live_work(kernel)] == [doel["id"]]


# --------------------------------------------------------------- opruimen


def test_pruning_removes_the_empty_layers_and_keeps_the_filled_one(kernel, drawing):
    only_these_layers(kernel, 0)
    for _ in range(3):
        drawing.create_operation("cut")
    vorm = drawing.create("rect", x_mm=10, y_mm=10, width_mm=20, height_mm=20)
    gevuld = drawing.single_layer(vorm["ids"], kind="cut")["operation_id"]
    assert len(list(kernel.elements.ops())) > 1

    result = drawing.prune_operations()

    assert result["removed"] >= 1
    assert [op.id for op in kernel.elements.ops()] == [gevuld]


def test_pruning_counts_a_layer_with_only_dead_references_as_empty(
    kernel, drawing, editor
):
    """
    Na het splitsen houdt een laag een verwijzing naar het verdwenen pad.

    Zonder deze regel zou zo'n laag als 'gevuld' tellen en blijven staan — een
    laag die niets meer voorstelt en toch in de lijst staat.
    """
    pad = one_path_of_two_rects(kernel, drawing)
    laag = drawing.create_operation("cut", label="Rest")
    kernel.elements.find_node(laag["id"]).add_reference(kernel.elements.find_node(pad))
    editor.split(pad)

    drawing.prune_operations()

    assert kernel.elements.find_node(laag["id"]) is None


def test_pruning_leaves_a_test_board_layer_alone(kernel, drawing):
    laag = kernel.elements.find_node(drawing.create_operation("cut")["id"])
    laag.label = LABEL_LAYER

    drawing.prune_operations()

    assert kernel.elements.find_node(laag.id) is not None


def test_pruning_an_already_tidy_design_changes_nothing(kernel, drawing):
    vorm = drawing.create("rect", x_mm=10, y_mm=10, width_mm=20, height_mm=20)
    drawing.single_layer(vorm["ids"], kind="cut")
    drawing.prune_operations()
    voor = [op.id for op in kernel.elements.ops()]

    result = drawing.prune_operations()

    assert result["removed"] == 0
    assert [op.id for op in kernel.elements.ops()] == voor


# ------------------------------------------------------------------- routes


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
    pad = list(kernel.elements.elems())[0].id

    gesplitst = client.post("/api/design/split", json={"ids": [pad]})
    assert gesplitst.status_code == 200, gesplitst.text
    stukken = gesplitst.json()["ids"]
    assert len(stukken) == 2

    naar = client.post(
        "/api/design/single-layer", json={"ids": stukken, "type": "cut"}
    )
    assert naar.status_code == 200, naar.text
    assert [op.type for op in layers_with_live_work(kernel)] == ["op cut"]

    opgeruimd = client.post("/api/design/operations/prune")
    assert opgeruimd.status_code == 200, opgeruimd.text
    assert opgeruimd.json()["removed"] >= 1
    # Wat overblijft heeft werk. Eén uitzondering blijft staan: de labellaag
    # van een testbord, die bij een bord hoort en niet bij de gebruiker.
    met_werk = {op.id for op in layers_with_live_work(kernel)}
    leeg = [
        op.label for op in kernel.elements.ops() if op.id not in met_werk
    ]
    assert all(label == LABEL_LAYER for label in leeg), leeg
    assert len(met_werk) == 1


def test_a_bad_request_says_what_is_wrong(client):
    antwoord = client.post("/api/design/split", json={"ids": []})
    assert antwoord.status_code == 409
    assert antwoord.json()["detail"]


def test_the_snapshot_says_how_many_pieces_a_path_holds(kernel, drawing, client):
    """
    Het paneel moet op zijn knop kunnen zetten wat splitsen oplevert.

    Dat getal komt uit de pad-data die de snapshot toch al meestuurt (elk stuk
    begint met een `M`), dus het kost geen extra rekenwerk per snapshot.
    """
    pad = one_path_of_two_rects(kernel, drawing)

    elementen = client.get("/api/design").json()["elements"]
    stuk = next(e for e in elementen if e["id"] == pad)

    assert stuk["subpaths"] == 2

    losse = drawing.create("rect", x_mm=90, y_mm=10, width_mm=10, height_mm=10)
    elementen = client.get("/api/design").json()["elements"]
    enkel = next(e for e in elementen if e["id"] == losse["ids"][0])
    assert enkel["subpaths"] == 1
