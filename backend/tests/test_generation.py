import base64
import io
import json
from types import SimpleNamespace
import urllib.error
import threading
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from sqlalchemy import select

from app.api import generation as api
from app.config import settings
from app.models import SessionLocal, Project, Asset, AnalysisRun, CompletionPlan, CompletionTask, Evidence, Gap, Job, uid
from app.providers import video_generation as provider_module
from app.providers.video_generation import HappyHorseProvider, GenerationError, download_video, validate_download_url
from app.services.generation import check_capacity
from app.workers.queue import execute
from app.workflows import generation as workflow
from app.workflows.generation import reference_frame as build_reference_frame
from app.workflows.pipeline import config_hash


@pytest.fixture
def context(client, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "model_provider", "qwen")
    monkeypatch.setattr(settings, "model_api_key", "test-private-key")
    monkeypatch.setattr(settings, "model_base_url", "https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1")
    monkeypatch.setattr(settings, "video_generation_enabled", True)
    monkeypatch.setattr(settings, "video_generation_base_url", "")
    monkeypatch.setattr(api, "dispatch", lambda _: None)
    reference_key = "generation-test-frame.jpg"
    (settings.data_dir / reference_key).write_bytes(b"jpeg-test-frame")
    with SessionLocal() as db:
        p = Project(id=uid(), title="Vlog", intent="Show preparation", style="natural", input_mode="vlog", target_duration_s=60)
        db.add(p)
        db.flush()
        asset = Asset(id=uid(), project_id=p.id, source_type="real_capture", original_name="source.mp4", storage_key="source.mp4", sha256="source", duration_s=20, width=1280, height=720, has_audio=False, status="ready", meta={"scene_shots": [{"id": "first-shot", "start_s": 0, "end_s": 20, "keyframes": [{"time_s": 2, "key": reference_key}]}], "shots": []})
        db.add(asset)
        p.constraints_json = {"primary_asset_id": asset.id}
        run = AnalysisRun(id=uid(), project_id=p.id, project_revision=p.revision, asset_snapshot=[asset.id], config_hash=config_hash(), status="succeeded", data={"project_config": {"intent": p.intent, "style": p.style, "input_mode": p.input_mode, "target_duration_s": p.target_duration_s, "constraints_json": p.constraints_json}})
        db.add(run)
        db.flush()
        p.latest_analysis_id = run.id
        evidence = Evidence(id=uid(), project_id=p.id, analysis_id=run.id, data={"asset_id": asset.id, "source_start_s": 2, "source_end_s": 4, "evidence_type": "visual", "action": "Prepare a drink"})
        gap = Gap(id=uid(), project_id=p.id, analysis_id=run.id, data={"status": "confirmed", "uncertain": False})
        plan = CompletionPlan(id=uid(), project_id=p.id, analysis_id=run.id, data={})
        db.add_all([evidence, gap, plan])
        db.flush()
        task = CompletionTask(id=uid(), project_id=p.id, plan_id=plan.id, data={"type": "reshoot", "gap_ids": [gap.id], "reference_evidence_ids": [evidence.id], "instruction": "Show the next action", "requirement_description": "Show preparation", "recommendation": {"duration_s": 5, "subject_action": "Pour a drink", "shot_scale": "close-up"}})
        db.add(task)
        db.commit()
        result = SimpleNamespace(project_id=p.id, asset_id=asset.id, analysis_id=run.id, task_id=task.id, gap_id=gap.id, revision=p.revision)
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"jpeg-test-frame")
    monkeypatch.setattr(workflow, "reference_frame", lambda *args: frame)
    result.body = {"prompt": "Generate the next action", "duration_s": 5, "resolution": "720P", "reference_asset_id": result.asset_id, "reference_time_s": 2}
    result.url = f"/api/v1/completion-tasks/{result.task_id}/generations"
    return result


def post(client, context, key="generation-key", **changes):
    return client.post(context.url, headers={"Idempotency-Key": key}, json={**context.body, **changes})


