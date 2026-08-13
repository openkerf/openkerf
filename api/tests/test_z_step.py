"""
Zakken per pass (punt 3 uit de tweede testronde van Jelle).

De engine kent dit niet: `passes` is bij haar een teller op één cutcode-object
en alle passes delen één settings-dict. Wat er wél is, is `util console` — een
bewerking die middenin een job een consolecommando draait — en `z_move` op de
GRBL-driver. Deze tests pinnen vast dat wij die twee tot een echte Z-stap
combineren, en dat het veld wegblijft op een machine die geen Z-as heeft.
"""

import pytest
from fastapi.testclient import TestClient
from meerk40t.kernel import Kernel
from meerk40t.core.node.util_console import ConsoleOperation

from openkerf_api.commands import CommandRunner
from openkerf_api.server import ApiServer


# --------------------------------------------------------------- een GRBL-kern


def _grbl_kernel(z_axis: bool):
    """Een kern met een GRBL-apparaat; het enige met een Z-as in de engine."""
    kernel = Kernel("MeerK40t", "0.0.0-testing", "OpenKerf_Z", ansi=False, ignore_settings=True)
    from meerk40t.core import core, svg_io
    from meerk40t.device import basedevice, dummydevice
    from meerk40t.extra import coolant
    from meerk40t.fill import fills
    from meerk40t.grbl import plugin as grbldevice
    from meerk40t.image import imagetools
    from meerk40t.network import kernelserver

    for module in (
        kernelserver,
        basedevice,
        dummydevice,
        core,
        imagetools,
        fills,
        coolant,
        svg_io,
        grbldevice,
    ):
        kernel.add_plugin(module.plugin)
    kernel(partial=True)
    kernel.console("service device start grbl -i\n")
    kernel.device.supports_z_axis = z_axis
    return kernel


@pytest.fixture
def grbl():
    kernel = _grbl_kernel(z_axis=True)
    yield kernel
    kernel()


@pytest.fixture
def grbl_zonder_z():
    kernel = _grbl_kernel(z_axis=False)
    yield kernel
    kernel()


def client_for(kernel, tmp_path):
    return TestClient(ApiServer(kernel, library_path=tmp_path / "z.db").build_app())


def een_laag(client, passes=4):
    """Een rechthoek in een snijlaag met meerdere passes."""
    element = client.post(
        "/api/design/elements",
        json={"type": "rect", "x_mm": 10, "y_mm": 10, "width_mm": 20, "height_mm": 20},
    ).json()["ids"][0]
    layer = client.post("/api/design/operations", json={"type": "cut"}).json()["id"]
    client.post("/api/design/assign", json={"ids": [element], "operation_id": layer})
    client.patch(f"/api/design/operations/{layer}", json={"passes": passes})
    return layer


# ------------------------------------------------------------ wat de machine kan


def test_a_machine_with_a_z_axis_offers_the_step(grbl, tmp_path):
    with client_for(grbl, tmp_path) as client:
        assert client.get("/api/design/capabilities").json()["z_step"] is True


def test_a_machine_without_a_z_axis_does_not(grbl_zonder_z, tmp_path):
    with client_for(grbl_zonder_z, tmp_path) as client:
        assert client.get("/api/design/capabilities").json()["z_step"] is False


def test_a_ruida_does_not_offer_the_step(kernel, tmp_path):
    """De dummy uit de gewone testkern kent geen Z-as — net als een Ruida."""
    with client_for(kernel, tmp_path) as client:
        assert client.get("/api/design/capabilities").json()["z_step"] is False


def test_the_step_is_refused_without_a_z_axis(grbl_zonder_z, tmp_path):
    """Liever geen veld dan een veld dat niets doet — dezelfde regel als B11."""
    with client_for(grbl_zonder_z, tmp_path) as client:
        layer = een_laag(client)

        response = client.patch(f"/api/design/operations/{layer}", json={"z_step_mm": 0.5})

        assert response.status_code == 409
        assert "Z-as" in response.json()["detail"]


def test_an_absurd_step_is_refused(grbl, tmp_path):
    with client_for(grbl, tmp_path) as client:
        layer = een_laag(client)

        assert client.patch(
            f"/api/design/operations/{layer}", json={"z_step_mm": 50}
        ).status_code == 409


def test_the_step_is_stored_and_shown(grbl, tmp_path):
    with client_for(grbl, tmp_path) as client:
        layer = een_laag(client)

        client.patch(f"/api/design/operations/{layer}", json={"z_step_mm": 0.5})

        operations = client.get("/api/design").json()["operations"]
        assert [o["z_step_mm"] for o in operations if o["id"] == layer] == [0.5]


