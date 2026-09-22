"""Real media/HTTP integration with deterministic, explicitly synthetic reviews."""

import subprocess

import pytest

from app.config import settings
from app.models import SessionLocal, Project, Asset
from app.providers.models import MockProvider


def ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


@pytest.fixture(scope="module")
def joined_vlog(tmp_path_factory):
    path = tmp_path_factory.mktemp("vlog-workflow") / "三段合成Vlog_测试.mp4"
    command = [settings.ffmpeg_bin, "-y", "-v", "error"]
    for color in ("red", "lime", "blue"):
        command.extend([
            "-f", "lavfi", "-i", f"color=c={color}:s=320x180:r=25:d=2",
        ])
    command.extend([
        "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
        "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]",
        "-map", "[v]", "-map", "3:a", "-c:v", "libx264",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path),
    ])
    subprocess.run(command, check=True)
    return path


def new_project(client):
    return ok(client.post("/api/v1/projects", json={
        "title": "合成 Vlog 集成测试",
        "intent": "验证已剪辑视频的镜头定位和补拍流程",
    }), 201)


def upload(client, project_id, path, name="主Vlog.mp4"):
    with path.open("rb") as stream:
        result = ok(client.post(
            f"/api/v1/projects/{project_id}/assets",
            files={"file": (name, stream, "video/mp4")},
            data={"source_type": "edited_video"},
        ), 202)
    job = ok(client.get("/api/v1/jobs/" + result["job_id"]))
    assert job["status"] == "succeeded", job
    return result["asset_id"]


def analyze(client, project_id, *, success=True):
    started = ok(client.post(f"/api/v1/projects/{project_id}/analyses"), 202)
    job = ok(client.get("/api/v1/jobs/" + started["job_id"]))
    assert job["status"] == ("succeeded" if success else "failed"), job
    result = ok(client.get(f"/api/v1/analyses/{started['analysis_id']}/diagnosis"))
    return result, job


@pytest.fixture
def deterministic_model(monkeypatch):
    seen = {"extractions": [], "reviews": [], "fail_shot": None,
            "audio_dependent": False, "review_hook": None}

    def analyze_clip(self, asset, shot):
        seen["extractions"].append(asset.id)
        if seen["fail_shot"] in ("all", shot["shot_index"]):
            raise ValueError("测试注入：此镜头画面理解失败")
        start, end = shot["start_s"], shot["end_s"]
        # Separate observations in one real shot deliberately create extra
        # evidence records, to exercise the two-reference display limit.
        return [
            {
                "source_start_s": start + (end - start) * offset,
                "source_end_s": start + (end - start) * (offset + 0.6),
                "subjects": ["合成色块测试图"],
                "action": f"测试镜头{shot['shot_index']}的观察{number}",
                "story_roles": [], "quality_issues": [], "uncertainty": "",
                "evidence_type": "visual",
            }
            for number, offset in [(1, 0.0), (2, 0.3)]
        ]

    def review_vlog(self, project, shots, evidence, coverage):
        seen["reviews"].append({"shots": shots, "evidence": evidence, "coverage": coverage})
        anchor, related = shots[:2]
        citations = [
            item["id"] for item in evidence
            if item["shot_id"] in (anchor["id"], related["id"])
        ]
        if seen["review_hook"]:
            seen["review_hook"]()
        return {
            "summary": "三段合成色块视频，仅用于验证数据流程。",
            "vlog_type": "合成测试样片",
            "chapters": [{
                "title": "测试时间线", "shot_ids": [shot["id"] for shot in shots],
                "summary": "按真实切点排列的三段测试画面。",
            }],
            "findings": [{
                "kind": "transition",
                "title": f"第1与第2镜头之间需要交代 · 测试{len(seen['reviews'])}",
                "observation": "第1镜头切到第2镜头，中间没有可见的空间连接。",
                "impact": "观众无法确认两个镜头的空间关系。",
                "missing_information": "连接两个画面所在空间的过渡镜头",
                "anchor_shot_id": anchor["id"], "related_shot_id": related["id"],
                "evidence_ids": citations, "priority": "should", "confidence": "high",
                "audio_dependent": seen["audio_dependent"],
                "recommendation": {
                    "kind": "reshoot", "instruction": "补拍从第一处空间走向第二处的入口。",
                    "shot_scale": "中景", "subject_action": "走过连接两处空间的入口",
                    "duration_s": 3.0, "insert_position": "after",
                    "acceptance_checks": ["入口同时交代两个空间的关系"],
                },
            }],
        }

    # This label represents injected test observations, never a live API call.
    monkeypatch.setattr(MockProvider, "name", "test-observation")
    monkeypatch.setattr(MockProvider, "analyze_clip", analyze_clip)
    monkeypatch.setattr(MockProvider, "review_vlog", review_vlog)
    return seen


