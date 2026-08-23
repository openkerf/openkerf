"""Drawing shapes and text, and managing layers."""

import pytest
from fastapi.testclient import TestClient

from meerk40t.core.units import UNITS_PER_MM

from openkerf_api.design import DesignReader
from openkerf_api.drawing import Drawing
from openkerf_api.edits import DesignEditor, DesignError
from openkerf_api.server import ApiServer


@pytest.fixture
def client(kernel, tmp_path):
    with TestClient(ApiServer(kernel, library_path=tmp_path / "d.db").build_app()) as c:
        yield c


@pytest.fixture
def drawing(kernel):
    return Drawing(kernel)


def bounds_mm(kernel, element_id):
    node = kernel.elements.find_node(element_id)
    return [round(v / UNITS_PER_MM, 1) for v in node.bounds]


# ---------------------------------------------------------------- shapes

def test_rect_lands_where_it_was_asked_for(kernel, drawing):
    result = drawing.create("rect", x_mm=20, y_mm=15, width_mm=60, height_mm=40)

    assert bounds_mm(kernel, result["ids"][0]) == [20.0, 15.0, 80.0, 55.0]
    assert result["type"] == "elem rect"


def test_circle_and_ellipse(kernel, drawing):
    circle = drawing.create("circle", cx_mm=50, cy_mm=50, r_mm=10)
    ellipse = drawing.create("ellipse", cx_mm=120, cy_mm=50, rx_mm=20, ry_mm=10)

    assert bounds_mm(kernel, circle["ids"][0]) == [40.0, 40.0, 60.0, 60.0]
    assert bounds_mm(kernel, ellipse["ids"][0]) == [100.0, 40.0, 140.0, 60.0]


def test_line(kernel, drawing):
    line = drawing.create("line", x1_mm=10, y1_mm=10, x2_mm=40, y2_mm=30)

    assert bounds_mm(kernel, line["ids"][0]) == [10.0, 10.0, 40.0, 30.0]


def test_text_becomes_vector_geometry(kernel, drawing):
    """Bitmap text has no geometry, so it would be invisible on the canvas."""
    result = drawing.create("text", x_mm=20, y_mm=40, text="OpenKerf")

    node = kernel.elements.find_node(result["ids"][0])
    assert node.bounds is not None
    assert hasattr(node, "as_geometry")
    snapshot = DesignReader(kernel).snapshot()
    assert any(e["id"] == result["ids"][0] and e["path"] for e in snapshot["elements"])


def test_empty_text_is_refused(drawing):
    for bad in ("", "   ", None):
        with pytest.raises(DesignError):
            drawing.create("text", x_mm=10, y_mm=10, text=bad)


def test_unknown_shape_is_refused(drawing):
    with pytest.raises(DesignError):
        drawing.create("driehoek", x_mm=1, y_mm=1, width_mm=1, height_mm=1)


def test_sizes_must_be_positive(drawing):
    with pytest.raises(DesignError):
        drawing.create("rect", x_mm=10, y_mm=10, width_mm=0, height_mm=10)
    with pytest.raises(DesignError):
        drawing.create("circle", cx_mm=10, cy_mm=10, r_mm=-5)


def test_a_new_shape_is_selected(kernel, drawing):
    """So you can drag or resize it straight away."""
    result = drawing.create("rect", x_mm=10, y_mm=10, width_mm=10, height_mm=10)

    emphasized = [n.id for n in kernel.elements.elems(emphasized=True)]
    assert emphasized == result["ids"]


def test_drawing_is_undoable(kernel, drawing, client):
    drawing.create("rect", x_mm=10, y_mm=10, width_mm=10, height_mm=10)
    assert len(list(kernel.elements.elems())) == 1

    client.post("/api/design/undo")

    assert len(list(kernel.elements.elems())) == 0


# --------------------------------------------------------- delete/duplicate

def test_delete_removes_only_the_named_elements(kernel, drawing):
    keep = drawing.create("rect", x_mm=10, y_mm=10, width_mm=10, height_mm=10)
    drop = drawing.create("rect", x_mm=40, y_mm=10, width_mm=10, height_mm=10)

    drawing.delete(drop["ids"])

    remaining = [n.id for n in kernel.elements.elems()]
    assert remaining == keep["ids"]


def test_delete_of_a_stale_id_is_refused(drawing):
    with pytest.raises(DesignError):
        drawing.delete(["meerk40t:bestaatniet"])


def test_duplicate_adds_a_copy(kernel, drawing):
    original = drawing.create("rect", x_mm=10, y_mm=10, width_mm=20, height_mm=20)

    copy = drawing.duplicate(original["ids"])

    assert len(list(kernel.elements.elems())) == 2
    assert copy["ids"] != original["ids"]
    assert bounds_mm(kernel, copy["ids"][0]) == bounds_mm(kernel, original["ids"][0])


# ---------------------------------------------------------------- layers

def test_create_a_layer_with_settings(kernel, drawing):
    result = drawing.create_operation("cut", label="Buitenrand", speed=12, power_percent=65)

    node = kernel.elements.find_node(result["id"])
    assert node.type == "op cut"
    assert node.label == "Buitenrand"
    assert node.speed == 12
    # 0-1000 in the engine, percent on the wire.
    assert node.power == 650


