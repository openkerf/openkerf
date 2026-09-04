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