def test_default_vlog_real_cuts_and_automatic_primary(client, joined_vlog):
    project = new_project(client)
    assert project["input_mode"] == "vlog"
    asset_id = upload(client, project["id"], joined_vlog)
    current = ok(client.get("/api/v1/projects/" + project["id"]))
    assert current["constraints_json"]["primary_asset_id"] == asset_id
    asset = ok(client.get(f"/api/v1/projects/{project['id']}/assets"))[0]
    assert asset["status"] == "ready" and asset["shot_count"] == 3
    shots = asset["shots"]
    assert [shot["start_s"] for shot in shots] == pytest.approx([0, 2, 4], abs=0.05)
    assert shots[-1]["end_s"] == pytest.approx(6, abs=0.05)
    assert len({shot["id"] for shot in shots}) == 3
    assert all(shot["asset_id"] == asset_id for shot in shots)
    assert client.get(shots[1]["thumbnail_url"]).status_code == 200
    diagnosis, _ = analyze(client, project["id"])
    # The real segmentation works in mock mode without inventing content findings.
    assert diagnosis["vlog"]["shot_count"] == 3 and diagnosis["gaps"] == []
    assert not diagnosis["analysis"]["coverage"]["visual_complete"]


def test_key_evidence_specific_plan_and_supplement_exclusion(
    client, joined_vlog, deterministic_model
):
    project = new_project(client)
    primary_id = upload(client, project["id"], joined_vlog)
    supplement_id = upload(client, project["id"], joined_vlog, "补充素材.mp4")
    diagnosis, _ = analyze(client, project["id"])
    assert diagnosis["vlog"]["primary_asset_id"] == primary_id
    assert {item["asset_id"] for item in diagnosis["evidence"]} == {primary_id}
    assert set(deterministic_model["extractions"]) == {primary_id}
    assert supplement_id not in deterministic_model["extractions"]
    assert {item["asset_id"] for item in diagnosis["analysis"]["coverage"]["ranges"]} == {primary_id}
    assert len(diagnosis["evidence"]) == 6
    gap = diagnosis["gaps"][0]
    assert len(gap["evidence_ids"]) == 2
    cited = [item for item in diagnosis["evidence"] if item["id"] in gap["evidence_ids"]]
    assert len({item["shot_id"] for item in cited}) == 2
    assert gap["anchor"]["insert_at_s"] == pytest.approx(2, abs=0.05)
    assert not gap["uncertain"] and not gap["optional"]
    ok(client.patch("/api/v1/gaps/" + gap["id"], json={
        "status": "confirmed", "reason": "测试人工确认",
    }))
    plan = ok(client.post(f"/api/v1/projects/{project['id']}/completion-plans", json={
        "analysis_id": diagnosis["analysis"]["id"], "budget_min": 15,
    }), 201)
    assert len(plan["tasks"]) == 1
    task = plan["tasks"][0]
    assert task["type"] == "reshoot" and task["selected"]
    assert task["instruction"] == gap["recommendation"]["instruction"]
    assert task["acceptance_checks"] == gap["recommendation"]["acceptance_checks"]
    assert len(task["reference_frames"]) == len(task["reference_evidence_ids"]) == 2
    assert task["anchor"] == gap["anchor"]