def fake_generation(monkeypatch, fail_download=False):
    calls = {"submit": 0, "query": 0, "download": 0, "preprocess": 0}

    class FakeProvider:
        def submit(self, *args):
            calls["submit"] += 1
            return "provider-task-1"

        def query(self, task_id):
            assert task_id == "provider-task-1"
            calls["query"] += 1
            return {"task_status": "SUCCEEDED", "video_url": "https://result.oss-cn-beijing.aliyuncs.com/test.mp4?signed=private"}

    def download(url, target):
        calls["download"] += 1
        if fail_download and calls["download"] == 1:
            raise GenerationError("Download failed safely")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"mp4")
        return "sha256-generated"

    def preprocess(job, progress):
        calls["preprocess"] += 1
        with SessionLocal() as db:
            asset = db.get(Asset, job.data["asset_id"])
            asset.status = "ready"
            db.commit()

    monkeypatch.setattr(workflow, "HappyHorseProvider", FakeProvider)
    monkeypatch.setattr(workflow, "download_video", download)
    monkeypatch.setattr(workflow, "probe", lambda _: {"duration_s": 5, "width": 1280, "height": 720, "has_audio": True, "source_start_time": 0})
    monkeypatch.setattr(workflow, "process_asset", preprocess)
    return calls


def test_provider_exact_async_contract_and_no_secret_in_output(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "model_api_key", "test-private-key")
    monkeypatch.setattr(settings, "model_base_url", "https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1")
    monkeypatch.setattr(settings, "video_generation_base_url", "")
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={"output": {"task_id": "test-task", "task_status": "PENDING"}})

    original = httpx.Client
    monkeypatch.setattr(provider_module.httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs))
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"frame")
    provider = HappyHorseProvider()
    assert provider.submit("motion", frame, 5, "720P") == "test-task"
    provider.query("test-task")
    payload = json.loads(requests[0].content)
    assert str(requests[0].url) == "https://workspace.cn-beijing.maas.aliyuncs.com/api/v1/services/aigc/video-generation/video-synthesis"
    assert requests[0].headers["X-DashScope-Async"] == "enable"
    assert requests[0].headers["Authorization"] == "Bearer test-private-key"
    assert payload["parameters"] == {"resolution": "720P", "duration": 5, "watermark": True}
    assert payload["model"] == "happyhorse-1.1-i2v"
    assert payload["input"]["media"] == [{"type": "first_frame", "url": "data:image/jpeg;base64," + base64.b64encode(b"frame").decode()}]
    assert str(requests[1].url).endswith("/api/v1/tasks/test-task")


def test_provider_timeout_never_retries_billable_post(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "model_api_key", "test-private-key")
    calls = []

    def handle(request):
        calls.append(request)
        raise httpx.ReadTimeout("Secret signed URL and private key", request=request)

    original = httpx.Client
    monkeypatch.setattr(provider_module.httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs))
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"frame")
    with pytest.raises(GenerationError) as error:
        HappyHorseProvider().submit("test", frame, 5, "720P")
    assert len(calls) == 1
    assert "Secret" not in str(error.value) and "private" not in str(error.value)


def test_options_and_idempotency_enforce_exact_reference(client, context):
    options = client.get(context.url.removesuffix("generations") + "generation-options").json()
    assert options["available"] and len(options["reference_frames"]) == 1
    assert options["reference_frames"][0]["asset_id"] == context.asset_id
    assert client.post(context.url, json=context.body).status_code == 400
    assert post(client, context, reference_time_s=3).status_code == 409
    assert post(client, context, reference_asset_id=uid()).status_code == 409
    assert post(client, context, duration_s=2).status_code == 422
    assert post(client, context, duration_s=5.5).status_code == 422
    assert client.post(context.url, headers={"Idempotency-Key": "nan", "Content-Type": "application/json"}, content=json.dumps({**context.body, "reference_time_s": float("nan")})).status_code == 422
    first = post(client, context)
    assert first.status_code == 202
    assert post(client, context).json() == first.json()
    assert post(client, context, prompt="different").status_code == 409
    assert post(client, context, key="new-key").status_code == 409
    assert len(client.get(context.url).json()) == 1


