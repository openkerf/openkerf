"""The design snapshot the canvas renders from."""

import json

import pytest
from fastapi.testclient import TestClient

from openkerf_api.design import DesignReader
from openkerf_api.drawing import Drawing
from openkerf_api.server import ApiServer


@pytest.fixture
def client(kernel):
    with TestClient(ApiServer(kernel).build_app()) as c:
        yield c


@pytest.fixture
def drawing(kernel):
    kernel.console("rect 1cm 1cm 4cm 2cm\n")
    kernel.console("circle 8cm 3cm 1cm\n")
    kernel.console("element* cut -s 12 -p 65\n")
    return kernel


def test_empty_document_yields_no_elements(kernel):
    snapshot = DesignReader(kernel).snapshot()

    assert snapshot["elements"] == []
    assert snapshot["units_per_mm"] > 0


def test_elements_carry_svg_path_data(drawing):
    snapshot = DesignReader(drawing).snapshot()

    assert len(snapshot["elements"]) == 2
    for element in snapshot["elements"]:
        assert element["path"].startswith("M ")
        assert element["id"]
        assert element["type"].startswith("elem ")
        assert len(element["bounds"]) == 4


def test_geometry_is_in_native_units_so_the_scale_matches(drawing):
    """A 1cm offset must land on 10mm once units_per_mm is applied."""
    snapshot = DesignReader(drawing).snapshot()
    units_per_mm = snapshot["units_per_mm"]
    rect = next(e for e in snapshot["elements"] if e["type"] == "elem rect")

    x0, y0, x1, y1 = rect["bounds"]

    assert x0 / units_per_mm == pytest.approx(10.0, abs=0.1)
    assert (x1 - x0) / units_per_mm == pytest.approx(40.0, abs=0.1)
    assert (y1 - y0) / units_per_mm == pytest.approx(20.0, abs=0.1)


def test_operations_reference_their_elements(drawing):
    snapshot = DesignReader(drawing).snapshot()

    assert snapshot["operations"], "the cut operation is a layer"
    element_ids = {e["id"] for e in snapshot["elements"]}
    for operation in snapshot["operations"]:
        assert operation["element_ids"]
        assert set(operation["element_ids"]) <= element_ids


def test_unused_operations_are_left_out(drawing):
    """
    A layer with nothing in it is not a layer the canvas has to draw.

    The empty one is made here, and until now it was not. The docstring said "the engine
    keeps a stack of default operations" and that was true only of a kernel that had
    inherited one: a clean kernel opens with no operations at all (measured: `ops()` is
    empty, and this fixture's two shapes bring exactly two layers, both filled). The stack
    came in through `operations.cfg` from whichever test ran before — so this assertion
    was measuring the leak that `_operations_of_its_own` has since closed, and it passed
    or failed by the order of the suite.
    """
    Drawing(drawing).create_operation("raster")
    total_ops = len(list(drawing.elements.ops()))
    reported = len(DesignReader(drawing).snapshot()["operations"])

    assert 0 < reported < total_ops


def test_ids_survive_a_change_to_the_tree(drawing):
    """
    Selection needs identity that outlives an edit. Index-based ids would
    shift as soon as an element is added, pointing the selection elsewhere.
    """
    reader = DesignReader(drawing)
    before = {e["id"]: e["type"] for e in reader.snapshot()["elements"]}

    drawing.console("rect 15cm 1cm 2cm 2cm\n")
    after = {e["id"]: e["type"] for e in reader.snapshot()["elements"]}

    assert len(after) == len(before) + 1
    for element_id, element_type in before.items():
        assert after.get(element_id) == element_type


def test_ids_resolve_back_to_a_node(drawing):
    snapshot = DesignReader(drawing).snapshot()
    element_id = snapshot["elements"][0]["id"]

    node = drawing.elements.find_node(element_id)

    assert node is not None
    assert node.type == snapshot["elements"][0]["type"]


def test_elements_can_belong_to_several_operations(drawing):
    """
    MeerK40t classifies an element into every operation whose colour matches,
    so membership is many-to-many. The canvas must not assume one owner.
    """
    snapshot = DesignReader(drawing).snapshot()

    for element in snapshot["elements"]:
        assert element["operation_ids"]
        assert element["operation_id"] == element["operation_ids"][0]

    claimed = max(len(e["operation_ids"]) for e in snapshot["elements"])
    assert claimed >= 1


def test_snapshot_is_json_serialisable(drawing):
    """Bounds come back as numpy floats and colours as Color objects."""
    payload = json.dumps(DesignReader(drawing).snapshot())

    assert "np.float64" not in payload
    assert "Color(" not in payload


def test_endpoint_returns_the_design(drawing, client):
    response = client.get("/api/design")

    assert response.status_code == 200
    body = response.json()
    assert len(body["elements"]) == 2
    assert body["operations"]


def test_reader_skips_nodes_without_geometry(kernel):
    """A node whose geometry raises must not take the whole snapshot down."""

    class Broken:
        type = "elem path"
        bounds = (0, 0, 1, 1)

        def as_geometry(self, **kws):
            raise RuntimeError("no geometry here")

    assert DesignReader(kernel)._element(Broken(), "e0") is None


def test_labels_have_their_placeholders_filled_in(drawing):
    """
    Operation labels are templates like "Engrave ({percent}, {speed}mm/s)".
    Showing them raw leaked "{percent}" into the layer list.
    """
    snapshot = DesignReader(drawing).snapshot()

    for entry in snapshot["operations"] + snapshot["elements"]:
        assert "{" not in entry["label"], entry["label"]
        assert entry["label"].strip()


def test_elements_report_the_group_they_belong_to(kernel):
    """
    Without this the canvas draws a grid as loose squares, and each one can be
    dragged out of the grid on its own.
    """
    kernel.console("rect 10mm 10mm 10mm 10mm\n")
    kernel.console("rect 30mm 10mm 10mm 10mm\n")
    kernel.elements.set_emphasis(list(kernel.elements.elems()))
    kernel.console("group\n")

    snapshot = DesignReader(kernel).snapshot()

    groups = {e["group_id"] for e in snapshot["elements"]}
    assert len(groups) == 1
    assert groups.pop() is not None


def test_a_loose_element_has_no_group(kernel):
    kernel.console("rect 10mm 10mm 10mm 10mm\n")

    snapshot = DesignReader(kernel).snapshot()

    assert snapshot["elements"][0]["group_id"] is None
