#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
command -v uv >/dev/null || { echo '请先安装 uv：https://docs.astral.sh/uv/'; exit 1; }
command -v node >/dev/null || { echo '请先安装 Node.js 22.12+ 或 24 LTS'; exit 1; }
command -v ffmpeg >/dev/null || { echo '请先安装 FFmpeg（macOS: brew install ffmpeg）'; exit 1; }
command -v ffprobe >/dev/null || { echo '缺少 ffprobe，请完整安装 FFmpeg'; exit 1; }
if [ ! -x .venv/bin/python ]; then uv venv --python 3.12 .venv; fi
uv pip sync backend/requirements.lock --python .venv/bin/python
if [ ! -f .env ]; then cp .env.example .env; fi
PYTHONPATH=backend .venv/bin/alembic -c backend/alembic.ini upgrade head
npm --prefix frontend ci
echo '依赖已就绪。运行 bash scripts/dev.sh 启动旭光集。'
