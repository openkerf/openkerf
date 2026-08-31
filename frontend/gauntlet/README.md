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
| `docs-shots.mjs` | the pictures for the handbook: `node gauntlet/docs-shots.mjs [name-fragment]` → `docs/images/`. English, light theme, desktop 1440×900 and phone 390×844. Seeds its own drawing through the API, so a rerun gives the same picture; it does not start the laser, so there is no shot of the queue |
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
