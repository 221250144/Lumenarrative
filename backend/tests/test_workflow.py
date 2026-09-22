import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from app.config import settings
from app.models import SessionLocal, Project, AnalysisRun, Job, Asset
from app.workflows.pipeline import create_analysis, analyze


def ok(response, code=200):
    assert response.status_code == code, response.text
    return response.json()


def demo(client, scenario="missing"):
    p = ok(client.post("/api/v1/demo", params={"scenario": scenario}), 201)
    for job_id in p["job_ids"]:
        job = ok(client.get("/api/v1/jobs/" + job_id))
        assert job["status"] == "succeeded", job
    return p


def diagnosis(client, p):
    run = ok(client.post(f"/api/v1/projects/{p['id']}/analyses"), 202)
    job = ok(client.get("/api/v1/jobs/" + run["job_id"]))
    assert job["status"] == "succeeded", job
    return ok(client.get(f"/api/v1/analyses/{run['analysis_id']}/diagnosis"))


def test_real_upload_remains_playable_and_analyzable_without_editing(client, tmp_path):
    original = tmp_path / "中文名字_静音.mp4"
    subprocess.run(
        [
            settings.ffmpeg_bin,
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=320x180:r=24:d=1.5",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(original),
        ],
        check=True,
    )
    p = ok(
        client.post(
            "/api/v1/projects", json={"title": "真实媒体链路", "intent": "感受色彩变化"}
        ),
        201,
    )

    def upload():
        with original.open("rb") as f:
            return client.post(
                f"/api/v1/projects/{p['id']}/assets",
                files={"file": ("中文名字_静音.mp4", f, "video/mp4")},
                data={"source_type": "real_capture"},
                headers={"Idempotency-Key": "upload-once"},
            )

    uploaded = ok(upload(), 202)
    assert ok(upload(), 202) == uploaded
    assets = ok(client.get(f"/api/v1/projects/{p['id']}/assets"))
    assert (
        len(assets) == 1
        and assets[0]["status"] == "ready"
        and not assets[0]["has_audio"]
    )
    preview = client.get(assets[0]["preview_url"], headers={"Range": "bytes=0-99"})
    assert preview.status_code == 206 and len(preview.content) == 100
    d = diagnosis(client, p)
    assert all(e["provenance"]["demo"] for e in d["evidence"])
    assert all(g["uncertain"] for g in d["gaps"])
    result = client.get(assets[0]["original_url"])
    assert result.status_code == 200 and result.content == original.read_bytes()
    assert client.post(
        f"/api/v1/projects/{p['id']}/edits", json={"analysis_id": d["analysis"]["id"]},
    ).status_code == 410
    invalid = client.post(
        f"/api/v1/projects/{p['id']}/assets",
        files={"file": ("fake.mp4", b"not a real video", "video/mp4")},
    )
    assert invalid.status_code == 422 and "request_id" in invalid.json()
    assert len(ok(client.get(f"/api/v1/projects/{p['id']}/assets"))) == 1


def test_missing_wrong_submission_then_correct_completion(client):
    p = demo(client)
    d = diagnosis(client, p)
    assert len(d["gaps"]) == 1 and "制作" in d["gaps"][0]["description"]
    ok(
        client.patch(
            "/api/v1/gaps/" + d["gaps"][0]["id"],
            json={"status": "confirmed", "reason": "人工核实缺少过程"},
        )
    )
    plan = ok(
        client.post(
            f"/api/v1/projects/{p['id']}/completion-plans",
            json={"analysis_id": d["analysis"]["id"], "budget_min": 15},
        ),
        201,
    )
    chosen = [t for t in plan["tasks"] if t["selected"]]
    assert len(chosen) == 1
    task = chosen[0]

    def submit(role, key):
        a = ok(
            client.post(
                f"/api/v1/projects/{p['id']}/demo-asset", params={"role": role}
            ),
            202,
        )
        response = ok(
            client.post(
                f"/api/v1/completion-tasks/{task['id']}/submissions",
                json={"asset_id": a["asset_id"]},
                headers={"Idempotency-Key": key},
            ),
            202,
        )
        assert (
            ok(
                client.post(
                    f"/api/v1/completion-tasks/{task['id']}/submissions",
                    json={"asset_id": a["asset_id"]},
                    headers={"Idempotency-Key": key},
                ),
                202,
            )
            == response
        )
        current = ok(client.get("/api/v1/completion-plans/" + plan["id"]))
        return next(t for t in current["tasks"] if t["id"] == task["id"])[
            "submissions"
        ][0]

    wrong = submit("result", "wrong")
    assert wrong["verification_status"] == "failed"
    assert (
        ok(client.get("/api/v1/analyses/" + d["analysis"]["id"] + "/diagnosis"))[
            "gaps"
        ][0]["status"]
        == "confirmed"
    )
    right = submit("process", "right")
    assert right["verification_status"] == "passed", right
    new = diagnosis(client, p)
    assert new["gaps"] == []
    assert new["analysis"]["coverage"]["cached_asset_ids"]
    # Both failed and accepted candidates remain available for the creator;
    # task verification no longer leads into an in-product editing workflow.
    assets = ok(client.get(f"/api/v1/projects/{p['id']}/assets"))
    assert {wrong["asset_id"], right["asset_id"]} <= {asset["id"] for asset in assets}


