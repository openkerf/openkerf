"""
Meer passes mag geen extra lagen in het bestand betekenen.

Gevonden op de machine: een testbord van twee passes gaf "file invalid" op het
display en de laser deed niets. De oorzaak zit niet in de passes zelf maar in de
vorm van het bestand.

`blob` maakt van elke pass een eigen stuk cutcode **met een eigen settings-dict**
(`core/cutplan.py:_blob_convert` kopieert de dict zodra `passes` en
`implicit_passes` verschillen), en de Ruida-driver groepeert zijn RD-lagen op de
identiteit van die dict (`ruida/rdjob.py:1434`). Elke pass werd dus een extra
laag. Gemeten op de echte RD-stroom van een bord met vier vakjes:

    één pass  : 16 cutobjecten, 4 RD-lagen  (max_layer_part 3)
    twee passes: 32 cutobjecten, 8 RD-lagen (max_layer_part 7)
    twee passes, settings gedeeld: 32 cutobjecten, 4 RD-lagen

Een bord van zestien vakjes komt bij twee passes dus op 33 lagen, en dat neemt de
controller niet meer aan. Wat hieronder getest wordt is de vorm van het plan die
dat voorkomt: dezelfde bewerking meerdere keren in de planlijst, zodat `blob`
per plek verse cutcode maakt en de settings-dict één object blijft.
"""

import pytest
from fastapi.testclient import TestClient

from openkerf_api.commands import CommandRunner
from openkerf_api.server import ApiServer


@pytest.fixture
def client(kernel, tmp_path):
    with TestClient(ApiServer(kernel, library_path=tmp_path / "d.db").build_app()) as c:
        yield c


def schone_lei(kernel):
    """
    Zonder de lagen van een vorige sessie.

    De engine zet de lagenlijst van de vorige sessie terug uit een gedeelde
    `operations.cfg` (zie de upstream-lijst in CLAUDE.md), en die lagen kunnen
    zelf passes dragen. Een test die lagen telt, moet met een lege lijst
    beginnen.
    """
    for op in list(kernel.elements.ops()):
        op.remove_node()


def twee_lagen(client, kernel, passes: int) -> list[str]:
    """Twee snijlagen met elk een eigen vorm, allebei met dit aantal passes."""
    schone_lei(kernel)
    ids = []
    for x in (10, 60):
        vorm = client.post(
            "/api/design/elements",
            json={"type": "rect", "x_mm": x, "y_mm": 10, "width_mm": 20, "height_mm": 20},
        ).json()["ids"][0]
        laag = client.post(
            "/api/design/operations", json={"type": "cut", "speed": 10}
        ).json()
        # Exclusief, niet erbij: een vorm die de engine ook nog in een eigen
        # laag classificeert, brandt twee keer en dan telt dit niets meer.
        client.post(
            "/api/design/single-layer",
            json={"ids": [vorm], "operation_id": laag["id"]},
        )
        client.patch(f"/api/design/operations/{laag['id']}", json={"passes": passes})
        ids.append(laag["id"])
    return ids


def lagen_en_branden(kernel, uitvouwen=True) -> tuple[int, int]:
    """
    (aantal RD-lagen, aantal keer branden), langs dezelfde weg als een echte job.

    Het aantal RD-lagen is het aantal verschillende settings-dicts van de
    cutobjecten: dát is waar `ruida/rdjob.py:1434` zijn lagen op groepeert.
    Spoolen doen we niet — dat zou de job starten.
    """
    from meerk40t.core.node.util_console import ConsoleOperation

    from openkerf_api.commands import PLAN_BLOB, PLAN_COPY

    runner = CommandRunner(kernel)
    plan = kernel.planner.get_or_make_plan("0")
    runner.run(PLAN_COPY)
    if uitvouwen and runner._multi_pass_layers():
        plan.plan[:] = runner._with_passes(list(plan.plan), ConsoleOperation)
    runner.run(PLAN_BLOB)
    if uitvouwen:
        plan.plan[:] = runner._share_pass_settings(list(plan.plan))

    objecten = [
        item
        for stap in plan.plan
        if hasattr(stap, "__iter__")
        for item in stap
        if isinstance(getattr(item, "settings", None), dict)
    ]
    dicts = {id(item.settings) for item in objecten}
    return len(dicts), len(objecten)


