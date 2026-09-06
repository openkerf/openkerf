"""
A layer is called what it is, and a layer without a name is refused.

Pattern P12. Two things the engine side used to let through onto three screens
at once:

- **The engine's own formatter reached the panel.** `operation_label` only fell
  back to the kind when the rendered name held a colour code, and an image layer's
  does not. Measured on the running server, importing a 120 x 80 PNG:
  ``Image=B2T 250mm/s @1000`` stood in the chip of the selection card, in the layer
  list and in the pre-flight table — three truncations of engine syntax.
- **An empty name was accepted.** ``PATCH /api/design/operations/{id}`` with
  ``{"label": "   "}`` answered **200** and left the layer with no name at all,
  while the library refuses exactly that for a material with "A material needs a
  name."
"""

import pytest
from fastapi.testclient import TestClient

from openkerf_api.design import operation_label
from openkerf_api.drawing import Drawing
from openkerf_api.edits import DesignError
from openkerf_api.server import ApiServer


@pytest.fixture
def drawing(kernel):
    return Drawing(kernel)


@pytest.fixture
def client(kernel, tmp_path):
    with TestClient(ApiServer(kernel, library_path=tmp_path / "d.db").build_app()) as c:
        yield c


def test_a_layer_nobody_named_is_called_after_its_kind(kernel):
    """A layer straight out of the engine carries no label; it gets the kind."""
    for kind, expected in (
        ("op image", "Image"),
        ("op raster", "Raster"),
        ("op engrave", "Engrave"),
        ("op cut", "Cut"),
    ):
        operation = kernel.elements.op_branch.add(type=kind, speed=250, power=1000)
        name = operation_label(operation)
        assert name == expected, f"an unnamed {kind} is called {name!r}"
        # And none of the engine's own syntax survives into it.
        assert "mm/s" not in name and "@" not in name and "=" not in name


def test_the_layer_a_png_import_makes_is_called_Image(kernel, client, tmp_path):
    """
    The measured case. MeerK40t labels every operation in its default list with a
    template — `opnode_label` writes "Image ({percent}, {speed}mm/s)" — so the layer a
    PNG lands in does carry a label, and rendering it gave the node's own formatter:
    "Image=B2T 250mm/s @1000", which then stood in three places on the screen.
    """
    from PIL import Image

    png = tmp_path / "plate.png"
    picture = Image.new("L", (120, 80), 255)
    for y in range(80):
        for x in range(120):
            picture.putpixel((x, y), 0 if (x // 10 + y // 10) % 2 == 0 else 255)
    picture.save(png)

    with png.open("rb") as handle:
        loaded = client.post(
            "/api/job/load", files={"file": ("plate.png", handle, "image/png")}
        )
    assert loaded.status_code == 200

    images = [op for op in kernel.elements.ops() if str(op.type) == "op image"]
    assert images, "the import made no image layer"
    for op in images:
        assert operation_label(op) == "Image", (
            f"the layer a PNG lands in is called {operation_label(op)!r}"
        )
    for layer in client.get("/api/design").json()["operations"]:
        assert "mm/s" not in layer["label"] or layer.get("grid"), (
            f"a layer reaches the screen as {layer['label']!r}"
        )


def test_a_layer_somebody_named_keeps_that_name(kernel, drawing):
    """The user's own name wins, and a grid cell's own name is one of those."""
    made = drawing.create_operation("cut", label="Outline", speed=12, power_percent=65)
    cut = kernel.elements.find_node(made["id"])
    assert operation_label(cut) == "Outline"

    cell = kernel.elements.op_branch.add(type="op cut", speed=5, power=300)
    cell.label = "5 mm/s · 30%"
    assert operation_label(cell) == "5 mm/s · 30%"


def test_a_layer_needs_a_name(drawing):
    made = drawing.create_operation("engrave", label="Caption", speed=250, power_percent=22)
    with pytest.raises(DesignError) as refused:
        drawing.update_operation(made["id"], label="   ")
    assert refused.value.code == "layer.needsName"
    assert str(refused.value) == "A layer needs a name."
    # And the name it had is still the name it has.
    assert operation_label(drawing._operation(made["id"])) == "Caption"


def test_the_route_refuses_it_with_the_code_in_the_header(client):
    made = client.post(
        "/api/design/operations",
        json={"type": "engrave", "label": "Caption", "speed": 250, "power_percent": 22},
    )
    assert made.status_code == 201
    refused = client.patch(
        f"/api/design/operations/{made.json()['id']}", json={"label": "  "}
    )
    assert refused.status_code == 409
    assert refused.headers["X-OpenKerf-Error"] == "layer.needsName"
    assert "name" in refused.json()["detail"].lower()