def test_zero_turns_the_step_off(grbl, tmp_path):
    """0 is uit, geen "nul millimeter zakken" — anders splitst het plan tóch."""
    with client_for(grbl, tmp_path) as client:
        layer = een_laag(client)
        client.patch(f"/api/design/operations/{layer}", json={"z_step_mm": 0.5})

        client.patch(f"/api/design/operations/{layer}", json={"z_step_mm": 0})

        operations = client.get("/api/design").json()["operations"]
        assert [o["z_step_mm"] for o in operations if o["id"] == layer] == [None]


# --------------------------------------------------------------- wat het plan doet


class Nep:
    """Een planstap met net genoeg eigenschappen om de opbouw te toetsen."""

    def __init__(self, passes=1, z_step_mm=None):
        self.passes = passes
        self.passes_custom = False
        self.z_step_mm = z_step_mm


def commands_of(steps):
    return [s.command for s in steps if isinstance(s, ConsoleOperation)]


def test_a_layer_without_a_step_is_left_alone():
    """De gewone job mag hier geen last van hebben."""
    stap = Nep(passes=3)

    uit = CommandRunner._with_z_moves([stap], ConsoleOperation)

    assert uit == [stap]
    assert stap.passes == 3


def test_one_pass_with_a_step_changes_nothing():
    """Zakken tussen één pass en niets is geen zakken."""
    stap = Nep(passes=1, z_step_mm=0.5)

    assert CommandRunner._with_z_moves([stap], ConsoleOperation) == [stap]


def test_four_passes_become_four_burns_with_a_move_between():
    stap = Nep(passes=4, z_step_mm=0.5)

    uit = CommandRunner._with_z_moves([stap], ConsoleOperation)

    # Vier keer branden, drie keer zakken, en één keer terug naar het begin.
    assert sum(1 for s in uit if s is stap) == 4
    assert commands_of(uit) == [
        "z_move 0.500mm",
        "z_move 0.500mm",
        "z_move 0.500mm",
        "z_move -1.500mm",
    ]


def test_the_burns_and_the_moves_alternate():
    """Zakken ná een pass, niet ervoor: de eerste pass staat op de ingestelde focus."""
    stap = Nep(passes=3, z_step_mm=1.0)

    soorten = [
        "zak" if isinstance(s, ConsoleOperation) else "brand"
        for s in CommandRunner._with_z_moves([stap], ConsoleOperation)
    ]

    assert soorten == ["brand", "zak", "brand", "zak", "brand", "zak"]


def test_the_head_returns_to_the_height_it_started_at():
    """Anders begint de volgende job te laag, en dat zie je pas aan het werkstuk."""
    stap = Nep(passes=5, z_step_mm=0.4)

    bewegingen = [
        float(c.removeprefix("z_move ").removesuffix("mm"))
        for c in commands_of(CommandRunner._with_z_moves([stap], ConsoleOperation))
    ]

    assert sum(bewegingen) == pytest.approx(0.0)


def test_the_repeat_moves_from_the_operation_to_the_plan():
    """De teller gaat naar één; het herhalen doet het plan nu zelf."""
    stap = Nep(passes=4, z_step_mm=0.5)

    CommandRunner._with_z_moves([stap], ConsoleOperation)

    assert stap.passes == 1
    assert stap.passes_custom is True


# ------------------------------------------------- en dan echt, door de engine


def test_the_engine_turns_it_into_alternating_cutcode_and_moves(grbl, tmp_path):
    """
    De volledige weg: laag met passes en Z-stap → plan → cutcode.

    Dit is de test die telt. Hij loopt tot en met `optimize` door de echte
    pijplijn van de engine — dezelfde stappen die `start_job` draait, alleen
    zonder `spool`, want spoolen laat een GRBL-apparaat een verbinding zoeken.
    """
    with client_for(grbl, tmp_path) as client:
        layer = een_laag(client, passes=3)
        client.patch(f"/api/design/operations/{layer}", json={"z_step_mm": 0.5})

    runner = CommandRunner(grbl)
    root = grbl.root
    root.setting(bool, "opt_merge_ops", True)
    root.setting(bool, "opt_merge_passes", True)
    root.opt_merge_ops = False
    root.opt_merge_passes = False
    runner.run("plan clear copy")
    plan = grbl.planner.get_or_make_plan("0")
    plan.plan[:] = CommandRunner._with_z_moves(plan.plan, ConsoleOperation)
    runner.run("plan preprocess validate blob preopt optimize")

    soorten = [
        s.command if isinstance(s, ConsoleOperation) else type(s).__name__
        for s in plan.plan
    ]
    assert soorten == [
        "CutCode",
        "z_move 0.500mm",
        "CutCode",
        "z_move 0.500mm",
        "CutCode",
        "z_move -1.000mm",
    ]
    # Elke pass draagt echt werk. Een gekopieerde bewerking zou zijn kinderen
    # kwijtraken en hier nul opleveren — de fout die je pas op materiaal ziet.
    assert all(len(s) > 0 for s in plan.plan if not isinstance(s, ConsoleOperation))


