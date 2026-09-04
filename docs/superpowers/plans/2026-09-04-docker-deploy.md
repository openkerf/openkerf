# Running OpenKerf in Docker — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One `compose.yml` that a person copies onto a Linux box beside the laser, fills a token into, and starts — with the frontend, the engine and the camera inside one prebuilt image.

**Architecture:** A two-stage Dockerfile under `deploy/` builds the SvelteKit frontend on Node and installs `api/` (which pins MeerK40t) on `python:3.13-slim`, then hands both to a shell entrypoint that runs the engine headless with our `openkerf` command. Compose runs that image on the host network with one volume on `/data` and the camera device passed through. A GitHub workflow builds it for amd64 and arm64, smoke-tests it, and pushes it to GHCR.

**Tech Stack:** Docker (multi-stage, Buildx, QEMU), Docker Compose, GitHub Actions (`docker/build-push-action`), GHCR, Python 3.13, Node 24, MeerK40t headless.

**Spec:** `docs/superpowers/specs/2026-09-04-docker-deploy-design.md`

## Global Constraints

- Nothing under `meerk40t/` is touched and the image never sees that directory. The engine comes from PyPI through the pin in `api/pyproject.toml` (`meerk40t>=0.9.9000,<0.10`), and that file stays the only place the engine version is written.
- Image name is `ghcr.io/openkerf/openkerf`; platforms `linux/amd64` and `linux/arm64`.
- The container runs as user `openkerf` (uid 1000), in group `video`, with `HOME=/data`.
- Environment variables: `OPENKERF_TOKEN` (required, no default), `OPENKERF_PORT` (default `8080`), `OPENKERF_BIND` (default `0.0.0.0`).
- Without `OPENKERF_TOKEN` the container exits 1 with one sentence saying what is missing and how to make one.
- OpenCV is in the default image via the existing extra `openkerf-api[camera]`; there is no second image variant.
- `network_mode: host`; no `ports:` mapping.
- Handbook pages must keep `frontend/tests/docs.test.ts` green: no double-quoted prose that is not a sentence from `en.ts` (use backticks for names and commands), every `.md` link resolves, no `images/...` references to files that do not exist.
- Numbers in the handbook page are measured, not guessed; a docstring or a page that names an unmeasured number is worse than one that says nothing.
- Never start a job or move the head to test anything. The smoke tests only read `/api/health` and `/`.
- Commit messages follow the repository's style: a plain sentence saying what changed, ending with the `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` trailer.
- Docker Desktop must be running for every step that builds or runs a container. If `docker info` fails, start it first and wait for `docker info` to succeed.

---

## File structure

| File | Responsibility |
|---|---|
| `.dockerignore` (repo root) | Keeps `meerk40t/`, `workshop/`, `node_modules/`, `.venv/`, `docs/`, tests and build output out of the build context. |
| `deploy/Dockerfile` | The two-stage build; the only place that knows how the frontend is built and the API installed. |
| `deploy/entrypoint.sh` | Reads the three environment variables, refuses without a token, `exec`s the engine. |
| `deploy/smoke.sh` | The test for the image: takes an image name, proves the frontend, the API, OpenCV and the token refusal. Used locally and by CI. |
| `deploy/compose.yml` | The one service, host network, volume, camera device, commented USB block. |
| `deploy/.env.example` | The three variables with comments. |
| `.github/workflows/image.yml` | Build, smoke test, push to GHCR. |
| `docs/running-in-docker.md` | The handbook page; `docs/README.md` and `README.md` link to it. |

---

### Task 1: The image, and the script that proves it

**Files:**
- Create: `.dockerignore`
- Create: `deploy/Dockerfile`
- Create: `deploy/entrypoint.sh`
- Create: `deploy/smoke.sh`

**Interfaces:**
- Produces: an image whose entrypoint honours `OPENKERF_TOKEN`, `OPENKERF_PORT`, `OPENKERF_BIND`; a script `deploy/smoke.sh <image>` that exits 0 when the image is sound and prints a numbered line per check. Task 3 calls `deploy/smoke.sh` unchanged.

- [ ] **Step 1: Write the failing test — `deploy/smoke.sh`**

