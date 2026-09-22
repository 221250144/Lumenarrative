#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHONPATH=backend .venv/bin/alembic -c backend/alembic.ini upgrade head
PYTHONPATH=backend .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 &
api_pid=$!
npm --prefix frontend run dev &
web_pid=$!
cleanup() { kill "$api_pid" "$web_pid" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
echo '旭光集：http://127.0.0.1:5173'
wait "$api_pid" "$web_pid"