def test_layer_types(kernel, drawing):
    for kind, expected in (
        ("cut", "op cut"),
        ("engrave", "op engrave"),
        ("raster", "op raster"),
        ("dots", "op dots"),
    ):
        result = drawing.create_operation(kind)
        assert kernel.elements.find_node(result["id"]).type == expected


def test_unknown_layer_type_is_refused(drawing):
    with pytest.raises(DesignError):
        drawing.create_operation("laser-beam")


def test_update_a_layer(kernel, drawing):
    created = drawing.create_operation("cut", speed=10, power_percent=50)

    drawing.update_operation(
        created["id"], label="Snijden fijn", speed=8, power_percent=70, passes=2, output=False
    )

    node = kernel.elements.find_node(created["id"])
    assert node.label == "Snijden fijn"
    assert node.speed == 8
    assert node.power == 700
    assert node.passes == 2
    assert node.output is False


def test_power_outside_the_range_is_refused(drawing):
    created = drawing.create_operation("cut")
    for bad in (0, -10, 150):
        with pytest.raises(DesignError):
            drawing.update_operation(created["id"], power_percent=bad)


def test_delete_a_layer_keeps_the_elements(kernel, drawing):
    element = drawing.create("rect", x_mm=10, y_mm=10, width_mm=10, height_mm=10)
    layer = drawing.create_operation("cut", speed=10, power_percent=50)
    kernel.elements.find_node(layer["id"]).add_reference(
        kernel.elements.find_node(element["ids"][0])
    )

    drawing.delete_operation(layer["id"])

    assert kernel.elements.find_node(layer["id"]) is None
    assert kernel.elements.find_node(element["ids"][0]) is not None


def test_an_element_is_not_a_layer(kernel, drawing):
    element = drawing.create("rect", x_mm=10, y_mm=10, width_mm=10, height_mm=10)
    with pytest.raises(DesignError):
        drawing.delete_operation(element["ids"][0])


# ------------------------------------------------------------------- HTTP

def test_draw_over_http(kernel, client):
    response = client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 20, "y_mm": 15, "width_mm": 60, "height_mm": 40},
    )

    assert response.status_code == 201
    assert bounds_mm(kernel, response.json()["ids"][0]) == [20.0, 15.0, 80.0, 55.0]


def test_layer_lifecycle_over_http(kernel, client):
    created = client.post(
        "/api/design/operations", json={"type": "engrave", "label": "Tekst", "speed": 200}
    )
    assert created.status_code == 201
    layer_id = created.json()["id"]

    patched = client.patch(f"/api/design/operations/{layer_id}", json={"power_percent": 25})
    assert patched.status_code == 200
    assert kernel.elements.find_node(layer_id).power == 250

    removed = client.delete(f"/api/design/operations/{layer_id}")
    assert removed.status_code == 200
    assert kernel.elements.find_node(layer_id) is None


def test_bad_shape_over_http_is_a_409(client):
    response = client.post("/api/design/elements", json={"type": "rect", "x_mm": "kaas"})
    assert response.status_code == 409


def test_a_new_empty_layer_stays_visible(kernel, client):
    """
    A fresh element tree carries 201 empty default operations, so empty layers
    are normally hidden. A layer you just created yourself must not vanish
    before you have put anything in it.
    """
    before = len(client.get("/api/design").json()["operations"])

    created = client.post("/api/design/operations", json={"type": "cut", "label": "Nieuw"})

    operations = client.get("/api/design").json()["operations"]
    assert len(operations) == before + 1
    assert any(o["id"] == created.json()["id"] for o in operations)


def test_the_default_stack_stays_hidden(kernel, client):
    """Showing every empty operation would flood the list with 201 entries."""
    operations = client.get("/api/design").json()["operations"]
    assert len(operations) < 10


def test_a_removed_layer_disappears_again(kernel, client):
    created = client.post("/api/design/operations", json={"type": "cut"}).json()
    assert any(o["id"] == created["id"] for o in client.get("/api/design").json()["operations"])

    client.delete(f"/api/design/operations/{created['id']}")

    assert not any(
        o["id"] == created["id"] for o in client.get("/api/design").json()["operations"]
    )


def test_all_layers_go_in_one_action_and_the_shapes_stay(kernel, client):
    """
    Punt 4 van Jelle: alle lagen weggooien moest per laag, drie klikken elk.

    The promise is the same as with one layer: throwing a layer away is not throwing work
    away. Afterwards the shapes are still there, in no layer.
    """
    client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 10, "y_mm": 10, "width_mm": 20, "height_mm": 20},
    )
    client.post("/api/design/operations", json={"type": "cut", "label": "Cut"})
    client.post("/api/design/operations", json={"type": "engrave", "label": "Engrave"})
    voor = client.get("/api/design").json()
    assert len(voor["operations"]) >= 2
    vormen = len(voor["elements"])

    response = client.delete("/api/design/operations")

    assert response.status_code == 200
    assert response.json()["kept_elements"] == vormen
    na = client.get("/api/design").json()
    assert na["operations"] == []
    assert len(na["elements"]) == vormen


def test_dropping_all_layers_without_any_is_refused(client):
    client.delete("/api/design/operations")

    assert client.delete("/api/design/operations").status_code == 409


def test_export_writes_an_svg_that_carries_the_operations(kernel, client):
    """
    Without saving, all work is fleeting. MeerK40t's own writer keeps its
    namespace, so operations survive a round trip.
    """
    client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 20, "y_mm": 15, "width_mm": 60, "height_mm": 40},
    )

    response = client.get("/api/design/export.svg")

    assert response.status_code == 200
    body = response.text
    assert body.startswith("<svg")
    assert "meerk40t" in body