```bash
#!/usr/bin/env bash
# Proves an OpenKerf image is sound, without touching any machine.
#
#   deploy/smoke.sh ghcr.io/openkerf/openkerf:latest
#
# Four checks, each one a claim the handbook makes: the API answers, the frontend build
# is inside the image, OpenCV imports, and a start without a token is refused with a
# sentence. Exits non-zero on the first failure. Uses port 18080 so a running OpenKerf
# on 8080 is left alone.
set -euo pipefail

IMAGE="${1:?usage: smoke.sh <image>}"
PORT=18080
NAME="openkerf-smoke-$$"

cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "1. a start without a token is refused"
set +e
out=$(docker run --rm -e OPENKERF_PORT=$PORT "$IMAGE" 2>&1)
code=$?
set -e
[ "$code" -eq 1 ] || { echo "   expected exit 1, got $code"; exit 1; }
grep -q "OPENKERF_TOKEN" <<<"$out" || { echo "   refusal does not name OPENKERF_TOKEN:"; echo "$out"; exit 1; }

echo "2. with a token the API answers on /api/health"
docker run -d --name "$NAME" -p 127.0.0.1:$PORT:$PORT \
  -e OPENKERF_TOKEN=smoke -e OPENKERF_PORT=$PORT "$IMAGE" >/dev/null
for i in $(seq 1 60); do
  if body=$(curl -fsS "http://127.0.0.1:$PORT/api/health" 2>/dev/null); then break; fi
  sleep 1
done
[ -n "${body:-}" ] || { echo "   no answer on /api/health after 60 s"; docker logs "$NAME"; exit 1; }
grep -q '"ok":true' <<<"$body" || { echo "   unexpected body: $body"; exit 1; }
echo "   healthy after ${i} s"

echo "3. the frontend build is inside the image"
page=$(curl -fsS "http://127.0.0.1:$PORT/")
grep -q "_app/immutable/" <<<"$page" || { echo "   / does not reference _app/immutable/"; exit 1; }

echo "4. OpenCV imports"
docker run --rm --entrypoint python "$IMAGE" -c "import cv2; print('   cv2', cv2.__version__)"

echo "ok"
```

Make it executable: `chmod +x deploy/smoke.sh`.

Note on check 2: the smoke test maps a port because it runs against a plain `docker run`, not compose. Compose in Task 2 uses host networking and needs no mapping.

- [ ] **Step 2: Run it and see it fail**

Run: `docker info >/dev/null && deploy/smoke.sh openkerf:dev`
Expected: fails at check 1 with `Unable to find image 'openkerf:dev'` (the image does not exist yet).

- [ ] **Step 3: Write `.dockerignore`**

```
# The engine's working copy is for exploration and tests; the image gets MeerK40t from PyPI.
meerk40t/
# The private working record.
workshop/
# Build products and dependency trees are made inside the build.
**/node_modules/
frontend/build/
frontend/.svelte-kit/
**/.venv/
**/__pycache__/
**/*.egg-info/
# Not needed to run.
docs/
api/tests/
frontend/tests/
frontend/gauntlet/
.git/
.github/
screenshots/
```

- [ ] **Step 4: Write `deploy/entrypoint.sh`**

```bash
#!/usr/bin/env sh
# Starts the MeerK40t engine headless with the OpenKerf API and the built frontend.
# Configuration comes from the environment, so compose and a plain `docker run` say the
# same thing.
set -eu

PORT="${OPENKERF_PORT:-8080}"
BIND="${OPENKERF_BIND:-0.0.0.0}"

if [ -z "${OPENKERF_TOKEN:-}" ]; then
  echo "OpenKerf will not start: OPENKERF_TOKEN is not set. Bound to ${BIND} the API needs a token for anything that changes the design or moves the machine; make one with 'openssl rand -base64 24' and put it in .env." >&2
  exit 1
fi

# `exec` so the engine is PID 1 and receives the stop signal from Docker: ApiServer.stop()
# then waits for the Ruida controller to go idle before the process ends.
exec meerk40t --no-gui --daemon \
  --execute "openkerf -p ${PORT} -b ${BIND} -f /app/frontend -t ${OPENKERF_TOKEN}"
```

Make it executable: `chmod +x deploy/entrypoint.sh`.

- [ ] **Step 5: Write `deploy/Dockerfile`**

