# CLAUDE.md — working on OpenKerf

House rules for this codebase. They are short because each one cost something to learn;
the reasoning behind them, and the measurements, are in the working record (a separate
private repository — ask if you need it).

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

## The engine has bugs, and we work around them here

A dozen or so, each one measured, each one worked around in our layer with a comment
naming the file and line in the engine — search for `upstream` in `api/openkerf_api/`. Two
that matter for anything you build on top:

- **The rasteriser lives in the wxPython GUI.** Headless, a raster layer would burn
  nothing, so `api/openkerf_api/rasterizer.py` registers a Pillow one — but only if
  nothing else has.
- **`geomstr.Clip` drops arcs.** Ours clips in `api/openkerf_api/tiling.py`:
  `clip_geometry` for a rectangle, `clip_to_outline` for a shape.

Generic fixes go upstream as pull requests, not into this repository.

## Safety

This drives a laser. Never start a job to test something; never move the head to see if a
route works. The pre-flight, the estimate and the cut-path window all exist so that a
mistake is found before the material is in the machine, and none of them touch the machine.
