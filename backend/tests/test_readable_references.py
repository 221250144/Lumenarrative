from copy import deepcopy
import pytest

from app.models import SessionLocal, Project, Asset, AnalysisRun, Evidence, Gap, CompletionPlan, CompletionTask, Submission, uid
from app.services.diagnosis.presentation import ReadableReferences


SHOT = "03c1dd6c-b185-5047-93cb-a88aafad18cb"
SECOND = "904c3e44-ff3c-55bc-8561-2c866f68754d"
EVIDENCE = "7e067ec4-7a63-4e49-b21e-44bd24b0cfd7"
UNKNOWN = "00000000-0000-4000-8000-000000000099"


@pytest.mark.parametrize("reference", [
    SHOT, f"shot_id '{SHOT}'", f'shot_id: "{SHOT}"', f"SHOT_ID=`{SHOT.upper()}`",
    f"镜头编号：‘{SHOT}’", f"id: {SHOT}", f"shot_id: [{SHOT}]", f"shot_id（{SHOT}）",
])
def test_prose_references_become_actual_source_seconds(reference):
    render = ReadableReferences([{"id": SHOT, "start_s": 24.4, "end_s": 25.9}])
    assert render.text(f"将 {reference} 前移") == "将 24.4–25.9 秒 前移"


def test_multiple_shots_and_evidence_keep_their_own_intervals():
    render = ReadableReferences(
        [{"id": SHOT, "start_s": 24.4, "end_s": 25.9}, {"id": SECOND, "start_s": 60.033333, "end_s": 60.066667}],
        [{"id": EVIDENCE, "source_start_s": 24.6, "source_end_s": 25.2}],
    )
    assert render.text(f"{SHOT} 后接 '{SECOND}'，证据 id: {EVIDENCE}") == "24.4–25.9 秒 后接 60.033–60.067 秒，24.6–25.2 秒"
    assert render.text("镜头 7，从24.4秒到25.9秒；identity保持不变") == "镜头 7，从24.4秒到25.9秒；identity保持不变"


def test_unknown_and_invalid_references_do_not_invent_times():
    render = ReadableReferences([{"id": SHOT, "start_s": float('nan'), "end_s": 5}])
    for reference in [SHOT, UNKNOWN, "shot_id: deleted-shot"]:
        assert render.text(reference) == "对应片段（时间待核实）"


def test_projection_keeps_ids_urls_and_original_data_unchanged():
    render = ReadableReferences([{"id": SHOT, "start_s": 1, "end_s": 2}])
    raw = {"id": SHOT, "shot_id": SHOT, "evidence_ids": [SHOT], "issue_key": f"asset:{SHOT}:transition",
           "url": f"/shots/{SHOT}", "anchor": {"shot_id": SHOT},
           "recommendation": {"instruction": f"将 shot_id '{SHOT}' 移到开头", "acceptance_checks": [f"{SHOT} 可见"]}}
    original = deepcopy(raw)
    result = render.payload(raw)
    assert raw == original
    for key in ("id", "shot_id", "evidence_ids", "issue_key", "url", "anchor"):
        assert result[key] == original[key]
    assert result["recommendation"] == {"instruction": "将 1–2 秒 移到开头", "acceptance_checks": ["1–2 秒 可见"]}


@pytest.fixture
def archived(client):
    with SessionLocal() as db:
        p = Project(id=uid(), title="历史结果", intent="记录旅行", revision=1)
        db.add(p)
        db.flush()
        asset = Asset(id=uid(), project_id=p.id, source_type="edited_video", original_name="vlog.mp4", storage_key="not-needed.mp4", sha256="test", duration_s=70, width=640, height=360, has_audio=False, status="ready")
        db.add(asset)
        db.flush()
        run = AnalysisRun(id=uid(), project_id=p.id, project_revision=1, asset_snapshot=[asset.id], config_hash="archived", status="succeeded",
                          data={"shots": [{"id": SHOT, "asset_id": asset.id, "index": 7, "start_s": 24.4, "end_s": 25.9}], "vlog": {"summary": f"shot_id '{SHOT}' 展示地铁出口"}})
        db.add(run)
        db.flush()
        evidence = Evidence(id=EVIDENCE, project_id=p.id, analysis_id=run.id, data={"asset_id": asset.id, "shot_id": SHOT, "source_start_s": 24.5, "source_end_s": 25.6, "action": f"{SHOT} 出现人物"})
        gap = Gap(id=uid(), project_id=p.id, analysis_id=run.id, data={"description": "缺少转场", "reason": f"shot_id '{SHOT}' 显示地铁出口", "evidence_ids": [EVIDENCE], "anchor": {"shot_id": SHOT}, "recommendation": {"instruction": f"将 '{SHOT}' 前移"}})
        db.add_all([evidence, gap])
        plan = CompletionPlan(id=uid(), project_id=p.id, analysis_id=run.id, data={})
        db.add(plan)
        db.flush()
        task = CompletionTask(id=uid(), project_id=p.id, plan_id=plan.id, data={"instruction": f"将 '{SHOT}' 前移", "acceptance_checks": [f"{SHOT} 交代出口"], "reference_evidence_ids": [EVIDENCE]})
        db.add(task)
        db.flush()
        new_id, new_shot = uid(), uid()
        extra = Asset(id=uid(), project_id=p.id, source_type="real_capture", original_name="extra.mp4", storage_key="extra.mp4", sha256="extra", duration_s=3, width=640, height=360, has_audio=False, status="ready", meta={"scene_shots": [{"id": new_shot, "index": 1, "start_s": 0, "end_s": 3, "boundary_type": "start", "keyframes": [{"time_s": 0, "key": "unused.jpg"}]}]})
        db.add(extra)
        db.flush()
        sub = Submission(id=uid(), project_id=p.id, task_id=task.id, asset_id=extra.id, data={"reason": f"新证据 {new_id} 与 '{SHOT}' 连贯", "new_evidence": [{"id": new_id, "shot_id": new_shot, "source_start_s": 0.5, "source_end_s": 2}], "checks": [{"check": f"{SHOT} 交代出口", "reason": f"证据 id: {new_id} 位于 shot_id '{new_shot}'", "evidence_ids": [new_id]}]})
        db.add(sub)
        db.commit()
        return {"analysis_id": run.id, "plan_id": plan.id, "task_id": task.id, "gap_id": gap.id, "new_id": new_id}


