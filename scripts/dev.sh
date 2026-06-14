#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

docker compose up -d elasticsearch

PYTHON_BIN="${PYTHON:-}"
if [ -z "$PYTHON_BIN" ]; then
  if [ -x ".venv/bin/python" ]; then
    PYTHON_BIN=".venv/bin/python"
  else
    PYTHON_BIN="python3"
  fi
fi

"$PYTHON_BIN" -m backend.app.ingestion.pipeline \
  --source-dir backend/examples/bank_sample \
  --reset-index

"$PYTHON_BIN" -m uvicorn backend.app.main:app --reload --port "${APP_PORT:-9000}" &
BACKEND_PID=$!

if command -v npm >/dev/null 2>&1; then
  (cd frontend && npm install && npm run dev) &
  FRONTEND_PID=$!
else
  echo "npm is not installed; backend is running on http://localhost:${APP_PORT:-9000}" >&2
  wait "$BACKEND_PID"
  exit 0
fi

trap 'kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true' EXIT
wait
