# Running OpenKerf in Docker — design

*4 September 2026. Agreed in conversation; the implementation plan follows from this.*

## Purpose

OpenKerf is deployed by hand today: a Python venv, a Node build, and a command line
that has to be typed right. The goal is a `compose.yml` that a person copies onto a
Linux box in the same LAN as the laser, fills a token into, and starts. Nothing else
to install, nothing to build. The first machine in mind is a NAS, a mini-pc or a
Raspberry Pi next to a Ruida-controlled CO₂ laser, with a USB camera over the bed.

## Decisions

| Question | Decision | Why |
|---|---|---|
| Where does it live | In this repository, under `deploy/`, with the workflow in `.github/workflows/` | The image is built from the source, so the Dockerfile belongs beside it. One commit changes code, image and compose together, and the handbook page moves on the same rule as the rest. A separate repository would hold only a compose file and a readme, and two repositories that must stay in step is the "route without a caller" problem across a repo boundary. |
| How a user gets the image | Prebuilt on GHCR, `ghcr.io/openkerf/openkerf`, for `linux/amd64` and `linux/arm64` | The user needs neither Node nor Python. arm64 is the Pi. |
| Network | `network_mode: host` | The Ruida listens on UDP 50200 and answers from 40200, and machine discovery is a broadcast. Neither crosses a Docker bridge reliably. Host networking makes the container behave like a normal installation. Consequence: no `ports:` mapping; the app listens on the host directly. |
| Camera | OpenCV in the default image; `/dev/video0` passed through in compose | Passthrough without OpenCV gives a polite refusal and nothing else. `opencv-python-headless` has wheels for both architectures, so one image does everything. No second tag. |
| Laser over USB | Out of scope; a commented `devices:` block only | Not the machine this is written for. One line to enable later. |
| Token | Required. The container refuses to start without `OPENKERF_TOKEN` | Bound to `0.0.0.0` the API demands a token for writes. A generated token would only exist in the log, which nobody reads on a NAS. A refusal with a sentence is better than a running app nobody can use. |
| State | One named volume on `/data`, with `HOME=/data` | On Linux the engine writes to `~/.config/MeerK40t`; the library, the layer list and the autosave sit beside it. Setting `HOME` moves all of it into the volume without touching the engine. |
| Runs as | Non-root user `openkerf`, in group `video` | The camera device is `root:video` on every common distribution. |

The engine is installed from upstream git at a pinned revision (`5f68a45` as of this
writing, the `MEERK40T_REV` build argument), not from PyPI: no PyPI release contains
modules this code imports, and against PyPI 0.9.9100, 193 of 1625 API tests fail. This
means the version constraint in `api/pyproject.toml` and the pinned SHA in
`deploy/Dockerfile` are two places that move together — bumping one without checking the
other reintroduces the gap.

## The image (`deploy/Dockerfile`)

Two stages.

1. **`node:24-alpine`** — `npm ci` and `npm run build` in `frontend/`. Output is the
   static build (adapter-static, `index.html` fallback).
2. **`python:3.13-slim`** — `pip install ./api[camera]` plus the engine's non-GUI
   requirements (Pillow, numpy, pyusb, pyserial, ezdxf). MeerK40t arrives as the pinned
   PyPI dependency from `api/pyproject.toml`; that file remains the only place the
   engine version is written. No wxPython. The frontend build is copied to
   `/app/frontend`.

The final image:

- creates user `openkerf` (uid 1000) in group `video`, `HOME=/data`, `/data` owned by it;
- declares `VOLUME /data` and `EXPOSE 8080` (documentation only under host networking);
- carries `org.opencontainers.image.revision` and `.version` labels from build args;
- `HEALTHCHECK` on `GET http://127.0.0.1:${OPENKERF_PORT}/api/health` via Python's
  `urllib`, so no curl in the image;
- `ENTRYPOINT ["/app/entrypoint.sh"]`.

