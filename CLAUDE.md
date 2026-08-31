# CLAUDE.md — working on OpenKerf

House rules for this codebase. They are short because each one cost something to learn;
the reasoning behind them is in the working record — a private repository with the round
logs, the design system, the numbered decisions (`B1`, `L3`, `T4` …) and the screenshot
archive. Older comments in the code point at documents that live there
(`DESIGN-SYSTEM.md`, `BESLISSINGEN.md`, `GAUNTLET-LOG.md`); the measurements they rely on
are repeated below.

## What this is

A browser interface and an API layer **beside** the MeerK40t engine, never inside it.
OpenKerf loads through MeerK40t's own `meerk40t.extension` entry point and changes nothing
under `meerk40t/`. If a change seems to require touching the engine, that is a signal to
reconsider — or to send it upstream as a pull request.

- `api/openkerf_api/` — FastAPI routes and the engine seam. Refusals are whole sentences
  with a code (`DesignError("...", code="draw.emptyText")`); the code travels in the
  `X-OpenKerf-Error` header so the interface can say it in the reader's language.
- `frontend/` — SvelteKit 2 with Svelte 5 runes, TypeScript, static adapter.
- `docs/` — the handbook, in English, with screenshots taken by `frontend/gauntlet/`.

## Language

**English is the source language**, in the interface and in the code. Translations sit on
top of it; Dutch is the first. `frontend/src/lib/i18n/README.md` explains how to add one.

- Keys are semantic (`job.phase.queued.title`), never the English text.
- **A message is a whole sentence.** Gluing two halves together in the markup only works
  between languages with the same word order, and the test refuses a message that is a
  bare conjunction or starts with a space.
- Numbers and dates go through `Intl`, not through the catalogue: 3,5 mm against 3.5 mm is
  the difference between two values to somebody at a laser.
- Values in the database and in the API stay as they are (`snijden`, `graveren-raster`):
  they are users' data, not text for users. They never reach a screen as a key.

## Where a new thing goes

- a **value** you set and read back → the context panel on the right
- a **verb on the selection** → the right-click menu (and a shortcut)
- a **frequent verb** (align, group, mirror, undo) → also the action bar
- a **mode** (what the next click does) → the tool rail
- **document- or machine-wide** → the top bar
- a **workspace where you search and compare** → a window of its own, unless you visit it
  once per machine, in which case it belongs at the moment it is needed

Handlings are described **once**, in `frontend/src/lib/actions.ts` — name, shortcut, and
the reason something cannot be done now — and the menu, the action bar and the keyboard all
read from there. `frontend/tests/actions.test.ts` guards that.

The same pattern holds wherever more than one surface must know one thing: `jobPhase` in
`api.ts` decides the phase of a running job, `offerState` in `library.svelte.ts` decides
what the catalogue card says, `Series.burn_mutators()` decides what the next burn leaves
out. Add the third reader to the function, not a second copy of the rule.

## A route without a caller is not a feature

Twice in one round the engine side was finished — route, columns, refusals, tests, handbook
page — and no control existed on any screen. Both times a user found it. So at every new
route: grep the new field names and paths in `frontend/src` and require at least one hit
that is not a type or a comment. Nothing is not a loose end to tidy later; it is the
feature not existing.

The hiding place: the handbook can write the gap up neatly and make it invisible. A page
that says "this is not on the form yet" is a finding, not a text.

## Measure, do not read

The rule that has found the most: when the answer matters, measure it. Not "the code says
it clips to the outline" but 160 slits in the box against 132 in the circle. Test
docstrings carry the numbers, and a docstring that names a number nobody measured is worse
than one that says nothing.

Two corollaries learned the hard way:

- **A measurement taken too early is a wrong measurement.** Reading the DOM 2 s after a
  click showed a stale preview and nearly became a second bug report; the answer landed at
  7.8 s. Wait for the answer, not for a guess about how long it takes.
- **Tests and scripts must not write where the user lives.** The material library and the
  engine's layer list are keyed to the kernel name, not to the profile, so `-P/--profile`
  does not isolate them. `api/tests/conftest.py` has autouse fixtures that fence both off;
  do not remove them. A script that measures the app may only press what it measures.

## The handbook moves with the screen

Whoever changes a feature updates its page **in the same commit**. A page that is a week
behind is worse than no page, because the reader trusts it. `frontend/tests/docs.test.ts`
checks that every screenshot a page names exists, that every sentence a page quotes is in
`en.ts` word for word, and that every action and window is named somewhere.