def test_export_filename_cannot_escape_its_directory(kernel, client):
    response = client.get("/api/design/export.svg", params={"filename": "../../etc/passwd"})

    assert response.status_code == 200
    assert response.headers["content-disposition"].count("passwd.svg") == 1


# ------------------------------------------------------ opslaan-status

def test_a_fresh_document_is_clean(client):
    assert client.get("/api/design").json()["dirty"] is False


def test_drawing_makes_the_document_dirty(client):
    client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 10, "y_mm": 10, "width_mm": 10, "height_mm": 10},
    )

    assert client.get("/api/design").json()["dirty"] is True


def test_saving_marks_it_clean_again(client):
    client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 10, "y_mm": 10, "width_mm": 10, "height_mm": 10},
    )

    client.get("/api/design/export.svg")

    assert client.get("/api/design").json()["dirty"] is False


def test_clearing_empties_the_design(kernel, client):
    client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 10, "y_mm": 10, "width_mm": 10, "height_mm": 10},
    )

    response = client.post("/api/design/clear")

    assert response.status_code == 200
    assert list(kernel.elements.elems()) == []
    assert client.get("/api/design").json()["dirty"] is False


def test_loading_replaces_rather_than_merges(kernel, client):
    """
    `load` adds to the tree, so opening a file used to pile it on top of what
    was already there. Clearing first is what makes it feel like opening.
    """
    svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg" width="50mm" height="50mm">'
        b'<rect x="1" y="1" width="20" height="10"/></svg>'
    )
    client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 90, "y_mm": 90, "width_mm": 10, "height_mm": 10},
    )

    client.post("/api/design/clear")
    client.post("/api/job/load", files={"file": ("d.svg", svg, "image/svg+xml")})

    assert len(list(kernel.elements.elems())) == 1
    assert client.get("/api/design").json()["dirty"] is False


# --------------------------------------------------------- tekstopties

def test_text_accepts_a_size(kernel, drawing):
    small = drawing.create("text", x_mm=10, y_mm=40, text="Ab", font_size_mm=4)
    large = drawing.create("text", x_mm=10, y_mm=80, text="Ab", font_size_mm=12)

    def height(result):
        b = kernel.elements.find_node(result["ids"][0]).bounds
        return (b[3] - b[1]) / UNITS_PER_MM

    assert height(large) > height(small) * 2


def test_text_rejects_a_nonsense_size(drawing):
    with pytest.raises(DesignError):
        drawing.create("text", x_mm=10, y_mm=10, text="Ab", font_size_mm=0)


def test_fonts_are_listed(kernel, drawing):
    fonts = drawing.fonts()

    assert isinstance(fonts, list)
    # Hidden system fonts start with a dot and are filtered out.
    assert all(not f["name"].startswith(".") for f in fonts)
    assert all("file" in f and "name" in f for f in fonts)


def test_a_font_whose_file_is_gone_is_not_offered(kernel, drawing, tmp_path):
    """
    The engine keeps its font list in a cache that does not notice a deleted file. Such a row
    can only fail: the picker shows it, fetches the file for the preview and gets a 409 back —
    without anything on the screen about what is going on.
    """
    weg = tmp_path / "Weggegooid.ttf"
    er_nog = tmp_path / "Present.ttf"
    er_nog.write_bytes(b"not really a font, but it exists")

    registry = kernel.root.fonts

    class Verzonnen:
        @staticmethod
        def available_fonts():
            return [
                (str(weg), "Weggegooid"),
                (str(er_nog), "Aanwezig"),
                # As the engine states its own Hershey fonts: a bare name, not a path. That
                # font does exist and has to stay — we set every test board's captions in
                # it.
                ("meerk40t.jhf", "MeerK40t Simple"),
            ]

    kernel.root.fonts = Verzonnen()
    try:
        namen = [f["name"] for f in drawing.fonts()]
    finally:
        kernel.root.fonts = registry

    assert "Aanwezig" in namen
    assert "MeerK40t Simple" in namen
    assert "Weggegooid" not in namen


# --------------------------------------------------------- tijdschatting

def test_estimate_before_starting(kernel, drawing, client):
    kernel.console("rect 20mm 15mm 60mm 40mm\n")
    kernel.console("element* cut -s 12 -p 650\n")

    response = client.get("/api/job/estimate")

    assert response.status_code == 200
    body = response.json()
    assert body["seconds"] > 0
    assert body["parts"] >= 1


def test_estimating_does_not_dirty_the_document(kernel, client):
    kernel.console("rect 20mm 15mm 60mm 40mm\n")
    kernel.console("element* cut -s 12 -p 650\n")
    client.get("/api/design/export.svg")
    assert client.get("/api/design").json()["dirty"] is False

    client.get("/api/job/estimate")

    assert client.get("/api/design").json()["dirty"] is False


def test_estimating_leaves_no_plan_behind(kernel, drawing, client):
    """Otherwise the next start would spool a stale plan."""
    kernel.console("rect 20mm 15mm 60mm 40mm\n")
    kernel.console("element* cut -s 12 -p 650\n")

    client.get("/api/job/estimate")

    assert len(kernel.planner.default_plan.plan) == 0


