# The OpenKerf handbook

OpenKerf is a laser-cutter interface that runs in a browser and drives your
machine through the MeerK40t engine. You draw or import a design on a bed drawn
to scale, put the shapes into layers that carry a speed and a power, and check
one screen before the head moves. What makes it different from a bare engine is
the bookkeeping around those numbers: a library of settings measured on your own
laser, on your own material, with the photo of the test board they came off.

## Starting it

Two things run: the engine with the OpenKerf API beside it, and the interface.

```bash
# the engine, headless, with the API on port 8080
meerk40t --no-gui -d -e "openkerf -p 8080"

# the interface
cd frontend && npm run dev
```

The interface opens on `http://localhost:5173` and talks to the API through a
proxy, so the addresses in the app are the same in development as in a finished
installation. A different API address goes in the environment variable
`OPENKERF_API`. To reach the app from a phone or tablet on the same network, give
the engine a bind address as well: `openkerf -p 8080 -b 0.0.0.0`.

When the API is reachable from the network it asks for a token before anything
may change or move; the engine prints that token in its own window at startup.
Until it has one the app is read-only. See [Reference](reference.md#the-token-for-write-actions).

## The pages

Read [Getting started](getting-started.md) first; the rest can be read in any
order or looked up when you need them.

| Page | What is in it |
| --- | --- |
| [Getting started](getting-started.md) | The road from a fresh installation to the first burn: the machine wizard — including what kind of laser it is and how strong — the sheet and its material, getting a design on the bed, giving it a layer, the pre-flight, and what to do when the machine is not answering. |
| [The bed](canvas.md) | The drawing area: the eight tools, drawing and editing curves, bridges that keep a cut part in the sheet, why an outline is caught on its line and a filled shape on its face, walking down a pile of overlapping shapes, snapping, moving the view, and sheets. |
| [Shapes, text, images and generators](shapes-and-generators.md) | Everything else that puts geometry on the bed — text, images, clipart, the eight generators — and the path operations that reshape it afterwards. |
| [Variable text](variable-text.md) | One design burned once per row of a list: the CSV or the counted range of numbers, `{name}` in a text, more than one on a plate, the run you press through at the machine, and a jig frame that burns only once. |
| [Layers](layers.md) | What the machine does with a shape: the four kinds of layer, speed, power and passes, the colour strip, burn order, raster settings, drop per pass and air assist. |
| [Burning](job.md) | The Job tab from top to bottom: the pre-flight, the cut path you can walk through before anything moves, the two taps that start a job, progress and adjustment while it burns, the queue, jogging the head, connecting, and the phone screen. |
| [The rotary](rotary.md) | Burning on a cylinder: where the settings live, calibrating from a burned line, what changes on the machine while a rotary is fitted, and the ten steps to work through standing at the laser. |
| [Test grids](test-grid.md) | Burning a board of squares to find the settings for a material, photographing it, aligning the photo and turning the best square into a saved setting — plus the code that lets a photograph find its own board, and cutting the board loose as a tile. |
| [The material library](library.md) | Keeping those settings: where a number came from and how far to trust it, applying one to a layer, renaming, merging and removing what is in the library, machine profiles, moving a library between computers, and taking a starting point from the catalogue other people share. |
| [Plates larger than the bed](tiling.md) | Burning a plate that does not fit, in tiles: alignment marks, sliding the plate along, and the two taps that tell the machine where it now lies. |
| [Reference](reference.md) | Every keyboard shortcut, every operation in the menus and the action bar, every reason a button is greyed out, and the app-wide settings — language, theme, notifications, the token and the camera. |

## How to update these pages

The screenshots are made by a script, not by hand, so that a picture shows the
same thing next month. With the app running, from the `frontend` directory:

```bash
node gauntlet/docs-shots.mjs          # all of them
node gauntlet/docs-shots.mjs 07       # only the shots whose name contains 07
```

Each shot puts the state it needs there itself through the API, so nothing
depends on what happened to be on the bed. That includes the machine: every
picture has a bed in it and this handbook quotes its size, so a run switches to
the KH-5030 if some other machine happens to be active. The files land in
`docs/images/`.

Two of them are held back on purpose. The pictures of a test board with a code
and with a cut-out have to *draw* a board, which writes a row into the library and
needs a cut setting for the material, so they only run against a library that is
expendable:

```bash
# an engine with a library of its own, and a dev server in front of it
meerk40t/.venv/bin/meerk40t --no-gui -d -e "openkerf -p 8092 -l /tmp/scratch/openkerf-library.db"
cd frontend && OPENKERF_API=http://127.0.0.1:8092 npx vite dev --port 5200

OK_SCRATCH_LIBRARY=1 OK_BASE=http://localhost:5200 node gauntlet/docs-shots.mjs 41
OK_SCRATCH_LIBRARY=1 OK_BASE=http://localhost:5200 node gauntlet/docs-shots.mjs 42
```

Without the flag the two shots are skipped and say so on the console. Two things
that scratch engine does *not* get its own copy of, because MeerK40t has none:
the machine list and the machine's own settings, which live in one
`MeerK40t.cfg` for every instance (see CLAUDE.md, the `-P/--profile` row). So
give it the bed and the name the handbook uses before you photograph anything —
otherwise the pictures show a bed and a machine name that no other page does.

What keeps the prose honest is a test:

```bash
node --test frontend/tests/docs.test.ts
```

It checks that every picture a page points at exists and every picture in
`docs/images/` is used, that every link between the pages resolves, that every
sentence the pages quote is really in the English catalogue, and that every
operation, shortcut, panel tab and window the interface offers is named
somewhere. A label renamed in `frontend/src/lib/i18n/en.ts` therefore fails the
test rather than quietly leaving a page wrong.

What it cannot see is the other direction: a page describing a button that has
been *deleted* passes, because there is no sentence to check any more. When a
window or a control goes, the page that described it has to be read by a person
in the same commit.