@pytest.mark.parametrize("change", ["model", "primary", "intent", "style", "gap", "type", "other_analysis"])
def test_stale_or_ineligible_task_cannot_generate(client, context, change):
    with SessionLocal() as db:
        project = db.get(Project, context.project_id)
        if change == "model":
            db.get(AnalysisRun, context.analysis_id).config_hash = "previous-model"
        elif change == "primary":
            project.constraints_json = {"primary_asset_id": uid()}
        elif change in ("intent", "style"):
            setattr(project, change, "changed")
        elif change == "gap":
            db.get(Gap, context.gap_id).data = {"status": "needs_review"}
        elif change == "type":
            task = db.get(CompletionTask, context.task_id)
            task.data = {**task.data, "type": "reedit"}
        else:
            project.latest_analysis_id = uid()
        db.commit()
    assert post(client, context).status_code == 409


def test_completed_generation_is_durable_ai_asset_and_never_resolves_gap(client, context, monkeypatch):
    calls = fake_generation(monkeypatch)
    job_id = post(client, context).json()["job_id"]
    execute(job_id)
    job = client.get(f"/api/v1/jobs/{job_id}").json()
    assert job["status"] == "succeeded" and job["provider_task_id"] == "provider-task-1"
    assert job["task_id"] == context.task_id and "video_url" not in job
    with SessionLocal() as db:
        generated = db.get(Asset, job["asset_id"])
        assert generated.source_type == "ai_generated" and generated.status == "ready"
        assert generated.meta["synthetic_media"] and generated.meta["generation"]["watermark"]
        assert db.get(Gap, context.gap_id).data["status"] == "confirmed"
        assert db.get(Project, context.project_id).revision == context.revision + 1
    assert post(client, context).json()["job_id"] == job_id
    execute(job_id)  # duplicate delivery is harmless
    assert calls == {"submit": 1, "query": 1, "download": 1, "preprocess": 1}
    assert "generation_retryable" in client.get(f"/api/v1/projects/{context.project_id}/jobs").json()[0]


def test_user_confirmed_uncertain_suggestion_can_generate_candidate_without_changing_gap(client, context, monkeypatch):
    fake_generation(monkeypatch)
    with SessionLocal() as db:
        gap = db.get(Gap, context.gap_id)
        gap.data = {**gap.data, "uncertain": True, "human_reason": "The creator wants this candidate"}
        original_gap = dict(gap.data)
        db.commit()
    options = client.get(context.url.removesuffix("generations") + "generation-options").json()
    assert options["available"]
    response = post(client, context)
    assert response.status_code == 202
    execute(response.json()["job_id"])
    assert client.get(f"/api/v1/jobs/{response.json()['job_id']}").json()["status"] == "succeeded"
    with SessionLocal() as db:
        assert db.get(Gap, context.gap_id).data == original_gap


def test_download_retry_resumes_provider_id_without_second_submission(client, context, monkeypatch):
    calls = fake_generation(monkeypatch, fail_download=True)
    job_id = post(client, context).json()["job_id"]
    execute(job_id)
    first = client.get(f"/api/v1/jobs/{job_id}").json()
    assert first["status"] == "failed" and first["generation_retryable"]
    assert post(client, context, key="another-key").status_code == 409
    assert client.post(f"/api/v1/jobs/{job_id}/retry").status_code == 202
    job = client.get(f"/api/v1/jobs/{job_id}").json()
    assert job["status"] == "succeeded"
    assert calls["submit"] == 1 and calls["query"] == 2 and calls["download"] == 2
    with SessionLocal() as db:
        assert len(list(db.scalars(select(Asset).where(Asset.project_id == context.project_id)))) == 2


def test_unknown_submission_is_not_retried_or_replaced(client, context, monkeypatch):
    calls = []

    class LostResponse:
        def submit(self, *args):
            calls.append(1)
            raise GenerationError("上次提交结果尚未确认")

    monkeypatch.setattr(workflow, "HappyHorseProvider", LostResponse)
    job_id = post(client, context).json()["job_id"]
    execute(job_id)
    job = client.get(f"/api/v1/jobs/{job_id}").json()
    assert job["provider_submission_started"] and not job["generation_retryable"]
    with SessionLocal() as db:
        assert db.get(AnalysisRun, context.analysis_id).status == "succeeded"
    assert client.post(f"/api/v1/jobs/{job_id}/retry").status_code == 409
    assert post(client, context, key="different-key").status_code == 409
    assert post(client, context).json()["job_id"] == job_id
    assert len(calls) == 1


