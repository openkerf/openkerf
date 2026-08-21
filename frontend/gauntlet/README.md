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
| `i-shots.mjs` | the screenshot set per language: `node gauntlet/i-shots.mjs en\|nl` → `screenshots/i18n/<language>/` |
| `i-overflow.mjs` | measures text that does not fit its box, per language. Elements that clip by design are listed in the script itself |
| `docs-shots.mjs` | the pictures for the handbook: `node gauntlet/docs-shots.mjs [name-fragment]` → `docs/images/`. English, light theme, desktop 1440×900 and phone 390×844. Seeds its own drawing through the API, so a rerun gives the same picture; it does not start the laser, so there is no shot of the queue |
| `selftest.mjs` | checks the checker: injects a contrast that is too low and fails if the measurement does not find it |
| `i-apply.py` | moves a batch of literals out of a component into the catalogues (used for the English conversion; kept for the next language) |

The one-off scripts of the earlier usability and accessibility rounds are gone.
They asked for Dutch selectors and Dutch button labels that no longer exist, so
they measured nothing; what they found is in `CLAUDE.md`, in the commits of those
rounds, and in `screenshots/`.