```dockerfile
# syntax=docker/dockerfile:1
# OpenKerf: the MeerK40t engine headless, our API beside it, and the built frontend
# served from the same process. Build from the repository root:
#
#   docker build -f deploy/Dockerfile -t openkerf:dev .
#
# The engine comes from PyPI through the pin in api/pyproject.toml; the meerk40t/ working
# copy in the checkout is not part of the build context (see .dockerignore).

# ── Stage 1: the frontend ──────────────────────────────────────────────────────────────
FROM node:24-alpine AS frontend
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ── Stage 2: the engine and the API ─────────────────────────────────────────────────────
FROM python:3.13-slim
ARG REVISION=unknown
ARG VERSION=dev
LABEL org.opencontainers.image.title="OpenKerf" \
      org.opencontainers.image.source="https://github.com/openkerf/openkerf" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.licenses="MIT"

# libusb for pyusb (a laser on USB, later); libGL/glib for opencv-python-headless.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libusb-1.0-0 libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

# The engine's own non-GUI requirements that its PyPI package does not declare:
# Pillow (the rasteriser and images) and ezdxf (DXF import). numpy, pyserial and pyusb
# come with meerk40t itself. `[camera]` is opencv-python-headless.
COPY api/ /app/api/
RUN pip install --no-cache-dir "/app/api[camera]" "Pillow>=10" "ezdxf>=1.1" \
 && rm -rf /app/api

COPY --from=frontend /src/build /app/frontend
COPY deploy/entrypoint.sh /app/entrypoint.sh

# Non-root, in `video` so the camera device (root:video on every common distribution) can
# be read. HOME=/data puts ~/.config/MeerK40t — settings, layer list, library, autosave —
# inside the one volume.
RUN groupadd --system --gid 44 video 2>/dev/null || true \
 && useradd --uid 1000 --gid video --home-dir /data --create-home --shell /usr/sbin/nologin openkerf \
 && chmod +x /app/entrypoint.sh
USER openkerf
ENV HOME=/data \
    OPENKERF_PORT=8080 \
    OPENKERF_BIND=0.0.0.0
VOLUME /data
EXPOSE 8080

# Python's own urllib: no curl in the image. The port is read at check time so a changed
# OPENKERF_PORT keeps the check honest.
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import os, urllib.request as u; u.urlopen('http://127.0.0.1:%s/api/health' % os.environ.get('OPENKERF_PORT', '8080'), timeout=4)" || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
```

Note on the `video` group: `python:3.13-slim` (Debian) already ships a `video` group with gid 44, so the `groupadd` is a no-op there and exists only so the Dockerfile says what it relies on. If `useradd` complains that gid 44 is `video` already, that is the expected path.

- [ ] **Step 6: Build the image**

Run: `docker build -f deploy/Dockerfile -t openkerf:dev .`
Expected: both stages complete. Note the wall-clock time of the first build and the image size from `docker image ls openkerf:dev --format '{{.Size}}'`; both go into the handbook page in Task 4.

If `pip install` fails on `opencv-python-headless`, check that the failing wheel is for the platform being built and read the error; do not drop the extra. If it fails resolving `meerk40t`, the pin in `api/pyproject.toml` is the thing to read, not the Dockerfile.

- [ ] **Step 7: Run the smoke test and see it pass**

Run: `deploy/smoke.sh openkerf:dev`
Expected:

```
1. a start without a token is refused
2. with a token the API answers on /api/health
   healthy after N s
3. the frontend build is inside the image
4. OpenCV imports
   cv2 4.x.y
ok
```

Record N (time to first healthy answer) for Task 4.

- [ ] **Step 8: Verify the two things the test cannot see**

Run:

```bash
docker run --rm -e OPENKERF_TOKEN=x --entrypoint sh openkerf:dev -c 'id && echo $HOME && ls -ld /data'
```

Expected: `uid=1000(openkerf) gid=44(video)`, `/data`, and `/data` owned by `openkerf`.

Run: `docker run --rm --entrypoint python openkerf:dev -c "import meerk40t, openkerf_api; print(meerk40t.__version__ if hasattr(meerk40t,'__version__') else 'meerk40t ok')"`
Expected: no `ImportError`.

- [ ] **Step 9: Commit**

