# OpenKerf

A modern interface for a laser cutter, built on top of the
[MeerK40t](https://github.com/meerk40t/meerk40t) engine.

MeerK40t drives the machine and does it well. OpenKerf is the part in front of it: a
browser interface for drawing, laying out and burning, and a small API layer that talks
to the engine as an ordinary plugin. Nothing in the engine is forked or patched — the
whole of OpenKerf hangs off MeerK40t's own `meerk40t.extension` entry point, so the
engine can be updated without a merge.

The machine it was written for is a 5030 CO₂ laser with a Ruida controller. Anything
MeerK40t drives should work; only Ruida has been used in earnest.

## What it does today

- **Draw and edit** on a bed that knows its own size: rectangles, circles, lines, points,
  a pen with curves, text as real geometry, node editing, measuring, snapping.
- **Layers** that are laser operations — cut, engrave, raster, dots — with speed, power,
  passes and burn order, and one tap to put a material setting on one.
- **A material library** on local SQLite: speed and power per material and thickness, with
  where each number came from and how far to trust it.
- **A test grid** you burn, photograph and read settings off — including a QR code on the
  board, so a photograph finds its own row, and an optional cut-out so the tile can be
  kept.
- **Generators**: repeats, boxes with finger joints, QR and barcodes, arc text, a living
  hinge that fills the shape you selected, a focus test on machines whose Z the software
  can move.
- **Work bigger than the bed**, in tiles, with two-point alignment.
- **Variable text from a list**: one design, one burn per row of a CSV.
- **A job you can inspect before it moves**: pre-flight, the cut path step by step, an
  estimate that is arithmetic on the real cut plan.

The handbook is in [`docs/`](docs/README.md), in English, and every screen in it is a
screenshot taken by a script so the pages cannot quietly drift from the app.

## What it does not do yet, plainly

- **No board with a QR code or a cut-out has ever been burned.** Those numbers are
  measurements on cut plans and synthetic photographs, not on wood.
- **The shared settings catalogue holds 26 starting points and zero measurements.** See
  [presetariat](https://github.com/openkerf/presetariat).
- **Rotary and print-and-cut are built but unverified against a machine.**
- **Tablet, phone and dark theme work but have not been measured** the way the desktop
  light theme has.
- Sending a job to a Ruida's own memory (upload without cutting) is not implemented: the
  opcodes exist in MeerK40t but nothing calls them.

## Running it

You need Python 3.9+ (developed on 3.14) and Node 20+.

```bash
# the engine, as an ordinary dependency
python3 -m venv .venv
.venv/bin/pip install -e api

# the API beside the engine, headless
.venv/bin/meerk40t --no-gui -d -e "openkerf -p 8080"

# the interface
cd frontend && npm install && npm run dev
```

The interface then runs on `http://localhost:5173` and talks to the API through a proxy.
To reach it from a tablet next to the machine, start the engine with
`openkerf -p 8080 -b 0.0.0.0`.

`openkerf -l <path>` gives the API a library file of its own, which is what you want for
anything experimental: the library lives beside the engine's settings and is shared by
every instance on the machine.

## Tests

```bash
.venv/bin/python -m pytest api/tests -q      # 1523 tests
cd frontend && npx svelte-check              # types
cd frontend && node --test tests/*.test.ts   # the promises the interface makes
```

The test suites are the argument, not the decoration. Where a test docstring quotes a
number, that number was measured on this machine and can be measured again.

## Licence

MIT, the same as the engine it is built on. See [LICENSE](LICENSE).

The settings catalogue is a separate repository under CC BY 4.0, because settings are data
somebody else measured and attribution travels with them.
