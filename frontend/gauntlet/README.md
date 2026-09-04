# gauntlet

Scripts that look at the running app and measure it, instead of trusting that it
looks fine. They need a browser (`playwright`) and a running OpenKerf.

```bash
# the engine plus our API
meerk40t/.venv/bin/meerk40t --no-gui -d -e "openkerf -p 8090"
# and, while developing, the dev server that serves the current source
cd frontend && npx vite dev --port 8090   # then use OK_BASE=http://localhost:8090
```

Every script takes its origin from `OK_BASE` and falls back to
`http://127.0.0.1:8090`.

| Script | What it does |
|---|---|
| `harness.mjs` | shared: browser, themes, widths, a clean slate, `survey()` for boxes and computed styles, `report()` for findings |
| `seed.mjs` | puts a design with four layers, work in each of them and two awkward states (no burn along, passes) on the bed. Pure API, so it survives interface changes |
| `i-shots.mjs` | the screenshot set per language: `node gauntlet/i-shots.mjs en\|nl` → `workshop/screenshots/i18n/<language>/` |
| `i-overflow.mjs` | measures text that does not fit its box, per language. Elements that clip by design are listed in the script itself. Twelve screens, the material library among them — that is where the offer of starting settings lives, and its sentences are the longest in the app |
| `docs-shots.mjs` | the pictures for the handbook: `node gauntlet/docs-shots.mjs [name-fragment]` → `docs/images/`. English, light theme, desktop 1440×900 and phone 390×844. Seeds its own drawing through the API, so a rerun gives the same picture; it does not start the laser, so there is no shot of the queue. Refuses to run against an engine that shares the layer list — see below |
| `preview-check.mjs` | the cut-path window, measured: overlapping numbers, the reachable end of the scrubber, the false "server is away" on the way in, what lies over the drawing, and where Tab goes. What of it fits in a test is in `tests/cutpath-window.test.ts`; the stacking and the focus ring are here |
| `selftest.mjs` | checks the checker: injects a contrast that is too low and fails if the measurement does not find it |
| `i-apply.py` | moves a batch of literals out of a component into the catalogues (used for the English conversion; kept for the next language) |

One trap worth knowing before you write another script. The offer of starting
settings carries a **Not now** of its own, and pressing it writes
`starter_state = 'dismissed'` on the machine that is active — so a script that
clears banners by pressing whatever says "Not now" takes the offer away from the
reader's real library and then measures the empty space. Both scripts here
exclude it with `button:not(.away)`; `tests/starter.test.ts` keeps them honest.
And point a scratch server at its own database (`openkerf -l <path>`) before you
let anything press a button: `machine-name.test.ts` really does create machines,
and it does not clean them up.

The one-off scripts of the earlier usability and accessibility rounds are gone.
They asked for Dutch selectors and Dutch button labels that no longer exist, so
they measured nothing; what they found is in `CLAUDE.md`, in the commits of those
rounds, and in `workshop/screenshots/` — the working record, a private repository
of its own that hangs in this one as `workshop/`.

## The library the handbook's pictures are of

`docs-library.mjs` writes it: twenty materials, presets of all four kinds, and a test
grid with two presets picked off it. Until this round the library screenshots were taken
against whoever ran `docs-shots.mjs` — the pictures showed the author's own materials —
and that only came out when the words in the app changed and they had to be taken again.

```bash
# an engine with a library and a layer list of its own; -P/--profile isolates neither,
# the two paths do
meerk40t --no-gui -d -e "openkerf -p 8092 -l /tmp/docs/lib/library.db \
                                  -o /tmp/docs/lib/operations.cfg -f frontend/build"
cd frontend
OK_SCRATCH_LIBRARY=1 OK_BASE=http://127.0.0.1:8092 node gauntlet/docs-library.mjs
OK_SCRATCH_LIBRARY=1 OK_BASE=http://127.0.0.1:8092 node gauntlet/docs-shots.mjs
```

## The layer list is the second file that is not yours

`-l` fences off the library; `-o` fences off the engine's layer list, and until this
round only the first of the two existed. Both are keyed to the **kernel name** and not
to the profile, so without them a screenshot run reads and writes the files of the app
you actually work in.

What that cost, measured: the pre-flight picture came back with a fourth layer reading
"Engrave, 20 mm/s, 100%" where the seeding asks for "Logo area, 300 mm/s, 30%", and 1:19
on the clock had become 2:22. Nothing in the script put that layer there — it comes from
the `[_default …]` sections of the developer's own `operations.cfg`, which is the set
the engine files a new shape under when its colour has no layer yet.

`docs-shots.mjs` therefore asks `/api/health` first and refuses unless it answers
`"operations": "own"`. With the fence in place, and measured: two runs of the same shot
differed in 41 of 1,296,000 pixels — all of them in the animation in the top bar — three
runs after that were identical to one another, and the real `operations.cfg` came through
a full run and a tidy shutdown byte for byte identical.

The same run also showed the script's own half of the fault. `seed()` took its layers
from the *positions* in the list after the drawing was done, and the engine makes a layer
of its own for a colour it has none for — so `ops[3]` was an engine-made engrave layer,
the QR code went into it, and "Logo area" was pruned away empty. It now keeps the ids the
four layers came back with.

Two locks keep it off a real library: the flag, and a library that has to be empty. It
makes no machine — that list lives in one `MeerK40t.cfg` for every instance, so creating
one would put a machine in yours — and it expects the handbook's KH-5030 to be there.

`docs-shots.mjs` expects the same machine and, since this round, will not *make* it so
either: it used to activate the Ruida when it found another machine active, and that is a
write in the one file neither `-l` nor `-o` can fence off. Measured, with the KH-5030
already active: a whole run leaves `MeerK40t.cfg` byte for byte identical. Measured with
`lihuiyu-device` active instead: the run wrote `activated_device = ruida` at once — taking
a photograph changed which laser the reader's own app opens on. Putting it back is not
enough either, and that is measured too: after the Ruida was activated again, `[space]`
still held the K40's 310 × 210 mm bed where the Ruida's 500 × 300 belongs. So the script
asks and refuses, and activating the right machine is a thing you do yourself.

Three things worth knowing before you run it:

- **A row that says it was measured needs a board behind it.** Give a preset
  `source: 'testraster'` without one and the provenance panel says so ("no test grid
  hangs off it"), and the picture of that panel is then a picture of a fault. The seeder
  picks squares off a real grid instead.
- **Shot 15 needs a preset in the library**, and takes it from what this seeds. Before,
  it depended on a row shot 41 makes later, so on an empty library the run stopped there.
- **The set can trip over its own dialogs.** Measured on one run: shot 39 could not click
  the tool rail because the window from shot 38 was still open and its backdrop swallowed
  the click. Taking the last few by name (`node gauntlet/docs-shots.mjs 39`) gets round it.