```bash
git add .dockerignore deploy/Dockerfile deploy/entrypoint.sh deploy/smoke.sh
git commit -m "An image with the engine, the API and the frontend in one process, and the script that proves it

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Compose, the volume, and the proof that a restart keeps the settings

**Files:**
- Create: `deploy/compose.yml`
- Create: `deploy/.env.example`

**Interfaces:**
- Consumes: the image from Task 1 (locally `openkerf:dev`; in the file, `ghcr.io/openkerf/openkerf:latest`).
- Produces: `deploy/compose.yml` and `deploy/.env.example`, which Task 4 pastes into the handbook page verbatim.

- [ ] **Step 1: Write the failing test — validate a compose file that does not exist**

Run: `docker compose -f deploy/compose.yml config`
Expected: fails with `no such file or directory`.

- [ ] **Step 2: Write `deploy/.env.example`**

```
# Required. The API is reachable from the whole LAN, so anything that changes the design or
# moves the machine needs this token. Make one with:  openssl rand -base64 24
OPENKERF_TOKEN=

# Where the app listens on the host. Host networking: this is the host's port directly.
OPENKERF_PORT=8080
OPENKERF_BIND=0.0.0.0
```

- [ ] **Step 3: Write `deploy/compose.yml`**

```yaml
# OpenKerf beside a laser, on a Linux box in the same network.
#
#   cp .env.example .env      # and fill in OPENKERF_TOKEN
#   docker compose up -d
#
# Host networking is deliberate: the Ruida listens on UDP 50200 and answers from 40200,
# and finding a machine is a broadcast. Neither crosses a Docker bridge reliably, so the
# container is given the host's network and there is no `ports:` block — the app is on
# the host's OPENKERF_PORT directly. (Docker Desktop on Mac or Windows has no host
# network; there discovery does not work and the machine's address is typed by hand.)
services:
  openkerf:
    image: ghcr.io/openkerf/openkerf:latest
    container_name: openkerf
    network_mode: host
    restart: unless-stopped
    env_file: .env
    volumes:
      # Settings, the chosen machine, the layer list, the material library and the
      # autosave all live under /data. Back it up and you have everything.
      - openkerf-data:/data
    devices:
      # The camera over the bed. `ls /dev/video*` on the host shows what is there; a
      # Pi camera often makes two nodes, and the even one carries the picture.
      - /dev/video0:/dev/video0
    # A laser on USB (a K40 and the like) is not covered by this version. This is the
    # line that would give the container the USB bus; untested here:
    # devices:
    #   - /dev/bus/usb:/dev/bus/usb

volumes:
  openkerf-data:
```

- [ ] **Step 4: Validate**

Run: `cd deploy && cp .env.example .env && sed -i.bak 's/^OPENKERF_TOKEN=$/OPENKERF_TOKEN=local-test/' .env && rm .env.bak && docker compose config >/dev/null && echo valid`
Expected: `valid`. (`docker compose config` resolves `env_file`, so the `.env` has to exist for this step; `.env` is never committed — Step 8 adds it to `.gitignore`.)

- [ ] **Step 5: Bring it up against the local image and measure the start**

The compose file names the GHCR image, which does not exist yet. Override for the local run without editing the file:

```bash
cd deploy
docker compose -f compose.yml -f <(printf 'services:\n  openkerf:\n    image: openkerf:dev\n') up -d
```

If `/dev/video0` does not exist on this computer (it does not on a Mac) compose refuses with `error gathering device information`. Then add a second override line `    devices: []` to the printf above for the local run; that is also the measurement the spec asks for — "with no camera device present the rest of the app runs" — so note that the container starts and `/api/health` answers without it.

Then time the start:

```bash
start=$(date +%s); until [ "$(docker inspect -f '{{.State.Health.Status}}' openkerf)" = healthy ]; do sleep 1; done; echo "healthy after $(( $(date +%s) - start )) s"
```

Record the number. Note: on Docker Desktop (Mac) host networking is emulated and `http://localhost:8080` reaches the container; on Linux it is the host's port outright.

- [ ] **Step 6: Prove the volume keeps the settings across a restart**

Choose a machine through the API (this activates a device in the engine and writes `MeerK40t.cfg`; it does not connect to anything and moves nothing). First list what can be chosen:

```bash
curl -s http://localhost:8080/api/machines/catalog | head -c 600
```

