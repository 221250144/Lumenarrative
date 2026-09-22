"""Retired editing endpoints must not mutate history or disable source media."""
from copy import deepcopy

import pytest
from sqlalchemy import select

from app.api import routes
from app.models import SessionLocal, Project, AnalysisRun, Asset, EditVersion, Job, uid, serialize
from app.providers.storage import storage
from app.workers.queue import execute


@pytest.fixture
def history(client):
    with SessionLocal() as db:
        project = Project(id=uid(), title="Existing project", intent="Review a Vlog", revision=3)
        db.add(project)
        db.flush()
        analysis = AnalysisRun(id=uid(), project_id=project.id, project_revision=3, asset_snapshot=[], config_hash="historic", status="succeeded", data={})
        db.add(analysis)
        db.flush()
        source_key = f"retirement/{uid()}/generated.mp4"
        output_key = f"retirement/{uid()}/historic-edit.mp4"
        for key, content in [(source_key, b"AI source bytes kept for download"), (output_key, b"Historic edited output remains on disk")]:
            path = storage.path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        asset = Asset(id=uid(), project_id=project.id, source_type="ai_generated", original_name="AI-candidate.mp4", storage_key=source_key, sha256="generated", duration_s=5, width=1280, height=720, has_audio=False, status="ready", meta={"synthetic_media": True, "proxy_key": source_key})
        db.add(asset)
        db.flush()
        edit = EditVersion(id=uid(), project_id=project.id, analysis_id=analysis.id, render_status="succeeded", output_key=output_key, data={"timeline": [{"asset_id": asset.id, "source_in_s": 0, "source_out_s": 5}], "project_revision": 3, "duration_s": 5})
        db.add(edit)
        db.flush()
        job = Job(id=uid(), project_id=project.id, type="render", status="failed", retry_count=2, error_code="OLD_ERROR", error_message="Existing error", data={"edit_id": edit.id})
        db.add(job)
        db.commit()
        return {
            "project_id": project.id, "analysis_id": analysis.id, "edit_id": edit.id,
            "asset_id": asset.id, "job_id": job.id, "output_key": output_key,
            "source_key": source_key, "project": deepcopy(serialize(project)),
            "analysis": deepcopy(serialize(analysis)), "edit": deepcopy(serialize(edit)),
            "asset": deepcopy(serialize(asset)), "job": deepcopy(serialize(job)),
        }


@pytest.mark.parametrize("method,path", [
    ("POST", "/api/v1/projects/{project_id}/edits"),
    ("GET", "/api/v1/projects/{project_id}/edits"),
    ("GET", "/api/v1/edits/{edit_id}"),
    ("GET", "/api/v1/edits/{edit_id}/video"),
    ("GET", "/api/v1/edits/{edit_id}/edl"),
])
def test_editing_routes_return_gone_without_creating_jobs_or_mutating_history(client, history, monkeypatch, method, path):
    dispatched = []
    monkeypatch.setattr(routes, "dispatch", dispatched.append)
    kwargs = {"json": {"analysis_id": history["analysis_id"], "allow_reedit": True}} if method == "POST" else {}
    response = client.request(method, path.format(**history), **kwargs)
    assert response.status_code == 410 and response.json()["code"] == "HTTP_410"
    assert "外部剪辑软件" in response.json()["message"]
    assert not dispatched
    with SessionLocal() as db:
        for cls, key in [(Project, "project"), (AnalysisRun, "analysis"), (EditVersion, "edit"), (Asset, "asset"), (Job, "job")]:
            assert serialize(db.get(cls, history[key + "_id"])) == history[key]
        assert len(list(db.scalars(select(EditVersion)))) == len(list(db.scalars(select(Job)))) == 1
    assert storage.path(history["output_key"]).read_bytes() == b"Historic edited output remains on disk"
    assert storage.path(history["source_key"]).read_bytes() == b"AI source bytes kept for download"


@pytest.mark.parametrize("status", ["failed", "queued", "running", "succeeded", "cancelled"])
def test_render_retry_is_retired_without_cancelling_or_restarting_old_work(client, history, monkeypatch, status):
    with SessionLocal() as db:
        job = db.get(Job, history["job_id"])
        job.status = status
        db.commit()
        before = deepcopy(serialize(job))
    dispatched = []
    monkeypatch.setattr(routes, "dispatch", dispatched.append)
    response = client.post(f"/api/v1/jobs/{history['job_id']}/retry")
    assert response.status_code == 410 and not dispatched
    with SessionLocal() as db:
        assert serialize(db.get(Job, history["job_id"])) == before
        assert serialize(db.get(EditVersion, history["edit_id"])) == history["edit"]


def test_ai_source_preview_and_download_remain_available(client, history):
    data = client.get(f"/api/v1/projects/{history['project_id']}/assets").json()
    assert len(data) == 1 and data[0]["source_type"] == "ai_generated"
    assert data[0]["synthetic_media"]
    source = client.get(data[0]["original_url"])
    assert source.status_code == 200 and source.content == storage.path(history["source_key"]).read_bytes()
    preview = client.get(data[0]["preview_url"], headers={"Range": "bytes=0-9"})
    assert preview.status_code == 206 and preview.content == source.content[:10]


def test_legacy_queued_render_can_finish_without_reopening_the_public_api(client, history, monkeypatch):
    from app.workflows import pipeline

    with SessionLocal() as db:
        db.get(Job, history["job_id"]).status = "queued"
        db.get(EditVersion, history["edit_id"]).render_status = "queued"
        db.commit()
    monkeypatch.setattr(pipeline, "render", lambda *args: (history["output_key"], {"duration_s": 5}))
    execute(history["job_id"])
    with SessionLocal() as db:
        assert db.get(Job, history["job_id"]).status == "succeeded"
        assert db.get(EditVersion, history["edit_id"]).render_status == "succeeded"
    assert client.get(f"/api/v1/edits/{history['edit_id']}/video").status_code == 410


def test_public_schema_omits_retired_editing_endpoints(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert not any("/edits" in path for path in paths)
    assert "/api/v1/assets/{id}/media/{kind}" in paths
    assert "/api/v1/completion-tasks/{id}/generations" in paths
    assert "/api/v1/completion-tasks/{id}/submissions" in paths


def test_retirement_notice_does_not_require_the_old_edit_payload(client, history):
    response = client.post(f"/api/v1/projects/{history['project_id']}/edits")
    assert response.status_code == 410
