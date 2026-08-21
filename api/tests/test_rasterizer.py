"""
De rasteraar zonder GUI.

What is tested here really goes into the machine: a raster layer that comes out wrong burns
wrong. So not only "an image comes out", but also how big it is and which pixels are
black.
"""

import numpy as np
import pytest
from PIL import Image

from meerk40t.core.node.node import Node
from meerk40t.svgelements import Color

from openkerf_api import rasterizer


MM = 65535 / 25.4  # één millimeter in native eenheden (Tats)


@pytest.fixture
def make_raster(kernel):
    dienst = kernel.root.lookup("render-op/make_raster")
    assert dienst is not None, "the rasteriser should be registered by our plugin"
    return dienst


def _rect(kernel, x_mm, y_mm, w_mm, h_mm, fill=None):
    kernel.console(f"rect {x_mm}mm {y_mm}mm {w_mm}mm {h_mm}mm\n")
    node = list(kernel.elements.elems())[-1]
    if fill is not None:
        node.fill = Color(fill)
    node.set_dirty_bounds()
    return node


def _grijs(image):
    return np.asarray(image.convert("L"))


# -------------------------------------------------------- the service itself


def test_the_engine_has_a_rasteriser(kernel):
    """
    Without this service `OpRasterNode.preprocess` takes the `strip_rasters` branch: the
    layer throws its own children away and produces no cutcode. Our plugin fills that gap in
    the place MeerK40t offers for it.
    """
    assert callable(kernel.root.lookup("render-op/make_raster"))


def test_a_gui_rasteriser_wins_from_ours(kernel):
    """
    If somebody runs *with* wxPython, that version draws with the real fonts and the real pen
    strokes. We are the fallback, not the preference.
    """
    van_de_gui = object()
    kernel.root.register("render-op/make_raster", van_de_gui)

    assert rasterizer.register(kernel) is False
    assert kernel.root.lookup("render-op/make_raster") is van_de_gui


# ------------------------------------------------------- maat en contract


def test_without_bounds_there_is_nothing_to_render(make_raster):
    assert make_raster([], bounds=None) is None


def test_an_empty_node_list_does_not_fall_over(make_raster):
    """A layer without drawable children produces an empty sheet, not an error."""
    beeld = make_raster([], bounds=(0, 0, 10 * MM, 10 * MM), step_x=100, step_y=100)

    assert beeld.mode == "RGB"
    assert _grijs(beeld).min() == 255


def test_the_size_follows_the_step_rate(kernel, make_raster):
    """
    The step is the inverse dpi: the machine's `dpi_to_steps` goes with an image that covers
    the frame exactly. If that does not hold, the image is at the wrong scale in the bed.
    """
    step_x, step_y = kernel.device.view.dpi_to_steps(250)
    bounds = (0, 0, 30 * MM, 20 * MM)

    beeld = make_raster([], bounds=bounds, step_x=step_x, step_y=step_y)

    assert beeld.size == (
        int(np.ceil(30 * MM / step_x)),
        int(np.ceil(20 * MM / step_y)),
    )


def test_an_explicit_size_wins_from_the_step_rate(make_raster):
    beeld = make_raster([], bounds=(0, 0, 30 * MM, 20 * MM), width=64, height=32)

    assert beeld.size == (64, 32)


def test_a_zero_step_is_treated_as_one(make_raster):
    """A step of zero is not a step but a division by zero."""
    beeld = make_raster([], bounds=(0, 0, 100, 50), step_x=0, step_y=0)

    assert beeld.size == (100, 50)


def test_keep_ratio_uses_the_smallest_of_both_scales(kernel, make_raster):
    """
    With `keep_ratio` the image must not be stretched: a square stays a square, in a frame
    that is not one as well.
    """
    node = _rect(kernel, 0, 0, 20, 20, fill="black")
    bounds = Node.union_bounds([node], attr="paint_bounds")

    breed = make_raster([node], bounds=bounds, width=200, height=100, keep_ratio=True)
    vlek = _grijs(breed) < 128

    hoogte = vlek.any(axis=1).sum()
    breedte = vlek.any(axis=0).sum()
    assert abs(hoogte - breedte) <= 2, (hoogte, breedte)