def test_two_passes_keep_one_layer_per_operation(client, kernel):
    twee_lagen(client, kernel, 2)

    lagen, branden = lagen_en_branden(kernel)

    assert lagen == 2, "twee bewerkingen horen twee RD-lagen te geven"
    # Acht snijstukken per pass (twee rechthoeken van vier zijden), dus zestien.
    assert branden == 16, "en toch alles twee keer branden"


def test_one_pass_is_the_yardstick(client, kernel):
    twee_lagen(client, kernel, 1)

    assert lagen_en_branden(kernel) == (2, 8)


def test_without_the_sharing_the_layers_double(client, kernel):
    """
    De tegenproef, want anders bewijst de test hierboven niets.

    Zonder onze ingreep geeft `blob` elke pass een eigen settings-dict — de vorm
    die de controller weigerde.
    """
    twee_lagen(client, kernel, 2)

    lagen, branden = lagen_en_branden(kernel, uitvouwen=False)

    assert (lagen, branden) == (4, 16)


def test_a_grid_of_sixteen_squares_stays_sixteen_layers(client, kernel):
    """
    Het geval waar het op stukliep: een testbord met twee passes.

    Zestien vakjes plus de labellaag is zeventien lagen, en zo hoort het te
    blijven. Zonder de ingreep werden het drieëndertig.
    """
    from openkerf_api.testgrid import TestGridGenerator, plan_grid

    schone_lei(kernel)
    plan, cells = plan_grid(
        operation="snijden",
        speed_min=5, speed_max=20, speed_steps=4,
        power_min=40, power_max=90, power_steps=4,
        cell_mm=8, gap_mm=2, origin_x_mm=20, origin_y_mm=20,
        passes=2,
    )
    TestGridGenerator(kernel).draw(plan, cells)

    lagen, branden = lagen_en_branden(kernel)

    assert len(cells) == 16
    # Zestien vakjes en één labellaag, en die laatste brandt één keer.
    assert lagen == 17
    assert branden > 32


def test_a_layer_that_does_not_burn_is_left_out(client, kernel):
    ids = twee_lagen(client, kernel, 3)
    client.patch(f"/api/design/operations/{ids[0]}", json={"output": False})

    runner = CommandRunner(kernel)
    assert [op.id for op in runner._multi_pass_layers()] == [ids[1]]


def test_the_z_step_still_gets_its_moves_between_passes(client, kernel):
    """De Z-stap loopt over dezelfde uitvouwing; die mag hier niet sneuvelen."""
    from meerk40t.core.node.util_console import ConsoleOperation

    class Nep:
        def __init__(self, passes, z_step_mm=None):
            self.passes = passes
            self.passes_custom = True
            self.implicit_passes = passes
            self.z_step_mm = z_step_mm

    stap = Nep(passes=3, z_step_mm=0.5)
    uit = CommandRunner._with_passes([stap], ConsoleOperation)

    commandos = [getattr(s, "command", None) for s in uit]
    assert commandos.count("z_move 0.500mm") == 2
    assert "z_move -1.000mm" in commandos
    assert uit.count(stap) == 3
    assert stap.passes == 1


def test_without_a_z_step_there_are_no_moves(client, kernel):
    from meerk40t.core.node.util_console import ConsoleOperation

    class Nep:
        def __init__(self, passes):
            self.passes = passes
            self.passes_custom = True
            self.implicit_passes = passes
            self.z_step_mm = None

    stap = Nep(passes=2)
    uit = CommandRunner._with_passes([stap], ConsoleOperation)

    assert uit == [stap, stap]
    assert stap.passes == 1