def test_estimating_never_builds_the_plan(kernel, drawing, client, monkeypatch):
    """
    The reason this route cost minutes on a heavy design (gap J1).

    `plan copy` kopieert de cutcode één keer per pass en de optimalisatie erna
    scales quadratically; measured: 960 shapes × 60 passes took 169 s. The estimate now
    computes on the geometry, so the plan pipeline must no longer be called — hence we make it
    explode here.
    """
    kernel.console("rect 20mm 15mm 60mm 40mm\n")
    kernel.console("element* cut -s 12 -p 650\n")
    origineel = drawing.runner.run

    def run(command, *args, **kwargs):
        if command.startswith("plan"):
            raise AssertionError(f"the estimate built a plan after all: {command}")
        return origineel(command, *args, **kwargs)

    monkeypatch.setattr(drawing.runner, "run", run)

    body = client.get("/api/job/estimate").json()

    assert body["method"] == "geometry"
    assert body["seconds"] > 0


def test_the_fast_estimate_matches_the_plan(kernel, drawing, client):
    """
    Fast must not come at the cost of right.

    The same sum as `duration_cut` + `duration_travel`, only without building the plan first:
    burn length divided by the layer's speed, plus the jumps in between. The travel order the
    optimisation chooses is not in it, so a few per cent of difference belongs with it.
    """
    for index in range(8):
        kernel.console(f"circle {10 + index * 20}mm 30mm 8mm\n")
    kernel.console("element* cut -s 12 -p 650\n")

    snel = client.get("/api/job/estimate").json()
    plan = client.get("/api/job/estimate?exact=1").json()

    assert plan["method"] == "plan"
    assert abs(snel["seconds"] - plan["seconds"]) / plan["seconds"] < 0.1


def test_passes_multiply_the_estimate(client):
    """Een laag die zes keer over hetzelfde gaat, duurt zes keer zo lang."""
    client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 20, "y_mm": 20, "width_mm": 50, "height_mm": 40},
    )
    een = client.get("/api/job/estimate").json()["seconds"]

    for laag in client.get("/api/design").json()["operations"]:
        assert client.patch(
            f"/api/design/operations/{laag['id']}", json={"passes": 6}
        ).status_code == 200

    assert client.get("/api/job/estimate").json()["seconds"] == pytest.approx(
        een * 6, rel=0.02
    )


def test_an_outline_in_a_raster_layer_costs_nothing(kernel, drawing, client):
    """
    A raster layer burns the area, and an outlined shape does not have one.

    Working on the bounding box would report eight minutes here for work that does
    not happen: the real plan gives zero cutcode for such a layer (measured).
    """
    kernel.console("rect 20mm 20mm 60mm 40mm\n")
    kernel.console("element* cut -s 12 -p 650\n")
    zonder = client.get("/api/job/estimate").json()["seconds"]

    kernel.console("element* raster -s 100 -p 300\n")

    assert client.get("/api/job/estimate").json()["seconds"] == zonder


# ------------------------------------------------------ tekst bijwerken

def test_text_reports_its_source(kernel, drawing):
    """A path has no words in it; the engine keeps the source on the node."""
    created = drawing.create("text", x_mm=20, y_mm=40, text="Hallo", font_size_mm=8)

    element = next(
        e for e in DesignReader(kernel).snapshot()["elements"] if e["id"] == created["ids"][0]
    )

    assert element["text"]["text"] == "Hallo"
    assert element["text"]["font_size_mm"] == pytest.approx(8, abs=0.1)
    assert element["text"]["align"] == "start"


def test_changing_the_words_rerenders(kernel, drawing):
    created = drawing.create("text", x_mm=20, y_mm=40, text="Ab", font_size_mm=8)
    before = bounds_mm(kernel, created["ids"][0])

    drawing.update_text(created["ids"][0], text="Abcdefgh")

    after = bounds_mm(kernel, created["ids"][0])
    assert after[2] - after[0] > before[2] - before[0]


def test_changing_the_size_rerenders(kernel, drawing):
    created = drawing.create("text", x_mm=20, y_mm=40, text="Ab", font_size_mm=6)
    before = bounds_mm(kernel, created["ids"][0])

    drawing.update_text(created["ids"][0], font_size_mm=18)

    after = bounds_mm(kernel, created["ids"][0])
    assert (after[3] - after[1]) > (before[3] - before[1]) * 2


def test_changing_the_font_rerenders(kernel, drawing):
    created = drawing.create("text", x_mm=20, y_mm=40, text="Hallo wereld", font_size_mm=8)
    other = [f for f in drawing.fonts()][3]

    drawing.update_text(created["ids"][0], font=other["file"])

    element = next(
        e for e in DesignReader(kernel).snapshot()["elements"] if e["id"] == created["ids"][0]
    )
    # The engine stores only the file name, not the full path.
    assert element["text"]["font"] == other["basename"]


def test_alignment_is_validated(kernel, drawing):
    created = drawing.create("text", x_mm=20, y_mm=40, text="Ab")

    drawing.update_text(created["ids"][0], align="middle")
    with pytest.raises(DesignError):
        drawing.update_text(created["ids"][0], align="schuin")


def test_only_text_elements_can_be_retyped(kernel, drawing):
    rect = drawing.create("rect", x_mm=10, y_mm=10, width_mm=10, height_mm=10)
    with pytest.raises(DesignError):
        drawing.update_text(rect["ids"][0], text="Hallo")


