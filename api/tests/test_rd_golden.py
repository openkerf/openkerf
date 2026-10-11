"""
Golden RD files: the bytes `build_job_bytes` makes, pinned before the transport changes.

`CommandRunner.build_job_bytes` assembles a whole job file offline, through a
`RuidaDriver` of its own whose controller only fills an `RDJob` buffer. Phase 0
of replacing MeerK40t's Ruida transport with our own: when the transport
changes, these bytes may not. Each design is drawn through our own HTTP API on a
Ruida machine made through `POST /api/machines` (the way the wizard makes one),
in a kernel of its own, and compared byte for byte with `fixtures/rd/`.

The bytes are *unswizzled*: `RDJob.write_command` appends plain commands and
the swizzle (magic 0x88 for this device) is applied by the transport on the way
out, not in the buffer.

Regenerate after a deliberate encoding change, and only then:

    OPENKERF_REGENERATE_RD=1 .venv/bin/python -m pytest api/tests/test_rd_golden.py
"""

import itertools
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from meerk40t.core.elements import elements as elements_module
from meerk40t.ruida.rdjob import RDJob, parse_commands

from openkerf_api.server import ApiServer

FIXTURES = Path(__file__).parent / "fixtures" / "rd"
REGENERATE = os.environ.get("OPENKERF_REGENERATE_RD") == "1"

_kernels = itertools.count()


# ------------------------------------------------------------------ the designs


def _element(client, **body) -> str:
    response = client.post("/api/design/elements", json=body)
    assert response.status_code == 201, response.text
    return response.json()["ids"][0]


def _layer(client, kind: str) -> str:
    response = client.post("/api/design/operations", json={"type": kind})
    assert response.status_code in (200, 201), response.text
    return response.json()["id"]


def cut_rect_circle(client, kernel):
    """A 20 x 10 mm rectangle and a circle of radius 8 mm in one cut layer."""
    ids = [
        _element(client, type="rect", x_mm=10, y_mm=10, width_mm=20, height_mm=10),
        _element(client, type="circle", cx_mm=50, cy_mm=20, r_mm=8),
    ]
    return ids, _layer(client, "cut")


def raster_filled_rect(client, kernel):
    """A filled 10 x 5 mm rectangle in a raster layer, through our headless rasteriser.

    Filled through `POST /api/design/fill`: without a fill the rasteriser draws
    only the outline.
    """
    ids = [_element(client, type="rect", x_mm=10, y_mm=10, width_mm=10, height_mm=5)]
    filled = client.post("/api/design/fill", json={"ids": ids, "filled": True})
    assert filled.status_code == 200, filled.text
    return ids, _layer(client, "raster")


def cut_3_passes(client, kernel):
    """A 20 x 10 mm rectangle in a cut layer with three passes.

    The Z step is asked for too, and refused: a Ruida has no Z axis the driver
    can move (`Drawing.z_step_supported`), so through the API this is what a
    3-pass layer on a Ruida is.
    """
    ids = [_element(client, type="rect", x_mm=10, y_mm=10, width_mm=20, height_mm=10)]
    layer = _layer(client, "cut")
    response = client.patch(f"/api/design/operations/{layer}", json={"passes": 3})
    assert response.json()["applied"] == {"passes": 3}, response.text
    refused = client.patch(f"/api/design/operations/{layer}", json={"z_step_mm": 0.5})
    assert refused.status_code == 409, refused.text
    return ids, layer


def cut_3_passes_zstep(client, kernel):
    """`cut_3_passes`, with a 0.5 mm Z step the layer brought along.

    The API refuses the step on a Ruida, but a layer keeps its step when the
    machine changes (see `CommandRunner._z_stepped_layers`), so a design made on
    a machine with a Z axis reaches a Ruida like this. Set on the node directly
    because the test kernel has no GRBL device to set it through.
    """
    ids, layer = cut_3_passes(client, kernel)
    operation = next(op for op in kernel.elements.ops() if op.id == layer)
    operation.z_step_mm = 0.5
    return ids, layer


DESIGNS = {
    "cut_rect_circle": cut_rect_circle,
    "raster_filled_rect": raster_filled_rect,
    "cut_3_passes": cut_3_passes,
    "cut_3_passes_zstep": cut_3_passes_zstep,
}


# ------------------------------------------------------------------ building


