"""Durable I2V orchestration: submit once, resume queries/download/preprocessing."""
import hashlib
import time
from types import SimpleNamespace
from sqlalchemy import select

from app.config import settings
from app.models import SessionLocal, Job, Asset, Project, uid
from app.providers.storage import storage
from app.providers.video_generation import HappyHorseProvider, GenerationError, SubmissionRejected, download_video
from app.services.concurrency import resource_slot
from app.services.generation import generation_context, check_capacity
from app.services.media.pipeline import run as media_run, probe
from app.services.media.views import selected_reference_frame
from app.workflows.pipeline import process_asset


def update_job(job_id, **changes):
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        job.data = {**job.data, **changes}
        db.commit()
        return dict(job.data)


def reference_frame(job_id, asset, time_s):
    selected = selected_reference_frame(asset, time_s)
    source = storage.path(selected["key"])
    if not source.is_file():
        raise GenerationError("参考素材原文件不存在，请重新上传")
    if not 0.4 <= asset.width / asset.height <= 2.5:
        raise GenerationError("参考首帧比例超出 HappyHorse 支持范围")
    target = storage.path(f"generation/{job_id}/first-frame.jpg")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        media_run([
            settings.ffmpeg_bin, "-y",
            "-protocol_whitelist", "file,pipe", "-i", str(source),
            "-frames:v", "1", "-an", "-vf",
            "scale='if(gte(iw,ih),-2,640)':'if(gte(iw,ih),640,-2)'",
            "-q:v", "3", str(target),
        ], timeout=60)
    except Exception:
        raise GenerationError("生成参考首帧失败，请检查原视频是否可解码") from None
    if not target.is_file() or not 0 < target.stat().st_size <= 20 * 1024 * 1024:
        raise GenerationError("参考首帧为空或超过 20MB")
    return target


def _resume_asset(job_id, data, progress):
    with SessionLocal() as db:
        asset = db.get(Asset, data["asset_id"])
        if not asset:
            raise GenerationError("生成素材记录不存在，无法恢复")
        ready = asset.status == "ready"
    if not ready:
        progress("生成完成，正在预处理片段", 3, 4)
        process_asset(SimpleNamespace(data={"asset_id": data["asset_id"]}), progress)
    update_job(job_id, generation_state="ready")
    progress("AI 片段已保存，可预览并提交验收", 4, 4)


