#!/usr/bin/env bash
# Starts both local dev servers with one command:
#   uvicorn (FastAPI, :8000) + next dev (:3000)
#
# Unlike `docker compose -f deploy/docker-compose.yml up`, this runs both
# processes directly with their native hot reload (no image rebuild), which
# is what you want while actively editing either side. Use docker compose
# instead when you need to test the actual container topology.
#
# Ctrl+C stops both.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_UVICORN="$ROOT_DIR/.venv/bin/uvicorn"

if [[ ! -x "$VENV_UVICORN" ]]; then
  echo "error: $VENV_UVICORN not found — create the venv first (see PERSON_B_PLAN_v2.md)." >&2
  exit 1
fi

cleanup() {
  echo ""
  echo "Stopping..."
  kill "$API_PID" "$WEB_PID" 2>/dev/null || true
  wait "$API_PID" "$WEB_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "Starting FastAPI (uvicorn) on :8000..."
(cd "$ROOT_DIR" && "$VENV_UVICORN" api.main:app --reload --port 8000) &
API_PID=$!

echo "Starting Next.js (next dev) on :3000..."
(cd "$ROOT_DIR/web" && npm run dev) &
WEB_PID=$!

wait "$API_PID" "$WEB_PID"
