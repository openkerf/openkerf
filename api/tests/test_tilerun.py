"""
De plan-bewerkers en de lopende tegelreeks.

Het uitgangspunt van al deze tests: wat er ook in het plan gebeurt, de
elementenboom van de gebruiker komt er onveranderd uit.
"""

import pytest

from openkerf_api.commands import PLAN_AND_SPOOL, CommandRunner
from openkerf_api.tiling import Alignment, Rect
from openkerf_api.tilerun import TileMutator

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
