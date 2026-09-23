"""Keep supplement verification tied to its task, not an obsolete model config."""
from sqlalchemy import select

from app.config import settings
from app.models import AnalysisRun, CompletionPlan, Evidence, Project, Requirement


def verification_context(db, task, *, lock=False):
    if not task:
        raise ValueError("补拍任务不存在")
    query = select(Project).where(Project.id == task.project_id)
    if lock:
        query = query.with_for_update()
    project = db.scalar(query.execution_options(populate_existing=True))
    plan = db.get(CompletionPlan, task.plan_id)
    run = db.get(AnalysisRun, plan.analysis_id, populate_existing=True) if plan else None
    if (not project or project.deleted_at or not run
            or plan.project_id != project.id or run.project_id != project.id):
        raise ValueError("补拍任务与项目不一致或项目已删除")
    if run.status != "succeeded":
        raise ValueError("原视频分析尚未完成，请完成分析后再验证补拍")

    snapshot = run.data.get("project_config", {})
    for key in ("intent", "style", "input_mode", "target_duration_s", "demo_scenario"):
        if snapshot.get(key) != getattr(project, key):
            raise ValueError("创作需求已变更，请重新分析并生成任务")
    for key in ("primary_asset_id", "requirements"):
        if snapshot.get("constraints_json", {}).get(key) != project.constraints_json.get(key):
            raise ValueError("主片或创作需求已变更，请重新分析并生成任务")
    latest = db.scalar(select(AnalysisRun.id).where(
        AnalysisRun.project_id == project.id, AnalysisRun.status == "succeeded",
    ).order_by(AnalysisRun.created_at.desc()).limit(1))
    if (project.latest_analysis_id and project.latest_analysis_id != run.id) or latest != run.id:
        raise ValueError("已有更新的分析，请使用最新补拍任务")

    # Model/prompt upgrades are safe for a new verification attempt. Demo
    # evidence is not: never silently present it as a real model's judgment.
    source_provider = run.data.get("provider")
    is_mock = settings.model_provider == "mock"
    if not source_provider or (source_provider == "mock") != is_mock:
        raise ValueError("演示与真实模型模式已切换，请重新分析并生成任务")
    for row in db.scalars(select(Evidence).where(Evidence.analysis_id == run.id)):
        provenance = row.data.get("provenance", {})
        if not is_mock and provenance.get("demo") is True:
            raise ValueError("原分析包含演示证据，请用真实模型重新分析")
        if is_mock and row.data.get("evidence_type", "visual") != "audio" and (
            provenance.get("demo") is False
            or provenance.get("provider") not in (None, "mock")
        ):
            raise ValueError("原分析包含真实模型证据，不能使用演示模式验证")

    requirement = db.get(Requirement, task.data.get("requirement_id"), populate_existing=True)
    if (not requirement or requirement.project_id != project.id
            or requirement.analysis_id != run.id):
        raise ValueError("补拍任务缺少对应需求，请重新生成任务")
    return project, run, requirement