The answer is a list of families, each with `machines: [{"key": ..., ...}]`. Take the `key` of the Ruida entry (it contains `ruida`) and create it, which also makes it active. `POST /api/machines` takes `{"info": "<key>"}` and needs the token in the `X-OpenKerf-Token` header. Nothing here connects to a machine or moves anything; `device add` only writes the engine's settings.

```bash
KEY=$(curl -s http://localhost:8080/api/machines/catalog | python3 -c "import json,sys; print(next(m['key'] for f in json.load(sys.stdin) for m in f['machines'] if 'ruida' in m['key']))")
curl -s -X POST -H 'X-OpenKerf-Token: local-test' -H 'Content-Type: application/json' \
  -d "{\"info\": \"$KEY\"}" http://localhost:8080/api/machines
curl -s http://localhost:8080/api/machines | head -c 400     # the new one is marked active
docker compose restart
until [ "$(docker inspect -f '{{.State.Health.Status}}' openkerf)" = healthy ]; do sleep 1; done
curl -s http://localhost:8080/api/machines | head -c 400     # still the Ruida, not lhystudios
```

If the catalog's shape differs from the expression above (`f['machines']`, `m['key']`), read `Machines.catalog()` in `api/openkerf_api/machines.py` around line 137 and adjust the two field names; do not change what is being proved.

Expected: the same device name before and after. This is the engine finding `MeerK40t.cfg` under `/data/.config/MeerK40t/`. Confirm the file exists:

```bash
docker compose exec openkerf ls -la /data/.config/MeerK40t/
```

Expected: `MeerK40t.cfg` and, if a preset was written, the library file beside it.

- [ ] **Step 7: Take it down and leave nothing running**

```bash
docker compose down
docker volume ls | grep openkerf
```

The volume remains (that is the point). Remove it only if this machine should not keep test state: `docker volume rm deploy_openkerf-data`.

- [ ] **Step 8: Keep `.env` out of git**

Append to `.gitignore`:

```
# The real token lives in deploy/.env; only the example is committed.
deploy/.env
```

- [ ] **Step 9: Commit**

```bash
git add deploy/compose.yml deploy/.env.example .gitignore
git commit -m "One compose file: host network, one volume, the camera passed through

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: The workflow that builds, proves and publishes the image

**Files:**
- Create: `.github/workflows/image.yml`

**Interfaces:**
- Consumes: `deploy/Dockerfile`, `deploy/smoke.sh` from Task 1, unchanged.
- Produces: `ghcr.io/openkerf/openkerf` with tags `latest` (main), `sha-<7>` (always), and `<version>` on a `v*` tag.

- [ ] **Step 1: Write the failing test — lint a workflow that does not exist**

Run: `docker run --rm -v "$PWD:/repo" -w /repo rhysd/actionlint:latest -color`
Expected: `no YAML files found` or an error naming `.github/workflows` (nothing to lint yet).

- [ ] **Step 2: Write `.github/workflows/image.yml`**

```yaml
# Builds the OpenKerf image for amd64 and arm64, proves it with deploy/smoke.sh, and
# pushes it to GHCR. Pull requests build and prove but never push, so a broken Dockerfile
# is visible on the PR and `latest` never points at an image without a frontend or
# without OpenCV.
name: image

on:
  push:
    branches: [main]
    tags: ['v*']
  pull_request:

permissions:
  contents: read
  packages: write

env:
  IMAGE: ghcr.io/openkerf/openkerf