def build(name: str, tmp_path, monkeypatch) -> bytes:
    """
    The job bytes of one design, from a kernel that has seen nothing before.

    The conftest fence gives one `operations.cfg` per *test*; two kernels in one
    test would hand each other their layers through it. Measured: the second of
    two raster builds then carried a layer restored from the first, and its
    bytes differed at command 29 (`ca 06`, the colour of that restored layer)
    and in the file sum. So every kernel here gets a folder of its own.

    Drawing a shape also puts it in a default engrave layer (`E1`); every layer
    but the design's own is deleted through the API, so the file holds only
    the layer the design describes.
    """
    from conftest import _bootstrap

    real = elements_module.Settings
    folder = tmp_path / f"kernel-{next(_kernels)}"
    folder.mkdir()
    monkeypatch.setattr(
        elements_module,
        "Settings",
        lambda directory, filename, *a, **kw: real(None, str(folder / filename), *a, **kw),
    )
    kernel = _bootstrap()
    monkeypatch.setattr(elements_module, "Settings", real)
    try:
        server = ApiServer(kernel)
        with TestClient(server.build_app()) as client:
            made = client.post("/api/machines", json={"info": "ruida-beta", "label": "Golden"})
            assert made.json()["active"] is True, made.text
            ids, layer = DESIGNS[name](client, kernel)
            assigned = client.post(
                "/api/design/assign", json={"ids": ids, "operation_id": layer}
            )
            assert assigned.json()["added"] == len(ids), assigned.text
            for operation in list(kernel.elements.ops()):
                if operation.id != layer:
                    gone = client.delete(f"/api/design/operations/{operation.id}")
                    assert gone.status_code == 200, gone.text
            assert [op.id for op in kernel.elements.ops()] == [layer]
            return server.commands.build_job_bytes()
    finally:
        kernel()


# ------------------------------------------------------------------ decoding


def decode(data: bytes) -> list[str]:
    """One line per command: offset, hex, and the engine's own description.

    `parse_commands` cuts the stream on bytes >= 0x80; `RDJob.process` with a
    channel says what each command is, the same text the emulator logs.
    """
    lines: list[str] = []
    job = RDJob(channel=lines.append)
    offset = 0
    for command in parse_commands(data):
        before = len(lines)
        try:
            job.process(list(command), offset=offset)
        except Exception as error:  # a broken command is exactly what to show
            lines.append(f"{offset:06x}-**-> {command.hex()}\t(undecodable: {error!r})")
        if len(lines) == before:
            lines.append(f"{offset:06x}-**-> {command.hex()}\t(?)")
        offset += len(command)
    return lines


def describe_mismatch(expected: bytes, actual: bytes, context: int = 6) -> str:
    first = next(
        (i for i, (a, b) in enumerate(zip(expected, actual)) if a != b),
        min(len(expected), len(actual)),
    )
    want, got = decode(expected), decode(actual)

    def around(lines):
        starts = [int(line[:6], 16) for line in lines]
        index = max(0, sum(1 for start in starts if start <= first) - 1)
        return "\n    ".join(lines[max(0, index - context) : index + context + 1])

    return (
        f"RD bytes differ: expected {len(expected)} bytes, got {len(actual)}; "
        f"first difference at offset {first} (0x{first:06x}).\n"
        f"  expected ({len(want)} commands):\n    {around(want)}\n"
        f"  actual ({len(got)} commands):\n    {around(got)}\n"
        "If the change is deliberate: OPENKERF_REGENERATE_RD=1, and say why in the commit."
    )


def _kinds(data: bytes) -> list[str]:
    """The description of every command, without offset and hex."""
    return [line.split("\t(", 1)[1][:-1] for line in decode(data)]


def _count(kinds, prefix: str) -> int:
    return sum(1 for kind in kinds if kind.startswith(prefix))


def _fixture(name: str) -> bytes:
    return (FIXTURES / f"{name}.rd").read_bytes()


# ------------------------------------------------------------------ the tests


@pytest.mark.parametrize("name", list(DESIGNS))
def test_the_bytes_match_the_golden_file(name, tmp_path, monkeypatch):
    actual = build(name, tmp_path, monkeypatch)
    path = FIXTURES / f"{name}.rd"
    if REGENERATE:
        FIXTURES.mkdir(parents=True, exist_ok=True)
        path.write_bytes(actual)
    expected = path.read_bytes()
    assert actual == expected, describe_mismatch(expected, actual)


@pytest.mark.parametrize("name", list(DESIGNS))
def test_two_fresh_kernels_build_the_same_bytes(name, tmp_path, monkeypatch):
    """
    Measured before the files were stored: each design built in two fresh
    kernels gave identical bytes, and so did five separate processes with
    PYTHONHASHSEED 0, 1, 2, 12345 and random (one SHA-1 per design across all
    five). Nothing is normalised: no timestamp, id or name reaches the buffer.
    """
    assert build(name, tmp_path, monkeypatch) == build(name, tmp_path, monkeypatch)


def test_the_mismatch_message_points_at_the_first_difference():
    data = bytearray(_fixture("cut_3_passes"))
    data[400] ^= 0x01
    message = describe_mismatch(_fixture("cut_3_passes"), bytes(data))
    assert "first difference at offset 400 (0x000190)" in message