Screenshots are refreshed with `node gauntlet/docs-shots.mjs` (see
`frontend/gauntlet/README.md`); each shot seeds its own state through the API, so a rerun
gives the same picture.

## Engine findings, measured

The engine is good and it has bugs, and a few of its limits shape our code. Each row below
was measured on this project's working copy (MeerK40t 0.9.9040, Python 3.14) and is worked
around **in our layer**, never in `meerk40t/`. Comments in the code point here by name.
Generic fixes belong upstream as pull requests, not in this repository.

| What | Where | What goes wrong, and what we do |
|---|---|---|
| **The rasteriser lives in the wxPython GUI** | `gui/plugin.py:79` registers `render-op/make_raster`; `core/node/op_raster.py:468` looks it up | Headless it is absent, and then `OpRasterNode.preprocess` takes the `strip_rasters` branch: the layer **removes its own children** and yields no cutcode. Measured: a design with nine raster layers estimated 0.0 s over 0 parts. So every raster engraving would come out of the machine blank. `api/openkerf_api/rasterizer.py` registers a Pillow rasteriser from our plugin, and only if nothing else has — with the GUI running, theirs wins. After it: 323.5 s over 1 part for a filled 60×40 mm area. |
| **`Geomstr.Clip` drops arcs** | `core/geomstr.py:5784` ([#3262](https://github.com/meerk40t/meerk40t/issues/3262)), `:6088` ([#3263](https://github.com/meerk40t/meerk40t/issues/3263)) | `_arc_position` recurses on the whole array instead of the row, so asking for midpoints in one go — which `Clip.inside` does — raises `RecursionError` on two or more arcs. And `split` has no arc branch, so `polycut` loses a quarter of a circle that does not even cross the boundary. Upstream's own test only clips lines. We clip ourselves in `api/openkerf_api/tiling.py`: `clip_geometry` against a rectangle, `clip_to_outline` against a shape, splitting on the parameter so an arc stays an arc. |
| **Undo steps back two edits, and does nothing at all once the stack is full** | `core/undos.py:140` vs `:258` ([#3258](https://github.com/meerk40t/meerk40t/issues/3258)) | The stack keeps the state *before* each change but `undo()` restores `_undo_index - 1`, one too far; and it computes its target *before* calling `validate()`, which shifts every index when the stack overflows. Measured: after 25 changes, deleting a shape and pressing undo left it deleted. `edits.py` computes the target itself and calls `validate()` first. |
| **A job never reaches 100% and stays in the queue** | `core/laserjob.py` (`calc_steps` vs `execute`) | `calc_steps` counts one step more than `execute` runs — measured 576/577 — so progress tops out at 0.998 and the job sits as `Waiting`. Our UI would read a finished job as stalled, which is the one thing you must not show under a job that is done. |
| **The chosen machine only survives a tidy shutdown** | `device/basedevice.py:322` writes `activated_device` at `preshutdown` | Kill a headless engine and it restarts on `lhystudios` — a K40 driver where a Ruida belongs. Measured: choose the machine, restart, active device is the stand-in. `machines.py:_remember_active` writes the same key at the moment of activation. |
| **`-P/--profile` is parsed and never used** | `main.py:107` defines it; `:227-230` passes `APPLICATION_NAME` as the profile | Every instance writes the same `MeerK40t.cfg`, silently. For us that meant parallel test servers seeing each other's machines, and `-X` wiping the config of every other instance. What *does* isolate: a port of its own and `openkerf -l <path>`. |
| **The library and the layer list are keyed to the kernel name** | `library.default_path`; `core/elements/elements.py:764` | Neither `-P` nor `ignore_settings` reaches them, so a test kernel reads and writes the developer's real files. Measured: twelve `ApiServer(kernel)` calls in seven test files opened the real library; one run of the test-grid tests took the real `operations.cfg` from 3 sections to 20. Two autouse fixtures in `api/tests/conftest.py` fence both off. Do not remove them. |
| **Every pass becomes an extra layer in an RD file** | `core/cutplan.py` (`_blob_convert`) → `ruida/rdjob.py:1434` | In copy mode — which Ruida needs, since its driver never reads `cutobject.passes` — each pass gets its own settings dict, and the RD writer groups layers by that dict's identity. Measured on the real stream: a 4-cell board went from 4 layers to 8 with two passes; a 16-cell board from 17 to 33, and then the controller says "file invalid" and stands still. `CommandRunner._share_pass_settings` lets the copies share one dict after `blob`. |
| **`save_job` writes a 4-byte file** | `ruida/device.py:603` → `ruida/rdjob.py:627` | The driver's commands land in the RDJob's own buffer, and that buffer is only drained when the RDJob itself is executed. `save_job` redirects `controller.write` to a file and never runs it. Measured on a 40×20 mm rectangle in a cut layer: 4 bytes through `controller.write`, 623 still in the buffer — a complete job, ending in `SET_FILE_SUM` and `END_OF_FILE`. |
| **A Ruida cannot be handed a job to keep in memory** | `ruida/rdjob.py:2030` | `document_file_upload` exists and has **no callers** anywhere in the engine — the opcodes are there, the conversation is not. So "send the file, start it from the panel" is not available. |
| **The Ruida's send thread writes on a closed connection** | `ruida/controller.py:128` | `_data_sender` drains its queue without checking the session, so a connection lost with data still queued kills the thread with `ConnectionError` in the user's log. `ApiServer.stop()` waits up to 2 s for the controller to go idle, which removes the occasion rather than the cause. |
| **The coolant method "popup" blocks the laser thread on stdin** | `extra/coolant.py:275` → `kernel/kernel.py:4217` | Outside the wxPython GUI `kernel.yesno` is a plain `input()`. On a Ruida `popup` is the only claimable method, so setting air assist puts `coolant_on` in the plan and the spooler thread waits for a key nobody presses. `Drawing.LOZE_COOLANTS` refuses it. |
| **`copy(op_node)` gives a layer with no children** | `core/node/` | Measured: one child before the copy, none after. A copied layer in a plan burns nothing, and you find that out on material. Putting the same node in the plan list twice does work — `blob` makes fresh cutcode per place — and that is the route our Z-step-per-pass uses. |
| **Copied shapes keep the original's bounding box** | `core/elements/grid.py:240,360`; `core/elements/clipboard.py:127` | `copy(node)` followed by a raw `matrix *=` tells the node nothing, so `bounds` points at the old place while `as_geometry()` gives the new one: you click a copy, it gets its selection frame, and the handles appear around the original. We ask the nodes to forget their bounds (`generators.py:_recalculate_bounds`, `drawing.py:clipboard_paste`). |
| **`rotate <angle> --absolute` turns the wrong way** | `core/elements/shapes.py:2160` | The branch computes `start - target` where `target - start` is meant, so every call doubles the angle: 60° → `rotate 0deg -a` → 120° → 240°. Measured over four steps: `new = 2·old − target`. `edits.py` works out the difference itself. |
| **`subpath` leaves a reference to a path that is gone** | `core/elements/branches.py:1927` | The original is replaced by a group, and every operation that referred to it keeps referring — to a node no longer in the tree. Measured: an engrave layer with one child had three after splitting, so it would burn the whole path *and* the pieces. `DesignEditor._drop_dead_references()` after every split. |
| **`linetext` inherits the last font anybody chose** | `extra/hershey.py:895`, set at `:487` | Without `-f` it falls back to `context.last_font`, and *every* text placement writes that setting. Choose a font once and every caption on every test board after it is in that font — found with a test grid in Apple Chancery. We pass an explicit font and put `last_font` back. |
| **A counter runs on every read** | `extra/hershey.py:355` vs `core/wordlist.py:584` | `update_linetext` translates with the default `increment=True`, while its callers use `increment=False` to decide whether anything changed. Measured with a counter at 1: placing the text put it at 2, and every re-render gave 3, 4, 5. A counter is therefore incompatible with an app that shows what will burn before it burns; our numbers come from a column instead. |
| **A clock in the design eats the undo stack** | `extra/hershey.py:389` | Every re-render ends in `node.altered()`, which pushes a state. `{time}` changes per second, so "is this stale?" is always yes: measured, one `Element altered` per second in an app where nobody is doing anything, and with `Undo.levels` = 20, forty seconds of idling pushes out the user's last twenty real edits. We only ask texts that really read from a list. |
| **The CSV reader refuses any Dutch Excel export** | `core/wordlist.py:809` → `extra/encode_detect.py:17` | `ENCODING_CP1252` is declared and returned from no branch, so a file with semicolons and an accent — exactly what a Dutch Excel writes — loads as `(0, 0, [])` with the only explanation on a channel no screen shows. Its delimiter is sniffed rather than counted (a one-column list of numbers crashes on `bad delimiter value`), one quotation mark anywhere throws the whole file away, and `has_header` is a silent coin flip. We read the rows ourselves in `series.py`. |
| **`{name# +1}` means something other than `{name#+1}`** | `core/wordlist.py:526-533` | The branch tests `startswith("+")` on the unstripped string and then calls `int()`, which strips. One space turns a relative step into an absolute row, and nothing says so. Measured on five names with the pointer on row 3: `{name#+1}` → the next row, `{name# +1}` → row 2, always. `series.placeholders()` reproduces the quirk deliberately, because a preview that reads it differently from the burn is worse than no preview. |
| **An offset past the end burns its own syntax** | `core/wordlist.py:597`, `:263-269` | Beyond the last row the placeholder is simply left in place and rendered as text: `{name#+9}` comes out as those nine characters, at cutting power. Below the first row `fetch_value` counts into the row's own header fields. `series.OverrunMutator` takes the places with no row out of the plan. |
| **A text with no geometry makes a project file unreadable** | `extra/hershey.py` writes it; `core/svg_io.py:981` reads it back | A text whose whole content is a placeholder renders nothing, is written as `<path d="">`, and comes back as an `elem point` with `nan` bounds and no `mk` attributes. `nan` is not JSON, so our snapshot answered **500** and the canvas could not be drawn at all — with the shape at fault unreachable. `design.py:_finite()` turns such a box into `null` and flags the element `broken`. |
| **A Dots layer takes only points, silently** | `core/node/op_dots.py:24` | `_allowed_elements` is `("elem point",)` and `add_reference` drops anything else without a word. That is correct, but it means our layer has to say it: `edits.assign` checks afterwards and refuses with a sentence, and a layer holding shapes will not change into Dots at all. |
| **`*N` bridges spread over the perimeter, not the sides** | `fill/fills.py:563-575` | `"*4"` puts the tabs at 12.5/37.5/62.5/87.5 % of the *path length*. On a 100.2×36.4 mm rim the second lands 2.25 mm past a corner, with the edge of a 2 mm tab 1.25 mm from it — the weakest possible bridge in the corner of the tile you wanted to keep. `testgrid._side_middles` computes the four side middles instead. |
| **An `op engrave` never looks at `fill`** | `core/node/op_engrave.py:358+` | Not a bug, but the limit that decides a design: filled squares in an engrave layer come out as outlines, one per square, and no scanner reads that. The board code is therefore a raster layer at a fixed dpi. |
| **`image brightness` never does anything** | `image/imagetools.py:1228` | It reads its factor as `args[1]`, which is the command name, so every call lands in the `except` and prints the usage line. `contrast` and `sharpness` beside it do it correctly. |
| **`path "<d>"` scales the d-string** | `core/elements/` | A `d` in Tats comes out about 725× too large. To place a path in real units, hang a `Geomstr` on `elem_branch` directly. |
| **The grbl mock swallows every other move** | `grbl/mock_connection.py` + `grbl/controller.py` | With `interface = mock` the first move lands and the next snaps the position back to home, strictly alternating; after a few commands nothing moves at all. Usable to see whether a command arrives, not to replay a sequence of moves. |
| **The font list remembers files that are gone** | `extra/hershey.py` | The list is built once and refreshed on request, so a deleted typeface stays in it. Our picker showed the row, fetched the file for a preview and got a 409. `drawing.fonts` drops rows whose absolute path does not exist — only absolute ones, because the engine's own Hershey fonts are listed as bare names. |
| **The Ruida's connection lifecycle is unpredictable from outside** | `ruida/device.py:448,460` → `ruida/ruidasession.py` | Measured on a real KH-5030 over UDP, three ways: a fresh server connects and reports the head's position; after disconnecting, every further attempt fails silently (three of three, `ruida_connect` swallows its own error); and on a server with the app attached the connection reopens **by itself** within about 6 s. What reopens it was not found. So the button reports the state the engine gives and promises nothing about what comes after. |

Not the engine's bugs, but worth knowing:

- **`segno.make` returns a Micro QR for a short payload, and no scanner reads it.**
  Measured: `make("OK1:7X4MQB2K", error="m")` gives `M4-Q`, and both OpenCV detectors read
  nothing off a clean render; `make_qr` gives `1-Q` and both read it. Use `make_qr`.
- **Which OpenCV detector you pick matters more than the resolution, on a photograph.**
  On synthetic board photographs (5° rotation, blur, noise, JPEG 85) the plain
  `QRCodeDetector` read 1 of 10 where `QRCodeDetectorAruco().detectAndDecodeMulti` read
  9 of 10. Without the photograph the order reverses, so measure with noise and
  compression or you are measuring a render.

## Safety

This drives a laser. Never start a job to test something; never move the head to see if a
route works. The pre-flight, the estimate and the cut-path window all exist so that a
mistake is found before the material is in the machine, and none of them touch the machine.
