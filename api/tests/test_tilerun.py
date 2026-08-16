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


def _wide_sheet(server):
    """
    Een plaat van 800 × 150 mm op het dummy-bed, met tegels aan.

    Die maat is niet willekeurig: het dummy-apparaat heeft een bed van
    320 × 220 mm (gemeten, niet de 500 × 300 die je zou verwachten), dus het
    bruikbare venster is 300 mm en deze plaat wordt precies drie tegels. Kies
    je 900, dan worden het er vier en vallen de tests om op een reden die
    niets met tegels te maken heeft.
    """
    vel = server.sheets.state()["sheets"][0]
    server.sheets.update(vel["id"], width_mm=800.0, height_mm=150.0)
    server.sheets.update(vel["id"], tiling={"enabled": True})
    server.kernel.console("rect 10mm 10mm 30mm 30mm\n")
    server.kernel.console("rect 600mm 10mm 30mm 30mm\n")
    server.kernel.console("classify\n")


def test_a_run_survives_a_restart_but_its_alignment_does_not(kernel, tmp_path):
    """
    De reeks is uren werk en overleeft afsluiten. De uitlijning niet: die zegt
    waar de plaat lag, en dat weet je na een pauze niet meer.
    """
    from openkerf_api.server import ApiServer

    server = ApiServer(kernel, library_path=tmp_path / "v.db")
    run = server.tiles
    _wide_sheet(server)
    run.start()
    run.align([{"x_mm": 0.0, "y_mm": 0.0}], reference="plate_corner")
    assert run.state()["aligned"] is True

    opnieuw = ApiServer(kernel, library_path=tmp_path / "v.db").tiles

    assert opnieuw.state()["current"] == 0
    assert opnieuw.state()["aligned"] is False


def test_the_fingerprint_is_the_same_in_a_fresh_process(kernel, tmp_path):
    """
    De vingerafdruk gaat naar schijf en wordt na een herstart vergeleken, dus
    hij moet buiten dit proces dezelfde waarde hebben.

    Dat klinkt vanzelfsprekend en is het niet: Python zout de hash van strings
    per proces, dus een vingerafdruk uit `hash()` komt na elke herstart anders
    terug en verklaart iedere hervatte reeks ongeldig — precies het geval
    waarvoor de reeks bewaard wordt. Een test die twee servers in hetzelfde
    proces maakt ziet daar niets van; alleen een echt tweede proces wel.
    """
    import subprocess
    import sys

    tekst = "|".join(["800.0x150.0", '{"enabled": true}', "elem rect:10-10-40-40"])
    script = "import hashlib;" f"print(hashlib.sha1({tekst!r}.encode()).hexdigest())"
    eerste = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    ).stdout
    tweede = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    ).stdout

    assert eerste == tweede != ""


def test_the_fingerprint_is_a_digest_and_not_a_process_hash(kernel, tmp_path):
    """
    Samen met de test hierboven sluit dit de keten: sha1 is over processen heen
    stabiel, en de vingerafdruk ís een sha1-digest.

    Veertig hexcijfers is het bewijs. `str(hash(...))` is een decimaal getal en
    valt hier meteen door — en dat is precies de fout die dit moet vangen, want
    zonder deze test kwam hij er pas na een herstart uit, als een reeks die
    zichzelf zonder reden ongeldig verklaart.
    """
    from openkerf_api.server import ApiServer

    server = ApiServer(kernel, library_path=tmp_path / "v.db")
    _wide_sheet(server)
    vel = server.sheets.state()["sheets"][0]

    afdruk = server.tiles._fingerprint(vel)

    assert len(afdruk) == 40
    assert all(teken in "0123456789abcdef" for teken in afdruk)
    assert afdruk == server.tiles._fingerprint(vel)


