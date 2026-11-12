#!/usr/bin/env bash
# The built wheel, installed fresh as a user would, serving a scratch data folder; then smoke.py
# against it. `make smoke` builds the wheel first.
set -euo pipefail
# A scratch server: none of the shell's rowlab settings, so it can't reach a real database or bucket.
unset $(compgen -e | grep -E '^(ROWLAB|WORKOS)_') || true
port=${SMOKE_PORT:-8001}
dir=$(mktemp -d)
pid=
trap '[ -n "$pid" ] && kill "$pid" 2>/dev/null; rm -rf "$dir"' EXIT

if curl -s "http://127.0.0.1:$port" >/dev/null; then
  echo "Port $port is taken; set SMOKE_PORT to a free one." >&2
  exit 1
fi
wheel=$(ls -t server/dist/rowlab-*.whl | head -1)
uv venv -q -p 3.13 "$dir/venv"
uv pip install -q -p "$dir/venv" "$wheel"
ROWLAB_DATA_DIR="$dir/data" "$dir/venv/bin/rowlab" serve --port "$port" >"$dir/log" 2>&1 &
pid=$!
for _ in $(seq 60); do
  kill -0 "$pid" 2>/dev/null || { cat "$dir/log"; exit 1; }  # it quit, e.g. couldn't bind
  curl -sf "http://127.0.0.1:$port/v1/health" >/dev/null && break
  sleep 0.5
done
python3 scripts/smoke.py "http://127.0.0.1:$port" || { cat "$dir/log"; exit 1; }
