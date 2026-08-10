"""Images: visible on the canvas, and adjustable."""

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from openkerf_api.design import DesignReader
from openkerf_api.edits import DesignError
from openkerf_api.images import Images
from openkerf_api.server import ApiServer


@pytest.fixture
def client(kernel, tmp_path):
    with TestClient(ApiServer(kernel, library_path=tmp_path / "i.db").build_app()) as c:
        yield c


@pytest.fixture
def images(kernel):
    return Images(kernel)


def a_png(size=(120, 80)):
    buffer = io.BytesIO()
    Image.new("RGB", size, (200, 120, 40)).save(buffer, "PNG")
    return buffer.getvalue()


@pytest.fixture
def loaded(client):
    client.post("/api/job/load", files={"file": ("foto.png", a_png(), "image/png")})
    elements = client.get("/api/design").json()["elements"]
    return next(e for e in elements if e["type"] == "elem image")


def test_an_image_appears_in_the_snapshot(loaded):
    """
    An image node has no as_geometry, so a path-only snapshot dropped it and it
    was invisible on the canvas.
    """
    assert loaded["image"] is not None
    assert loaded["image"]["width_mm"] > 0
    assert loaded["image"]["pixels"] == [120, 80]


def test_the_pixels_can_be_fetched(client, loaded):
    response = client.get(f"/api/design/elements/{loaded['id']}/image.png")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert Image.open(io.BytesIO(response.content)).size == (120, 80)


def test_asking_a_rectangle_for_pixels_is_refused(client):
    created = client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 10, "y_mm": 10, "width_mm": 10, "height_mm": 10},
    ).json()

    response = client.get(f"/api/design/elements/{created['ids'][0]}/image.png")

    assert response.status_code == 409


@pytest.mark.parametrize("adjustment", ["grayscale", "invert", "contrast", "dither"])
def test_adjustments_change_the_pixels(client, loaded, adjustment):
    """Without dithering a photo engraves as a grey smear, so this matters."""
    before = client.get(f"/api/design/elements/{loaded['id']}/image.png").content

    response = client.post(
        f"/api/design/elements/{loaded['id']}/image", json={"adjustment": adjustment}
    )

    assert response.status_code == 200
    after = client.get(f"/api/design/elements/{loaded['id']}/image.png").content
    assert after != before


def test_unknown_adjustment_is_refused(kernel, images, loaded):
    with pytest.raises(DesignError):
        images.adjust(loaded["id"], "sepia")


def test_dpi_can_be_set(client, loaded):
    response = client.post(
        f"/api/design/elements/{loaded['id']}/image", json={"dpi": 300}
    )

    assert response.status_code == 200
    element = next(
        e
        for e in client.get("/api/design").json()["elements"]
        if e["id"] == loaded["id"]
    )
    assert element["image"]["dpi"] == 300


def test_absurd_dpi_is_refused(client, loaded):
    for bad in (0, 5, 9999, "veel"):
        response = client.post(
            f"/api/design/elements/{loaded['id']}/image", json={"dpi": bad}
        )
        assert response.status_code == 409, bad


def test_an_image_can_be_moved_like_anything_else(kernel, client, loaded):
    before = loaded["image"]["x_mm"]

    client.post("/api/design/move", json={"ids": [loaded["id"]], "dx_mm": 10, "dy_mm": 0})

    element = next(
        e
        for e in client.get("/api/design").json()["elements"]
        if e["id"] == loaded["id"]
    )
    assert element["image"]["x_mm"] == pytest.approx(before + 10, abs=0.1)


def a_shape_png():
    from PIL import ImageDraw

    image = Image.new("L", (120, 90), 255)
    ImageDraw.Draw(image).ellipse((20, 15, 100, 75), fill=0)
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, "PNG")
    return buffer.getvalue()


def test_vectorisers_are_reported(client):
    """potrace needs an external library, so what is available is a question."""
    methods = client.get("/api/design/vectorisers").json()["methods"]
    assert "vectrace" in methods


def test_vectorising_turns_pixels_into_paths(client):
    client.post("/api/job/load", files={"file": ("tekening.png", a_shape_png(), "image/png")})
    image = next(
        e for e in client.get("/api/design").json()["elements"] if e["type"] == "elem image"
    )

    response = client.post(f"/api/design/elements/{image['id']}/vectorise", json={})

    assert response.status_code == 200
    assert response.json()["ids"], "vectoriseren leverde geen pad op"
    paths = [
        e for e in client.get("/api/design").json()["elements"] if e["type"] == "elem path"
    ]
    assert len(paths) == 1
    assert paths[0]["path"]


def test_unknown_vectoriser_is_refused(client, loaded):
    response = client.post(
        f"/api/design/elements/{loaded['id']}/vectorise", json={"method": "magie"}
    )
    assert response.status_code == 409


def test_cropping_shrinks_the_pixels(client, loaded):
    """De helft wegsnijden moet ook echt de helft van de pixels schelen."""
    box = loaded["image"]

    response = client.post(
        f"/api/design/elements/{loaded['id']}/crop",
        json={
            "x_mm": box["x_mm"],
            "y_mm": box["y_mm"],
            "width_mm": box["width_mm"] / 2,
            "height_mm": box["height_mm"],
        },
    )

    assert response.status_code == 200
    png = client.get(f"/api/design/elements/{loaded['id']}/image.png").content
    assert Image.open(io.BytesIO(png)).size == (60, 80)


def test_a_crop_outside_the_image_is_refused(client, loaded):
    response = client.post(
        f"/api/design/elements/{loaded['id']}/crop",
        json={"x_mm": 5000, "y_mm": 5000, "width_mm": 10, "height_mm": 10},
    )
    assert response.status_code == 409


def test_a_crop_without_size_is_refused(client, loaded):
    response = client.post(
        f"/api/design/elements/{loaded['id']}/crop",
        json={"x_mm": 0, "y_mm": 0, "width_mm": 0, "height_mm": 10},
    )
    assert response.status_code == 409
