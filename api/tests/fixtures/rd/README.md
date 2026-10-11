# Golden RD files

The bytes `CommandRunner.build_job_bytes()` returns for four small designs, pinned
before MeerK40t's Ruida transport is replaced by ours. MeerK40t keeps the RD encoding;
when the transport changes, these bytes must not. `api/tests/test_rd_golden.py` builds
each design again in a fresh kernel and compares byte for byte.

**Unswizzled.** These are the plain commands from the `RDJob` buffer. Swizzling happens
later, in the session on the way out (`ruida/ruidasession.py`, `self.swizzle(data)`),
with the device's magic: `0x88`, the `ruida-beta` default. Every file starts `d8 10`
(Ref Point Mode 2) and ends `e5 05 <file sum> d7`. To get what goes over the wire, swizzle
with `meerk40t.ruida.rdjob.encode_bytes(data, magic=0x88)`.

Each design is drawn through our HTTP API on a Ruida machine made with
`POST /api/machines {"info": "ruida-beta"}`, and every layer but the design's own is
deleted, so each file holds exactly one RD layer (part 0).

| File | Bytes | Commands | Design |
|---|---|---|---|
| `cut_rect_circle.rd` | 984 | 171 | 20 x 10 mm rectangle at (10, 10) mm and a circle r = 8 mm at (50, 20) mm, one cut layer, defaults (10 mm/s, 100 %) |
| `raster_filled_rect.rd` | 3625 | 850 | 10 x 5 mm rectangle at (10, 10) mm, filled (`POST /api/design/fill`), one raster layer, defaults (150 mm/s), our headless rasteriser |
| `cut_3_passes.rd` | 521 | 70 | 20 x 10 mm rectangle, cut layer with 3 passes; the Z step is refused on a Ruida (409), so none |
| `cut_3_passes_zstep.rd` | 418 | 59 | the same, plus `z_step_mm = 0.5` set on the layer node, as a layer brought along from a machine with a Z axis keeps it |

Two of these pinned behaviour that was wrong; one is repaired, one still pins it on purpose:

- `cut_3_passes_zstep.rd` holds **one** pass, not three. A Z step splits the plan into
  three cutcodes with `z_move` console steps between them, and every cutcode's
  `plot_start` calls `start_record()`, which clears the `RDJob` buffer. Only the last
  pass is left.
- `raster_filled_rect.rd` used to say 150 mm/s in the layer table and then
  `Speed Laser 1 10.0mm/s` in the stream before the first move, and nothing after it: the
  driver moved before it read the layer's settings and `RuidaDriver.set` did nothing.
  Repaired in `openkerf_api/ruida_speed.py`; the file was regenerated for it and now has
  the layer's 150 right after the jump, before the first cut (3618 → 3625 bytes, one
  command more).

Fixing the Z step changes the bytes too. Regenerate the file then, on purpose, and say why.

## Regenerating

```
OPENKERF_REGENERATE_RD=1 .venv/bin/python -m pytest api/tests/test_rd_golden.py
```

The landmark tests (byte counts, command counts, cuts) are written against these files
and fail after a regeneration that changes them. Measure the new numbers and update the
tests and this table together.

Determinism: each design gave the same bytes in two fresh kernels, and the same SHA-1 in
separate processes with `PYTHONHASHSEED` 0, 1, 2, 12345 and random. Nothing is
normalised. Two kernels in one test that share an `operations.cfg` do *not* give the
same bytes (the second restores the first one's layers), which is why the test gives
every kernel its own folder.
