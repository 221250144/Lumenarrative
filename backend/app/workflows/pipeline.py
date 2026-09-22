import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from types import MappingProxyType, SimpleNamespace
from sqlalchemy import select, delete
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
    Shot,
    TranscriptSegment,
    Submission,
    CompletionTask,
    CompletionPlan,
    EditVersion,
    uid,
    serialize,
)
from app.providers.models import provider, CompatibleASR, PROMPT_VERSION
from app.services.media.pipeline import preprocess, dense_frames, SEGMENTATION_VERSION
from app.services.diagnosis.engine import (
    validate_evidence,
    merge_evidence,
    validate_matches,
    diagnose,
)
from app.services.editing.render import render


def config_hash():
    return hashlib.sha256(
        json.dumps(
            {
                "provider": settings.model_provider,
                "base": settings.model_base_url,
                "vlm": settings.vlm_model,
                "llm": settings.llm_model,
                "prompt": PROMPT_VERSION,
                "window": settings.window_s,
                "overlap": settings.overlap_s,
                "fps": settings.sample_fps,
                "segmentation": SEGMENTATION_VERSION,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()


def create_analysis(db, project):
    assets = db.scalars(
        select(Asset).where(Asset.project_id == project.id).order_by(Asset.created_at)
    ).all()
    if not assets:
        raise ValueError("请先上传至少一个视频")
    analysis_assets = assets
    if project.input_mode == "vlog":
        analysis_assets = [a for a in assets if a.id == project.constraints_json.get("primary_asset_id")]
        if not analysis_assets:
            raise ValueError("请先指定一条主 Vlog")
    if any(a.status in ("queued", "processing") for a in analysis_assets):
        raise ValueError("素材仍在预处理中，请完成后再分析")
    if not any(a.status == "ready" for a in analysis_assets):
        raise ValueError("没有成功预处理的素材")
    if project.input_mode in ("vlog", "rough_cut", "mixed"):
        primary = project.constraints_json.get("primary_asset_id")
        if not primary or not any(
            a.id == primary and a.status == "ready" for a in assets
        ):
            raise ValueError("请先在素材列表指定一条可播放的剪辑初稿")
    run = AnalysisRun(
        id=uid(),
        project_id=project.id,
        project_revision=project.revision,
        asset_snapshot=[a.id for a in assets],
        config_hash=config_hash(),
        data={
            "project_config": {
                "intent": project.intent,
                "style": project.style,
                "input_mode": project.input_mode,
                "target_duration_s": project.target_duration_s,
                "constraints_json": project.constraints_json,
                "demo_scenario": project.demo_scenario,
            },
            "provider": settings.model_provider,
        },
    )
    db.add(run)
    db.flush()
    return run


def rows(db, cls, run_id):
    return [
        serialize(x)
        for x in db.scalars(
            select(cls).where(cls.analysis_id == run_id).order_by(cls.created_at)
        ).all()
    ]


def process_asset(job, progress):
    with SessionLocal() as db:
        asset = db.get(Asset, job.data["asset_id"])
        asset.status = "processing"
        db.commit()
        try:
            asset.meta = preprocess(asset, progress)
            try:
                transcripts, audio_status = CompatibleASR().transcribe(asset)
            except Exception:
                transcripts, audio_status = [], "failed"
            asset.meta = {**asset.meta, "audio_status": audio_status}
            db.execute(delete(Shot).where(Shot.asset_id == asset.id))
            db.execute(
                delete(TranscriptSegment).where(TranscriptSegment.asset_id == asset.id)
            )
            for shot in asset.meta["scene_shots"]:
                db.add(Shot(id=shot["id"], asset_id=asset.id, project_id=asset.project_id, data=shot))
            for segment in transcripts:
                db.add(
                    TranscriptSegment(
                        asset_id=asset.id, project_id=asset.project_id, data=segment
                    )
                )
            asset.status = "ready"
            db.commit()
        except Exception:
            asset.status = "failed"
            db.commit()
            raise


def extract_asset(db, asset, run, model, progress):
    cache_key = hashlib.sha256(
        (asset.project_id + asset.id + asset.sha256 + run.config_hash
         + json.dumps([(s.get("shot_id"), s["start_s"], s["end_s"]) for s in asset.meta.get("shots", [])])).encode()
    ).hexdigest()
    cached = asset.meta.get("evidence_cache", {})
    if cached.get("key") == cache_key and not cached.get("failed_ranges"):
        # IDs are unique to this analysis; manual edits live in the project overlay.
        return [{**e, "id": uid()} for e in cached["evidence"]], [], True

    def freeze(value):
        if isinstance(value, dict):
            return MappingProxyType({key: freeze(item) for key, item in value.items()})
        if isinstance(value, (list, tuple)):
            return tuple(freeze(item) for item in value)
        return value

    class ReadOnlyAsset(SimpleNamespace):
        def __setattr__(self, name, value):
            raise AttributeError("模型工作线程不能修改素材快照")

        def __delattr__(self, name):
            raise AttributeError("模型工作线程不能修改素材快照")

    # Materialize ORM attributes on the calling thread. Worker inputs contain
    # only immutable scalar/JSON snapshots, with no SQLAlchemy object/session.
    snapshot = ReadOnlyAsset(**{
        name: freeze(getattr(asset, name))
        for name in (
            "id", "project_id", "source_type", "original_name", "storage_key",
            "sha256", "duration_s", "width", "height", "has_audio", "status",
        )
        if hasattr(asset, name)
    }, meta=freeze({key: value for key, value in asset.meta.items() if key != "evidence_cache"}))
    shots = snapshot.meta.get("shots", ())
    model_name, vlm_model = model.name, settings.vlm_model

    def extract_window(shot):
        if snapshot.meta.get("demo_fail"):
            raise ValueError("固定演示：模拟分段分析失败")
        window_items = []
        for raw in model.analyze_clip(snapshot, shot):
            item = validate_evidence(raw, snapshot.id, snapshot.duration_s, shot)
            item["shot_id"] = shot.get("shot_id")
            item["provenance"] = {
                "provider": model_name,
                "model": vlm_model if model_name != "mock" else "fixed-fixture",
                "prompt_version": PROMPT_VERSION,
                "windows": [[shot["start_s"], shot["end_s"]]],
                "demo": model_name == "mock",
            }
            window_items.append(item)
        # No item escapes until every observation in this window is valid.
        return window_items

    window_results, window_failures = [None] * len(shots), [None] * len(shots)
    progress("提取素材证据", 0, len(shots))
    if shots:
        with ThreadPoolExecutor(
            max_workers=settings.model_concurrency, thread_name_prefix="vlog-analysis"
        ) as pool:
            futures = {pool.submit(extract_window, shot): i for i, shot in enumerate(shots)}
            for completed, future in enumerate(as_completed(futures), 1):
                index = futures[future]
                shot = shots[index]
                try:
                    window_results[index] = future.result()
                except Exception as exc:
                    window_failures[index] = {
                        "asset_id": snapshot.id,
                        "start_s": shot["start_s"],
                        "end_s": shot["end_s"],
                        "reason": str(exc)[:400],
                    }
                # Job progress and all database access remain on the caller.
                progress("提取素材证据", completed, len(shots))
    items = [item for result in window_results if result is not None for item in result]
    failed = [failure for failure in window_failures if failure is not None]
    transcripts = db.scalars(
        select(TranscriptSegment).where(TranscriptSegment.asset_id == asset.id)
    ).all()
    for segment in transcripts:
        s = segment.data
        items.append(
            {
                "id": uid(),
                "asset_id": asset.id,
                "source_start_s": s["start_s"],
                "source_end_s": s["end_s"],
                "action": s["text"],
                "subjects": [],
                "story_roles": [],
                "quality_issues": [],
                "uncertainty": "转写内容可能有误，请对照音频核实",
                "evidence_type": "audio",
                "provenance": {
                    "provider": s["provider"],
                    "windows": [[s["start_s"], s["end_s"]]],
                    "demo": False,
                },
            }
        )
    if asset.meta.get("demo_audio_context"):
        items.append(
            {
                "id": uid(),
                "asset_id": asset.id,
                "source_start_s": 0.0,
                "source_end_s": min(2, asset.duration_s),
                "action": "固定演示对白：今天在窗边做一杯咖啡",
                "subjects": [],
                "story_roles": ["地点"],
                "quality_issues": [],
                "uncertainty": "演示标注，无真实 ASR 调用",
                "evidence_type": "audio",
                "provenance": {
                    "provider": "mock",
                    "windows": [[0.0, 2.0]],
                    "demo": True,
                },
            }
        )
    items = merge_evidence(items)
    asset.meta = {
        **asset.meta,
        "evidence_cache": {
            "key": cache_key,
            "evidence": items,
            "failed_ranges": failed,
        },
    }
    db.commit()
    return items, failed, False


def analyze(job, progress):
    with SessionLocal() as db:
        run = db.get(AnalysisRun, job.data["analysis_id"])
        if run.config_hash != config_hash():
            raise ValueError(
                "模型或采样配置已改变，请创建新的分析，不混用历史任务的模式"
            )
        run.status = "running"
        run.stage = "理解创作目标"
        db.commit()
        # Retry replaces only this run's machine outputs, preserving project corrections.
        for cls in (Gap, RequirementMatch, Requirement, Evidence):
            db.execute(delete(cls).where(cls.analysis_id == run.id))
        db.commit()
        project = SimpleNamespace(**run.data["project_config"])
        model = provider()
        if project.input_mode == "vlog":
            from app.workflows.vlog import analyze_vlog
            analyze_vlog(db, run, project, model, progress)
            return
        progress("理解创作目标", 0, 1)
        requirements = project.constraints_json.get(
            "requirements"
        ) or model.requirements(project)
        requirements = [{**r, "id": uid()} for r in requirements]
        if not requirements:
            raise ValueError("未生成创作需求，请补充更具体的创作意图")
        assets = [db.get(Asset, aid) for aid in run.asset_snapshot]
        coverage = {
            "ranges": [],
            "failed_ranges": [],
            "visual_complete": True,
            "audio_complete": True,
            "cached_asset_ids": [],
            "reviewed_ranges": [],
            "mode": model.name,
            "sampling_note": f"稀疏采样约 {settings.sample_fps} fps；未覆盖帧间全部动作，事件边界不是帧级定位。",
        }
        evidence = []
        for asset in assets:
            if asset.status != "ready":
                coverage["failed_ranges"].append(
                    {
                        "asset_id": asset.id,
                        "start_s": 0,
                        "end_s": asset.duration_s,
                        "reason": "素材预处理失败",
                    }
                )
                continue
            new, failed, cached = extract_asset(db, asset, run, model, progress)
            evidence.extend(new)
            coverage["failed_ranges"].extend(failed)
            coverage["ranges"].append(
                {
                    "asset_id": asset.id,
                    "start_s": 0.0,
                    "end_s": asset.duration_s,
                    "visual_status": "partial" if failed else "sampled",
                    "audio_status": asset.meta.get("audio_status", "unconfigured"),
                }
            )
            if cached:
                coverage["cached_asset_ids"].append(asset.id)
            if asset.has_audio and asset.meta.get("audio_status") not in (
                "analyzed",
                "no_audio",
            ):
                coverage["audio_complete"] = False
        coverage["visual_complete"] = not coverage["failed_ranges"]
        if not evidence and model.name != "mock":
            raise ValueError("全部素材理解失败，请检查模型配置和素材；未生成诊断")
        progress("匹配需求与素材", 0, 1)
        matches = validate_matches(
            model.match(requirements, evidence, coverage, project),
            requirements,
            evidence,
        )
        # Review high-impact absences locally at 4 fps before generating a gap.
        critical = [
            m
            for m in matches
            if m["sufficiency"] in ("not_found", "partial")
            and next(r for r in requirements if r["id"] == m["requirement_id"])[
                "priority"
            ]
            == "must"
        ]
        if critical and model.name != "mock":
            for asset in [a for a in assets if a.status == "ready"][:2]:
                for shot in asset.meta["shots"][:2]:
                    progress("加密复核候选缺口", 0, 1)
                    try:
                        dense = {
                            **shot,
                            "keyframes": dense_frames(
                                asset, shot["start_s"], shot["end_s"]
                            ),
                        }
                        for raw in model.analyze_clip(asset, dense):
                            item = validate_evidence(
                                raw, asset.id, asset.duration_s, shot
                            )
                            item["provenance"] = {
                                "provider": model.name,
                                "model": settings.vlm_model,
                                "windows": [[shot["start_s"], shot["end_s"]]],
                                "dense_review": True,
                                "demo": False,
                            }
                            evidence.append(item)
                        coverage["reviewed_ranges"].append(
                            {
                                "asset_id": asset.id,
                                "start_s": shot["start_s"],
                                "end_s": shot["end_s"],
                                "fps": 4,
                            }
                        )
                    except Exception as exc:
                        coverage.setdefault("review_errors", []).append(str(exc)[:200])
            evidence = merge_evidence(evidence)
            matches = validate_matches(
                model.match(requirements, evidence, coverage, project),
                requirements,
                evidence,
            )
        gaps = diagnose(
            requirements,
            matches,
            coverage,
            project.constraints_json.get("gap_overrides"),
        )
        for cls, items in (
            (Evidence, evidence),
            (Requirement, requirements),
            (RequirementMatch, matches),
            (Gap, gaps),
        ):
            for item in items:
                item = dict(item)
                row_id = item.pop("id", uid())
                db.add(
                    cls(
                        id=row_id,
                        project_id=run.project_id,
                        analysis_id=run.id,
                        data=item,
                    )
                )
        current = db.scalar(
            select(Project)
            .where(Project.id == run.project_id)
            .execution_options(populate_existing=True)
        )
        stale = current.revision != run.project_revision
        run.status, run.stage = "succeeded", "分析完成"
        run.data = {
            **run.data,
            "coverage": coverage,
            "stale": stale,
            "requirement_count": len(requirements),
            "gap_count": len(gaps),
        }
        if not stale:
            current.latest_analysis_id = run.id
        db.commit()
        progress("分析完成" + (" · 已保存为历史版本" if stale else ""), 1, 1)


def verify_submission(job, progress):
    with SessionLocal() as db:
        submission = db.get(Submission, job.data["submission_id"])
        task = db.get(CompletionTask, submission.task_id)
        plan = db.get(CompletionPlan, task.plan_id)
        run = db.get(AnalysisRun, plan.analysis_id)
        if run.config_hash != config_hash():
            raise ValueError("模型配置已改变，请重新分析并生成任务后再验证")
        asset = db.get(Asset, submission.asset_id)
        if asset.status != "ready":
            raise ValueError("新增素材还未准备好，请在预处理完成后重试")
        model = provider()
        evidence, failures, _ = extract_asset(db, asset, run, model, progress)
        previous = rows(db, Evidence, run.id)
        progress("逐项验证验收条件", 0, 1)
        result = model.verify(task.data, evidence, previous)
        if [c["check"] for c in result["checks"]] != task.data["acceptance_checks"]:
            raise ValueError("模型未逐项返回原任务验收条件")
        valid_ids = {e["id"] for e in evidence}
        if any(e not in valid_ids for c in result["checks"] for e in c["evidence_ids"]):
            raise ValueError("验收引用了不存在的新素材证据")
        for c in result["checks"]:
            if c["status"] == "passed" and not c["evidence_ids"]:
                raise ValueError("通过的验收项缺少证据")
        req = db.get(Requirement, task.data["requirement_id"])
        project_config = SimpleNamespace(**run.data["project_config"])
        new_coverage = {
            "visual_complete": not failures,
            "audio_complete": not asset.has_audio
            or asset.meta.get("audio_status") == "analyzed",
            "ranges": [
                {"asset_id": asset.id, "start_s": 0.0, "end_s": asset.duration_s}
            ],
            "failed_ranges": failures,
        }
        rematch = validate_matches(
            model.match(
                [serialize(req)], previous + evidence, new_coverage, project_config
            ),
            [serialize(req)],
            previous + evidence,
        )[0]
        statuses = [c["status"] for c in result["checks"]]
        passed = (
            all(s == "passed" for s in statuses)
            and result["requirement_status"] == "passed"
            and rematch["sufficiency"] == "supported"
            and not result["continuity_issues"]
            and not failures
        )
        status = (
            "passed"
            if passed
            else "uncertain"
            if failures or "uncertain" in statuses
            else "partial"
            if "passed" in statuses
            else "failed"
        )
        current = db.scalar(
            select(Project)
            .where(Project.id == submission.project_id)
            .execution_options(populate_existing=True)
        )
        stale = current.revision != submission.data["project_revision"]
        submission.verification_status = status
        submission.data = {
            **submission.data,
            **result,
            "new_evidence": evidence,
            "rematch": rematch,
            "stale": stale,
        }
        if passed and not stale:
            for gid in task.data["gap_ids"]:
                gap = db.get(Gap, gid)
                gap.data = {
                    **gap.data,
                    "status": "resolved",
                    "resolution_submission_id": submission.id,
                }
        if result["continuity_issues"] and not stale:
            for reason in result["continuity_issues"]:
                db.add(
                    Gap(
                        project_id=run.project_id,
                        analysis_id=run.id,
                        data={
                            "requirement_id": req.id,
                            "type": "transition_issue",
                            "severity": "review",
                            "status": "needs_review",
                            "evidence_ids": [],
                            "searched_ranges": new_coverage["ranges"],
                            "reason": reason,
                            "description": req.data["description"],
                            "optional": False,
                            "uncertain": True,
                            "alternative_edit": {
                                "feasible": False,
                                "reason": "需人工确认连续性",
                            },
                            "submission_id": submission.id,
                        },
                    )
                )
        db.commit()
        progress("验收完成" + (" · 历史结果" if stale else ""), 1, 1)


def render_edit(job, progress):
    with SessionLocal() as db:
        edit = db.get(EditVersion, job.data["edit_id"])
        assets = {
            a.id: a
            for a in db.scalars(
                select(Asset).where(Asset.project_id == edit.project_id)
            )
        }
        edit.render_status = "running"
        db.commit()
        key, meta = render(edit.id, edit.data["timeline"], assets, progress)
        edit.output_key = key
        edit.render_status = "succeeded"
        edit.data = {**edit.data, "media_info": meta}
        db.commit()
