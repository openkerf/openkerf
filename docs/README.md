# The OpenKerf handbook

OpenKerf is a laser-cutter interface that runs in a browser and drives your
machine through the MeerK40t engine. You draw or import a design on a bed drawn
to scale, put the shapes into layers that carry a speed and a power, and check
one screen before the head moves. What makes it different from a bare engine is
the bookkeeping around those numbers: a library of presets measured on your own
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
| [Burning](job.md) | The Job tab from top to bottom: the pre-flight, the cut path you can walk through before anything moves, the two taps that start a job, progress and adjustment while it burns, the queue, jogging the head, and connecting. |
| [The rotary](rotary.md) | Burning on a cylinder: where the settings live, calibrating from a burned line, what changes on the machine while a rotary is fitted, and the ten steps to work through standing at the laser. |
| [Test grids](test-grid.md) | Burning a board of squares to find the presets for a material, photographing it, aligning the photo and turning the best square into a saved preset — plus the code that lets a photograph find its own board, and cutting the board loose as a tile. |
| [The material library](library.md) | Keeping those presets: where a number came from and how far to trust it, applying one to a layer, renaming, merging and removing what is in the library, machine profiles, moving a library between computers, and taking a starting point from the catalogue other people share. |
| [Plates larger than the bed](tiling.md) | Burning a plate that does not fit, in tiles: alignment marks, sliding the plate along, and the two taps that tell the machine where it now lies. |
| [Reference](reference.md) | Every keyboard shortcut, every operation in the menus and the action bar, every reason a button is greyed out, and the app-wide settings — language, notifications, the token and the camera. |
| [Running in Docker](running-in-docker.md) | One compose file for a Linux box beside the laser: the image, the token, the data volume, the camera, the engine and OpenKerf's own line to a Ruida, one program per controller, updating, and the two limits — no machine discovery on Docker Desktop, and no laser over USB in this version. |

## How to update these pages

The screenshots are made by a script, not by hand, so that a picture shows the
same thing next month. It runs against a disposable server — its own temporary
library, layer list, projects and machine configuration, nothing of yours — with
an **emulated Ruida** in place of a laser:

```bash
# from the repository root, with the frontend built (npm --prefix frontend run build)
env PYTHONPATH=api python frontend/gauntlet/scratch_server.py --ruida-emulator

# in another terminal
OK_SCRATCH_LIBRARY=1 node frontend/gauntlet/docs-library.mjs   # the library the pictures show
OK_SCRATCH_LIBRARY=1 node frontend/gauntlet/docs-shots.mjs       # all of them
node frontend/gauntlet/docs-shots.mjs 07 50 53                   # only these
```

**The machine in the pictures is that emulator**, not a laser. It is a Ruida called
"KH-5030 (emulated)" with the KH-5030's bed of 500 × 300 mm, on OpenKerf's own line
to the engine's Ruida emulator on 127.0.0.1, so the top bar of every picture names it
that way — on purpose: a simulated machine is labelled as one. Where a page reports
a measurement *on the KH-5030* — a stop acknowledged in 6 ms, a raster burned in
77 s — that was measured on the real machine, and the pictures beside it only show
the screens. The server refuses every route that would execute anything (jobs,
moves, connecting, starting a series run), and the scratch server drives the
emulator's state for the pictures that need one — connected, a second program on
the line. One thing in those pictures is simulated outright and said so where it
appears: the job under way in the picture of a Ruida burning, which carries the name
"Sheet 1 (simulated)", because a real job is never started to take a photograph.
The details are in `frontend/gauntlet/README.md`.

Each shot puts the state it needs there itself through the API, so nothing depends
on what happened to be on the bed, and a run stops at the first shot that fails.
The files land in `docs/images/`. Four shots draw a test board, which writes a row
into the library, so they only run with `OK_SCRATCH_LIBRARY=1`: 41, 42, 43 and 44.
Without it they are skipped and say so on the console.

A few pictures are kept from an earlier run rather than retaken, because the
disposable server cannot show their state truthfully: the wizard's list of laser
kinds (02; the scratch engine loads only the Ruida driver, so the model counts would
be wrong), the name already taken (03; it needs a machine called KH-5030) and a
series run going (37; starting a run is refused there). Two more wait for a fix to
the screen itself: the cut path (29), which now numbers the inner square and the one
around it as "1+1", and print and cut (34), whose block runs past the edge of the
panel. All five show an older look of the same screens.

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
