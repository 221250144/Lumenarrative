#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHONPATH=backend .venv/bin/pytest backend/tests -q
npm --prefix frontend run build