# ------------------------------------------------------- wit en zwart


def test_white_is_white_and_black_is_black(kernel, make_raster):
    """
    White is background, black is work — the engine thresholds this afterwards. So a filled
    area should come out as a blot, not as an outline.
    """
    node = _rect(kernel, 10, 10, 20, 10, fill="black")
    bounds = Node.union_bounds([node], attr="paint_bounds")

    grijs = _grijs(make_raster([node], bounds=bounds, step_x=200, step_y=200))

    hoogte, breedte = grijs.shape
    assert grijs[hoogte // 2, breedte // 2] < 40, "the middle of a filled area is black"
    assert grijs.mean() < 80, "a filled area is predominantly black"


def test_an_unfilled_shape_burns_its_outline_and_not_its_middle(kernel, make_raster):
    """
    Exactly what the wx version does: it draws with the node's colours. A square without a
    fill is an outline — filling it would burn material the user has not pointed at.
    """
    node = _rect(kernel, 10, 10, 20, 20)
    bounds = Node.union_bounds([node], attr="paint_bounds")

    grijs = _grijs(make_raster([node], bounds=bounds, step_x=200, step_y=200))

    hoogte, breedte = grijs.shape
    assert grijs[hoogte // 2, breedte // 2] > 200, "het midden blijft onaangeroerd"
    assert grijs[hoogte // 2, 1] < 128, "the left edge is the outline"
    assert grijs[1, breedte // 2] < 128, "the top edge as well"


def test_the_shape_lands_where_the_bounds_say_it_lands(kernel, make_raster):
    """
    Two areas in one frame: the left one should be on the left. If it is mirrored or shifted,
    the machine burns in the wrong place.
    """
    links = _rect(kernel, 0, 0, 10, 40, fill="black")
    rechts = _rect(kernel, 30, 0, 10, 10, fill="black")
    bounds = Node.union_bounds([links, rechts], attr="paint_bounds")

    grijs = _grijs(make_raster([links, rechts], bounds=bounds, step_x=400, step_y=400))
    vlek = grijs < 128
    hoogte, breedte = grijs.shape

    assert vlek[:, : breedte // 4].mean() > 0.5, "there is a tall column on the left"
    assert vlek[hoogte // 2 :, breedte * 3 // 4 :].mean() < 0.1, (
        "there is nothing at the bottom right"
    )


def test_a_text_node_does_not_bring_the_raster_down(kernel, make_raster):
    """
    Without a GUI there is no font engine. Our app converts text into geometry before the
    planning moment; if an `elem text` does come past, drawing nothing is better than half a
    plan and an exception.
    """
    kernel.console('text "hallo"\n')
    tekst = [n for n in kernel.elements.elems() if n.type == "elem text"]
    vlak = _rect(kernel, 0, 0, 10, 10, fill="black")

    beeld = make_raster(tekst + [vlak], bounds=(0, 0, 20 * MM, 20 * MM), step_x=400, step_y=400)

    assert beeld.size[0] > 0


def test_an_image_node_is_pasted_with_its_own_matrix(kernel, make_raster):
    """
    An image carries its placement in its matrix, not in its pixels. If that is ignored, the
    photo ends up at the origin instead of in the place where it lies.
    """
    from meerk40t.core.node.elem_image import ImageNode
    from meerk40t.svgelements import Matrix

    plaatje = Image.new("L", (10, 10), 0)
    matrix = Matrix()
    matrix.post_scale(MM, MM)
    matrix.post_translate(20 * MM, 0)
    node = ImageNode(image=plaatje, matrix=matrix, dpi=500)
    kernel.elements.elem_branch.add_node(node)
    node.set_dirty_bounds()

    # An outline of 40 × 20 mm sets the frame; inside it you can see *where* the image lands
    # instead of only *that* it is there.
    kader = _rect(kernel, 0, 0, 40, 20)

    bounds = Node.union_bounds([kader, node], attr="paint_bounds")
    grijs = _grijs(make_raster([kader, node], bounds=bounds, width=80, height=40))
    vlek = grijs < 128

    assert vlek[5:15, 45:55].mean() > 0.9, "the image is at the top right"
    assert vlek[5:15, 5:15].mean() < 0.1, "and there is nothing at the top left"


# ------------------------------------------------------- van laag tot cutcode


def test_a_raster_layer_now_produces_cutcode(kernel):
    """
    The point of all this: `op raster` produces work headless instead of a
    lege laag. Voorheen gaf ditzelfde ontwerp nul stukken en nul seconden.
    """
    node = _rect(kernel, 10, 10, 20, 20, fill="black")
    operatie = kernel.elements.op_branch.add(
        type="op raster", speed=100, power=500, dpi=250, label="Vlak"
    )
    operatie.add_reference(node)

    kernel.console("plan copy preprocess validate blob preopt optimize\n")
    plan = kernel.planner.default_plan

    stukken = [item for item in plan.plan if hasattr(item, "duration_cut")]
    assert stukken, "het plan is niet leeg"
    assert sum(item.duration_cut() for item in stukken) > 0


# ------------------------------------------------- gaten in een vorm (de "0")


def ring(kernel, buiten_mm=20.0, binnen_mm=10.0):
    """
    Een ring als één pad met twee deelpaden: de vorm van een "0".

    Precies het geval waar het op stukliep: op het canvas stond het midden open
    en op het hout was de nul helemaal dichtgebrand.
    """
    from meerk40t.core.units import UNITS_PER_MM
    from meerk40t.svgelements import Color
    from meerk40t.core.geomstr import Geomstr

    midden = 30.0 * UNITS_PER_MM
    geometry = Geomstr()
    geometry.append(Geomstr.circle(buiten_mm * UNITS_PER_MM, midden, midden))
    geometry.append(Geomstr.circle(binnen_mm * UNITS_PER_MM, midden, midden))
    node = kernel.elements.elem_branch.add(
        geometry=geometry,
        type="elem path",
        stroke=Color("#000000"),
        fill=Color("#000000"),
    )
    kernel.elements.validate_ids()
    return node


def zwart_op(beeld, x: int, y: int) -> bool:
    """Is deze pixel gebrand? Het beeld is wit met het werk in zwart."""
    return beeld.convert("L").getpixel((x, y)) < 128


def test_a_hole_in_a_shape_stays_unburned(kernel, make_raster):
    """
    Het midden van een nul hoort wit te blijven.

    Onze rasteraar vulde elk deelpad apart, dus de binnencontour werd net zo
    zwart als de buitenkant. Op het scherm klopte het wel — het canvas tekent
    het pad in één keer met `fill-rule="nonzero"` — en dat maakte het verschil
    pas op het hout zichtbaar.
    """
    node = ring(kernel)
    beeld = make_raster([node], node.bounds, 200, 200, None, 1, 1, True)

    assert zwart_op(beeld, 100, 8), "de rand van de ring hoort gebrand te worden"
    assert not zwart_op(beeld, 100, 100), "het gat in het midden hoort wit te blijven"


def test_the_ring_is_not_simply_left_out(kernel, make_raster):
    """Tegenproef: er moet wél een ring staan, en niet niets."""
    node = ring(kernel)
    beeld = make_raster([node], node.bounds, 200, 200, None, 1, 1, True).convert("L")

    donker = sum(1 for pixel in beeld.getdata() if pixel < 128)
    # Een ring van 20 mm buiten en 10 mm binnen: driekwart van het vlak van de
    # cirkel, en de cirkel vult π/4 van het vierkante beeld.
    verwacht = 200 * 200 * (3.1416 / 4) * 0.75
    assert donker == pytest.approx(verwacht, rel=0.15)


def test_a_shape_without_holes_is_still_solid(kernel, make_raster):
    """De gewone weg mag er niet onder lijden."""
    from meerk40t.core.units import UNITS_PER_MM
    from meerk40t.svgelements import Color
    from meerk40t.core.geomstr import Geomstr

    midden = 30.0 * UNITS_PER_MM
    node = kernel.elements.elem_branch.add(
        geometry=Geomstr.circle(20.0 * UNITS_PER_MM, midden, midden),
        type="elem path",
        stroke=Color("#000000"),
        fill=Color("#000000"),
    )
    beeld = make_raster([node], node.bounds, 200, 200, None, 1, 1, True)

    assert zwart_op(beeld, 100, 100)
