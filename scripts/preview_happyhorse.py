"""Serve the built experiment UI and API together on a local preview port."""
import argparse
import os
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
os.chdir(root)
sys.path.insert(0, str(root / "backend"))

from fastapi.staticfiles import StaticFiles
import uvicorn
from app.main import app
from app.config import settings


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8002)
    args = parser.parse_args()
    if settings.queue_mode != "local":
        parser.error("Local preview requires QUEUE_MODE=local and its own database/data directory")
    if not (root / "frontend/dist/index.html").is_file():
        parser.error("Build the UI first: cd frontend && npm run build")
    app.mount("/", StaticFiles(directory=root / "frontend/dist", html=True), name="preview")
    uvicorn.run(app, host="127.0.0.1", port=args.port)
