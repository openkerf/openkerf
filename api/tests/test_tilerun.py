"""
De plan-bewerkers en de lopende tegelreeks.

Het uitgangspunt van al deze tests: wat er ook in het plan gebeurt, de
elementenboom van de gebruiker komt er onveranderd uit.
"""

import pytest

from openkerf_api.commands import PLAN_AND_SPOOL, CommandRunner
from openkerf_api.tiling import Alignment, Point, Rect
from openkerf_api.tilerun import TileMutator, marker_geometry

UNITS_PER_MM = 65535 / 25.4


def test_a_plain_job_still_takes_the_single_line_route(kernel):
    """
    Zonder bewerkers blijft het één regel. Dat pad wordt bij elke job gelopen
    en verdient geen omweg voor een functie die de meeste mensen niet gebruiken.

    Er wordt tegen de constante getoetst en niet tegen een uitgeschreven regel:
    die regel bevat `clear`, en waaróm dat er staat is een dure les (zonder
    clear stapelt elke start hetzelfde werk opnieuw op het plan). Een testliteral
    die de constante nadoet, gaat vroeg of laat uit de pas lopen met het origineel
    en dan is de test een val in plaats van een vangnet.
    """
    runner = CommandRunner(kernel)
    gedraaid = []
    runner.run = lambda regel: gedraaid.append(regel) or []

    runner._plan_and_spool()

    assert gedraaid == [PLAN_AND_SPOOL]


def test_a_mutator_gets_the_plan_steps_and_can_replace_them(kernel):
    runner = CommandRunner(kernel)
    gezien = {}

    def bewerker(steps):
        gezien["aantal"] = len(steps)
        return list(steps)

    kernel.console("rect 0 0 10mm 10mm\n")
    kernel.console("classify\n")
    runner._plan_and_spool(mutators=[bewerker])

    assert "aantal" in gezien


def _design(kernel):
    """Twee vierkanten: één links op de plaat, één rechts."""
    kernel.console("rect 10mm 10mm 30mm 30mm\n")
    kernel.console("rect 300mm 10mm 30mm 30mm\n")
    kernel.console("classify\n")


def _shapes(steps):
    """
    De vormen in een bewerkt plan.

    Via `build_plan` en niet via een hele `plan`-regel: `blob` vervangt de
    bewerkingen door één `CutCode`, en dan valt er over het klippen niets meer
    vast te stellen.
    """
    return [c for step in steps for c in getattr(step, "children", []) or []]


def test_only_what_lies_in_the_tile_survives(kernel):
    _design(kernel)
    runner = CommandRunner(kernel)
    mutator = TileMutator(
        burn_mm=Rect(0, 0, 200, 200),
        alignment=Alignment(0.0, 0.0, 0.0, 0.0),
        units_per_mm=UNITS_PER_MM,
    )

    steps = runner.build_plan([mutator])

    assert len(_shapes(steps)) == 1


def test_the_users_tree_is_untouched_after_spooling(kernel):
    """
    De belangrijkste test van dit ontwerp. Het plan mag verminkt worden, het
    ontwerp niet — anders verliest de gebruiker werk aan een job.
    """
    _design(kernel)
    voor = [
        (n.type, tuple(round(v, 3) for v in n.bounds)) for n in kernel.elements.elems()
    ]
    runner = CommandRunner(kernel)

    runner.build_plan(
        [
            TileMutator(
                burn_mm=Rect(0, 0, 200, 200),
                alignment=Alignment(0.0, -100.0, 0.0, 0.0),
                units_per_mm=UNITS_PER_MM,
            )
        ]
    )

    na = [
        (n.type, tuple(round(v, 3) for v in n.bounds)) for n in kernel.elements.elems()
    ]
    assert na == voor


def test_the_alignment_shift_moves_the_tile_into_the_bed(kernel):
    """
    Tegel 2 staat op de plaat op x=300, maar ligt na het verschuiven van de
    plaat op x=100 onder de kop. Het plan moet dat laatste bevatten.
    """
    _design(kernel)
    runner = CommandRunner(kernel)

    steps = runner.build_plan(
        [
            TileMutator(
                burn_mm=Rect(200, 0, 400, 200),
                alignment=Alignment(0.0, -200.0, 0.0, 0.0),
                units_per_mm=UNITS_PER_MM,
            )
        ]
    )

    vormen = _shapes(steps)
    assert len(vormen) == 1
    assert vormen[0].bounds[0] / UNITS_PER_MM == pytest.approx(100.0, abs=0.5)