def test_text_update_over_http(kernel, client):
    created = client.post(
        "/api/design/elements",
        json={"type": "text", "x_mm": 20, "y_mm": 40, "text": "Ab", "font_size_mm": 8},
    ).json()

    response = client.patch(
        f"/api/design/elements/{created['ids'][0]}/text", json={"text": "Nieuw"}
    )

    assert response.status_code == 200
    assert response.json()["text"] == "Nieuw"


# ------------------------------------------------------------ lijnen

def test_a_line_reports_both_endpoints(kernel, drawing):
    """Bounds alone cannot say which way a line runs."""
    created = drawing.create("line", x1_mm=10, y1_mm=10, x2_mm=40, y2_mm=30)

    element = next(
        e for e in DesignReader(kernel).snapshot()["elements"] if e["id"] == created["ids"][0]
    )

    assert element["line"] == pytest.approx(
        {"x1_mm": 10, "y1_mm": 10, "x2_mm": 40, "y2_mm": 30}, abs=0.01
    )


def test_moving_one_endpoint(kernel, drawing):
    created = drawing.create("line", x1_mm=10, y1_mm=10, x2_mm=40, y2_mm=30)

    drawing.update_line(created["ids"][0], x2_mm=80, y2_mm=60)

    element = next(
        e for e in DesignReader(kernel).snapshot()["elements"] if e["id"] == created["ids"][0]
    )
    assert element["line"]["x2_mm"] == pytest.approx(80, abs=0.01)
    assert element["line"]["x1_mm"] == pytest.approx(10, abs=0.01)
    assert bounds_mm(kernel, created["ids"][0]) == [10.0, 10.0, 80.0, 60.0]


def test_only_lines_have_endpoints(kernel, drawing):
    rect = drawing.create("rect", x_mm=10, y_mm=10, width_mm=10, height_mm=10)
    with pytest.raises(DesignError):
        drawing.update_line(rect["ids"][0], x1_mm=0)


# --------------------------------------------------- uitlijnen/groeperen

def three_rects(drawing):
    return [
        drawing.create("rect", x_mm=10 + i * 30, y_mm=50 + i * 10, width_mm=20, height_mm=10)[
            "ids"
        ][0]
        for i in range(3)
    ]


def test_align_top(kernel, drawing):
    ids = three_rects(drawing)

    drawing.align(ids, "top")

    tops = {bounds_mm(kernel, i)[1] for i in ids}
    assert len(tops) == 1


def test_align_needs_two_elements(drawing):
    one = drawing.create("rect", x_mm=10, y_mm=10, width_mm=10, height_mm=10)
    with pytest.raises(DesignError):
        drawing.align(one["ids"], "top")


def test_unknown_alignment_is_refused(drawing):
    ids = three_rects(drawing)
    with pytest.raises(DesignError):
        drawing.align(ids, "diagonaal")


def test_group_and_ungroup(kernel, drawing):
    ids = three_rects(drawing)

    drawing.group(ids)
    grouped = {
        e["group_id"] for e in DesignReader(kernel).snapshot()["elements"] if e["id"] in ids
    }
    assert len(grouped) == 1 and grouped.pop() is not None

    drawing.ungroup(ids)
    loose = {
        e["group_id"] for e in DesignReader(kernel).snapshot()["elements"] if e["id"] in ids
    }
    assert loose == {None}


def test_ungrouping_something_loose_is_refused(drawing):
    ids = three_rects(drawing)
    with pytest.raises(DesignError):
        drawing.ungroup(ids)


def test_endpoints_follow_a_rotation(kernel, drawing):
    """
    Rotating sets a matrix on the node and leaves x1..y2 alone, so reporting
    the raw points would put the handles where the line used to be.
    """
    created = drawing.create("line", x1_mm=10, y1_mm=10, x2_mm=50, y2_mm=10)
    DesignEditor(kernel).rotate(created["ids"], 90)

    element = next(
        e for e in DesignReader(kernel).snapshot()["elements"] if e["id"] == created["ids"][0]
    )
    line = element["line"]
    bounds = bounds_mm(kernel, created["ids"][0])

    # Both endpoints must sit on the rotated shape, not the original one.
    for x, y in ((line["x1_mm"], line["y1_mm"]), (line["x2_mm"], line["y2_mm"])):
        assert bounds[0] - 0.1 <= x <= bounds[2] + 0.1
        assert bounds[1] - 0.1 <= y <= bounds[3] + 0.1


def test_moving_an_endpoint_of_a_rotated_line(kernel, drawing):
    """The client speaks in bed coordinates; the node stores pre-matrix ones."""
    created = drawing.create("line", x1_mm=10, y1_mm=10, x2_mm=50, y2_mm=10)
    DesignEditor(kernel).rotate(created["ids"], 90)

    drawing.update_line(created["ids"][0], x2_mm=70, y2_mm=70)

    element = next(
        e for e in DesignReader(kernel).snapshot()["elements"] if e["id"] == created["ids"][0]
    )
    assert element["line"]["x2_mm"] == pytest.approx(70, abs=0.1)
    assert element["line"]["y2_mm"] == pytest.approx(70, abs=0.1)


# --------------------------------------------------- spiegelen en boolean