def generate_video(job, progress):
    # Hold this independent slot for the complete upstream task, not just HTTP
    # calls: HappyHorse's limit counts outstanding video-generation tasks.
    progress("等待 AI 视频生成名额", 0, 4)
    with resource_slot("video-generation", settings.video_generation_concurrency):
        with SessionLocal() as db:
            current = db.get(Job, job.id)
            data = dict(current.data)
            project_id = current.project_id
        if data.get("asset_id"):
            return _resume_asset(job.id, data, progress)
        if data.get("generated_asset_id"):
            saved = storage.path(f"assets/{project_id}/{data['generated_asset_id']}/original.mp4")
            if saved.is_file():
                digest = hashlib.sha256(saved.read_bytes()).hexdigest()
                return _store_video(job.id, project_id, data, saved, digest, progress)
        if data.get("provider_terminal"):
            raise GenerationError("百炼任务已结束且未生成视频，请查看失败原因后新建生成任务")
        if data.get("provider_submission_started") and not data.get("provider_task_id"):
            raise GenerationError("上次提交结果尚未确认；为避免重复计费，不会自动重新提交，请在百炼控制台核查")
        provider = HappyHorseProvider()
        if not data.get("provider_task_id"):
            with SessionLocal() as db:
                _, _, _, references = generation_context(db, data["task_id"])
                if data["model"] != settings.video_generation_model:
                    raise GenerationError("视频生成模型配置已变更，请重新创建任务")
                if not any(f["asset_id"] == data["reference_asset_id"] and abs(f["time_s"] - data["reference_time_s"]) < 0.001 for f in references):
                    raise GenerationError("参考首帧已不属于该补全建议")
                check_capacity(db, project_id, data["duration_s"], exclude_job_id=job.id)
                asset = db.get(Asset, data["reference_asset_id"])
                first_frame = reference_frame(job.id, asset, data["reference_time_s"])
            progress("正在提交 HappyHorse 图生视频任务", 1, 4)
            # Commit before sending a billable request. A crash or timeout in the
            # following gap may require manual reconciliation, never a second POST.
            with resource_slot("video-generation-submit", 1):
                with SessionLocal() as db:
                    outstanding = [row for row in db.scalars(select(Job).where(Job.type == "generation"))
                                   if row.id != job.id and row.data.get("provider_submission_started")
                                   and not row.data.get("provider_terminal") and not row.data.get("asset_id")]
                if len(outstanding) >= settings.video_generation_concurrency:
                    raise GenerationError("已有视频生成任务占用名额，请先恢复查询或核实这些任务后再生成新片段")
                data = update_job(job.id, provider_submission_started=True, generation_state="submitting")
            try:
                task_id = provider.submit(data["prompt"], first_frame, data["duration_s"], data["resolution"])
            except SubmissionRejected:
                update_job(job.id, provider_terminal=True, generation_state="rejected")
                raise
            data = update_job(job.id, provider_task_id=task_id, generation_state="submitted")
        progress("HappyHorse 正在生成片段，通常需要 1—5 分钟", 2, 4)
        deadline = time.monotonic() + settings.video_generation_timeout_s
        while True:
            output = provider.query(data["provider_task_id"])
            state = output.get("task_status")
            if state == "SUCCEEDED":
                video_url = output.get("video_url")
                if not isinstance(video_url, str) or not video_url:
                    raise GenerationError("百炼任务已成功，但视频地址尚不可用；可重试获取")
                break
            if state in ("FAILED", "CANCELED", "UNKNOWN"):
                update_job(job.id, provider_terminal=True, generation_state=str(state).lower())
                raise GenerationError("百炼视频生成失败、取消或任务已过期；请检查控制台后重新创建生成任务")
            if state not in ("PENDING", "RUNNING"):
                raise GenerationError("百炼返回未知任务状态；可重试继续查询")
            if time.monotonic() >= deadline:
                raise GenerationError("视频生成等待超时；可重试原任务继续查询，不会再次提交或重复计费")
            time.sleep(settings.video_generation_poll_s)
        progress("生成完成，正在下载片段", 3, 4)
        asset_id = data.get("generated_asset_id") or uid()
        data = update_job(job.id, generated_asset_id=asset_id, generation_state="downloading")
        key = f"assets/{project_id}/{asset_id}/original.mp4"
        target = storage.path(key)
        if target.is_file():
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
        else:
            digest = download_video(video_url, target)
        return _store_video(job.id, project_id, data, target, digest, progress)


def _store_video(job_id, project_id, data, target, digest, progress):
    asset_id = data["generated_asset_id"]
    key = str(target.relative_to(settings.data_dir.resolve()))
    try:
        metadata = probe(target)
    except Exception:
        target.unlink(missing_ok=True)
        raise GenerationError("生成结果不是可解码的视频；可重试重新下载") from None
    # Persist the asset and its job link in one transaction. A resumed job
    # cannot create a duplicate Asset or increment the project revision twice.
    with resource_slot("generation-project-" + project_id, 1):
        with SessionLocal() as db:
            project = db.scalar(select(Project).where(Project.id == project_id).with_for_update())
            check_capacity(db, project_id, metadata["duration_s"], exclude_job_id=job_id)
            asset = Asset(
                id=asset_id, project_id=project_id, source_type="ai_generated",
                original_name=f"AI补全-{data['model']}-{job_id[:8]}.mp4",
                storage_key=key, sha256=digest, duration_s=metadata["duration_s"],
                width=metadata["width"], height=metadata["height"], has_audio=metadata["has_audio"],
                meta={
                    "source_start_time": metadata["source_start_time"], "synthetic_media": True,
                    "generation": {
                        "model": data["model"], "job_id": job_id,
                        "provider_task_id": data["provider_task_id"], "completion_task_id": data["task_id"],
                        "reference_asset_id": data["reference_asset_id"], "reference_time_s": data["reference_time_s"],
                        "prompt": data["prompt"], "watermark": True,
                        "requires_review": True,
                    },
                },
            )
            db.add(asset)
            project.revision += 1
            project.latest_analysis_id = None
            current = db.get(Job, job_id)
            current.data = {**current.data, "asset_id": asset_id, "generation_state": "preprocessing"}
            db.commit()
            data = dict(current.data)
    return _resume_asset(job_id, data, progress)
