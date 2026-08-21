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
| [Getting started](getting-started.md) | The road from a fresh installation to the first burn: the machine wizard, the sheet and its material, getting a design on the bed, giving it a layer, the pre-flight, and what to do when the machine is not answering. |
| [The bed](canvas.md) | The drawing area: the eight tools, why an outline is caught on its line and a filled shape on its face, walking down a pile of overlapping shapes, snapping, moving the view, and sheets. |
| [Shapes, text, images and generators](shapes-and-generators.md) | Everything else that puts geometry on the bed — text, images, clipart, the seven generators — and the path operations that reshape it afterwards. |
| [Layers](layers.md) | What the machine does with a shape: the four kinds of layer, speed, power and passes, the colour strip, burn order, raster settings, drop per pass and air assist. |
| [Burning](job.md) | The Job tab from top to bottom: the pre-flight, the two taps that start a job, progress and adjustment while it burns, the queue, jogging the head, connecting, and the phone screen. |
| [Test grids](test-grid.md) | Burning a board of squares to find the settings for a material, photographing it, aligning the photo and turning the best square into a saved setting. |
| [The material library](library.md) | Keeping those settings: where a number came from and how far to trust it, applying one to a layer, machine profiles, and moving a library between computers or taking settings from other people. |
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
depends on what happened to be on the bed. The files land in `docs/images/`.

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
