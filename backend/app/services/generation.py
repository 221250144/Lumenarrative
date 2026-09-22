"""Shared eligibility and quota rules for the API and asynchronous worker."""
import math
from sqlalchemy import select
from app.config import settings
from app.models import Project, Asset, AnalysisRun, CompletionTask, CompletionPlan, Evidence, Gap, Job
from app.providers.video_generation import GenerationError, generation_base_url
from app.providers.storage import storage
from app.services.media.views import selected_reference_frame
from app.workflows.pipeline import config_hash


def generation_jobs(db, task_id):
    task = db.get(CompletionTask, task_id)
    if not task:
        raise GenerationError("补全任务不存在")
    return [job for job in db.scalars(
        select(Job).where(Job.project_id == task.project_id, Job.type == "generation").order_by(Job.created_at.desc())
    ) if job.data.get("task_id") == task_id]


def retryable(job):
    data = job.data
    if data.get("generated_asset_id") and storage.path(
        f"assets/{job.project_id}/{data['generated_asset_id']}/original.mp4"
    ).is_file():
        return True
    return not data.get("provider_terminal") and (
        bool(data.get("asset_id") or data.get("provider_task_id"))
        or not data.get("provider_submission_started")
    )


def check_capacity(db, project_id, duration_s, exclude_job_id=None):
    assets = list(db.scalars(select(Asset).where(Asset.project_id == project_id)))
    pending = [j for j in db.scalars(select(Job).where(Job.project_id == project_id, Job.type == "generation"))
               if j.id != exclude_job_id and not j.data.get("asset_id")
               and not j.data.get("provider_terminal")
               and (j.status in ("queued", "running") or j.data.get("provider_submission_started"))]
    if len(assets) + len(pending) >= settings.max_assets:
        raise GenerationError("项目素材数量已达上限（含待生成片段）")
    if sum(a.duration_s for a in assets) + sum(j.data.get("duration_s", 0) for j in pending) + duration_s > settings.max_project_duration_s:
        raise GenerationError("项目素材总时长已达上限（含待生成片段）")


def generation_context(db, task_id):
    if not settings.video_generation_enabled:
        raise GenerationError("当前服务尚未启用 AI 片段生成")
    if settings.model_provider == "mock" or not settings.model_api_key:
        raise GenerationError("AI 片段生成需要配置真实百炼模型服务")
    generation_base_url()
    task = db.get(CompletionTask, task_id)
    if not task:
        raise GenerationError("补全任务不存在")
    plan = db.get(CompletionPlan, task.plan_id)
    project = db.get(Project, task.project_id)
    run = db.get(AnalysisRun, plan.analysis_id) if plan else None
    if not project or not run or plan.project_id != project.id or run.project_id != project.id:
        raise GenerationError("补全计划与项目不一致")
    if task.data.get("type") not in ("reshoot", "generate"):
        raise GenerationError("只有补拍或生成任务支持 AI 片段生成；重剪任务请调整已有片段")
    if run.status != "succeeded" or run.config_hash != config_hash():
        raise GenerationError("分析模型配置已更新或分析未完成，请重新分析并生成补全计划")
    snapshot = run.data.get("project_config", {})
    if any(snapshot.get(key) != getattr(project, key) for key in ("intent", "style", "input_mode", "target_duration_s")):
        raise GenerationError("创作需求已变更，请重新分析并生成补全计划")
    for key in ("primary_asset_id", "requirements"):
        if snapshot.get("constraints_json", {}).get(key) != project.constraints_json.get(key):
            raise GenerationError("主片或需求已变更，请重新分析并生成补全计划")
    if project.latest_analysis_id and project.latest_analysis_id != run.id:
        raise GenerationError("已有更新的分析，请使用最新补全计划")
    latest_succeeded = db.scalar(select(AnalysisRun).where(
        AnalysisRun.project_id == project.id, AnalysisRun.status == "succeeded"
    ).order_by(AnalysisRun.created_at.desc()).limit(1))
    if latest_succeeded and latest_succeeded.id != run.id:
        raise GenerationError("已有更新的成功分析，请使用最新补全计划")
    gap_ids = task.data.get("gap_ids", [])
    if not gap_ids:
        raise GenerationError("任务没有可追溯的补全建议")
    for gap_id in gap_ids:
        gap = db.get(Gap, gap_id)
        if not gap or gap.project_id != project.id or gap.analysis_id != run.id:
            raise GenerationError("补全建议与当前分析不一致")
        if gap.data.get("status") in ("resolved", "dismissed"):
            raise GenerationError("对应问题已解决或已忽略，无需生成片段")
        if gap.data.get("status") != "confirmed":
            raise GenerationError("请先确认这条补全建议，再生成 AI 片段")
    references = []
    for evidence_id in task.data.get("reference_evidence_ids", []):
        evidence = db.get(Evidence, evidence_id)
        if not evidence or evidence.project_id != project.id or evidence.analysis_id != run.id:
            continue
        data = evidence.data
        asset = db.get(Asset, data.get("asset_id"))
        at = data.get("source_start_s")
        if data.get("evidence_type") == "audio" or not asset or asset.project_id != project.id or asset.id not in run.asset_snapshot or asset.status != "ready":
            continue
        if not isinstance(at, (float, int)) or not math.isfinite(at) or not 0 <= at < asset.duration_s:
            continue
        if not 0.4 <= asset.width / asset.height <= 2.5:
            continue
        try:
            selected = selected_reference_frame(asset, float(at))
            if not storage.path(selected["key"]).is_file():
                continue
            at = selected["time_s"]
        except (ValueError, KeyError):
            continue
        frame = {
            "asset_id": asset.id, "time_s": float(at),
            "url": f"/api/v1/assets/{asset.id}/frame?at={at}",
            "caption": str(data.get("action", "补全建议的参考画面"))[:300],
        }
        if not any(f["asset_id"] == frame["asset_id"] and f["time_s"] == frame["time_s"] for f in references):
            references.append(frame)
    if not references:
        raise GenerationError("没有可用的画面证据首帧，或参考画面比例超出 1:2.5～2.5:1")
    return task, project, run, references[:2]


def default_prompt(task):
    data = task.data
    recommendation = data.get("recommendation") or {}
    parts = [
        "依据输入首帧生成一段自然真实的 Vlog 补充镜头。",
        "镜头目的：" + str(data.get("requirement_description", "补足叙事信息")),
        "补全建议：" + str(data.get("instruction", "")),
        "主体动作：" + str(recommendation.get("subject_action", "自然、连续地完成已有动作")),
        "景别：" + str(recommendation.get("shot_scale", "保持首帧景别")),
        str(data.get("continuity", "保持首帧的主体、服装、场景与光线一致。")),
        "保持主体外观一致，动作连贯，避免突然换场、镜头跳切、字幕和额外人物。仅生成建议所需画面，不凭空补充真实事件。",
    ]
    return "\n".join(parts)[:2000]
