"""
Een job als bestand: de bytes, het gesprek en wat er misgaat.

Nooit tegen een laser. De end-to-end-toets praat tegen de Ruida-emulator van de
engine zelf, die dit gesprek aanneemt en het bestand wegschrijft.
"""

import pytest

from openkerf_api.commands import CommandRunner
from openkerf_api.edits import DesignError


@pytest.fixture
def ruida(kernel):
    """Een echte Ruida-service, zoals test_machine_connect die ook maakt."""
    kernel.console("service device start ruida -i\n")
    return kernel


def a_rectangle(kernel):
    """Iets om te branden: één rechthoek in een snijlaag."""
    kernel.console("rect 20mm 20mm 40mm 30mm\n")
    kernel.console("operation* delete\n")
    kernel.console("op cut\n")
    kernel.console("element* classify\n")


def test_the_job_becomes_bytes_that_end_like_a_file(ruida):
    """
    `save_job` in de engine schrijft 4 bytes en laat 623 in de buffer staan
    (gemeten, zie CLAUDE.md). Wij halen ze uit de buffer, en dan hoort er een
    compleet bestand uit te komen: het eindigt op SET_FILE_SUM gevolgd door
    END_OF_FILE.
    """
    a_rectangle(ruida)
    runner = CommandRunner(ruida)

    data = runner.build_job_bytes()

    assert len(data) > 100, f"only {len(data)} bytes — the buffer was not drained"
    # `\xD7` is END_OF_FILE; `\xCC` staat er niet in dit stadium.
    assert data.endswith(b"\xd7"), data[-8:].hex(" ")
    # SET_FILE_SUM staat er vlak voor. Let op: dat is `E5 05`
    # (`meerk40t/ruida/rdjob.py:173`), niet D8 11 — het plan had het mis en de
    # controller heeft dat vóór de uitvoering rechtgezet.
    assert b"\xe5\x05" in data[-16:], data[-16:].hex(" ")


def test_building_the_bytes_does_not_spool_anything(ruida):
    """
    Bouwen is niet branden. Wie deze route aanroept mag geen job in de wachtrij
    krijgen — dat is het hele verschil met `start_job`.
    """
    a_rectangle(ruida)
    runner = CommandRunner(ruida)

    runner.build_job_bytes()

    spooler = ruida.device.spooler
    assert not list(spooler.queue), "a job was spooled while only bytes were asked for"


def test_an_empty_bed_refuses_with_a_sentence(ruida):
    runner = CommandRunner(ruida)

    with pytest.raises(DesignError) as error:
        runner.build_job_bytes()

    assert "nothing" in str(error.value).lower()


def test_building_the_bytes_restores_the_merge_settings(ruida):
    """
    `_plan_without_spooling` turns `opt_merge_ops`/`opt_merge_passes` off while it
    works — same reason as `_plan_with_mutators`: on, the optimisation glues pieces
    together and pushes console steps to the back, so a Z would drop after burning
    instead of between passes. A mutator run during the build sees them off; once
    `build_job_bytes` returns, they are back to whatever they were before —
    the user's settings, not ours to leave changed.
    """
    a_rectangle(ruida)
    root = ruida.root
    root.setting(bool, "opt_merge_ops", True)
    root.setting(bool, "opt_merge_passes", True)
    root.opt_merge_ops = True
    root.opt_merge_passes = True
    runner = CommandRunner(ruida)
    seen = {}

    def spy(steps):
        seen["during"] = (root.opt_merge_ops, root.opt_merge_passes)
        return steps

    runner.build_job_bytes(mutators=[spy])

    assert seen["during"] == (False, False), "the flags were not off while building"
    assert (root.opt_merge_ops, root.opt_merge_passes) == (True, True), (
        "the flags were not put back"
    )