def test_mirroring_flips_the_shape_not_its_bounds(kernel, drawing):
    """
    A mirror about the centre leaves the bounding box alone, so bounds prove
    nothing — the path has to be checked.
    """
    created = drawing.create("line", x1_mm=10, y1_mm=10, x2_mm=50, y2_mm=30)
    before = DesignReader(kernel).snapshot()["elements"][0]["path"]

    drawing.mirror(created["ids"], "horizontal")

    after = DesignReader(kernel).snapshot()["elements"][0]["path"]
    assert after != before
    assert bounds_mm(kernel, created["ids"][0]) == [10.0, 10.0, 50.0, 30.0]


def test_mirror_axis_is_validated(drawing):
    created = drawing.create("rect", x_mm=10, y_mm=10, width_mm=10, height_mm=10)
    with pytest.raises(DesignError):
        drawing.mirror(created["ids"], "diagonaal")


def two_overlapping(drawing):
    a = drawing.create("rect", x_mm=10, y_mm=10, width_mm=40, height_mm=40)
    b = drawing.create("rect", x_mm=30, y_mm=30, width_mm=40, height_mm=40)
    return a["ids"] + b["ids"]


@pytest.mark.parametrize("operation", ["union", "difference", "intersection", "xor"])
def test_boolean_operations_produce_one_path(kernel, drawing, operation):
    ids = two_overlapping(drawing)

    result = drawing.boolean(ids, operation)

    assert len(result["ids"]) == 1
    remaining = list(kernel.elements.elems())
    assert len(remaining) == 1
    assert remaining[0].type == "elem path"


def test_union_covers_both_shapes(kernel, drawing):
    ids = two_overlapping(drawing)

    result = drawing.boolean(ids, "union")

    assert bounds_mm(kernel, result["ids"][0]) == [10.0, 10.0, 70.0, 70.0]


def test_intersection_is_only_the_overlap(kernel, drawing):
    ids = two_overlapping(drawing)

    result = drawing.boolean(ids, "intersection")

    assert bounds_mm(kernel, result["ids"][0]) == [30.0, 30.0, 50.0, 50.0]


def test_boolean_needs_two_shapes(drawing):
    one = drawing.create("rect", x_mm=10, y_mm=10, width_mm=10, height_mm=10)
    with pytest.raises(DesignError):
        drawing.boolean(one["ids"], "union")


def test_unknown_boolean_is_refused(drawing):
    ids = two_overlapping(drawing)
    with pytest.raises(DesignError):
        drawing.boolean(ids, "samenvoegen")


def test_boolean_over_http(kernel, client):
    a = client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 10, "y_mm": 10, "width_mm": 40, "height_mm": 40},
    ).json()["ids"]
    b = client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 30, "y_mm": 30, "width_mm": 40, "height_mm": 40},
    ).json()["ids"]

    response = client.post(
        "/api/design/boolean", json={"ids": a + b, "operation": "union"}
    )

    assert response.status_code == 200
    assert len(list(kernel.elements.elems())) == 1


# ------------------------------------------------- padbewerkingen/effects

def test_offset_makes_a_second_contour(kernel, drawing):
    created = drawing.create("rect", x_mm=20, y_mm=20, width_mm=40, height_mm=30)

    result = drawing.offset(created["ids"], 3)

    assert result["ids"] and result["ids"][0] != created["ids"][0]
    assert len(list(kernel.elements.elems())) == 2
    outer = bounds_mm(kernel, result["ids"][0])
    inner = bounds_mm(kernel, created["ids"][0])
    assert outer[0] < inner[0] and outer[2] > inner[2]


def test_offset_of_nothing_is_refused(drawing):
    created = drawing.create("rect", x_mm=10, y_mm=10, width_mm=10, height_mm=10)
    with pytest.raises(DesignError):
        drawing.offset(created["ids"], 0)


def test_simplify_leaves_the_element_in_place(kernel, drawing):
    created = drawing.create("rect", x_mm=10, y_mm=10, width_mm=40, height_mm=30)
    before = bounds_mm(kernel, created["ids"][0])

    drawing.simplify(created["ids"])

    assert bounds_mm(kernel, created["ids"][0]) == before


@pytest.mark.parametrize("effect", ["hatch", "wobble"])
def test_an_effect_wraps_the_element(kernel, drawing, effect):
    """
    Effects are containers in the *element* tree, not operations: the command
    hangs the node on first_node.parent and takes the shapes as children.
    Looking for them among the operations finds nothing.
    """
    created = drawing.create("rect", x_mm=10, y_mm=10, width_mm=40, height_mm=30)

    drawing.add_effect(created["ids"], effect)

    element = next(
        e for e in DesignReader(kernel).snapshot()["elements"] if e["id"] == created["ids"][0]
    )
    assert element["effect"] is not None
    assert element["effect"]["type"] == effect


def test_an_element_without_an_effect_says_so(kernel, drawing):
    created = drawing.create("rect", x_mm=10, y_mm=10, width_mm=10, height_mm=10)
    element = next(
        e for e in DesignReader(kernel).snapshot()["elements"] if e["id"] == created["ids"][0]
    )
    assert element["effect"] is None


def test_unknown_effect_is_refused(drawing):
    created = drawing.create("rect", x_mm=10, y_mm=10, width_mm=10, height_mm=10)
    with pytest.raises(DesignError):
        drawing.add_effect(created["ids"], "glitter")


