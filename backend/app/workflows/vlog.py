from sqlalchemy import delete, select
from app.models import Asset, Project, Shot, Evidence, Requirement, RequirementMatch, Gap, uid
from app.schemas import VlogReviewOutput
from app.services.media.pipeline import preprocess, SEGMENTATION_VERSION
from app.services.media.views import asset_shots
from app.services.diagnosis.vlog import build_vlog_diagnosis


def normalize_chapters(chapters, shots):
    """A chapter must cover a contiguous part of the real, ordered timeline."""
    expected = [s["id"] for s in shots]
    flattened = [sid for chapter in chapters for sid in chapter["shot_ids"]]
    if flattened != expected:
        return [{"title": "主 Vlog", "shot_ids": expected, "summary": "按原片顺序查看镜头。"}]
    return chapters


def analyze_vlog(db, run, project, model, progress):
    from app.workflows.pipeline import extract_asset

    primary_id = project.constraints_json.get("primary_asset_id")
    asset = db.get(Asset, primary_id) if primary_id in run.asset_snapshot else None
    if not asset or asset.project_id != run.project_id or asset.status != "ready":
        raise ValueError("主 Vlog 未就绪，请选择一条完成预处理的视频")
    run.stage = "切分主 Vlog"
    db.commit()
    if asset.meta.get("segmentation_version") != SEGMENTATION_VERSION:
        asset.meta = preprocess(asset, progress)
        db.execute(delete(Shot).where(Shot.asset_id == asset.id))
        for shot in asset.meta["scene_shots"]:
            db.add(Shot(id=shot["id"], asset_id=asset.id, project_id=asset.project_id, data=shot))
        db.commit()
    shots = asset_shots(asset)
    if not shots:
        raise ValueError("没有有效镜头，请重新预处理主 Vlog")
    run.stage = "逐镜头理解主 Vlog"
    db.commit()
    evidence, failed, cached = extract_asset(db, asset, run, model, progress)
    # ASR segments can cross visual cuts. Split their references at shot boundaries;
    # the text remains an attributed transcript, never a visual observation.
    localized = []
    for item in evidence:
        if item.get("shot_id"):
            localized.append(item)
            continue
        for shot in shots:
            start = max(item["source_start_s"], shot["start_s"])
            end = min(item["source_end_s"], shot["end_s"])
            if start < end:
                localized.append({**item, "id": uid(), "shot_id": shot["id"],
                                  "source_start_s": start, "source_end_s": end})
    evidence = localized
    if not any(e.get("evidence_type") == "visual" for e in evidence):
        raise ValueError("主 Vlog 画面理解全部失败，未生成补拍结论；请检查模型配置后重试")
    for shot in shots:
        observations = [e for e in evidence if e["shot_id"] == shot["id"] and e.get("evidence_type") == "visual"]
        shot["evidence_ids"] = [e["id"] for e in evidence if e["shot_id"] == shot["id"]]
        shot["observed"] = bool(observations) and model.name != "mock"
        shot["summary"] = "；".join(dict.fromkeys(e["action"] for e in observations))[:500] or "画面理解失败，请人工查看此镜头"
        if not observations and not any(f["start_s"] < shot["end_s"] and f["end_s"] > shot["start_s"] for f in failed):
            failed.append({"asset_id": asset.id, "start_s": shot["start_s"], "end_s": shot["end_s"], "reason": "没有有效视觉观察"})
    coverage = {
        "ranges": [{"asset_id": asset.id, "start_s": 0.0, "end_s": asset.duration_s,
                    "visual_status": "partial" if failed else "sampled",
                    "audio_status": asset.meta.get("audio_status", "unconfigured")}],
        "failed_ranges": failed, "visual_complete": not failed and model.name != "mock",
        "audio_complete": not asset.has_audio or asset.meta.get("audio_status") == "analyzed",
        "cached_asset_ids": [asset.id] if cached else [], "reviewed_ranges": [], "mode": model.name,
        "sampling_note": "先检测剪辑切点，再在每个镜头内抽取最多4帧/窗口理解；采样可能遗漏动作，复杂叠化可能漏检。仅分析主 Vlog，补充素材用于任务验收。",
    }
    run.stage = "定位值得修改的具体镜头"
    db.commit()
    progress(run.stage, 0, 1)
    review = VlogReviewOutput.model_validate(model.review_vlog(project, shots, evidence, coverage)).model_dump()
    result = build_vlog_diagnosis(review, shots, evidence, coverage, project.constraints_json.get("gap_overrides"))
    for cls, items in ((Evidence, evidence), (Requirement, result["requirements"]),
                       (RequirementMatch, result["matches"]), (Gap, result["gaps"])):
        for item in items:
            data = dict(item)
            row_id = data.pop("id", uid())
            db.add(cls(id=row_id, project_id=run.project_id, analysis_id=run.id, data=data))
    current = db.scalar(select(Project).where(Project.id == run.project_id).execution_options(populate_existing=True))
    stale = current.revision != run.project_revision
    run.status, run.stage = "succeeded", "Vlog 分析完成"
    run.data = {**run.data, "coverage": coverage, "stale": stale,
                "requirement_count": len(result["requirements"]), "gap_count": len(result["gaps"]),
                "shots": shots,
                "vlog": {"summary": review["summary"], "vlog_type": review["vlog_type"],
                         "chapters": normalize_chapters(review["chapters"], shots),
                         "primary_asset_id": asset.id, "shot_count": len(shots)}}
    if not stale:
        current.latest_analysis_id = run.id
    db.commit()
    progress("Vlog 分析完成" + (" · 已保存为历史版本" if stale else ""), 1, 1)
