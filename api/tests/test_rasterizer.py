"""
De rasteraar zonder GUI.

Wat hier getest wordt gaat écht de machine in: een rasterlaag die er verkeerd
uitkomt, brandt verkeerd. Daarom niet alleen "er komt een plaatje uit", maar ook
hoe groot het is en welke pixels zwart zijn.
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
    assert dienst is not None, "de rasteraar hoort door onze plugin geregistreerd te zijn"
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


# ------------------------------------------------------- de dienst zelf


def test_the_engine_has_a_rasteriser(kernel):
    """
    Zonder deze dienst neemt `OpRasterNode.preprocess` de `strip_rasters`-tak:
    de laag gooit zijn eigen kinderen weg en levert nul cutcode. Onze plugin
    vult dat gat op de plek die MeerK40t er zelf voor biedt.
    """
    assert callable(kernel.root.lookup("render-op/make_raster"))


def test_a_gui_rasteriser_wins_from_ours(kernel):
    """
    Draait iemand mét wxPython, dan tekent die versie met de echte fonts en de
    echte penstreken. Wij zijn de terugval, niet de voorkeur.
    """
    van_de_gui = object()
    kernel.root.register("render-op/make_raster", van_de_gui)

    assert rasterizer.register(kernel) is False
    assert kernel.root.lookup("render-op/make_raster") is van_de_gui


# ------------------------------------------------------- maat en contract


def test_without_bounds_there_is_nothing_to_render(make_raster):
    assert make_raster([], bounds=None) is None


def test_an_empty_node_list_does_not_fall_over(make_raster):
    """Een laag zonder tekenbare kinderen levert een leeg vel, geen fout."""
    beeld = make_raster([], bounds=(0, 0, 10 * MM, 10 * MM), step_x=100, step_y=100)

    assert beeld.mode == "RGB"
    assert _grijs(beeld).min() == 255


def test_the_size_follows_the_step_rate(kernel, make_raster):
    """
    De stap is de omgekeerde dpi: bij `dpi_to_steps` van de machine hoort een
    afbeelding die het kader precies dekt. Klopt dat niet, dan staat het beeld
    straks op de verkeerde schaal in het bed.
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
    """Een stap van nul is geen stap maar een deling door nul."""
    beeld = make_raster([], bounds=(0, 0, 100, 50), step_x=0, step_y=0)

    assert beeld.size == (100, 50)


def test_keep_ratio_uses_the_smallest_of_both_scales(kernel, make_raster):
    """
    Met `keep_ratio` mag het beeld niet uitgerekt worden: een vierkant blijft
    vierkant, ook in een kader dat dat niet is.
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
    Wit is achtergrond, zwart is werk — de engine drempelt dit hierna. Een
    gevuld vlak hoort dus als vlek uit te komen, niet als omtrek.
    """
    node = _rect(kernel, 10, 10, 20, 10, fill="black")
    bounds = Node.union_bounds([node], attr="paint_bounds")

    grijs = _grijs(make_raster([node], bounds=bounds, step_x=200, step_y=200))

    hoogte, breedte = grijs.shape
    assert grijs[hoogte // 2, breedte // 2] < 40, "het midden van een gevuld vlak is zwart"
    assert grijs.mean() < 80, "een gevuld vlak is overwegend zwart"


def test_an_unfilled_shape_burns_its_outline_and_not_its_middle(kernel, make_raster):
    """
    Precies wat de wx-versie doet: hij tekent met de kleuren van de knoop. Een
    vierkant zonder vulling is een omtrek — vullen zou materiaal verbranden dat
    de gebruiker niet heeft aangewezen.
    """
    node = _rect(kernel, 10, 10, 20, 20)
    bounds = Node.union_bounds([node], attr="paint_bounds")

    grijs = _grijs(make_raster([node], bounds=bounds, step_x=200, step_y=200))

    hoogte, breedte = grijs.shape
    assert grijs[hoogte // 2, breedte // 2] > 200, "het midden blijft onaangeroerd"
    assert grijs[hoogte // 2, 1] < 128, "de linkerrand is de omtrek"
    assert grijs[1, breedte // 2] < 128, "de bovenrand ook"


def test_the_shape_lands_where_the_bounds_say_it_lands(kernel, make_raster):
    """
    Twee vlakken in één kader: het linker hoort links te staan. Staat het
    gespiegeld of verschoven, dan brandt de machine op de verkeerde plek.
    """
    links = _rect(kernel, 0, 0, 10, 40, fill="black")
    rechts = _rect(kernel, 30, 0, 10, 10, fill="black")
    bounds = Node.union_bounds([links, rechts], attr="paint_bounds")

    grijs = _grijs(make_raster([links, rechts], bounds=bounds, step_x=400, step_y=400))
    vlek = grijs < 128
    hoogte, breedte = grijs.shape

    assert vlek[:, : breedte // 4].mean() > 0.5, "links staat een hoge kolom"
    assert vlek[hoogte // 2 :, breedte * 3 // 4 :].mean() < 0.1, (
        "rechtsonder staat niets"
    )


def test_a_text_node_does_not_bring_the_raster_down(kernel, make_raster):
    """
    Zonder GUI is er geen font-engine. Onze app zet tekst vóór het planmoment om
    in geometrie; komt er toch een `elem text` langs, dan is niets tekenen beter
    dan een half plan en een uitzondering.
    """
    kernel.console('text "hallo"\n')
    tekst = [n for n in kernel.elements.elems() if n.type == "elem text"]
    vlak = _rect(kernel, 0, 0, 10, 10, fill="black")

    beeld = make_raster(tekst + [vlak], bounds=(0, 0, 20 * MM, 20 * MM), step_x=400, step_y=400)

    assert beeld.size[0] > 0


def test_an_image_node_is_pasted_with_its_own_matrix(kernel, make_raster):
    """
    Een afbeelding draagt zijn plaatsing in zijn matrix, niet in zijn pixels.
    Wordt die genegeerd, dan komt de foto op de oorsprong terecht in plaats van
    op de plek waar hij ligt.
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

    # Een omtrek van 40 × 20 mm zet het kader; daarbinnen is te zien wáár de
    # afbeelding belandt in plaats van alleen dát hij er is.
    kader = _rect(kernel, 0, 0, 40, 20)

    bounds = Node.union_bounds([kader, node], attr="paint_bounds")
    grijs = _grijs(make_raster([kader, node], bounds=bounds, width=80, height=40))
    vlek = grijs < 128

    assert vlek[5:15, 45:55].mean() > 0.9, "de afbeelding staat rechtsboven"
    assert vlek[5:15, 5:15].mean() < 0.1, "en linksboven staat niets"


# ------------------------------------------------------- van laag tot cutcode


def test_a_raster_layer_now_produces_cutcode(kernel):
    """
    Het punt van dit alles: `op raster` levert headless werk in plaats van een
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
