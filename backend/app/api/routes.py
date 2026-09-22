import asyncio
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Annotated, Literal
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.config import settings
from app.models import (
    SessionLocal,
    Project,
    Asset,
    AnalysisRun,
    Evidence,
    Requirement,
    RequirementMatch,
    Gap,
    CompletionPlan,
    CompletionTask,
    Submission,
    EditVersion,
    Job,
    Idempotency,
    uid,
    serialize,
)
from app.schemas import (
    ProjectCreate,
    ProjectPatch,
    RequirementPatch,
    GapPatch,
    PlanCreate,
    SubmissionCreate,
    EditCreate,
)
from app.providers.storage import storage
from app.providers.media_sources import LocalUploadAdapter, Insta360Adapter
from app.services.media.pipeline import probe
from app.services.media.views import asset_shots
from app.services.diagnosis.vlog import select_key_evidence
from app.services.diagnosis.presentation import ReadableReferences
from app.services.media.demo import SCENARIOS, create_demo_asset
from app.services.planning.engine import plan_tasks
from app.services.editing.render import make_timeline, validate_timeline
from app.workflows.pipeline import create_analysis, rows
from app.workers.queue import dispatch

router = APIRouter(prefix="/api/v1")


def session():
    with SessionLocal() as db:
        yield db


DB = Annotated[Session, Depends(session)]
Key = Annotated[str | None, Header(alias="Idempotency-Key", max_length=200)]


def get(db, cls, id):
    row = db.get(cls, id)
    if not row:
        raise HTTPException(404, "对象不存在")
    return row


def bump(project):
    project.revision += 1
    project.latest_analysis_id = None


def check_current(db, run, project_id):
    p = get(db, Project, project_id)
    if run.project_id != project_id:
        raise HTTPException(404, "分析不属于当前项目")
    if run.status != "succeeded":
        raise HTTPException(409, "分析尚未成功完成")
    if run.project_revision != p.revision:
        raise HTTPException(409, "项目已更新，请重新分析后继续")
    return p


def request_fingerprint(payload):
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def repeated(db, scope, key, fingerprint):
    if not key:
        return None
    entry = db.scalar(
        select(Idempotency).where(Idempotency.scope == scope, Idempotency.key == key)
    )
    if entry and entry.fingerprint != fingerprint:
        raise HTTPException(409, "同一幂等键不能用于不同请求")
    return entry.response if entry else None


def remember(db, scope, key, fingerprint, response):
    if key:
        db.add(
            Idempotency(
                scope=scope, key=key, fingerprint=fingerprint, response=response
            )
        )


def commit_request(db, scope, key, fingerprint, response):
    try:
        db.commit()
        return response
    except IntegrityError:
        # Concurrent requests can race the initial read; the unique key is authoritative.
        db.rollback()
        previous = repeated(db, scope, key, fingerprint)
        if previous is not None:
            return previous
        raise


def job_for(db, project_id, kind, data):
    job = Job(id=uid(), project_id=project_id, type=kind, data=data)
    db.add(job)
    db.flush()
    return job


def asset_json(asset):
    data = serialize(asset)
    data.pop("storage_key", None)
    data.pop("sha256", None)
    meta = data.pop("meta")
    data.update(
        {
            "preview_url": f"/api/v1/assets/{asset.id}/media/preview"
            if meta.get("proxy_key")
            else None,
            "original_url": f"/api/v1/assets/{asset.id}/media/original",
            "thumbnail_url": f"/api/v1/assets/{asset.id}/media/thumbnail"
            if meta.get("thumbnail_key")
            else None,
            "audio_status": meta.get("audio_status", "pending"),
            "synthetic_media": meta.get("synthetic_media", False),
            "shots": asset_shots(asset),
            "shot_count": len(meta.get("scene_shots", [])),
            "segmentation_version": meta.get("segmentation_version"),
        }
    )
    return data


@router.get("/health")
def health():
    return {
        "name": "旭光集",
        "provider": settings.model_provider,
        "model_configured": bool(settings.model_api_key),
        "queue_mode": settings.queue_mode,
        "ffmpeg_available": bool(shutil.which(settings.ffmpeg_bin)),
        "asr_configured": bool(settings.asr_base_url and settings.asr_model),
        "limits": {
            "max_upload_mb": settings.max_upload_mb,
            "max_assets": settings.max_assets,
            "max_duration_s": settings.max_project_duration_s,
        },
        "model_destination": settings.model_base_url
        if settings.model_provider != "mock"
        else None,
    }


