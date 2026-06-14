#!/usr/bin/env bash
set -euo pipefail

MODEL="${LLM_MODEL:-Qwen/Qwen3-14B-MLX-4bit}"
HOST="${LLM_HOST:-127.0.0.1}"
PORT="${LLM_PORT:-8000}"

MLX_SERVER="${MLX_SERVER:-}"
if [ -z "$MLX_SERVER" ]; then
  if [ -x ".venv/bin/mlx_lm.server" ]; then
    MLX_SERVER=".venv/bin/mlx_lm.server"
  else
    MLX_SERVER="$(command -v mlx_lm.server || true)"
  fi
fi

if [ -z "$MLX_SERVER" ]; then
  echo "mlx_lm.server is not installed. Run: uv tool install mlx-lm" >&2
  exit 1
fi

exec "$MLX_SERVER" \
  --model "$MODEL" \
  --host "$HOST" \
  --port "$PORT" \
  --chat-template-args '{"enable_thinking":false}' \
  --decode-concurrency 1 \
  --prompt-concurrency 1
