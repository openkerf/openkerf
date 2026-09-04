#!/usr/bin/env bash
# Proves an OpenKerf image is sound, without touching any machine.
#
#   deploy/smoke.sh ghcr.io/openkerf/openkerf:latest
#
# Five checks, each one a claim the handbook makes: the API answers, the frontend build
# is inside the image, OpenCV imports, a start without a token is refused with a
# sentence, and the token given with -t never lands in the container log. Exits non-zero
# on the first failure. Uses port 18080 so a running OpenKerf on 8080 is left alone.
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

echo "5. the token is not in the container log"
if docker logs "$NAME" 2>&1 | grep -q smoke; then
  echo "   the token 'smoke' appears in docker logs"; exit 1
fi

echo "ok"