@router.get("/media-sources/capabilities")
def capabilities():
    return [LocalUploadAdapter().capabilities(), Insta360Adapter().capabilities()]


@router.get("/projects")
def projects(db: DB):
    result = []
    for p in db.scalars(select(Project).order_by(Project.created_at.desc())):
        assets = db.scalars(
            select(Asset).where(Asset.project_id == p.id).order_by(Asset.created_at)
        ).all()
        result.append(
            {
                **serialize(p),
                "asset_count": len(assets),
                "duration_s": sum(a.duration_s for a in assets),
                "cover_url": next(
                    (
                        asset_json(a)["thumbnail_url"]
                        for a in assets
                        if a.meta.get("thumbnail_key")
                    ),
                    None,
                ),
            }
        )
    return result


@router.post("/projects", status_code=201)
def create_project(body: ProjectCreate, db: DB):
    p = Project(**body.model_dump())
    db.add(p)
    db.commit()
    return serialize(p)


@router.get("/projects/{id}")
def project(id: str, db: DB):
    return serialize(get(db, Project, id))


@router.patch("/projects/{id}")
def patch_project(id: str, body: ProjectPatch, db: DB):
    p = get(db, Project, id)
    data = body.model_dump(exclude_none=True)
    primary = data.pop("primary_asset_id", None)
    if primary:
        asset = get(db, Asset, primary)
        if asset.project_id != id:
            raise HTTPException(404, "素材不属于本项目")
        p.constraints_json = {**p.constraints_json, "primary_asset_id": primary}
    if "intent" in data and data["intent"] != p.intent:
        p.constraints_json = {
            k: v
            for k, v in p.constraints_json.items()
            if k not in ("requirements", "gap_overrides")
        }
    for k, v in data.items():
        setattr(p, k, v)
    bump(p)
    db.commit()
    return serialize(p)


@router.get("/projects/{id}/assets")
def assets(id: str, db: DB):
    get(db, Project, id)
    return [
        asset_json(a)
        for a in db.scalars(
            select(Asset).where(Asset.project_id == id).order_by(Asset.created_at)
        )
    ]


