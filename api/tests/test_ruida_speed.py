"""
Every cut on a Ruida goes at its own layer's speed.

Found while pinning the RD bytes for the new transport: the first layer of a job carried
its own speed in its block and then the driver's default 10 mm/s in the cut stream, right
before the first move, and nothing after it (see `ruida_speed`). The test reads the
file the way the controller does — the last `Speed Laser 1` before a cut is the one that
cut runs at — and asks that of every cut in the job.
"""

import pytest
from fastapi.testclient import TestClient
from meerk40t.ruida.driver import RuidaDriver
from meerk40t.ruida.rdjob import RDJob, parse_commands

from openkerf_api import ruida_speed
from openkerf_api.server import ApiServer


def _commands(data: bytes) -> list[str]:
    """The engine's own description of each command, in order."""
    lines: list[str] = []
    job = RDJob(channel=lines.append)
    for command in parse_commands(data):
        job.process(list(command))
    return [line.split("\t(", 1)[1][:-1] if "\t(" in line else line for line in lines]


def _speeds_at_cuts(data: bytes) -> list[float]:
    """The speed in force at each cut, read top to bottom."""
    speed = None
    at_cuts = []
    for kind in _commands(data):
        if kind.startswith("Speed Laser 1"):
            speed = float(kind.split()[3].removesuffix("mm/s"))
        elif kind.startswith("Cut "):
            at_cuts.append(speed)
    return at_cuts


@pytest.fixture
def ruida(kernel, tmp_path):
    server = ApiServer(kernel, library_path=tmp_path / "d.db")
    with TestClient(server.build_app()) as client:
        made = client.post("/api/machines", json={"info": "ruida-beta", "label": "Speed"})
        assert made.json()["active"] is True, made.text
        yield client, server, kernel


def _layer(client, kind, speed, element):
    layer = client.post("/api/design/operations", json={"type": kind}).json()["id"]
    assert client.patch(f"/api/design/operations/{layer}", json={"speed": speed}).status_code == 200
    assigned = client.post("/api/design/assign", json={"ids": [element], "operation_id": layer})
    assert assigned.json()["added"] == 1, assigned.text
    return layer


def _only(client, kernel, keep):
    for operation in list(kernel.elements.ops()):
        if operation.id not in keep:
            assert client.delete(f"/api/design/operations/{operation.id}").status_code == 200


def _rect(client, **body):
    return client.post("/api/design/elements", json={"type": "rect", **body}).json()["ids"][0]


def test_a_raster_layer_burns_at_its_own_speed(ruida):
    """
    Measured without the repair: all 465 cut commands at 10 mm/s in a 150 mm/s layer.
    With it: all 465 at 150.
    """
    client, server, kernel = ruida
    element = _rect(client, x_mm=10, y_mm=10, width_mm=10, height_mm=5)
    assert client.post("/api/design/fill", json={"ids": [element], "filled": True}).status_code == 200
    layer = _layer(client, "raster", 150, element)
    _only(client, kernel, {layer})

    speeds = _speeds_at_cuts(server.commands.build_job_bytes())

    assert len(speeds) == 465
    assert set(speeds) == {150.0}


def test_each_layer_of_a_job_burns_at_its_own_speed(ruida):
    """
    Two layers, so the second one is covered too: it starts with a block of its own, and
    that block has to stay in force. Measured without the repair: the 25 mm/s cut layer's
    4 cuts at 10 mm/s, the 300 mm/s engrave layer's 4 at 300 — only the first layer of a
    job is hit. With it: 4 at 25 and 4 at 300.
    """
    client, server, kernel = ruida
    first = _layer(client, "cut", 25, _rect(client, x_mm=10, y_mm=10, width_mm=20, height_mm=10))
    second = _layer(client, "engrave", 300, _rect(client, x_mm=50, y_mm=10, width_mm=20, height_mm=10))
    _only(client, kernel, {first, second})

    speeds = _speeds_at_cuts(server.commands.build_job_bytes())

    assert 10.0 not in speeds
    assert sorted(set(speeds)) == [25.0, 300.0]
    # In burn order, and each layer as one run.
    assert speeds == sorted(speeds, key=[25.0, 300.0].index)


def test_the_repair_steps_aside_for_an_engine_that_has_its_own():
    """An engine whose `set` does something is left as it is."""
    original = RuidaDriver.set
    try:
        def own(self, key, value):
            self.speed_dirty = key == "speed"

        RuidaDriver.set = own
        assert ruida_speed.install() is False
        assert RuidaDriver.set is own
    finally:
        RuidaDriver.set = original


def test_installing_twice_changes_nothing_the_second_time():
    assert getattr(RuidaDriver.set, "openkerf_speed_repair", False)
    assert ruida_speed.install() is False