def test_pending_generation_reserves_project_capacity(client, context, monkeypatch):
    monkeypatch.setattr(settings, "max_assets", 2)
    assert post(client, context).status_code == 202
    with SessionLocal() as db:
        with pytest.raises(GenerationError, match="数量"):
            check_capacity(db, context.project_id, 3)


def test_reference_preview_and_uploaded_frame_share_exact_sample(client, context, monkeypatch):
    first_key, second_key = "first-selected.jpg", "next-shot.jpg"
    (settings.data_dir / first_key).write_bytes(b"first selected image")
    (settings.data_dir / second_key).write_bytes(b"next shot image")
    with SessionLocal() as db:
        asset = db.get(Asset, context.asset_id)
        asset.meta = {"scene_shots": [
            {"id": "first", "start_s": 0, "end_s": 2.1, "keyframes": [{"time_s": 1.8, "key": first_key}]},
            {"id": "second", "start_s": 2.1, "end_s": 20, "keyframes": [{"time_s": 2.1, "key": second_key}]},
        ], "shots": []}
        db.commit()
    options = client.get(context.url.removesuffix("generations") + "generation-options").json()
    assert options["reference_frames"][0]["time_s"] == 1.8
    assert client.get(options["reference_frames"][0]["url"]).content == b"first selected image"
    commands = []

    def ffmpeg(args, **kwargs):
        commands.append(args)
        from pathlib import Path
        Path(args[-1]).write_bytes(b"scaled image")

    monkeypatch.setattr(workflow, "media_run", ffmpeg)
    with SessionLocal() as db:
        build_reference_frame(uid(), db.get(Asset, context.asset_id), 1.8)
    assert commands[0][commands[0].index("-i") + 1] == str((settings.data_dir / first_key).resolve())
    assert "-ss" not in commands[0]


def test_running_job_after_crash_resumes_without_resubmission(client, context, monkeypatch):
    calls = fake_generation(monkeypatch)
    job_id = post(client, context).json()["job_id"]
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        job.status = "running"
        job.data = {**job.data, "provider_submission_started": True, "provider_task_id": "provider-task-1"}
        db.commit()
    assert client.post(f"/api/v1/jobs/{job_id}/retry").status_code == 202
    assert client.get(f"/api/v1/jobs/{job_id}").json()["status"] == "succeeded"
    assert calls["submit"] == 0 and calls["query"] == 1


def test_downloaded_video_recovers_even_after_provider_task_expires(client, context, monkeypatch):
    calls = fake_generation(monkeypatch)
    job_id = post(client, context).json()["job_id"]
    asset_id = uid()
    target = settings.data_dir / f"assets/{context.project_id}/{asset_id}/original.mp4"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"previously downloaded video")
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        job.status = "failed"
        job.data = {**job.data, "provider_submission_started": True, "provider_task_id": "provider-task-1", "generated_asset_id": asset_id, "provider_terminal": True}
        db.commit()
    assert client.post(f"/api/v1/jobs/{job_id}/retry").status_code == 202
    job = client.get(f"/api/v1/jobs/{job_id}").json()
    assert job["status"] == "succeeded" and job["asset_id"] == asset_id
    assert calls == {"submit": 0, "query": 0, "download": 0, "preprocess": 1}


def test_live_job_cannot_be_entered_twice(client, context, monkeypatch):
    calls = fake_generation(monkeypatch)
    provider_class = workflow.HappyHorseProvider
    original_submit = provider_class.submit
    entered, release = threading.Event(), threading.Event()

    def wait_submit(self, *args):
        entered.set()
        assert release.wait(5)
        return original_submit(self, *args)

    monkeypatch.setattr(provider_class, "submit", wait_submit)
    job_id = post(client, context).json()["job_id"]
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(execute, job_id)
        try:
            assert entered.wait(5)
            # Duplicate queue delivery and retry must both leave the live owner alone.
            execute(job_id)
            assert client.post(f"/api/v1/jobs/{job_id}/retry").status_code == 202
            assert client.get(f"/api/v1/jobs/{job_id}").json()["status"] == "running"
        finally:
            release.set()
        future.result(timeout=5)
    assert calls["submit"] == 1