@router.post("/projects/{id}/assets", status_code=202)
async def upload_asset(
    id: str,
    db: DB,
    file: UploadFile = File(),
    source_type: Literal[
        "real_capture", "ai_generated", "edited_video", "insta360_export", "unknown"
    ] = Form("unknown"),
    idempotency_key: Key = None,
):
    p = get(db, Project, id)
    aid = uid()
    folder = storage.path(f"assets/{id}/{aid}")
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "original.bin"
    size = 0
    digest = hashlib.sha256()
    try:
        with target.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > settings.max_upload_mb * 1024 * 1024:
                    raise HTTPException(413, "单文件超过上传限制")
                digest.update(chunk)
                out.write(chunk)
        fingerprint = request_fingerprint(
            {
                "sha256": digest.hexdigest(),
                "source_type": source_type,
                "name": file.filename,
            }
        )
        previous = repeated(db, f"upload:{id}", idempotency_key, fingerprint)
        if previous:
            shutil.rmtree(folder)
            return previous
        meta = await asyncio.to_thread(probe, target)
        # Serialize limits/revision mutations in PostgreSQL. Local mode runs one API process.
        p = db.scalar(
            select(Project)
            .where(Project.id == id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        previous = repeated(db, f"upload:{id}", idempotency_key, fingerprint)
        if previous:
            shutil.rmtree(folder)
            return previous
        existing = db.scalars(select(Asset).where(Asset.project_id == id)).all()
        if (
            len(existing) >= settings.max_assets
            or sum(a.duration_s for a in existing) + meta["duration_s"]
            > settings.max_project_duration_s
        ):
            raise HTTPException(413, "超过项目素材数量或总时长限制")
        asset = Asset(
            id=aid,
            project_id=id,
            source_type=source_type,
            original_name=Path((file.filename or "video").replace("\\", "/")).name[
                :250
            ],
            storage_key=str(target.relative_to(settings.data_dir.resolve())),
            sha256=digest.hexdigest(),
            duration_s=meta["duration_s"],
            width=meta["width"],
            height=meta["height"],
            has_audio=meta["has_audio"],
            meta={"source_start_time": meta["source_start_time"]},
        )
        db.add(asset)
        db.flush()
        if p.input_mode in ("vlog", "rough_cut") and not p.constraints_json.get(
            "primary_asset_id"
        ):
            p.constraints_json = {**p.constraints_json, "primary_asset_id": aid}
        bump(p)
        job = job_for(db, id, "preprocess", {"asset_id": aid})
        response = {"asset_id": aid, "job_id": job.id}
        remember(db, f"upload:{id}", idempotency_key, fingerprint, response)
        response = commit_request(
            db, f"upload:{id}", idempotency_key, fingerprint, response
        )
        if response["asset_id"] != aid:
            shutil.rmtree(folder)
        dispatch(response["job_id"])
        return response
    except Exception:
        db.rollback()
        if not db.get(Asset, aid):
            shutil.rmtree(folder, ignore_errors=True)
        raise
    finally:
        await file.close()


@router.get("/assets/{id}/media/{kind}")
def media(id: str, kind: Literal["preview", "original", "thumbnail"], db: DB):
    asset = get(db, Asset, id)
    key = (
        asset.storage_key
        if kind == "original"
        else asset.meta.get("proxy_key" if kind == "preview" else "thumbnail_key")
    )
    if not key or not storage.path(key).is_file():
        raise HTTPException(404, "媒体尚未就绪")
    return FileResponse(
        storage.path(key),
        media_type="image/jpeg"
        if kind == "thumbnail"
        else "video/mp4"
        if kind == "preview"
        else None,
    )


@router.get("/assets/{id}/frame")
def reference_frame(id: str, db: DB, at: float = 0):
    asset = get(db, Asset, id)
    if not 0 <= at < asset.duration_s:
        raise HTTPException(422, "参考帧时间超出素材范围")
    scene = next((s for s in asset.meta.get("scene_shots", []) if s["start_s"] <= at < s["end_s"]), None)
    frames = [f for shot in asset.meta.get("shots", [])
              if scene is None or shot.get("shot_id") == scene["id"]
              for f in shot["keyframes"]]
    if scene:
        frames += scene["keyframes"]
    if not frames:
        raise HTTPException(404, "参考帧尚未准备好")
    frame = min(frames, key=lambda f: abs(f["time_s"] - at))
    return FileResponse(storage.path(frame["key"]), media_type="image/jpeg")


@router.post("/projects/{id}/analyses", status_code=202)
def start_analysis(id: str, db: DB, idempotency_key: Key = None):
    p = get(db, Project, id)
    fingerprint = request_fingerprint({"project_id": id, "revision": p.revision})
    # An analysis retry reuses the original snapshot, even if project revision changed later.
    if idempotency_key:
        old = db.scalar(
            select(Idempotency).where(
                Idempotency.scope == f"analysis:{id}",
                Idempotency.key == idempotency_key,
            )
        )
        if old:
            return old.response
    run = create_analysis(db, p)
    job = job_for(db, id, "analysis", {"analysis_id": run.id})
    response = {"analysis_id": run.id, "job_id": job.id}
    remember(db, f"analysis:{id}", idempotency_key, fingerprint, response)
    response = commit_request(
        db, f"analysis:{id}", idempotency_key, fingerprint, response
    )
    dispatch(response["job_id"])
    return response


@router.get("/projects/{id}/analyses")
def analyses(id: str, db: DB):
    p = get(db, Project, id)
    return [
        {**serialize(r), "stale": r.project_revision != p.revision}
        for r in db.scalars(
            select(AnalysisRun)
            .where(AnalysisRun.project_id == id)
            .order_by(AnalysisRun.created_at.desc())
        )
    ]


@router.get("/analyses/{id}")
def analysis(id: str, db: DB):
    run = get(db, AnalysisRun, id)
    return {
        **serialize(run),
        "stale": run.project_revision != get(db, Project, run.project_id).revision,
    }


@router.get("/analyses/{id}/diagnosis")
def diagnosis(id: str, db: DB):
    run = get(db, AnalysisRun, id)
    evidence = rows(db, Evidence, id)
    gaps = rows(db, Gap, id)
    for gap in gaps:
        gap["evidence_ids"] = select_key_evidence(evidence, gap["evidence_ids"], limit=2)
    return ReadableReferences(run.data.get("shots", []), evidence).payload({
        "analysis": analysis(id, db),
        "requirements": rows(db, Requirement, id),
        "evidence": evidence,
        "matches": rows(db, RequirementMatch, id),
        "gaps": gaps,
        "shots": run.data.get("shots", []),
        "vlog": run.data.get("vlog"),
    })


@router.patch("/requirements/{id}")
def patch_requirement(id: str, body: RequirementPatch, db: DB):
    row = get(db, Requirement, id)
    run = get(db, AnalysisRun, row.analysis_id)
    p = check_current(db, run, row.project_id)
    edits = body.model_dump(exclude_none=True)
    row.data = {**row.data, **edits, "human_modified": True}
    db.flush()
    values = [
        {
            k: v
            for k, v in r.items()
            if k not in ("id", "created_at", "project_id", "analysis_id")
        }
        for r in rows(db, Requirement, run.id)
    ]
    p.constraints_json = {**p.constraints_json, "requirements": values}
    bump(p)
    db.commit()
    return {**serialize(row), "needs_reanalysis": True}


@router.patch("/gaps/{id}")
def patch_gap(id: str, body: GapPatch, db: DB):
    row = get(db, Gap, id)
    check_current(db, get(db, AnalysisRun, row.analysis_id), row.project_id)
    p = get(db, Project, row.project_id)
    row.data = {**row.data, "status": body.status, "human_reason": body.reason}
    overrides = {
        **p.constraints_json.get("gap_overrides", {}),
        row.data.get("issue_key", row.data["description"]): {"status": body.status, "reason": body.reason},
    }
    p.constraints_json = {**p.constraints_json, "gap_overrides": overrides}
    db.commit()
    return serialize(row)


@router.post("/projects/{id}/completion-plans", status_code=201)
def start_plan(id: str, body: PlanCreate, db: DB):
    run = get(db, AnalysisRun, body.analysis_id)
    p = check_current(db, run, id)
    result = plan_tasks(
        rows(db, Gap, run.id),
        rows(db, Requirement, run.id),
        rows(db, Evidence, run.id),
        body.budget_min,
        bool(p.demo_scenario),
    )
    tasks = result.pop("tasks")
    plan = CompletionPlan(id=uid(), project_id=id, analysis_id=run.id, data=result)
    db.add(plan)
    db.flush()
    for task in tasks:
        task_id = task.pop("id")
        db.add(CompletionTask(id=task_id, project_id=id, plan_id=plan.id, data=task))
    db.commit()
    return get_plan(plan.id, db)


@router.get("/completion-plans/{id}")
def get_plan(id: str, db: DB):
    plan = get(db, CompletionPlan, id)
    tasks = []
    for t in db.scalars(
        select(CompletionTask)
        .where(CompletionTask.plan_id == id)
        .order_by(CompletionTask.created_at)
    ):
        tasks.append(
            {
                **serialize(t),
                "submissions": [
                    serialize(s)
                    for s in db.scalars(
                        select(Submission)
                        .where(Submission.task_id == t.id)
                        .order_by(Submission.created_at.desc())
                    )
                ],
            }
        )
    run = get(db, AnalysisRun, plan.analysis_id)
    evidence = rows(db, Evidence, run.id)
    shots = list(run.data.get("shots", []))
    submitted_assets = set()
    for task in tasks:
        for submission in task["submissions"]:
            evidence.extend(submission.get("new_evidence", []))
            submitted_assets.add(submission["asset_id"])
    if submitted_assets:
        for asset in db.scalars(select(Asset).where(
            Asset.project_id == plan.project_id, Asset.id.in_(submitted_assets),
        )):
            shots.extend(asset.meta.get("scene_shots", []))
    return ReadableReferences(shots, evidence).payload(
        {**serialize(plan), "tasks": tasks}
    )


@router.get("/projects/{id}/completion-plans")
def list_plans(id: str, db: DB):
    get(db, Project, id)
    return [
        get_plan(p.id, db)
        for p in db.scalars(
            select(CompletionPlan)
            .where(CompletionPlan.project_id == id)
            .order_by(CompletionPlan.created_at.desc())
        )
    ]


@router.post("/completion-tasks/{id}/submissions", status_code=202)
def submit(id: str, body: SubmissionCreate, db: DB, idempotency_key: Key = None):
    task = get(db, CompletionTask, id)
    asset = get(db, Asset, body.asset_id)
    if asset.project_id != task.project_id:
        raise HTTPException(404, "素材不属于任务项目")
    fingerprint = request_fingerprint(body.model_dump())
    old = repeated(db, f"submit:{id}", idempotency_key, fingerprint)
    if old:
        return old
    p = get(db, Project, task.project_id)
    plan = get(db, CompletionPlan, task.plan_id)
    run = get(db, AnalysisRun, plan.analysis_id)
    if asset.id in run.asset_snapshot:
        raise HTTPException(409, "请选择本次分析之后补充的新素材")
    if asset.status != "ready":
        raise HTTPException(409, "素材预处理尚未成功完成")
    if p.intent != run.data["project_config"]["intent"] or p.constraints_json.get(
        "requirements"
    ) != run.data["project_config"]["constraints_json"].get("requirements"):
        raise HTTPException(409, "创作需求已变更，请重新分析并生成任务")
    if p.input_mode != run.data["project_config"]["input_mode"] or p.constraints_json.get("primary_asset_id") != run.data["project_config"]["constraints_json"].get("primary_asset_id"):
        raise HTTPException(409, "主片或分析模式已变更，请重新分析并生成任务")
    sub = Submission(
        id=uid(),
        project_id=p.id,
        task_id=id,
        asset_id=asset.id,
        data={"project_revision": p.revision},
    )
    db.add(sub)
    db.flush()
    job = job_for(db, p.id, "verification", {"submission_id": sub.id})
    response = {"submission_id": sub.id, "job_id": job.id}
    remember(db, f"submit:{id}", idempotency_key, fingerprint, response)
    response = commit_request(
        db, f"submit:{id}", idempotency_key, fingerprint, response
    )
    dispatch(response["job_id"])
    return response


@router.post("/projects/{id}/edits", status_code=202)
def create_edit(id: str, body: EditCreate, db: DB):
    run = get(db, AnalysisRun, body.analysis_id)
    p = check_current(db, run, id)
    assets = list(
        db.scalars(
            select(Asset)
            .where(Asset.project_id == id, Asset.status == "ready")
            .order_by(Asset.created_at)
        )
    )
    primary = p.constraints_json.get("primary_asset_id")
    protected = p.input_mode in ("vlog", "rough_cut", "mixed") and not body.allow_reedit
    duration_limit = settings.max_project_duration_s if p.input_mode == "vlog" else p.target_duration_s
    automatic_primary = primary if protected or p.input_mode == "vlog" else None
    if body.timeline is not None and protected:
        raise HTTPException(
            409, "初稿默认保留原顺序；需明确允许重剪才能提交自定义时间线"
        )
    timeline = (
        [c.model_dump() for c in body.timeline]
        if body.timeline is not None
        else make_timeline(
            eligible_render_assets(db, id, assets, automatic_primary),
            rows(db, Evidence, run.id),
            rows(db, RequirementMatch, run.id),
            duration_limit,
            automatic_primary,
        )
    )
    total = validate_timeline(timeline, {a.id: a for a in assets}, duration_limit)
    edit = EditVersion(
        id=uid(),
        project_id=id,
        analysis_id=run.id,
        data={
            "timeline": timeline,
            "project_revision": p.revision,
            "duration_s": total,
            "allow_reedit": body.allow_reedit,
            "note": "直切粗剪；已烘焙的字幕与音乐不会被拆分，重新编排可能造成音频衔接突兀。"
            if p.input_mode != "clips"
            else "直切粗剪，保留原片声音；无音轨素材补静音。不自动添加配乐。",
        },
    )
    db.add(edit)
    db.flush()
    job = job_for(db, id, "render", {"edit_id": edit.id})
    db.commit()
    dispatch(job.id)
    return {"edit_id": edit.id, "job_id": job.id}


def eligible_render_assets(db, project_id, assets, protected_primary=None):
    submissions = db.scalars(
        select(Submission).where(Submission.project_id == project_id)
    ).all()
    passed = {
        s.asset_id
        for s in submissions
        if s.verification_status == "passed" and not s.data.get("stale")
    }
    unverified = {s.asset_id for s in submissions if s.asset_id not in passed}
    # Never automatically add rejected/uncertain task submissions to the finished sequence.
    return [a for a in assets if a.id not in unverified or a.id == protected_primary]


@router.get("/edits/{id}")
def get_edit(id: str, db: DB):
    row = get(db, EditVersion, id)
    data = serialize(row)
    data.pop("output_key", None)
    return {
        **data,
        "output_url": f"/api/v1/edits/{id}/video" if row.output_key else None,
        "edl_url": f"/api/v1/edits/{id}/edl",
    }


@router.get("/projects/{id}/edits")
def list_edits(id: str, db: DB):
    get(db, Project, id)
    return [
        get_edit(e.id, db)
        for e in db.scalars(
            select(EditVersion)
            .where(EditVersion.project_id == id)
            .order_by(EditVersion.created_at.desc())
        )
    ]


@router.get("/edits/{id}/video")
def edit_video(id: str, db: DB):
    edit = get(db, EditVersion, id)
    if not edit.output_key or not storage.path(edit.output_key).is_file():
        raise HTTPException(404, "视频还未生成")
    return FileResponse(
        storage.path(edit.output_key),
        media_type="video/mp4",
        filename="旭光集-粗剪.mp4",
        content_disposition_type="inline",
    )


@router.get("/edits/{id}/edl")
def edit_edl(id: str, db: DB):
    edit = get(db, EditVersion, id)
    return JSONResponse(
        {
            "version": 1,
            "time_unit": "source_seconds",
            "interval": "[in, out)",
            "timeline": edit.data["timeline"],
        },
        headers={"Content-Disposition": 'attachment; filename="timeline.json"'},
    )


@router.get("/jobs/{id}")
def get_job(id: str, db: DB):
    return serialize(get(db, Job, id))


@router.get("/projects/{id}/jobs")
def list_jobs(id: str, db: DB):
    get(db, Project, id)
    return [
        serialize(j)
        for j in db.scalars(
            select(Job)
            .where(Job.project_id == id)
            .order_by(Job.created_at.desc())
            .limit(30)
        )
    ]


@router.get("/jobs/{id}/events")
async def job_events(id: str, request: Request):
    with SessionLocal() as db:
        get(db, Job, id)

    async def events():
        last = None
        while not await request.is_disconnected():
            with SessionLocal() as db:
                row = get_job(id, db)
            payload = json.dumps(row, ensure_ascii=False)
            if payload != last:
                yield f"id: {hashlib.sha256(payload.encode()).hexdigest()[:16]}\ndata: {payload}\n\n"
                last = payload
            else:
                yield ": keepalive\n\n"
            if row["status"] in ("succeeded", "failed", "cancelled"):
                break
            await asyncio.sleep(1)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/jobs/{id}/retry", status_code=202)
def retry_job(id: str, db: DB):
    job = get(db, Job, id)
    if job.status in ("running", "queued"):
        return serialize(job)
    if job.status != "failed":
        raise HTTPException(409, "只允许重试失败任务")
    job.status, job.error_code, job.error_message = "queued", None, None
    job.retry_count += 1
    db.commit()
    dispatch(job.id)
    return serialize(job)


@router.post("/demo", status_code=201)
def demo(db: DB, scenario: str = "missing"):
    if settings.model_provider != "mock":
        raise HTTPException(
            409, "演示样例仅在演示模式创建，避免意外发送演示媒体到模型服务"
        )
    if scenario not in SCENARIOS:
        raise HTTPException(422, "未知演示案例")
    p = Project(
        id=uid(),
        title={
            "missing": "一杯咖啡的午后",
            "complete": "完整故事 · 演示",
            "unordered": "镜头乱序 · 演示",
            "montage": "光影氛围 · 演示",
        }.get(scenario, "叙事验证 · " + scenario),
        intent="交代窗边的创作场景，展示清晰的咖啡制作过程，呈现完成后的结果。"
        if scenario != "montage"
        else "感受午后的光线与氛围，不需要完整因果故事。",
        target_duration_s=30,
        style="温暖 / 日常记录",
        demo_scenario=scenario,
    )
    db.add(p)
    db.flush()
    jobs = []
    for role in SCENARIOS[scenario]:
        asset = create_demo_asset(db, p, role)
        jobs.append(job_for(db, p.id, "preprocess", {"asset_id": asset.id}).id)
    db.commit()
    for job_id in jobs:
        dispatch(job_id)
    return {**serialize(p), "job_ids": jobs}


@router.post("/projects/{id}/demo-asset", status_code=202)
def demo_asset(id: str, db: DB, role: str = "process"):
    p = get(db, Project, id)
    if not p.demo_scenario or settings.model_provider != "mock":
        raise HTTPException(409, "仅用于固定演示样例")
    existing = db.scalars(select(Asset).where(Asset.project_id == id)).all()
    if (
        len(existing) >= settings.max_assets
        or sum(a.duration_s for a in existing) + 5 > settings.max_project_duration_s
    ):
        raise HTTPException(413, "超过项目素材限制")
    asset = create_demo_asset(db, p, role)
    job = job_for(db, p.id, "preprocess", {"asset_id": asset.id})
    db.commit()
    dispatch(job.id)
    return {"asset_id": asset.id, "job_id": job.id}