def test_a_layer_without_a_step_does_not_split_the_pipeline(grbl, tmp_path):
    """
    De gewone job blijft de gewone job.

    `_z_stepped_layers` is de schakelaar: alleen een laag met een Z-stap knipt
    de pijplijn in tweeën. Zo raakt het pad dat élke job loopt niet aan een
    functie die alleen op een GRBL met Z-as iets doet.

    De test kijkt naar de laag die hij zelf maakte en niet naar een lege lijst:
    de engine bewaart de laatste lagenstapel in één gedeelde `operations.cfg`
    (sectie `[previous …]`), profiel-overstijgend en ook met
    `ignore_settings=True`, dus een verse kern begint zelden schoon.
    """
    with client_for(grbl, tmp_path) as client:
        layer = een_laag(client, passes=3)
        runner = CommandRunner(grbl)
        assert layer not in [op.id for op in runner._z_stepped_layers()]

        client.patch(f"/api/design/operations/{layer}", json={"z_step_mm": 0.5})

        assert layer in [op.id for op in runner._z_stepped_layers()]


def test_a_stored_step_is_ignored_on_a_machine_without_a_z_axis(grbl, tmp_path):
    """
    Van machine wisselen mag geen commando opleveren dat die machine niet kent.

    De laag houdt zijn Z-stap — dat hoort ook, want je wisselt terug — maar het
    plan splitst niet meer, dus er gaat geen `z_move` naar een driver die het
    woord niet kent. Gevonden door na een screenshot te vragen wat er gebeurt
    als je hetzelfde ontwerp op de Ruida zet.
    """
    with client_for(grbl, tmp_path) as client:
        layer = een_laag(client, passes=3)
        client.patch(f"/api/design/operations/{layer}", json={"z_step_mm": 0.5})
        assert layer in [op.id for op in CommandRunner(grbl)._z_stepped_layers()]

        grbl.device.supports_z_axis = False

        assert CommandRunner(grbl)._z_stepped_layers() == []
        # De instelling zelf blijft staan: terugwisselen moet hem teruggeven.
        assert grbl.elements.find_node(layer).z_step_mm == 0.5


def test_a_layer_that_does_not_burn_is_left_out(grbl, tmp_path):
    """Meebranden uit betekent ook geen Z-beweging voor die laag."""
    with client_for(grbl, tmp_path) as client:
        layer = een_laag(client, passes=3)
        client.patch(f"/api/design/operations/{layer}", json={"z_step_mm": 0.5})

        client.patch(f"/api/design/operations/{layer}", json={"output": False})

        assert layer not in [op.id for op in CommandRunner(grbl)._z_stepped_layers()]


def test_the_step_survives_being_written_out_and_read_back(grbl, tmp_path):
    """
    Zonder dit zou de Z-stap na een herstart weg zijn terwijl de passes bleven
    staan — en dan snijd je vier keer op dezelfde hoogte zonder dat iets het
    zegt. De engine schrijft elke gewone eigenschap van een bewerking mee naar
    de opslag (`svg_io.py:456`, de generieke tak), dus onze eigen `z_step_mm`
    gaat vanzelf mee. Hier bewezen met de opslagroutine van de engine zelf.
    """
    with client_for(grbl, tmp_path) as client:
        layer = een_laag(client, passes=3)
        # Een eigen waarde: de engine bewaart de lagenstapel in één gedeelde
        # `operations.cfg`, dus er kunnen lagen van een andere test tussen staan.
        client.patch(f"/api/design/operations/{layer}", json={"z_step_mm": 0.37})

    elements = grbl.elements
    elements.save_persistent_operations("zsteptest")
    elements.clear_operations()
    elements.load_persistent_operations("zsteptest")

    assert 0.37 in [getattr(op, "z_step_mm", None) for op in elements.ops()]