jobs:
  image:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: docker/setup-qemu-action@v3
      - uses: docker/setup-buildx-action@v3

      - name: Log in to GHCR
        if: github.event_name != 'pull_request'
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Tags and labels
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: ${{ env.IMAGE }}
          tags: |
            type=raw,value=latest,enable={{is_default_branch}}
            type=sha,prefix=sha-
            type=semver,pattern={{version}}

      # The amd64 image first, loaded into the local daemon so the smoke test can run it.
      - name: Build amd64 for the smoke test
        uses: docker/build-push-action@v6
        with:
          context: .
          file: deploy/Dockerfile
          platforms: linux/amd64
          load: true
          tags: openkerf:smoke
          build-args: |
            REVISION=${{ github.sha }}
            VERSION=${{ steps.meta.outputs.version }}
          cache-from: type=gha
          cache-to: type=gha,mode=max

      - name: Smoke test (amd64)
        run: deploy/smoke.sh openkerf:smoke

      # arm64 under QEMU: only that OpenCV imports. Starting the engine under emulation is
      # slow and proves nothing the amd64 run does not.
      - name: Build arm64 and check OpenCV imports
        uses: docker/build-push-action@v6
        with:
          context: .
          file: deploy/Dockerfile
          platforms: linux/arm64
          load: true
          tags: openkerf:smoke-arm64
          build-args: |
            REVISION=${{ github.sha }}
            VERSION=${{ steps.meta.outputs.version }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
      - name: OpenCV imports (arm64)
        run: docker run --rm --platform linux/arm64 --entrypoint python openkerf:smoke-arm64 -c "import cv2; print(cv2.__version__)"

      - name: Build both and push
        if: github.event_name != 'pull_request'
        uses: docker/build-push-action@v6
        with:
          context: .
          file: deploy/Dockerfile
          platforms: linux/amd64,linux/arm64
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          build-args: |
            REVISION=${{ github.sha }}
            VERSION=${{ steps.meta.outputs.version }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

- [ ] **Step 3: Lint it**

Run: `docker run --rm -v "$PWD:/repo" -w /repo rhysd/actionlint:latest -color`
Expected: no output, exit 0. Fix anything it names.

- [ ] **Step 4: Run the smoke test the way CI will, from a clean shell**

Run: `bash -c 'deploy/smoke.sh openkerf:dev'`
Expected: `ok`. This guards against the script relying on anything in the developer's interactive shell.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/image.yml
git commit -m "The image is built for two architectures, proved, and pushed to GHCR

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

- [ ] **Step 6: Push and watch the first run**

Run: `git push origin main` and then `gh run watch` (or `gh run list --workflow=image -L 1`).
Expected: the job goes green and `ghcr.io/openkerf/openkerf:latest` exists. If GHCR refuses the push with a permissions error, the package has to be created once or the repository's Actions settings need "Read and write permissions" for `GITHUB_TOKEN`; fix that in the GitHub settings, re-run the job, and note the fix in the handbook page under updating. Record the run's wall-clock time for the page.

Then pull the published image and run the smoke test on it, so the page's numbers are about the image people get, not the local build:

```bash
docker pull ghcr.io/openkerf/openkerf:latest
docker image ls ghcr.io/openkerf/openkerf:latest --format '{{.Size}}'
deploy/smoke.sh ghcr.io/openkerf/openkerf:latest
```

---

### Task 4: The handbook page, with the numbers that were measured

**Files:**
- Create: `docs/running-in-docker.md`
- Modify: `docs/README.md` (the table of pages, around line 39-49)
- Modify: `README.md` (the "Running it" section, around line 40)

**Interfaces:**
- Consumes: the measured numbers from Task 1 step 6-7, Task 2 step 5-6 and Task 3 step 6; `deploy/compose.yml` and `deploy/.env.example` verbatim.

- [ ] **Step 1: Write the failing test — the link before the page**

Add the row to `docs/README.md`, after the Reference row in the table:

```markdown
| [Running in Docker](running-in-docker.md) | One compose file for a Linux box beside the laser: the image, the token, the data volume, the camera, updating, and the two limits — no machine discovery on Docker Desktop, and no laser over USB in this version. |
```

Run: `cd frontend && node --test tests/docs.test.ts`
Expected: `every link between the pages resolves` fails with `README.md → running-in-docker.md`.

- [ ] **Step 2: Write `docs/running-in-docker.md`**

Replace every `<...>` below with the number measured in the earlier tasks; a page that names an unmeasured number is not allowed to land.

````markdown
# Running in Docker

OpenKerf is one process: the MeerK40t engine headless, the API beside it, and the
interface served from the same port. The image on GHCR contains all three, plus OpenCV
for the camera over the bed. The box it is written for is a Linux machine in the same
network as the laser — a NAS, a mini-pc, a Raspberry Pi — and the two files below are
all it needs.

## The two files

Put these in a folder of their own on the box.

`compose.yml`:

```yaml
<paste deploy/compose.yml verbatim>
```

`.env`, copied from `.env.example` and with the token filled in:

```
<paste deploy/.env.example verbatim>
```

Then:

```bash
docker compose up -d
```

The interface is on `http://<the box>:8080`. On the first start the image is pulled;
measured on <where>, the container answered on `/api/health` <N> s after `up`.

## The token

Bound to the whole network, the API asks for a token for anything that changes the
design or moves the machine. Reading is free. Without `OPENKERF_TOKEN` the container
refuses to start and says so in its log:

```bash
docker compose logs openkerf
```

Make a token with `openssl rand -base64 24`, put it in `.env`, start again. The
interface asks for the token once and keeps it in the browser; the [Reference](reference.md)
says where it lives in the settings.

## Where the data lives

Everything the engine remembers is under `/data` in the container: the chosen machine
and its settings (`MeerK40t.cfg`), the layer list (`operations.cfg`), the material
library and the autosave. Compose puts that on a named volume, `openkerf-data`, so
`docker compose down` and `up` keep it, and so does an update. Measured: the machine
chosen before `docker compose restart` was the same machine after it.

A backup is the volume copied out:

```bash
docker run --rm -v openkerf-data:/data -v "$PWD":/backup alpine \
  tar czf /backup/openkerf-data.tgz -C /data .
```

## The camera

The compose file passes `/dev/video0` into the container. Find the right node on the
box with `ls /dev/video*`. A USB webcam is usually `video0`; a Pi camera often makes two
nodes, and the even one carries the picture. Change the line in `compose.yml` to match
and `docker compose up -d` again.

Without a camera device the rest of the app runs; the camera panel says that no camera
was found. If the node exists but the picture stays black, the container's user is in
the `video` group already — check the device's group on the host with `ls -l /dev/video0`.

## Updating

```bash
docker compose pull
docker compose up -d
```

The image is rebuilt on every change to `main`; `latest` is only published after the
build has proved that the interface, the API and OpenCV are inside it. A released
version is also available by number, `ghcr.io/openkerf/openkerf:0.1.0` and so on, for
a box that should not move on its own. The image is <size> MB on amd64 and <size> MB on
arm64.

## Two limits

**Docker Desktop on Mac or Windows has no host network.** OpenKerf finds a Ruida by
broadcast and talks to it on UDP 50200 and 40200, and neither crosses Docker Desktop's
network. Finding machines does not work there; typing the Ruida's address into the
machine wizard does. The Linux box beside the laser is the setup this page is for.

**A laser over USB is not covered in this version.** The compose file has the line
that would hand the USB bus to the container, commented out, and it has not been tested.
A Ruida over the network is what this image has run against.
````

- [ ] **Step 3: Link it from the root README**

In `README.md`, at the end of the "Running it" section (after the paragraph about `openkerf -l <path>`), add:

```markdown
To run it in Docker instead — one image with the engine, the API and the interface, for
a Linux box beside the laser — see [Running in Docker](docs/running-in-docker.md).
```

- [ ] **Step 4: Run the docs test and see it pass**

Run: `cd frontend && node --test tests/docs.test.ts`
Expected: all pass. If `every sentence the pages quote is in the English catalogue` fails, the page has a double-quoted phrase that is not an interface sentence; change those quotes to backticks or plain words.

- [ ] **Step 5: Read the page once as the person with the NAS**

Check three things by hand: every command in it was run in Tasks 1-3 as written; every number in it has a measurement behind it in this session; the compose and `.env.example` blocks match the files byte for byte (`diff <(sed -n '/^```yaml/,/^```/p' docs/running-in-docker.md | sed '1d;$d') deploy/compose.yml`).

- [ ] **Step 6: Commit**

```bash
git add docs/running-in-docker.md docs/README.md README.md
git commit -m "The handbook says how to run it in Docker, with the numbers that were measured

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

- [ ] **Step 7: Push**

Run: `git push origin main`, then `gh run list --workflow=image -L 1` to see the image job pass on this commit too.

---

## Self-review against the spec

- Image, two stages, non-root in `video`, `HOME=/data`, healthcheck via urllib, labels, entrypoint with `exec`, token refusal — Task 1.
- Compose: host network, one volume, camera device, commented USB block, `.env.example` — Task 2.
- CI: triggers, QEMU, both platforms, tags, smoke test on amd64, `import cv2` on arm64, no push on PR — Task 3.
- Measurements: size, time to healthy, persistence across restart, running without a camera device — Task 1 step 6-7, Task 2 step 5-6, written down in Task 4.
- Handbook page, linked from `docs/README.md` and `README.md`, docs test green — Task 4.
- Out of scope items are not touched by any task.