def test_raster_settings_can_be_changed(client):
    """
    DPI and overscan decide what an engraving looks like and how long it takes;
    without these fields you had to go back to MeerK40t.
    """
    created = client.post("/api/design/operations", json={"type": "raster"}).json()

    response = client.patch(
        f"/api/design/operations/{created['id']}",
        json={"dpi": 333, "overscan_mm": 2.5, "bidirectional": False},
    )

    assert response.status_code == 200
    operation = next(
        o
        for o in client.get("/api/design").json()["operations"]
        if o["id"] == created["id"]
    )
    assert operation["dpi"] == 333
    assert operation["overscan"] == "2.5mm"
    assert operation["bidirectional"] is False


def test_absurd_raster_settings_are_refused(client):
    created = client.post("/api/design/operations", json={"type": "raster"}).json()

    for body in ({"dpi": 5}, {"dpi": 9000}, {"overscan_mm": -1}, {"overscan_mm": 500}):
        response = client.patch(f"/api/design/operations/{created['id']}", json=body)
        assert response.status_code == 409, body


def test_a_new_layer_has_a_name_you_recognise(client):
    """
    The engine called a fresh layer "Cut defaultmm/s @default #ff0000": machine
    language in the place where you have to recognise your own work.
    """
    made = client.post("/api/design/operations", json={"type": "cut"}).json()

    layer = next(
        o for o in client.get("/api/design").json()["operations"] if o["id"] == made["id"]
    )
    assert layer["label"] == "Cut"


def test_a_new_layer_does_not_claim_zero_passes(client):
    """Zero passes reads as "cut zero times" — exactly the number somebody at a
    laser looks at before pressing start."""
    made = client.post("/api/design/operations", json={"type": "engrave"}).json()

    layer = next(
        o for o in client.get("/api/design").json()["operations"] if o["id"] == made["id"]
    )
    assert layer["passes"] >= 1


def test_a_new_shape_lands_in_exactly_one_layer(client):
    """
    Classification looks at the stroke colour, and several operations can claim
    the same colour. Then the same shape burns twice — the second time often at
    full power. You only notice that on material.
    """
    made = client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 10, "y_mm": 10, "width_mm": 30, "height_mm": 20},
    ).json()

    element = next(
        e for e in client.get("/api/design").json()["elements"] if e["id"] == made["ids"][0]
    )
    assert len(element["operation_ids"]) == 1


def test_the_preflight_lists_one_layer_for_one_shape(client):
    """What the pre-flight shows is what happens. Two layers for one shape is a double burn."""
    client.post("/api/design/clear")
    client.post(
        "/api/design/elements",
        json={"type": "circle", "cx_mm": 50, "cy_mm": 50, "r_mm": 20},
    )

    layers = client.get("/api/job/estimate").json()["layers"]
    assert len(layers) == 1, [l["label"] for l in layers]


# --------------------------------------------------------------- corners


def a_rectangle(client, w=40, h=30):
    answer = client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 10, "y_mm": 10, "width_mm": w, "height_mm": h},
    )
    assert answer.status_code == 201, answer.json()
    return answer.json()["ids"][0]


def test_a_rect_can_be_drawn_with_rounded_corners(client, kernel):
    """
    The engine already knows rounded rectangles: `rx`/`ry` on the node, and the
    console command has options for them. We simply did not pass them on.
    """
    created = client.post(
        "/api/design/elements",
        json={
            "type": "rect",
            "x_mm": 10,
            "y_mm": 10,
            "width_mm": 40,
            "height_mm": 30,
            "corner_radius_mm": 5,
        },
    )

    assert created.status_code == 201, created.json()
    element = client.get("/api/design").json()["elements"][0]
    assert element["type"] == "elem rect"
    # And the radius really arrived. Testing on the type alone would stay green
    # if the options had quietly fallen away.
    node = next(n for n in kernel.elements.elems() if n.type == "elem rect")
    units = 65535 / 25.4
    assert node.rx / units == pytest.approx(5.0, rel=1e-3)
    assert node.ry / units == pytest.approx(5.0, rel=1e-3)


def test_a_radius_that_does_not_fit_is_refused_with_the_maximum(client):
    """Refusing is fine; refusing without saying what *does* fit is not."""
    answer = client.post(
        "/api/design/elements",
        json={
            "type": "rect",
            "x_mm": 0,
            "y_mm": 0,
            "width_mm": 20,
            "height_mm": 10,
            "corner_radius_mm": 8,
        },
    )

    assert answer.status_code == 409
    assert "5" in answer.json()["detail"]


def test_rounding_a_rect_keeps_it_a_rect(client, kernel):
    """
    This is the whole reason rounding is a property and not a new shape: the width
    and height stay, and the radius can be changed later.
    """
    element_id = a_rectangle(client, w=40, h=30)

    answer = client.post(
        "/api/design/corners",
        json={"ids": [element_id], "style": "round", "size_mm": 5},
    )

    assert answer.status_code == 200, answer.json()
    assert answer.json()["rounded"] == [element_id]
    assert client.get("/api/design").json()["elements"][0]["type"] == "elem rect"
    node = next(n for n in kernel.elements.elems() if n.type == "elem rect")
    assert node.rx / (65535 / 25.4) == pytest.approx(5.0, rel=1e-3)


