import os
import tempfile
from pathlib import Path

scratch = Path(tempfile.mkdtemp(prefix="xuguangji-tests-"))
os.environ["DATABASE_URL"] = f"sqlite:///{scratch}/tests.db"
os.environ["DATA_DIR"] = str(scratch / "media")
os.environ["MODEL_PROVIDER"] = "mock"
os.environ["QUEUE_MODE"] = "local"

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.models import Base, engine
from app.api import routes
from app.workers.queue import execute


@pytest.fixture
def client(monkeypatch):
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(routes, "dispatch", execute)
    from app.auth import _attempts
    _attempts.clear()
    with TestClient(app) as client:
        client.headers["X-Requested-With"] = "XMLHttpRequest"
        response = client.post("/api/v1/auth/register", json={"username": "tester", "password": "test-password-123"})
        assert response.status_code == 201, response.text
        yield client
