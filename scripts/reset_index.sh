#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON:-}"
if [ -z "$PYTHON_BIN" ]; then
  if [ -x ".venv/bin/python" ]; then
    PYTHON_BIN=".venv/bin/python"
  else
    PYTHON_BIN="python3"
  fi
fi

"$PYTHON_BIN" - <<'PY'
from backend.app.config import settings
from backend.app.storage.elastic import KnowledgeIndex
from backend.app.storage.sqlite import SQLiteGraphStore

KnowledgeIndex().reset()
SQLiteGraphStore(settings.sqlite_path).reset()
print("Reset ops_knowledge index and SQLite graph")
PY
