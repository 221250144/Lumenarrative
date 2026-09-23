"""Supplement verification survives model upgrades without accepting stale goals."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.config import settings
from app.models import (
    AnalysisRun, Asset, CompletionPlan, CompletionTask, Evidence, Gap,
    Project, Requirement, SessionLocal, Submission, User, uid,
)
from app.workflows import pipeline


@pytest.fixture
def context(client):
    with SessionLocal() as db:
        owner_id = db.scalar(select(User.id).where(User.username == "tester"))
        project = Project(
            id=uid(), owner_id=owner_id, title="补拍验证", intent="交代沿河步道的环境",
            style="自然生活记录", input_mode="vlog", target_duration_s=60,
            constraints_json={"primary_asset_id": "primary-video"}, revision=2,
        )
        db.add(project)
        db.flush()
        original = AnalysisRun(
            id=uid(), project_id=project.id, project_revision=1,
            asset_snapshot=["primary-video"], config_hash="original-analysis-config",
            status="succeeded", created_at="2026-09-23T08:00:00+00:00",
            data={"provider": "mock", "project_config": {
                "intent": project.intent, "style": project.style,
                "input_mode": project.input_mode,
                "target_duration_s": project.target_duration_s,
                "constraints_json": deepcopy(project.constraints_json),
                "demo_scenario": project.demo_scenario,
            }},
        )
        db.add(original)
        db.flush()
        requirement = Requirement(
            id=uid(), project_id=project.id, analysis_id=original.id,
            data={"description": "交代沿河步道的环境", "accepted_evidence_types": ["visual"]},
        )
        reference = Evidence(
            id=uid(), project_id=project.id, analysis_id=original.id,
            data={"asset_id": "primary-video", "source_start_s": 0, "source_end_s": 4,
                  "action": "沿河行走", "evidence_type": "visual",
                  "provenance": {"provider": "mock", "demo": True}},
        )
        plan = CompletionPlan(id=uid(), project_id=project.id, analysis_id=original.id, data={})
        gap = Gap(
            id=uid(), project_id=project.id, analysis_id=original.id,
            data={"status": "confirmed", "requirement_id": requirement.id},
        )
        db.add_all([requirement, reference, plan, gap])
        db.flush()
        task = CompletionTask(
            id=uid(), project_id=project.id, plan_id=plan.id,
            data={"type": "reshoot", "requirement_id": requirement.id,
                  "gap_ids": [gap.id], "acceptance_checks": ["石板路纹理清晰", "河面可见"]},
        )
        asset = Asset(
            id=uid(), project_id=project.id, source_type="real_capture",
            original_name="补拍.mp4", storage_key="fixture-only.mp4", sha256="supplement",
            duration_s=4, width=1280, height=720, has_audio=False, status="ready", meta={},
        )
        db.add_all([task, asset])
        db.flush()
        submission = Submission(
            id=uid(), project_id=project.id, task_id=task.id, asset_id=asset.id,
            data={"project_revision": project.revision}, verification_status="failed",
        )
        db.add(submission)
        db.commit()
        return SimpleNamespace(
            project_id=project.id, run_id=original.id, requirement_id=requirement.id,
            evidence_id=reference.id, plan_id=plan.id, task_id=task.id, gap_id=gap.id,
            asset_id=asset.id, submission_id=submission.id,
        )


def check_context(context):
    from app.services.diagnosis.submission_context import verification_context

    with SessionLocal() as db:
        return tuple(row.id for row in verification_context(db, db.get(CompletionTask, context.task_id)))


def test_model_upgrade_and_supplement_revision_keep_original_task_usable(context):
    with SessionLocal() as db:
        project = db.get(Project, context.project_id)
        project.revision += 1
        project.latest_analysis_id = None
        db.commit()
    assert check_context(context) == (context.project_id, context.run_id, context.requirement_id)
    with SessionLocal() as db:
        assert db.get(AnalysisRun, context.run_id).config_hash == "original-analysis-config"


@pytest.mark.parametrize("field,value", [
    ("intent", "新的审看目标"), ("style", "快节奏"), ("input_mode", "clips"),
    ("target_duration_s", 90), ("demo_scenario", "missing"),
    ("primary_asset_id", "another-primary"), ("requirements", [{"description": "新的条件"}]),
])
def test_changed_project_semantics_reject_old_task(context, field, value):
    with SessionLocal() as db:
        project = db.get(Project, context.project_id)
        if field in ("primary_asset_id", "requirements"):
            project.constraints_json = {**project.constraints_json, field: value}
        else:
            setattr(project, field, value)
        db.commit()
    with pytest.raises(ValueError):
        check_context(context)


@pytest.mark.parametrize("case", ["unfinished", "deleted", "wrong_requirement", "newer_success"])
def test_ineligible_analysis_and_project_are_rejected(context, case):
    with SessionLocal() as db:
        project = db.get(Project, context.project_id)
        run = db.get(AnalysisRun, context.run_id)
        if case == "unfinished":
            run.status = "running"
        elif case == "deleted":
            project.deleted_at = "2026-09-23T09:00:00+00:00"
        elif case == "wrong_requirement":
            task = db.get(CompletionTask, context.task_id)
            task.data = {**task.data, "requirement_id": "missing-requirement"}
        else:
            db.add(AnalysisRun(
                id=uid(), project_id=project.id, project_revision=project.revision,
                asset_snapshot=[], config_hash="new-config", status="succeeded",
                created_at="2026-09-23T09:00:00+00:00", data=deepcopy(run.data),
            ))
            # Uploading a supplement clears this field, but cannot revive an old plan.
            project.latest_analysis_id = None
        db.commit()
    with pytest.raises(ValueError):
        check_context(context)


@pytest.mark.parametrize("original_provider,current_provider", [("mock", "qwen"), ("qwen", "mock")])
def test_mock_and_real_analysis_cannot_be_mixed(context, monkeypatch, original_provider, current_provider):
    monkeypatch.setattr(settings, "model_provider", current_provider)
    with SessionLocal() as db:
        run = db.get(AnalysisRun, context.run_id)
        run.data = {**run.data, "provider": original_provider}
        evidence = db.get(Evidence, context.evidence_id)
        evidence.data = {**evidence.data, "provenance": {
            "provider": original_provider, "demo": original_provider == "mock",
        }}
        db.commit()
    with pytest.raises(ValueError):
        check_context(context)


@pytest.mark.parametrize("mode,provenance", [
    ("qwen", {"provider": "qwen", "demo": True}),
    ("mock", {"provider": "qwen", "demo": True}),
    ("mock", {"provider": "mock", "demo": False}),
])
def test_conflicting_evidence_provenance_is_rejected(context, monkeypatch, mode, provenance):
    monkeypatch.setattr(settings, "model_provider", mode)
    with SessionLocal() as db:
        run = db.get(AnalysisRun, context.run_id)
        run.data = {**run.data, "provider": mode}
        evidence = db.get(Evidence, context.evidence_id)
        evidence.data = {**evidence.data, "provenance": provenance}
        db.commit()
    with pytest.raises(ValueError):
        check_context(context)


def fake_verification(monkeypatch, context, during_verify=lambda: None):
    evidence = {
        "id": "new-only-evidence", "asset_id": context.asset_id,
        "source_start_s": 0, "source_end_s": 4, "action": "石板路与河面可见",
        "evidence_type": "visual", "provenance": {"provider": "mock", "demo": True},
    }
    calls = []

    def extract(db, asset, run, model, progress):
        calls.append(run.config_hash)
        assert asset.id == context.asset_id
        assert run.config_hash == pipeline.config_hash()
        return [deepcopy(evidence)], [], False

    class Model:
        name = "mock"

        def verify(self, task, new_evidence, previous):
            assert [row["id"] for row in previous] == [context.evidence_id]
            assert new_evidence == [evidence]
            during_verify()
            return {
                "checks": [{"check": text, "status": "passed", "reason": "画面可见",
                            "evidence_ids": [evidence["id"]]} for text in task["acceptance_checks"]],
                "requirement_status": "passed", "reason": "补拍满足条件", "continuity_issues": [],
            }

        def match(self, requirements, all_evidence, coverage, project):
            return [{
                "requirement_id": requirements[0]["id"], "evidence_ids": [evidence["id"]],
                "semantic_match": "related", "sufficiency": "supported", "usability": "usable",
                "reason": "新素材支持需求", "alternative_edit": "", "continuity_issue": "",
            }]

    monkeypatch.setattr(pipeline, "extract_asset", extract)
    monkeypatch.setattr(pipeline, "provider", Model)
    return calls


def verify(context):
    pipeline.verify_submission(
        SimpleNamespace(data={"submission_id": context.submission_id}), lambda *args: None,
    )


def test_verification_uses_current_config_without_rewriting_source_analysis(context, monkeypatch):
    calls = fake_verification(monkeypatch, context)
    verify(context)
    with SessionLocal() as db:
        submission = db.get(Submission, context.submission_id)
        assert submission.verification_status == "passed"
        assert not submission.data["stale"]
        assert submission.data["verification_config_hash"] == pipeline.config_hash()
        assert submission.data["source_analysis_config_hash"] == "original-analysis-config"
        assert submission.data["verification_provider"] == "mock"
        assert db.get(AnalysisRun, context.run_id).config_hash == "original-analysis-config"
        assert db.get(Gap, context.gap_id).data["resolution_submission_id"] == submission.id
    assert calls == [pipeline.config_hash()]


@pytest.mark.parametrize("change,stale", [("supplement", False), ("intent", True), ("new_analysis", True)])
def test_completion_distinguishes_supplement_upload_from_stale_goals(context, monkeypatch, change, stale):
    def mutate():
        with SessionLocal() as db:
            project = db.get(Project, context.project_id)
            project.revision += 1
            project.latest_analysis_id = None
            if change == "intent":
                project.intent = "验证途中变更了需求"
            elif change == "new_analysis":
                source = db.get(AnalysisRun, context.run_id)
                db.add(AnalysisRun(
                    id=uid(), project_id=project.id, project_revision=project.revision,
                    asset_snapshot=[], config_hash=pipeline.config_hash(), status="succeeded",
                    created_at="2026-09-23T09:00:00+00:00", data=deepcopy(source.data),
                ))
            else:
                db.add(Asset(
                    id=uid(), project_id=project.id, source_type="real_capture",
                    original_name="另一段补拍.mp4", storage_key="not-read.mp4", sha256="second",
                    duration_s=3, width=640, height=360, has_audio=False, status="queued", meta={},
                ))
            db.commit()

    fake_verification(monkeypatch, context, mutate)
    verify(context)
    with SessionLocal() as db:
        submission = db.get(Submission, context.submission_id)
        gap = db.get(Gap, context.gap_id)
        assert submission.verification_status == "passed"
        assert submission.data["stale"] is stale
        assert gap.data["status"] == ("confirmed" if stale else "resolved")


@pytest.mark.parametrize("status", ["dismissed", "resolved"])
def test_late_result_does_not_overwrite_existing_gap_decision(context, monkeypatch, status):
    def decide():
        with SessionLocal() as db:
            gap = db.get(Gap, context.gap_id)
            gap.data = {**gap.data, "status": status, "resolution_submission_id": "earlier-decision"}
            db.commit()

    fake_verification(monkeypatch, context, decide)
    verify(context)
    with SessionLocal() as db:
        gap = db.get(Gap, context.gap_id)
        assert gap.data["status"] == status
        assert gap.data["resolution_submission_id"] == "earlier-decision"