`deploy/entrypoint.sh` reads `OPENKERF_PORT` (default 8080), `OPENKERF_BIND` (default
`0.0.0.0`) and `OPENKERF_TOKEN` (no default). Without a token it prints one sentence
saying which variable is missing and how to make one, and exits 1. With one it runs:

```
exec meerk40t --no-gui -d -e ".openkerf -p $PORT -b $BIND -f /app/frontend -t $TOKEN"
```

`exec` makes the engine PID 1, so Docker's stop signal reaches it directly — a shell in
between would swallow it and Docker would SIGKILL after its 10 s grace period instead.
The engine has no handler for that signal, so a stop is still abrupt; nothing runs the
engine's own quit. Little is lost even so, since the autosave writes every 5 s and
settings are written at the moment they change. A real handler is follow-up work. The
leading `.` silences the console echo of the command line, so the token passed with `-t`
does not end up a second time in `docker logs`.

## Compose (`deploy/compose.yml`, `deploy/.env.example`)

One service:

```yaml
services:
  openkerf:
    image: ghcr.io/openkerf/openkerf:latest
    network_mode: host
    restart: unless-stopped
    env_file: .env
    volumes:
      - openkerf-data:/data
    devices:
      - /dev/video0:/dev/video0     # the bed camera; see the handbook for finding the right node
    # For a laser on USB (K40 and the like) — not tested in this version:
    # devices:
    #   - /dev/bus/usb:/dev/bus/usb
volumes:
  openkerf-data:
```

`.env.example`:

```
OPENKERF_TOKEN=          # required; e.g. openssl rand -base64 24
OPENKERF_PORT=8080
OPENKERF_BIND=0.0.0.0
```

## CI (`.github/workflows/image.yml`)

Triggers: push to `main`, tags `v*`, pull requests.

1. Checkout, QEMU, Buildx, login to GHCR (not on pull requests).
2. `docker/build-push-action` for `linux/amd64,linux/arm64`, push only when not a PR.
   Tags: `latest` on main, `sha-<short>` always, the version on a `v*` tag. Build args
   carry the commit and version into the labels.
3. **Smoke test**, on the amd64 image loaded locally, before anything is pushed:
   - start with `OPENKERF_TOKEN=smoke`, wait for the container to report healthy
     (bounded at 60 s);
   - `GET /api/health` is JSON; `GET /` is HTML that references `_app/immutable/`, the asset path
     SvelteKit's static adapter emits, proving the frontend build is inside the image;
   - `docker run --rm <image> python -c "import cv2"` succeeds;
   - start once **without** a token and assert exit code 1 and the sentence.
   The arm64 image is verified only for `import cv2`, under QEMU, because starting the
   engine under emulation is slow and proves nothing the amd64 run does not.

A failing smoke test fails the workflow, so `latest` never points at an image with no
frontend or no camera.

## What is measured before the first commit lands

Numbers go into the handbook page, not guesses:

- image size on disk, both architectures;
- time from `docker compose up` to `healthy`, on the developer's machine;
- that after `docker compose restart` the chosen machine, one library preset and the
  layer list are still there (the `/data` volume does its job);
- that with no `/dev/video0` present the camera reports its refusal and the rest of
  the app runs.

## Handbook (`docs/running-in-docker.md`)

A page for the person with the NAS: the compose file, the three variables, where the
data lives and how to back it up (`docker run --rm -v openkerf-data:/data ...`), how to
find the camera node (`ls /dev/video*`; a Pi camera often gives two nodes, the even one
works), how to update (`docker compose pull && docker compose up -d`), and the two
limits stated plainly: on Docker Desktop (Mac, Windows) there is no host networking, so
machine discovery does not work and the Ruida must be given its address by hand; and a
laser on USB is not covered in this version. Linked from `docs/README.md` and from
`README.md` under "Running it". `frontend/tests/docs.test.ts` keeps passing because the
page quotes no interface sentences and names no screenshots.

## Out of scope

A reverse proxy with TLS, Kubernetes manifests, a Home Assistant add-on, the
`meerk40t/` working copy in the checkout (the image never sees it), USB laser
controllers beyond the commented block, and a second image variant without OpenCV.
