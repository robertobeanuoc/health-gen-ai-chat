#!/bin/bash
set -e

echo "[entrypoint] Compiling dbt artifacts..."
uv run dbt compile \
  --project-dir dbt_health_gen_ai_chat \
  --profiles-dir dbt_health_gen_ai_chat

echo "[entrypoint] Starting server..."
exec uv run uvicorn src.chat_agent.server:app --host 0.0.0.0 --port 8000