@pytest.mark.parametrize("prior_status", ["failed", "running", "queued"])
def test_upstream_outstanding_task_keeps_its_slot_after_worker_exit(client, context, monkeypatch, prior_status):
    calls = fake_generation(monkeypatch)
    monkeypatch.setattr(settings, "video_generation_concurrency", 1)
    job_id = post(client, context).json()["job_id"]
    with SessionLocal() as db:
        db.add(Job(project_id=context.project_id, type="generation", status=prior_status, data={"task_id": "other-task", "provider_submission_started": True, "provider_task_id": "other-provider-task", "duration_s": 5}))
        db.commit()
    execute(job_id)
    job = client.get(f"/api/v1/jobs/{job_id}").json()
    assert job["status"] == "failed" and not job["provider_submission_started"]
    assert calls["submit"] == 0


def test_definitive_provider_rejection_allows_new_explicit_generation(client, context, monkeypatch):
    class Rejected:
        def submit(self, *args):
            raise provider_module.SubmissionRejected("HTTP 403")

    monkeypatch.setattr(workflow, "HappyHorseProvider", Rejected)
    job_id = post(client, context).json()["job_id"]
    execute(job_id)
    job = client.get(f"/api/v1/jobs/{job_id}").json()
    assert job["provider_terminal"] and not job["generation_retryable"]
    assert client.post(f"/api/v1/jobs/{job_id}/retry").status_code == 409
    assert post(client, context, key="explicit-new-request").status_code == 202


def test_old_plan_does_not_revive_when_new_asset_clears_latest_pointer(client, context):
    with SessionLocal() as db:
        original = db.get(AnalysisRun, context.analysis_id)
        db.add(AnalysisRun(project_id=context.project_id, project_revision=2, asset_snapshot=original.asset_snapshot, config_hash=original.config_hash, status="succeeded", data=original.data, created_at="2099-01-01T00:00:00+00:00"))
        db.get(Project, context.project_id).latest_analysis_id = None
        db.commit()
    assert post(client, context).status_code == 409


@pytest.mark.parametrize("url", [
    "http://result.oss-cn-beijing.aliyuncs.com/a.mp4",
    "https://127.0.0.1/a.mp4", "https://evil.example/a.mp4",
    "https://user:secret@result.oss-cn-beijing.aliyuncs.com/a.mp4",
    "https://result.oss-cn-beijing.aliyuncs.com.evil.example/a.mp4",
    "https://result.oss-cn-beijing.aliyuncs.com:8000/a.mp4",
])
def test_download_rejects_untrusted_hosts(url):
    with pytest.raises(GenerationError):
        validate_download_url(url)


def test_download_rejects_private_dns(monkeypatch):
    monkeypatch.setattr(provider_module.socket, "getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("127.0.0.1", 443))])
    with pytest.raises(GenerationError):
        validate_download_url("https://result.oss-cn-beijing.aliyuncs.com/a.mp4")


def test_download_has_no_credentials_and_checks_redirects(monkeypatch, tmp_path):
    requests = []
    monkeypatch.setattr(provider_module.socket, "getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("8.8.8.8", 443))])

    class Opener:
        def open(self, request, timeout):
            requests.append(request)
            raise urllib.error.HTTPError(request.full_url, 302, "redirect", {"Location": "http://127.0.0.1/private?secret=abc"}, None)

    monkeypatch.setattr(provider_module.urllib.request, "build_opener", lambda *args: Opener())
    with pytest.raises(GenerationError) as error:
        download_video("https://result.oss-cn-beijing.aliyuncs.com/a.mp4?signature=private", tmp_path / "result.mp4")
    assert len(requests) == 1 and requests[0].get_header("Authorization") is None
    assert "signature" not in str(error.value) and "secret" not in str(error.value)


def test_download_stops_at_size_limit_and_removes_partial(monkeypatch, tmp_path):
    monkeypatch.setattr(provider_module, "validate_download_url", lambda url: url)
    monkeypatch.setattr(settings, "max_upload_mb", 1)

    class Response(io.BytesIO):
        headers = {}

    monkeypatch.setattr(provider_module.urllib.request, "build_opener", lambda *args: SimpleNamespace(open=lambda *args, **kwargs: Response(b"x" * (1024 * 1024 + 1))))
    target = tmp_path / "result.mp4"
    with pytest.raises(GenerationError, match="大小"):
        download_video("https://result.oss-cn-beijing.aliyuncs.com/a.mp4", target)
    assert not target.exists() and not target.with_suffix(".download").exists()