def test_all_required_story_cases(client):
    expected = {
        "complete": 0,
        "missing": 1,
        "obscured": 1,
        "unordered": 1,
        "montage": 0,
        "dialogue": 0,
        "conflict": 1,
        "partial": 1,
    }
    for scenario, gaps in expected.items():
        p = demo(client, scenario)
        d = diagnosis(client, p)
        assert len(d["gaps"]) == gaps, (scenario, d["gaps"])
        if scenario == "unordered":
            assert d["gaps"][0]["alternative_edit"]["feasible"]
            plan = ok(
                client.post(
                    f"/api/v1/projects/{p['id']}/completion-plans",
                    json={"analysis_id": d["analysis"]["id"]},
                ),
                201,
            )
            assert {t["type"] for t in plan["tasks"]} == {"reedit"}
        if scenario == "partial":
            assert not d["analysis"]["coverage"]["visual_complete"]
            assert d["gaps"][0]["uncertain"]
        if scenario == "conflict":
            assert d["gaps"][0]["type"] == "transition_issue"


def test_old_analysis_cannot_overwrite_project_and_corrections_persist(client):
    p = demo(client)
    with SessionLocal() as db:
        project = db.get(Project, p["id"])
        run = create_analysis(db, project)
        run_id = run.id
        db.commit()
    ok(client.patch("/api/v1/projects/" + p["id"], json={"style": "修改后的风格"}))
    analyze(SimpleNamespace(data={"analysis_id": run_id}), lambda *_: None)
    current = ok(client.get("/api/v1/projects/" + p["id"]))
    assert current["latest_analysis_id"] is None
    assert ok(client.get("/api/v1/analyses/" + run_id))["stale"]
    rejected = client.post(
        f"/api/v1/projects/{p['id']}/completion-plans", json={"analysis_id": run_id}
    )
    assert rejected.status_code == 409
    d = diagnosis(client, p)
    gap = d["gaps"][0]
    ok(
        client.patch(
            "/api/v1/gaps/" + gap["id"],
            json={"status": "dismissed", "reason": "艺术处理"},
        )
    )
    d2 = diagnosis(client, p)
    assert d2["gaps"][0]["status"] == "dismissed"
    req = d2["requirements"][0]
    ok(
        client.patch(
            "/api/v1/requirements/" + req["id"],
            json={"description": "人工指定的场景表达", "user_confirmed": True},
        )
    )
    d3 = diagnosis(client, p)
    assert d3["requirements"][0]["description"] == "人工指定的场景表达"


def test_failed_job_retry_and_real_mode_no_silent_fallback(client, monkeypatch):
    p = demo(client)
    monkeypatch.setattr(settings, "model_provider", "qwen")
    monkeypatch.setattr(settings, "model_api_key", "")
    r = ok(
        client.post(
            f"/api/v1/projects/{p['id']}/analyses",
            headers={"Idempotency-Key": "analysis-once"},
        ),
        202,
    )
    assert (
        ok(
            client.post(
                f"/api/v1/projects/{p['id']}/analyses",
                headers={"Idempotency-Key": "analysis-once"},
            ),
            202,
        )
        == r
    )
    job = ok(client.get("/api/v1/jobs/" + r["job_id"]))
    assert job["status"] == "failed" and "MODEL_API_KEY" in job["error_message"]
    assert ok(client.get("/api/v1/projects/" + p["id"]))["latest_analysis_id"] is None
    monkeypatch.setattr(settings, "model_provider", "mock")
    ok(client.post("/api/v1/jobs/" + r["job_id"] + "/retry"), 202)
    retried = ok(client.get("/api/v1/jobs/" + r["job_id"]))
    assert retried["status"] == "failed" and "配置已改变" in retried["error_message"]
    assert diagnosis(client, p)["analysis"]["provider"] == "mock"


