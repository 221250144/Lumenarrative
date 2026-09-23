from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.api.routes import DB, Key, get, request_fingerprint, repeated, remember, commit_request, job_for
from app.config import settings
from app.models import CompletionTask, Project, serialize
from app.providers.video_generation import GenerationError
from app.services.concurrency import resource_slot
from app.services.generation import generation_context, generation_jobs, default_prompt, retryable, check_capacity, reserved_generation_duration, readable_task_references
from app.workers.queue import dispatch

router = APIRouter(prefix="/api/v1")


class GenerationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    prompt: str = Field(min_length=1, max_length=2000)
    duration_s: int = Field(default=5, ge=3, le=15, strict=True)
    resolution: Literal["480P", "720P", "1080P"] = "720P"
    reference_asset_id: str = Field(min_length=1, max_length=36)
    reference_time_s: float = Field(ge=0, allow_inf_nan=False)


def job_json(job):
    return {**serialize(job), "generation_retryable": retryable(job)}


def blocked_previous(jobs):
    for job in jobs:
        if job.status in ("queued", "running"):
            return "该补全任务已有片段正在生成，请等待完成"
        if job.data.get("provider_submission_started") and not job.data.get("provider_task_id") and not job.data.get("provider_terminal"):
            return "上次提交结果尚未确认，为避免重复计费已暂停新生成；请先在百炼控制台核查任务"
        if job.status == "failed" and job.data.get("provider_task_id") and not job.data.get("provider_terminal") and not job.data.get("asset_id"):
            return "上次生成可恢复，请先重试原任务以继续查询或下载，不要再次付费生成"
    return None


@router.get("/completion-tasks/{id}/generation-options")
def generation_options(id: str, db: DB):
    task = get(db, CompletionTask, id)
    jobs = generation_jobs(db, id)
    readable = readable_task_references(db, task)
    duration = round(float((task.data.get("recommendation") or {}).get("duration_s", 5)))
    result = {
        "available": False, "model": settings.video_generation_model,
        "prompt": default_prompt(task, readable), "duration_s": max(3, min(15, duration)),
        "resolution": "720P", "reference_frames": [],
        "latest_job": job_json(jobs[0]) if jobs else None,
    }
    try:
        _, project, _, references = generation_context(db, id)
        result["reference_frames"] = [
            {**frame, "caption": readable.text(frame["caption"])[:300]}
            for frame in references
        ]
        if reason := blocked_previous(jobs):
            raise GenerationError(reason)
        check_capacity(db, project.id, reserved_generation_duration(result["duration_s"]))
        result["available"] = True
    except GenerationError as error:
        result["reason"] = str(error)
    return result


@router.get("/completion-tasks/{id}/generations")
def generations(id: str, db: DB):
    get(db, CompletionTask, id)
    return [job_json(job) for job in generation_jobs(db, id)]


@router.post("/completion-tasks/{id}/generations", status_code=202)
def generate(id: str, body: GenerationCreate, db: DB, idempotency_key: Key = None):
    if not idempotency_key or not idempotency_key.strip():
        raise HTTPException(400, "视频生成必须提供 Idempotency-Key 以避免重复计费")
    task = get(db, CompletionTask, id, lock=False)
    project_id = task.project_id
    scope, fingerprint = f"generation:{id}", request_fingerprint(body.model_dump())
    # POSIX lock also serializes local SQLite requests; PostgreSQL row lock protects
    # quota reservations against uploads and other writers across API workers.
    db.rollback()
    with resource_slot("generation-project-" + project_id, 1):
        # Revalidate ownership and deletion after acquiring the lock. A project
        # may have been deleted while this request waited for another upload.
        get(db, Project, project_id, lock=True)
        if previous := repeated(db, scope, idempotency_key, fingerprint):
            return previous
        try:
            _, project, run, references = generation_context(db, id)
            if reason := blocked_previous(generation_jobs(db, id)):
                raise GenerationError(reason)
            if not any(frame["asset_id"] == body.reference_asset_id and abs(frame["time_s"] - body.reference_time_s) < 0.001 for frame in references):
                raise GenerationError("首帧必须选择该补全建议提供的画面证据")
            check_capacity(db, project.id, reserved_generation_duration(body.duration_s))
        except GenerationError as error:
            raise HTTPException(409, str(error)) from None
        job = job_for(db, project.id, "generation", {
            **body.model_dump(), "task_id": id, "source_analysis_id": run.id,
            "model": settings.video_generation_model, "watermark": True,
            "provider_submission_started": False,
        })
        response = {"job_id": job.id}
        remember(db, scope, idempotency_key, fingerprint, response)
        response = commit_request(db, scope, idempotency_key, fingerprint, response)
    dispatch(response["job_id"])
    return response
