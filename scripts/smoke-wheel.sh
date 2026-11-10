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

wheel=$(ls -t server/dist/rowlab-*.whl | head -1)
uv venv -q -p 3.13 "$dir/venv"
uv pip install -q -p "$dir/venv" "$wheel"
ROWLAB_DATA_DIR="$dir/data" "$dir/venv/bin/rowlab" serve --port "$port" >"$dir/log" 2>&1 &
pid=$!
for _ in $(seq 60); do
  curl -sf "http://127.0.0.1:$port/v1/health" >/dev/null && break
  sleep 0.5
done
python3 scripts/smoke.py "http://127.0.0.1:$port" || { cat "$dir/log"; exit 1; }