def test_existing_diagnosis_is_readable_without_regeneration_or_db_mutation(client, archived):
    response = client.get(f"/api/v1/analyses/{archived['analysis_id']}/diagnosis")
    assert response.status_code == 200
    data = response.json()
    assert data["vlog"]["summary"] == "24.4–25.9 秒 展示地铁出口"
    assert data["gaps"][0]["reason"] == "24.4–25.9 秒 显示地铁出口"
    assert data["gaps"][0]["anchor"]["shot_id"] == SHOT
    assert data["gaps"][0]["evidence_ids"] == [EVIDENCE]
    assert data["shots"][0]["id"] == SHOT
    with SessionLocal() as db:
        assert db.get(Gap, archived["gap_id"]).data["reason"] == f"shot_id '{SHOT}' 显示地铁出口"
        assert db.get(AnalysisRun, archived["analysis_id"]).status == "succeeded"


def test_archived_plan_and_verification_show_times_but_keep_original_acceptance_checks(client, archived):
    response = client.get(f"/api/v1/completion-plans/{archived['plan_id']}")
    assert response.status_code == 200
    task = response.json()["tasks"][0]
    assert task["instruction"] == "将 24.4–25.9 秒 前移"
    assert task["acceptance_checks"] == ["24.4–25.9 秒 交代出口"]
    sub = task["submissions"][0]
    assert sub["reason"] == "新证据 0.5–2 秒 与 24.4–25.9 秒 连贯"
    assert sub["checks"][0]["reason"] == "0.5–2 秒 位于 0–3 秒"
    assert sub["checks"][0]["evidence_ids"] == [archived["new_id"]]
    with SessionLocal() as db:
        assert db.get(CompletionTask, archived["task_id"]).data["acceptance_checks"] == [f"{SHOT} 交代出口"]


def test_old_short_shots_merge_only_in_display_and_keep_navigation_sources(client, archived):
    with SessionLocal() as db:
        run = db.get(AnalysisRun, archived["analysis_id"])
        asset = db.get(Asset, run.asset_snapshot[0])
        raw_shots = [
            {"id": sid, "asset_id": asset.id, "index": i, "start_s": start, "end_s": end,
             "boundary_type": "hard_cut", "summary": f"画面{i}",
             "keyframes": [{"time_s": start, "key": "unused.jpg"}]}
            for i, (sid, start, end) in enumerate([
                (SECOND, 24.3, 24.4), (SHOT, 24.4, 25.9), (UNKNOWN, 25.9, 26.4),
            ], 1)
        ]
        run.data = {**run.data, "shots": raw_shots}
        asset.meta = {**asset.meta, "scene_shots": raw_shots, "segmentation_version": "vlog-shots-v2"}
        project_id, asset_id = asset.project_id, asset.id
        db.commit()

    data = client.get(f"/api/v1/analyses/{archived['analysis_id']}/diagnosis").json()
    assert data["shots"] == raw_shots
    displayed = data["display_shots"]
    assert [(s["start_s"], s["end_s"]) for s in displayed] == [(24.3, 25.9), (25.9, 26.4)]
    assert displayed[0]["source_shot_ids"] == [SECOND, SHOT]
    assert data["gaps"][0]["anchor"]["shot_id"] == SHOT
    assert "24.4–25.9 秒" in data["gaps"][0]["reason"]
    assets = client.get(f"/api/v1/projects/{project_id}/assets").json()
    public_asset = next(a for a in assets if a["id"] == asset_id)
    assert public_asset["shot_count"] == len(public_asset["shots"]) == 2
    with SessionLocal() as db:
        assert db.get(AnalysisRun, archived["analysis_id"]).data["shots"] == raw_shots
        assert db.get(Asset, asset_id).meta["scene_shots"] == raw_shots
