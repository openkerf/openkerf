#!/bin/zsh
set -eu
cd -- "$(dirname -- "$0")"
exec .venv/bin/meerk40t --no-gui -d -e "openkerf -p 8080 -f frontend/build"