def test_reanalysis_preserves_issue_override_with_new_title_and_evidence_ids(
    client, joined_vlog, deterministic_model
):
    project = new_project(client)
    primary_id = upload(client, project["id"], joined_vlog)
    first, _ = analyze(client, project["id"])
    old_gap = first["gaps"][0]
    ok(client.patch("/api/v1/gaps/" + old_gap["id"], json={
        "status": "dismissed", "reason": "有意保留跳切",
    }))
    second, _ = analyze(client, project["id"])
    new_gap = second["gaps"][0]
    assert old_gap["description"] != new_gap["description"]
    assert old_gap["issue_key"] == new_gap["issue_key"]
    assert old_gap["evidence_ids"] != new_gap["evidence_ids"]
    assert new_gap["status"] == "dismissed" and new_gap["human_reason"] == "有意保留跳切"
    assert second["analysis"]["coverage"]["cached_asset_ids"] == [primary_id]
    history = ok(client.get(f"/api/v1/analyses/{first['analysis']['id']}/diagnosis"))
    assert history["gaps"][0]["description"] == old_gap["description"]
    assert history["gaps"][0]["evidence_ids"] == old_gap["evidence_ids"]
    assert len(ok(client.get(f"/api/v1/projects/{project['id']}/analyses"))) == 2


@pytest.mark.parametrize("failure", [2, "all"])
def test_visual_failures_do_not_produce_definitive_absence(
    client, joined_vlog, deterministic_model, failure
):
    project = new_project(client)
    upload(client, project["id"], joined_vlog)
    deterministic_model["fail_shot"] = failure
    diagnosis, job = analyze(client, project["id"], success=failure != "all")
    if failure == "all":
        assert "全部失败" in job["error_message"]
        assert diagnosis["gaps"] == []
        assert not deterministic_model["reviews"]
        return
    gap = diagnosis["gaps"][0]
    assert gap["uncertain"] and gap["status"] == "needs_review"
    assert len(gap["evidence_ids"]) == 1
    assert not diagnosis["analysis"]["coverage"]["visual_complete"]
    assert not diagnosis["shots"][1]["observed"]
    assert diagnosis["matches"][0]["sufficiency"] == "uncertain"


def test_audio_uncertainty_cannot_be_cleared_by_confirming_gap(
    client, joined_vlog, deterministic_model
):
    project = new_project(client)
    upload(client, project["id"], joined_vlog)
    deterministic_model["audio_dependent"] = True
    diagnosis, _ = analyze(client, project["id"])
    assert not diagnosis["analysis"]["coverage"]["audio_complete"]
    gap = diagnosis["gaps"][0]
    assert gap["uncertain"] and "音频尚未完成识别" in gap["reason"]
    ok(client.patch("/api/v1/gaps/" + gap["id"], json={"status": "confirmed"}))
    plan = ok(client.post(f"/api/v1/projects/{project['id']}/completion-plans", json={
        "analysis_id": diagnosis["analysis"]["id"],
    }), 201)
    assert plan["tasks"][0]["needs_confirmation"] and not plan["tasks"][0]["selected"]
    rerun, _ = analyze(client, project["id"])
    assert rerun["gaps"][0]["status"] == "confirmed"
    assert rerun["gaps"][0]["uncertain"]


def test_inflight_project_change_saves_history_without_replacing_current(
    client, joined_vlog, deterministic_model
):
    project = new_project(client)
    upload(client, project["id"], joined_vlog)

    def change_project():
        with SessionLocal() as db:
            current = db.get(Project, project["id"])
            current.style = "处理中修改风格"
            current.revision += 1
            db.commit()

    deterministic_model["review_hook"] = change_project
    diagnosis, _ = analyze(client, project["id"])
    current = ok(client.get("/api/v1/projects/" + project["id"]))
    assert current["latest_analysis_id"] is None
    assert diagnosis["analysis"]["stale"]
    assert diagnosis["vlog"]["shot_count"] == 3 and len(diagnosis["gaps"]) == 1
    response = client.post(f"/api/v1/projects/{project['id']}/completion-plans", json={
        "analysis_id": diagnosis["analysis"]["id"],
    })
    assert response.status_code == 409


