# Desktop UI gauntlet

Use a disposable server, never the working installation. The shared guard refuses
origins other than loopback port 8092 and requires the scratch server marker.
The bootstrap loads only the dummy driver and puts kernel configuration, operations,
library and projects in a fresh temporary directory. `-P`, `-X`, or a separate port
alone do not isolate MeerK40t data.

From the repository root, using an environment with the app and engine dependencies:

```sh
rtk proxy npm --prefix frontend run build
rtk proxy env PYTHONPATH=api python frontend/gauntlet/scratch_server.py
```

In another terminal:

```sh
rtk proxy node frontend/gauntlet/seed.mjs
rtk proxy node --test frontend/gauntlet/scratch.test.mjs
rtk proxy env PYTHONPATH=api python -m unittest discover -s frontend/gauntlet -p test_scratch_server.py
```

Open http://127.0.0.1:8092. The server prints its disposable storage directory.
Use `OPENKERF_API=http://127.0.0.1:8092` if serving the frontend separately with Vite;
the browser target for the guarded scripts remains 8092. Stop the server normally
after the run. Do not copy the scratch configuration into the real installation.

## Simulated machine states

`POST /api/gauntlet/state` accepts `connection` (`connected`, `disconnected`,
`unknown`) and `phase` (`idle`, `queued`, `running`, `paused`, `done`). It changes
only the status payload, including the WebSocket; no engine job is queued.
The scratch capabilities expose controls for visual inspection. Execution and
machine-command routes return 409 instead of performing the action. The UI is
clearly labelled as a simulated device. These fixtures do not validate hardware.

```sh
rtk proxy curl -fsS -X POST http://127.0.0.1:8092/api/gauntlet/state \
  -H 'Content-Type: application/json' -d '{"connection":"connected","phase":"paused"}'
```

## Existing tools

| Tool | Purpose |
| --- | --- |
| `scratch_server.py`, `scratch.mjs` | Disposable backend and fail-closed target check |
| `seed.mjs` | Deterministic drawing and layers using guarded API calls |
| `harness.mjs` | Shared readiness, browser contexts, geometry survey and failing report |
| `i-shots.mjs`, `i-overflow.mjs` | Language screenshots and text-fit inspection |
| `preview-check.mjs` | Cut-path layout and focus inspection |
| `docs-library.mjs`, `docs-shots.mjs` | Handbook fixtures/images; additional scenario prerequisites still apply |
| `selftest.mjs` | Legacy measurement self-check; not a substitute for independent visual review |

Legacy handbook scenarios that require a real Ruida profile will refuse the dummy
fixture. Do not bypass the guard or activate a user's profile to make them pass.
Extend the disposable fixture or report the scenario as blocked. Missing controls,
failed readiness and API failures are failures, not evidence of a clean screen.
Documentation helpers that dismiss prompts are unsuitable for warning-state review.

## Emulated Ruida (handbook pictures)

```sh
rtk proxy env PYTHONPATH=api python frontend/gauntlet/scratch_server.py --ruida-emulator
OK_SCRATCH_LIBRARY=1 node frontend/gauntlet/docs-library.mjs   # the handbook's library
node frontend/gauntlet/docs-shots.mjs
```

Instead of the dummy, the scratch storage gets one Ruida at path `ruida`, labelled
"KH-5030 (emulated)", bed 500 × 300 mm, address 127.0.0.1, active and connected at
start — so `docs-shots.mjs`' machine guard passes. Its line is OpenKerf's own
(`RuidaLink`), to MeerK40t's emulator behind a UDP socket (`api/tests/ruida_peer.py`,
imported from there) on 127.0.0.1 at a free port, passed through
`OPENKERF_RUIDA_SEND_PORT`/`OPENKERF_RUIDA_LISTEN_PORT`. The emulator hands what it
decodes to a stand-in device that runs nothing. The marker gains
`"emulator": {"ruida": "127.0.0.1:<port>"}` and stays `hardware: false`. The machine
network scan never probes the network in either mode (USB and serial only).

`/api/status` and `/api/capabilities` are the real ones; `POST /api/gauntlet/state`
drives the emulator and answers once the line reads the new state back
(`settled`, `reading`, `machine_state`):

| Field | Values | What the emulator does |
| --- | --- | --- |
| `connection` | `connected` | answers again; reconnects the link if it was let go |
| | `connecting` | stops answering on a live line: the session probes on its own |
| | `disconnected` | stops answering and reconnects: the link gives up after 3 s with its own sentence |
| `phase` | `idle`, `running`, `paused` | status word from `peer.state` (idle, busy, hold) |
| | `moving` | the KH-5030's measured moving word (16975360) |
| `second_client` | `true`/`false` | loses 2 of every 5 status answers; "Connected, but not alone" after ~7 s, clears in ~5 s |
| `z_step` | `true`/`false` | as in dummy mode |

There is no `queued`/`done` here: a job phase needs a job on the line, and
execution and machine-command routes (`/api/machine/*` including connect,
`/api/job/*`, burns, `/api/series/start`) still return 409. Shot 37 (series run)
therefore stops `docs-shots.mjs`; run the shots after it by name.

## Review evidence

Use the authorised browser-control tool for actual browser interaction in an agent
session. Capture complete screens at 1440×900, dense states at 1366×768, and a wide
canvas check at 1920×1080. Check Dutch and English labels for regressions. Record
revision, fixture, CSS viewport, language and exact steps.

The engineer supplies before/after images. A separate senior reviewer must open
those actual images and record observations, then check relevant interactions and
siblings. Merely making screenshots or passing source tests is not visual approval.
Each finding has at most three implementation/review attempts. Unresolved failures
remain visible; do not reset finding IDs or call skipped coverage passed.

Process notes, the finding ledger and images belong in the private `workshop/`
repository. User-facing handbook images belong in `docs/images/` when updated.

### Focus and alarm fixtures

`POST /api/gauntlet/state` also accepts `{"z_step":true}` (default false).
Reload the page after changing it so design capabilities refresh. This reveals
Focus test and the layer Z-step settings; generation remains dummy-only and all
execution routes stay blocked. Restore with `{"z_step":false}`.

With a browser connected, `POST /api/gauntlet/alarm` with
`{"kind":"usb_missing"}` emits a simulated USB alarm over the existing WebSocket.
`{"kind":"usb_recovered"}` clears it. These are fixed display events, never
kernel or driver signals. The existing notification preference remains in charge
of desktop notifications; the fixture does not request permission.

These additions require the next scratch server start; editing this file does not
modify an already running process. Camera imagery is not simulated: the bootstrap
loads no camera plugin, so camera calibration remains unavailable without a
separate safe image fixture. Do not enable a real camera to fill this coverage gap.
