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

# `exec` makes the engine PID 1, so Docker's stop signal reaches it directly — a shell
# left in between would swallow it and Docker would SIGKILL after its 10 s grace period
# instead. The engine has no handler for that signal, so a stop is still abrupt: nothing
# runs the engine's own quit. Little is lost even so, since the autosave writes every 5 s
# and settings are written at the moment they change; a real handler is follow-up work.
#
# The leading `.` on the command is the engine's own way of not echoing a command line to
# its console channel (meerk40t/kernel/kernel.py) — without it the token passed with -t
# would appear a second time in `docker logs`, in plain text.
exec meerk40t --no-gui --daemon \
  --execute ".openkerf -p ${PORT} -b ${BIND} -f /app/frontend -t ${OPENKERF_TOKEN}"