# ------------------------------------------------------------------ landmarks


def test_every_file_is_unswizzled_one_layer_and_ends_like_a_file():
    """
    Measured on all four: they start `d8 10` (Ref Point Mode 2) in the clear,
    hold one RD layer (part 0, one Layer Number, one Max Layer), and end
    `e5 05 <sum> d7` where the sum is every byte before it plus 0xD7
    (`RDJob.write_tail`).
    """
    from meerk40t.ruida.rdjob import decodeu35

    for name in DESIGNS:
        data = _fixture(name)
        kinds = _kinds(data)
        assert data[:2] == b"\xd8\x10", (name, data[:8].hex(" "))
        assert data[-8:-6] == b"\xe5\x05" and data[-1:] == b"\xd7", (name, data[-8:].hex(" "))
        assert decodeu35(data[-6:-1]) == sum(data[:-8]) + 0xD7, name
        assert _count(kinds, "0, Layer Number") == 1, name
        assert _count(kinds, "0, Max Layer") == 1, name
        assert not any(kind.startswith("1, ") for kind in kinds), name


def test_the_cut_file():
    """
    Measured: 984 bytes, 171 commands. One absolute move and 4 absolute cuts
    for the rectangle; the circle is a second absolute move and 108 relative
    cuts. Work mode 0, 10 mm/s in the layer table and in the stream.
    """
    data = _fixture("cut_rect_circle")
    kinds = _kinds(data)
    assert (len(data), len(kinds)) == (984, 171)
    assert _count(kinds, "Move Absolute") == 2
    assert _count(kinds, "Cut Absolute") == 4
    assert _count(kinds, "Cut Relative") == 108
    assert "0, Work Mode 0" in kinds
    assert _count(kinds, "Speed Laser 1 10.0mm/s") == 2


def test_the_raster_file():
    """
    Measured: 3625 bytes, 850 commands, work mode 1 (`raster_step_y` set):
    one absolute move, then 106 vertical steps and 107 absolute cuts — about
    one long cut per line — between short horizontal moves and cuts.

    The jump to the start still carries `Parameters`' default
    `Speed Laser 1 10.0mm/s`, and right after it, before the first cut, the
    layer's own 150 mm/s (`ruida_speed`). Before that repair the 150 never
    came: 3618 bytes, 849 commands, and every cut at 10 mm/s.
    """
    data = _fixture("raster_filled_rect")
    kinds = _kinds(data)
    assert (len(data), len(kinds)) == (3625, 850)
    assert "Work Mode 1" in kinds
    assert _count(kinds, "Move Absolute") == 1
    assert _count(kinds, "Move Vertical Relative") == 106
    assert _count(kinds, "Cut Absolute") == 107
    assert "0, Speed 150.0mm/s" in kinds
    speeds = [kind for kind in kinds if kind.startswith("Speed Laser 1")]
    assert speeds == [
        "Speed Laser 1 150.0mm/s",
        "Speed Laser 1 10.0mm/s",
        "Speed Laser 1 150.0mm/s",
    ]


def test_three_passes_stay_one_layer():
    """
    Measured: 521 bytes, 70 commands. Three passes are one RD layer with the
    rectangle's 4 cuts three times — 12 absolute cuts after one absolute move —
    because `_share_pass_settings` gives the copies one settings dict. Without
    it every pass is a layer of its own (RECORD.md, "Elke pass wordt een éxtra
    laag").
    """
    data = _fixture("cut_3_passes")
    kinds = _kinds(data)
    assert (len(data), len(kinds)) == (521, 70)
    assert _count(kinds, "Move Absolute") == 1
    assert _count(kinds, "Cut Absolute") == 12
    assert _count(kinds, "Axis Z Move") == 0


def test_a_carried_over_z_step_leaves_one_pass_in_the_file():
    """
    Pins today's behaviour, which is a defect: 418 bytes, 59 commands, and
    only **4** absolute cuts — one pass of the three.

    `_with_passes` reads `z_step_mm` without asking the machine, so the plan
    becomes three cutcodes with a `z_move` console step between them (measured:
    `CutCode[4], z_move 0.500mm, CutCode[4], z_move 0.500mm, CutCode[4],
    z_move -1.000mm`). Every cutcode gets its own `plot_start`, which calls
    `controller.start_record()`, which does `job.clear()`. A spy on
    `start_record` saw three calls, throwing away buffers of 62 and 59
    commands, so `build_job_bytes` returns the last pass only. No Z move
    reaches the file.
    """
    data = _fixture("cut_3_passes_zstep")
    kinds = _kinds(data)
    assert (len(data), len(kinds)) == (418, 59)
    assert _count(kinds, "Move Absolute") == 1
    assert _count(kinds, "Cut Absolute") == 4
    assert _count(kinds, "Axis Z Move") == 0
