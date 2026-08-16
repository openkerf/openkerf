"""
De plan-bewerkers en de lopende tegelreeks.

Het uitgangspunt van al deze tests: wat er ook in het plan gebeurt, de
elementenboom van de gebruiker komt er onveranderd uit.
"""

import pytest

from openkerf_api.commands import PLAN_AND_SPOOL, CommandRunner


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
