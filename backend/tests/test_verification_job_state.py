import pytest
from sqlalchemy import select

from app.config import settings
from app.models import (
    AnalysisRun, Asset, CompletionPlan, CompletionTask, Job, Project,
    SessionLocal, Submission, User, uid,
)
from app.workers import queue
from app.workflows import pipeline


@pytest.fixture
def verification_job(client):
    with SessionLocal() as db:
        project = Project(
            id=uid(), owner_id=db.scalar(select(User.id)),
            title="补拍状态", intent="观察制作过程",
        )
        db.add(project)
        db.flush()
        asset = Asset(
            id=uid(), project_id=project.id, source_type="real_capture",
            original_name="pickup.mp4", storage_key="unused.mp4", sha256="test",
            duration_s=4, width=320, height=180, has_audio=False, status="ready",
        )
        run = AnalysisRun(
            id=uid(), project_id=project.id, project_revision=1,
            asset_snapshot=[], config_hash="test", status="succeeded", data={},
        )
        db.add_all([asset, run])
        db.flush()
        plan = CompletionPlan(id=uid(), project_id=project.id, analysis_id=run.id, data={})
        db.add(plan)
        db.flush()
        task = CompletionTask(id=uid(), project_id=project.id, plan_id=plan.id, data={})
        db.add(task)
        db.flush()
        submission = Submission(
            id=uid(), project_id=project.id, task_id=task.id, asset_id=asset.id,
            data={"project_revision": 1, "processing_error": "上次执行中断"},
        )
        db.add(submission)
        db.flush()
        job = Job(
            id=uid(), project_id=project.id, type="verification",
            data={"submission_id": submission.id},
        )
        db.add(job)
        db.commit()
        return job.id, submission.id


def test_processing_exception_is_not_a_negative_verification_verdict(verification_job, monkeypatch):
    job_id, submission_id = verification_job

    def interrupted(job, progress):
        with SessionLocal() as db:
            submission = db.get(Submission, submission_id)
            assert submission.verification_status == "running"
            assert "processing_error" not in submission.data
        raise ValueError("模型服务暂时不可用")

    monkeypatch.setattr(pipeline, "verify_submission", interrupted)
    queue.execute(job_id)
    with SessionLocal() as db:
        submission = db.get(Submission, submission_id)
        assert db.get(Job, job_id).status == "failed"
        assert submission.verification_status == "error"
        assert submission.data["processing_error"] == "模型服务暂时不可用"
        assert "checks" not in submission.data


def test_negative_verdict_stays_failed_with_successful_job(verification_job, monkeypatch):
    job_id, submission_id = verification_job

    def negative_result(job, progress):
        with SessionLocal() as db:
            submission = db.get(Submission, submission_id)
            submission.verification_status = "failed"
            submission.data = {**submission.data, "reason": "没有看到倒水动作"}
            db.commit()

    monkeypatch.setattr(pipeline, "verify_submission", negative_result)
    queue.execute(job_id)
    with SessionLocal() as db:
        submission = db.get(Submission, submission_id)
        assert db.get(Job, job_id).status == "succeeded"
        assert submission.verification_status == "failed"
        assert submission.data["reason"] == "没有看到倒水动作"
        assert "processing_error" not in submission.data


def test_queue_unavailable_also_marks_submission_interrupted(verification_job, monkeypatch):
    job_id, submission_id = verification_job
    monkeypatch.setattr(settings, "queue_mode", "celery")

    def unavailable(*args):
        raise ConnectionError("broker unavailable")

    monkeypatch.setattr(queue.celery_execute, "delay", unavailable)
    queue.dispatch(job_id)
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        submission = db.get(Submission, submission_id)
        assert job.error_code == "QUEUE_UNAVAILABLE"
        assert submission.verification_status == "error"
        assert submission.data["processing_error"] == job.error_message


def test_retry_requeues_submission_and_clears_old_progress(client, verification_job, monkeypatch):
    from app.api import routes

    job_id, submission_id = verification_job
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        job.status = "failed"
        job.error_code = "PROCESSING_FAILED"
        job.error_message = "上次执行中断"
        job.stage, job.completed_units, job.total_units = "逐项验证验收条件", 3, 4
        submission = db.get(Submission, submission_id)
        submission.verification_status = "error"
        db.commit()

    dispatched = []
    monkeypatch.setattr(routes, "dispatch", dispatched.append)
    response = client.post(f"/api/v1/jobs/{job_id}/retry")

    assert response.status_code == 202, response.text
    assert dispatched == [job_id]
    result = response.json()
    assert result["status"] == "queued"
    assert result["error_code"] is None and result["error_message"] is None
    assert result["stage"] == "等待补拍分析"
    assert result["completed_units"] == result["total_units"] == 0
    with SessionLocal() as db:
        submission = db.get(Submission, submission_id)
        assert submission.verification_status == "queued"
        assert "processing_error" not in submission.data
        assert submission.data["project_revision"] == 1
        assert db.get(Job, job_id).retry_count == 1