def test_long_primary_analysis_preserves_full_coverage_and_editing_is_retired(
    client, joined_vlog, tmp_path, deterministic_model, monkeypatch
):
    from app.api import routes

    long_vlog = tmp_path / "36秒主Vlog.mp4"
    subprocess.run([
        settings.ffmpeg_bin, "-y", "-v", "error", "-stream_loop", "5",
        "-i", str(joined_vlog), "-c", "copy", str(long_vlog),
    ], check=True)
    project = new_project(client)
    ok(client.patch("/api/v1/projects/" + project["id"], json={"target_duration_s": 30}))
    primary_id = upload(client, project["id"], long_vlog)
    supplement_id = upload(client, project["id"], joined_vlog, "补充素材.mp4")
    diagnosis, _ = analyze(client, project["id"])
    assets = ok(client.get(f"/api/v1/projects/{project['id']}/assets"))
    primary = next(asset for asset in assets if asset["id"] == primary_id)
    assert primary["duration_s"] > 30
    assert diagnosis["vlog"]["primary_asset_id"] == primary_id
    assert {e["asset_id"] for e in diagnosis["evidence"]} == {primary_id}
    assert supplement_id != primary_id
    assert diagnosis["shots"][0]["start_s"] == 0
    assert diagnosis["shots"][-1]["end_s"] == pytest.approx(primary["duration_s"])
    dispatched = []
    monkeypatch.setattr(routes, "dispatch", dispatched.append)
    retired = client.post(f"/api/v1/projects/{project['id']}/edits", json={
        "analysis_id": diagnosis["analysis"]["id"],
    })
    assert retired.status_code == 410 and dispatched == []


def test_supplement_still_processing_does_not_block_primary_analysis(
    client, joined_vlog, deterministic_model, monkeypatch
):
    from app.api import routes
    from app.workers.queue import execute

    project = new_project(client)
    primary_id = upload(client, project["id"], joined_vlog)
    monkeypatch.setattr(routes, "dispatch", lambda _: None)
    with joined_vlog.open("rb") as stream:
        pending = ok(client.post(f"/api/v1/projects/{project['id']}/assets", files={
            "file": ("处理中的补充素材.mp4", stream, "video/mp4"),
        }), 202)
    with SessionLocal() as db:
        db.get(Asset, pending["asset_id"]).status = "processing"
        db.commit()
    monkeypatch.setattr(routes, "dispatch", execute)
    diagnosis, _ = analyze(client, project["id"])
    assert diagnosis["vlog"]["primary_asset_id"] == primary_id
    assert {item["asset_id"] for item in diagnosis["evidence"]} == {primary_id}
    assert set(deterministic_model["extractions"]) == {primary_id}
    with SessionLocal() as db:
        assert db.get(Asset, pending["asset_id"]).status == "processing"


def test_changing_primary_rejects_submission_to_old_completion_task(
    client, joined_vlog, deterministic_model, monkeypatch
):
    from app.api import routes

    project = new_project(client)
    upload(client, project["id"], joined_vlog)
    diagnosis, _ = analyze(client, project["id"])
    ok(client.patch("/api/v1/gaps/" + diagnosis["gaps"][0]["id"], json={
        "status": "confirmed",
    }))
    plan = ok(client.post(f"/api/v1/projects/{project['id']}/completion-plans", json={
        "analysis_id": diagnosis["analysis"]["id"],
    }), 201)
    task = plan["tasks"][0]
    new_primary_id = upload(client, project["id"], joined_vlog, "新的主Vlog.mp4")
    supplement_id = upload(client, project["id"], joined_vlog, "旧任务补拍.mp4")
    ok(client.patch("/api/v1/projects/" + project["id"], json={
        "primary_asset_id": new_primary_id,
    }))
    dispatched = []
    monkeypatch.setattr(routes, "dispatch", dispatched.append)
    rejected = client.post(f"/api/v1/completion-tasks/{task['id']}/submissions", json={
        "asset_id": supplement_id,
    })
    assert rejected.status_code == 409 and "主片" in rejected.text
    assert dispatched == []
    unchanged_plan = ok(client.get("/api/v1/completion-plans/" + plan["id"]))
    assert unchanged_plan["tasks"][0]["submissions"] == []
