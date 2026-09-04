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

`.env`, copied from `.env.example` and with the token filled in:

```
# Required. The API is reachable from the whole LAN, so anything that changes the design or
# moves the machine needs this token. Make one with:  openssl rand -base64 24
OPENKERF_TOKEN=

# Where the app listens on the host. Host networking: this is the host's port directly.
OPENKERF_PORT=8080
OPENKERF_BIND=0.0.0.0
```

Then:

```bash
docker compose up -d
```

The interface is on `http://<the box>:8080`. On the first start the image is pulled;
measured on the developer's Mac, the container answered on `/api/health` 2 s after start,
both with a plain `docker run` and under `docker compose up`.

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

Everything the engine remembers is under `/data` in the container: `MeerK40t.cfg` (the
chosen machine and its settings), `operations.cfg` (the layer list), `openkerf-library.db`
(the material library) and `openkerf-photos/` (the test grid photographs). Compose puts
that on a named volume, `openkerf-data`, so `docker compose down` and `up` keep it, and
so does an update. Measured: a Ruida machine created through the API was still the
active machine after `docker compose restart`, with all four still on the volume.

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

Without a camera device the rest of the app runs; measured, the container starts,
becomes healthy and `/api/health` still answers. The camera panel says that no camera
was found. If you run it this way on purpose, delete the `devices:` line rather than
overriding it: a second compose file with `devices: []` does not remove it, since
Compose merges lists — `devices: !override []` does.

If the node exists but the picture stays black, the container's user is in the `video`
group already — check the device's group on the host with `ls -l /dev/video0`.

## Which engine the image runs

The Dockerfile installs MeerK40t from upstream git at revision `5f68a45` (version string
0.9.9040), not from PyPI: no PyPI release contains modules this code imports, and
against PyPI 0.9.9100, 193 of 1625 API tests fail. The revision is the `MEERK40T_REV`
build argument in `deploy/Dockerfile`. Bumping it is a deliberate step taken together
with this repository's working copy, not something to do on its own.

## Updating

```bash
docker compose pull
docker compose up -d
```

The image is rebuilt on every change to `main`; `latest` is only published after the
build has proved that the interface, the API and OpenCV are inside it. A released
version is also available by number, `ghcr.io/openkerf/openkerf:0.1.0` and so on, for
a box that should not move on its own. Measured on a local build of the same
Dockerfile, a pull downloads about 220 MB on arm64 and about 250 MB on amd64; the
registry's own figure may differ slightly with its compression. Unpacked on disk, once
the image has run, it takes about 910 MB on arm64 and about 990 MB on amd64. A clean
build takes about 40 s on the developer's Mac; the CI run that builds both
architectures and smoke-tests the image took 9 min 2 s.

## Two limits

**Docker Desktop on Mac or Windows has no host network in the way Linux gives it.**
OpenKerf finds a Ruida by broadcast and talks to it on UDP 50200 and 40200, and neither
crosses Docker Desktop's network the way it does on Linux. Measured on the developer's
Mac: machine discovery does not work there, and the interface itself was not reachable
from the browser at all, even with a plain nginx container run the same way. The Linux
box beside the laser is the setup this page is for.

**A laser over USB is not covered in this version.** The compose file has the line
that would hand the USB bus to the container, commented out, and it has not been tested.
A Ruida over the network is what this image has run against.