def test_the_mutator_counts_what_it_actually_burns(kernel):
    """
    `burned_length_units` is het getal waarop de dekkingstest van taak 12 rust:
    daar wordt het over alle tegels opgeteld en vergeleken met het hele ontwerp.
    Als het meetelt wat er niet gebrand wordt, of dubbel telt, gaat die test
    groen terwijl er van alles misgaat. Dus hier vastgepind tegen een vorm
    waarvan we de omtrek met de hand kunnen uitrekenen.
    """
    kernel.console("rect 10mm 10mm 30mm 20mm\n")
    kernel.console("classify\n")
    runner = CommandRunner(kernel)
    mutator = TileMutator(
        burn_mm=Rect(0, 0, 200, 200),
        alignment=Alignment(0.0, 0.0, 0.0, 0.0),
        units_per_mm=UNITS_PER_MM,
    )

    runner.build_plan([mutator])

    omtrek_mm = 2 * (30 + 20)
    assert mutator.burned_length_units / UNITS_PER_MM == pytest.approx(
        omtrek_mm, rel=1e-3
    )


def test_a_picture_belongs_to_one_tile_and_is_not_repeated(kernel):
    """
    Een afbeelding heeft geen geometrie om te klippen, dus hij gaat in zijn
    geheel mee of niet. Zonder die toets kwam een foto in élke tegel terecht —
    op de verkeerde plek, met de volle brandtijd, en dat per tegel opnieuw.
    """
    from meerk40t.core.node.elem_image import ImageNode
    from meerk40t.svgelements import Matrix
    from PIL import Image

    plaatje = ImageNode(
        image=Image.new("L", (20, 20), 0),
        matrix=Matrix.translate(20 * UNITS_PER_MM, 20 * UNITS_PER_MM),
        dpi=500,
    )
    kernel.elements.elem_branch.add_node(plaatje)
    # `classify` als consolecommando classificeert alleen wat geëmphaseerd is;
    # deze afbeelding is nooit geselecteerd geweest (in tegenstelling tot een
    # vorm die via `rect` getekend wordt). Rechtstreeks aanroepen omzeilt dat.
    kernel.elements.classify([plaatje])
    runner = CommandRunner(kernel)

    binnen = runner.build_plan(
        [
            TileMutator(
                burn_mm=Rect(0, 0, 200, 200),
                alignment=Alignment(0.0, 0.0, 0.0, 0.0),
                units_per_mm=UNITS_PER_MM,
            )
        ]
    )
    buiten = runner.build_plan(
        [
            TileMutator(
                burn_mm=Rect(400, 0, 600, 200),
                alignment=Alignment(0.0, 0.0, 0.0, 0.0),
                units_per_mm=UNITS_PER_MM,
            )
        ]
    )

    assert any(c.type == "elem image" for c in _shapes(binnen))
    assert not any(c.type == "elem image" for c in _shapes(buiten))


def test_an_operation_that_ends_up_empty_leaves_the_plan(kernel):
    """Een laag die niets meer doet hoort niet in de job te staan."""
    _design(kernel)
    runner = CommandRunner(kernel)

    steps = runner.build_plan(
        [
            TileMutator(
                burn_mm=Rect(600, 600, 800, 800),
                alignment=Alignment(0.0, 0.0, 0.0, 0.0),
                units_per_mm=UNITS_PER_MM,
            )
        ]
    )

    assert not [s for s in steps if getattr(s, "children", None)]


def test_a_mark_is_a_circle_with_a_cross_in_it(kernel):
    """
    De cirkel geeft een rand om de kop op te richten die een los kruis niet
    heeft; het kruis geeft het middelpunt dat je aantikt.
    """
    geom = marker_geometry([Point(100.0, 50.0)], size_mm=8.0, units_per_mm=UNITS_PER_MM)

    x0, y0, x1, y1 = geom.bbox()
    assert (x1 - x0) / UNITS_PER_MM == pytest.approx(8.0, abs=0.1)
    assert (y1 - y0) / UNITS_PER_MM == pytest.approx(8.0, abs=0.1)


def test_the_marks_are_burned_last(kernel):
    """
    Eerder branden betekent dat een latere snede er nog doorheen kan lopen, en
    dan lijn je uit op een merk dat half weg is.
    """
    _design(kernel)
    runner = CommandRunner(kernel)
    mutator = TileMutator(
        burn_mm=Rect(0, 0, 200, 200),
        alignment=Alignment(0.0, 0.0, 0.0, 0.0),
        units_per_mm=UNITS_PER_MM,
        marker_geometry=marker_geometry(
            [Point(180.0, 20.0), Point(180.0, 180.0)], 8.0, UNITS_PER_MM
        ),
    )

    steps = runner.build_plan([mutator])

    laatste = [s for s in steps if getattr(s, "children", None)][-1]
    assert laatste.label == "Uitlijnmerken"
    assert len(laatste.children) == 1


def test_the_last_tile_burns_no_marks(kernel):
    """Geen volgende tegel, dus niets om op uit te lijnen — en dus geen merk."""
    _design(kernel)
    runner = CommandRunner(kernel)

    steps = runner.build_plan(
        [
            TileMutator(
                burn_mm=Rect(0, 0, 200, 200),
                alignment=Alignment(0.0, 0.0, 0.0, 0.0),
                units_per_mm=UNITS_PER_MM,
                marker_geometry=None,
            )
        ]
    )

    assert not [s for s in steps if getattr(s, "label", None) == "Uitlijnmerken"]