def test_a_run_whose_sheet_is_deleted_expires_gracefully(kernel, tmp_path):
    """
    Het vel weggooien terwijl er een reeks loopt.

    Wat er dan feitelijk gebeurt is niet "geen vel meer": `Sheets.remove`
    activeert eerst een ander vel en gooit het oude daarna pas weg, en er is
    altijd precies één actief vel. De reeks hoort bij een vel dat er niet meer
    is, dus hij verloopt — en dat is precies goed.

    Wat deze test vastpint is dat je dat als staat terugkrijgt, en dat zowel
    branden als uitlijnen daarna netjes weigert met díe uitleg, niet met een
    melding uit de diepte over vellen terwijl je een merk staat aan te tikken.
    """
    from openkerf_api.edits import DesignError
    from openkerf_api.server import ApiServer

    server = ApiServer(kernel, library_path=tmp_path / "v.db")
    _wide_sheet(server)
    server.tiles.start()

    vel = server.sheets.state()["sheets"][0]
    server.sheets.add(name="Ander vel")
    server.sheets.remove(vel["id"])

    stand = server.tiles.state()
    assert stand["stale"] is True
    assert stand["message"]

    for aanroep in (
        lambda: server.tiles.burn(),
        lambda: server.tiles.align(
            [{"x_mm": 0.0, "y_mm": 0.0}], reference="plate_corner"
        ),
    ):
        with pytest.raises(DesignError) as fout:
            aanroep()
        # De reeks legt uit dat hij verlopen is. Een kale "Er is geen actief
        # vel." zou hier de verkeerde vraag beantwoorden.
        assert str(fout.value) == stand["message"]


def test_changing_the_design_invalidates_a_running_series(kernel, tmp_path):
    """
    Half het oude ontwerp en half het nieuwe branden is de duurste fout die dit
    systeem kan maken. Dus: ongeldig, en zichtbaar.
    """
    from openkerf_api.server import ApiServer

    server = ApiServer(kernel, library_path=tmp_path / "v.db")
    _wide_sheet(server)
    server.tiles.start()

    kernel.console("rect 500mm 100mm 20mm 20mm\n")
    kernel.console("classify\n")

    stand = server.tiles.state()
    assert stand["stale"] is True
    assert "ontwerp" in stand["message"].lower()


def test_burning_without_alignment_is_refused(kernel, tmp_path):
    from openkerf_api.server import ApiServer
    from openkerf_api.edits import DesignError

    server = ApiServer(kernel, library_path=tmp_path / "v.db")
    _wide_sheet(server)
    server.tiles.start()

    with pytest.raises(DesignError) as fout:
        server.tiles.burn()

    # Op "uitgelijnd" en niet op "uitlijn": dat laatste zit er niet in — er
    # staat "ge" tussen. En op "merken", want een weigering die niet zegt wat
    # je eraan doet, is een weigering waar de gebruiker niets aan heeft.
    melding = str(fout.value).lower()
    assert "uitgelijnd" in melding
    assert "merken" in melding


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


def test_a_tile_whose_marks_fall_off_the_bed_is_refused(kernel, tmp_path):
    """
    De merken liggen in de overlapzone en dus buiten het brandgebied. Een
    controle die alleen naar het brandgebied kijkt, laat een tegel door
    waarvan de merken naast het bed gebrand zouden worden — de kop tegen zijn
    eindaanslag, met materiaal in de machine.
    """
    from openkerf_api.edits import DesignError
    from openkerf_api.server import ApiServer

    server = ApiServer(kernel, library_path=tmp_path / "v.db")
    _wide_sheet(server)
    server.tiles.start()
    # Zo ver naar rechts dat het brandgebied nog past en de merken niet.
    server.tiles.align([{"x_mm": 30.0, "y_mm": 0.0}], reference="plate_corner")

    with pytest.raises(DesignError) as fout:
        server.tiles.burn()

    assert "buiten het bed" in str(fout.value)


def test_burning_the_same_tile_twice_asks_first(kernel, tmp_path):
    """
    Opnieuw branden mag — een afgebroken job moet je over kunnen doen — maar
    niet per ongeluk. De tweede keer gaat de laser over werk dat er al ligt.
    """
    from openkerf_api.edits import DesignError
    from openkerf_api.server import ApiServer

    server = ApiServer(kernel, library_path=tmp_path / "v.db")
    _wide_sheet(server)
    server.tiles.start()
    server.tiles.align([{"x_mm": 0.0, "y_mm": 0.0}], reference="plate_corner")
    server.tiles.burn()

    with pytest.raises(DesignError) as fout:
        server.tiles.burn()
    assert "al gebrand" in str(fout.value)

    # Met bevestiging mag het wel.
    assert server.tiles.burn(confirm_reburn=True)["burned_length_mm"] > 0


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