def test_chamfering_a_rect_turns_it_into_a_path(client):
    """
    And this is why bevelling *cannot* be a property: the engine always draws an
    `elem rect` rounded, so a bevelled rectangle has to become geometry of our own.
    That is one-way, and the test pins it down instead of leaving it to the UI.
    """
    element_id = a_rectangle(client, w=40, h=30)

    answer = client.post(
        "/api/design/corners",
        json={"ids": [element_id], "style": "chamfer", "size_mm": 5},
    )

    assert answer.status_code == 200, answer.json()
    assert answer.json()["paths"]
    assert client.get("/api/design").json()["elements"][0]["type"] == "elem path"


def test_a_corner_size_too_large_is_refused(client):
    element_id = a_rectangle(client, w=10, h=10)

    answer = client.post(
        "/api/design/corners",
        json={"ids": [element_id], "style": "chamfer", "size_mm": 8},
    )

    assert answer.status_code == 409
    assert "smaller size" in answer.json()["detail"]


# ------------------------------------------------- a point, and the layer that burns it


def test_a_dots_layer_says_what_it_takes_instead_of_dropping_it(client):
    """
    Reported by the user: set a layer to Dots and the shape in it falls out, the preview
    says there is nothing left to burn, and adding a shape is impossible — with no reason
    anywhere on screen.

    The engine is right about all of it: `OpDotsNode._allowed_elements` is `("elem point",)`
    (`core/node/op_dots.py:24`), and `add_reference` drops silently what is not in that
    list. Our layer told two untruths on top of it, and this pins both.

    Measured before: assigning a rectangle to a Dots layer answered `200 {"added": 1}`
    while the layer held 0, and changing a cut layer with one rectangle into Dots answered
    `200 {"elements": 1}` — claiming it had carried the shape over — with the new layer
    holding nothing.
    """
    ids = client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 10, "y_mm": 10, "width_mm": 40, "height_mm": 20},
    ).json()["ids"]
    made = client.post("/api/design/operations", json={"type": "dots"}).json()
    dots = made.get("id") or made["operations"][-1]["id"]

    refused = client.post(
        "/api/design/assign", json={"operation_id": dots, "ids": ids}
    )
    assert refused.status_code == 409, refused.text
    assert refused.headers["X-OpenKerf-Error"] == "layer.takesOnly"
    said = refused.json()["detail"]
    assert "point" in said and "Dots" in said, said

    layer = next(
        o for o in client.get("/api/design").json()["operations"] if o["id"] == dots
    )
    assert layer["element_ids"] == []


def test_a_layer_holding_shapes_refuses_to_become_a_dots_layer(client):
    """The other half: the shapes stay where they are, and the reason is said."""
    ids = client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 10, "y_mm": 10, "width_mm": 40, "height_mm": 20},
    ).json()["ids"]
    cut = client.post("/api/design/operations", json={"type": "cut"}).json()
    cut_id = cut.get("id") or cut["operations"][-1]["id"]
    client.post("/api/design/assign", json={"operation_id": cut_id, "ids": ids})

    answer = client.post(f"/api/design/operations/{cut_id}/type", json={"type": "dots"})
    assert answer.status_code == 409, answer.text
    assert answer.headers["X-OpenKerf-Error"] == "layer.typeWontHold"
    assert "1 shape" in answer.json()["detail"]

    # Nothing moved and nothing was emptied.
    layer = next(
        o for o in client.get("/api/design").json()["operations"] if o["id"] == cut_id
    )
    assert layer["type"] == "op cut"
    assert layer["element_ids"] == ids

    # And an empty layer may still change, because there is nothing to lose.
    empty = client.post("/api/design/operations", json={"type": "cut"}).json()
    empty_id = empty.get("id") or empty["operations"][-1]["id"]
    ok = client.post(f"/api/design/operations/{empty_id}/type", json={"type": "dots"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["type"] == "op dots"


def test_a_point_can_be_drawn_and_lands_where_it_can_burn(client):
    """
    Until this existed the app offered a layer kind that nothing in the app could fill.

    Measured: `type: "point"` answered `409 Unknown shape: point. Choose from circle,
    ellipse, line, rect, text.` — while Dots sat in the layer-kind list beside the other
    four. And a point may not be classified by its stroke colour like every other shape:
    `op cut._allowed_elements` (`core/node/op_cut.py:46`) has no `elem point` in it, so
    the colour route can only hand it to a layer that drops it. Measured before the
    exception: a fresh point ended with `operation_ids []` beside a new cut layer holding
    nothing.
    """
    answer = client.post(
        "/api/design/elements", json={"type": "point", "x_mm": 25, "y_mm": 40}
    )
    assert answer.status_code == 201, answer.text
    assert answer.json()["type"] == "elem point"

    design = client.get("/api/design").json()
    point = next(e for e in design["elements"] if e["type"] == "elem point")
    # It has to be drawable and clickable: finite bounds, and not flagged broken.
    assert point["broken"] is False
    assert point["bounds"] is not None
    assert len(point["operation_ids"]) == 1

    layer = next(
        o for o in design["operations"] if o["id"] == point["operation_ids"][0]
    )
    assert layer["type"] == "op dots"
    assert layer["element_ids"] == [point["id"]]

    # A second point joins the layer that is there rather than making another.
    client.post("/api/design/elements", json={"type": "point", "x_mm": 30, "y_mm": 40})
    again = client.get("/api/design").json()
    assert len([o for o in again["operations"] if o["type"] == "op dots"]) == 1
