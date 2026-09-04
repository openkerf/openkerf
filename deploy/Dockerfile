# syntax=docker/dockerfile:1
# OpenKerf: the MeerK40t engine headless, our API beside it, and the built frontend
# served from the same process. Build from the repository root:
#
#   docker build -f deploy/Dockerfile -t openkerf:dev .
#
# The engine is installed from upstream git at the revision the working copy pins (see
# MEERK40T_REV below), not from PyPI; the meerk40t/ working copy in the checkout is not
# part of the build context (see .dockerignore).

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

# libusb for pyusb (a laser on USB, later); libGL/glib for opencv-python-headless. Kept in
# their own layer since they are runtime libraries, not build-time tools.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libusb-1.0-0 libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

# The repo is measured against upstream git at this revision (version string 0.9.9040),
# which no PyPI release contains: the API's own suite, run against the newest release the
# pyproject.toml pin admits (0.9.9100), measured 181 failed / 12 errors of 1625 tests
# (32 files) — meerk40t.rotary.rotary_cam, which api/openkerf_api/rotary.py imports
# directly, does not exist in that release, and 0.9.9000 (the pin's floor) lacks it too.
# Bump this together with the working copy in meerk40t/, not independently.
ARG MEERK40T_REV=5f68a45

# git is a build-time tool only, needed to fetch the engine below. Installing it, using
# it, and purging it all happen in this one RUN so its bytes never land in a shipped
# layer — a purge in a later layer only hides the package from the final filesystem view,
# it does not shrink the layer that installed it. Installing the engine before the API
# lets pip see the pyproject.toml range (>=0.9.9000,<0.10) already satisfied by the git
# install, so it does not also fetch PyPI. The engine's own non-GUI requirements that it
# does not declare: Pillow (the rasteriser and images) and ezdxf (DXF import). numpy,
# pyserial and pyusb come with meerk40t itself. `[camera]` is opencv-python-headless.
COPY api/ /app/api/
RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && pip install --no-cache-dir "meerk40t @ git+https://github.com/meerk40t/meerk40t.git@${MEERK40T_REV}" \
 && pip install --no-cache-dir "/app/api[camera]" "Pillow>=10" "ezdxf>=1.1" \
 && apt-get purge -y git \
 && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/* /app/api

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