def test_variable_frame_rate_and_audio_not_invented(client, tmp_path):
    file = tmp_path / "vfr.mp4"
    subprocess.run(
        [
            settings.ffmpeg_bin,
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=320x180:r=30:d=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-vf",
            "select='if(lt(t,1),not(mod(n,3)),1)'",
            "-fps_mode",
            "vfr",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-shortest",
            str(file),
        ],
        check=True,
    )
    p = ok(
        client.post(
            "/api/v1/projects",
            json={
                "title": "VFR",
                "intent": "画面与对白的表达",
                "input_mode": "rough_cut",
            },
        ),
        201,
    )
    with file.open("rb") as stream:
        r = ok(
            client.post(
                f"/api/v1/projects/{p['id']}/assets",
                files={"file": ("可变帧率.mp4", stream)},
            ),
            202,
        )
    job = ok(client.get("/api/v1/jobs/" + r["job_id"]))
    assert job["status"] == "succeeded", job
    a = ok(client.get(f"/api/v1/projects/{p['id']}/assets"))[0]
    assert a["has_audio"] and a["audio_status"] == "unconfigured"
    d = diagnosis(client, p)
    assert not d["analysis"]["coverage"]["audio_complete"]
    retired = client.post(
        f"/api/v1/projects/{p['id']}/edits",
        json={
            "analysis_id": d["analysis"]["id"],
            "timeline": [{"asset_id": a["id"], "source_in_s": 0, "source_out_s": 1}],
        },
    )
    assert retired.status_code == 410


def test_concurrent_analysis_idempotency(client, monkeypatch):
    from app.api import routes

    p = demo(client)
    monkeypatch.setattr(routes, "dispatch", lambda _: None)

    def request():
        return ok(
            client.post(
                f"/api/v1/projects/{p['id']}/analyses",
                headers={"Idempotency-Key": "concurrent"},
            ),
            202,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: request(), range(2)))
    assert responses[0] == responses[1]
    assert len(ok(client.get(f"/api/v1/projects/{p['id']}/analyses"))) == 1


def test_stale_verification_does_not_close_gap(client, monkeypatch):
    from app.providers.models import MockProvider

    original_verify = MockProvider.verify
    p = demo(client)
    d = diagnosis(client, p)
    gap_id = d["gaps"][0]["id"]
    ok(client.patch("/api/v1/gaps/" + gap_id, json={"status": "confirmed"}))
    plan = ok(
        client.post(
            f"/api/v1/projects/{p['id']}/completion-plans",
            json={"analysis_id": d["analysis"]["id"]},
        ),
        201,
    )
    task = next(t for t in plan["tasks"] if t["selected"])
    asset = ok(client.post(f"/api/v1/projects/{p['id']}/demo-asset?role=process"), 202)

    def changing_project(self, *args):
        result = original_verify(self, *args)
        with SessionLocal() as db:
            project = db.get(Project, p["id"])
            project.intent = "过程中用户修改了目标"
            project.revision += 1
            db.commit()
        return result

    monkeypatch.setattr(MockProvider, "verify", changing_project)
    ok(
        client.post(
            f"/api/v1/completion-tasks/{task['id']}/submissions",
            json={"asset_id": asset["asset_id"]},
        ),
        202,
    )
    updated = ok(client.get("/api/v1/completion-plans/" + plan["id"]))
    submission = next(t for t in updated["tasks"] if t["id"] == task["id"])[
        "submissions"
    ][0]
    assert submission["verification_status"] == "passed" and submission["stale"]
    assert (
        ok(client.get("/api/v1/analyses/" + d["analysis"]["id"] + "/diagnosis"))[
            "gaps"
        ][0]["status"]
        == "confirmed"
    )
