"""Account boundaries apply to IDs, media URLs and long-lived job streams alike."""

import hashlib
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.main import app
from app.models import (
    AnalysisRun,
    Asset,
    CompletionPlan,
    CompletionTask,
    Evidence,
    Gap,
    Job,
    Project,
    Requirement,
    SessionLocal,
    uid,
)
from app.providers.storage import storage
from app.workflows.pipeline import config_hash


API = "/api/v1"
MUTATION_HEADERS = {"X-Requested-With": "XMLHttpRequest"}
PASSWORD = "private-test-password"


@pytest.fixture
def accounts(client):
    # Depend on the existing database-reset fixture, but do not share its cookie
    # jar: each client represents a separate browser/account.
    with TestClient(app, headers=MUTATION_HEADERS) as alice, TestClient(
        app, headers=MUTATION_HEADERS
    ) as bob:
        for browser, username in ((alice, "alice"), (bob, "bob")):
            response = browser.post(
                f"{API}/auth/register",
                json={"username": username, "password": PASSWORD},
            )
            assert response.status_code == 201, response.text
        yield SimpleNamespace(alice=alice, bob=bob)


def create_project(browser, title="Private Vlog"):
    response = browser.post(
        f"{API}/projects",
        json={"title": title, "intent": "展示活动经过", "input_mode": "vlog"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def seed_project(browser):
    """Build a complete local object graph without model or FFmpeg calls."""
    project_id = create_project(browser)
    folder = f"account-tests/{project_id}"
    original_key, frame_key = f"{folder}/original.mp4", f"{folder}/frame.jpg"
    storage.path(original_key).parent.mkdir(parents=True, exist_ok=True)
    storage.path(original_key).write_bytes(b"private-video")
    storage.path(frame_key).write_bytes(b"private-frame")
    with SessionLocal() as db:
        project = db.get(Project, project_id)
        asset = Asset(
            id=uid(), project_id=project_id, source_type="edited_video",
            original_name="private.mp4", storage_key=original_key,
            sha256="account-test", duration_s=5, width=640, height=360,
            has_audio=False, status="ready",
            meta={
                "proxy_key": original_key, "thumbnail_key": frame_key,
                "scene_shots": [{
                    "id": uid(), "index": 1, "start_s": 0, "end_s": 5,
                    "boundary_type": "start",
                    "keyframes": [{"time_s": 2, "key": frame_key}],
                }],
            },
        )
        db.add(asset)
        db.flush()
        project.constraints_json = {"primary_asset_id": asset.id}
        run = AnalysisRun(
            id=uid(), project_id=project_id, project_revision=project.revision,
            asset_snapshot=[asset.id], config_hash=config_hash(), status="succeeded",
            data={"project_config": {
                "intent": project.intent, "style": project.style,
                "input_mode": project.input_mode,
                "target_duration_s": project.target_duration_s,
                "constraints_json": project.constraints_json,
            }},
        )
        db.add(run)
        db.flush()
        project.latest_analysis_id = run.id
        evidence = Evidence(
            id=uid(), project_id=project_id, analysis_id=run.id,
            data={"asset_id": asset.id, "source_start_s": 0, "source_end_s": 5,
                  "evidence_type": "visual", "action": "参加活动"},
        )
        requirement = Requirement(
            id=uid(), project_id=project_id, analysis_id=run.id,
            data={"description": "说明活动地点", "priority": "should"},
        )
        gap = Gap(
            id=uid(), project_id=project_id, analysis_id=run.id,
            data={"description": "地点不清楚", "status": "confirmed",
                  "uncertain": False, "evidence_ids": [evidence.id]},
        )
        plan = CompletionPlan(id=uid(), project_id=project_id, analysis_id=run.id, data={})
        db.add_all([evidence, requirement, gap, plan])
        db.flush()
        task = CompletionTask(
            id=uid(), project_id=project_id, plan_id=plan.id,
            data={"type": "reshoot", "instruction": "补充地点镜头",
                  "requirement_description": "说明活动地点",
                  "gap_ids": [gap.id], "reference_evidence_ids": [evidence.id],
                  "recommendation": {"duration_s": 5, "subject_action": "进入活动场地",
                                     "shot_scale": "wide"}},
        )
        job = Job(id=uid(), project_id=project_id, type="analysis", status="succeeded",
                  data={"analysis_id": run.id})
        db.add_all([task, job])
        db.commit()
        return SimpleNamespace(
            project=project_id, asset=asset.id, analysis=run.id, requirement=requirement.id,
            gap=gap.id, plan=plan.id, task=task.id, job=job.id,
            original_key=original_key,
        )


def read_urls(graph):
    return [
        f"/projects/{graph.project}",
        f"/projects/{graph.project}/assets",
        f"/projects/{graph.project}/analyses",
        f"/projects/{graph.project}/completion-plans",
        f"/projects/{graph.project}/jobs",
        f"/assets/{graph.asset}/media/original",
        f"/assets/{graph.asset}/media/preview",
        f"/assets/{graph.asset}/media/thumbnail",
        f"/assets/{graph.asset}/frame?at=2",
        f"/analyses/{graph.analysis}",
        f"/analyses/{graph.analysis}/diagnosis",
        f"/completion-plans/{graph.plan}",
        f"/completion-tasks/{graph.task}/generation-options",
        f"/completion-tasks/{graph.task}/generations",
        f"/jobs/{graph.job}",
        f"/jobs/{graph.job}/events",
    ]


def generation_body(graph):
    return {
        "prompt": "补充活动地点镜头", "duration_s": 5, "resolution": "720P",
        "reference_asset_id": graph.asset, "reference_time_s": 2,
    }


def test_anonymous_cannot_read_accounts_projects_or_private_media(accounts):
    graph = seed_project(accounts.alice)
    with TestClient(app, headers=MUTATION_HEADERS) as anonymous:
        for path in ["/auth/me", "/projects", *read_urls(graph)]:
            response = anonymous.get(API + path)
            assert response.status_code == 401, (path, response.text)
        response = anonymous.post(
            f"{API}/projects", json={"title": "No account", "intent": "Private"},
        )
        assert response.status_code == 401


def test_accounts_only_see_and_edit_their_own_projects(accounts):
    alice_id = create_project(accounts.alice, "Alice only")
    bob_id = create_project(accounts.bob, "Bob only")
    for owner, other, own_id, other_id in (
        (accounts.alice, accounts.bob, alice_id, bob_id),
        (accounts.bob, accounts.alice, bob_id, alice_id),
    ):
        assert [p["id"] for p in owner.get(f"{API}/projects").json()] == [own_id]
        response = owner.patch(f"{API}/projects/{own_id}", json={"title": "Updated"})
        assert response.status_code == 200
        assert response.json()["title"] == "Updated"
        assert owner.get(f"{API}/projects/{other_id}").status_code == 404
        assert owner.patch(f"{API}/projects/{other_id}", json={"title": "Stolen"}).status_code == 404
        assert owner.delete(f"{API}/projects/{other_id}").status_code == 404
        assert other.get(f"{API}/projects/{other_id}").status_code == 200


def test_private_object_ids_media_and_generation_are_all_owner_scoped(accounts):
    graph = seed_project(accounts.alice)
    # The URLs really exist and work for the owner, including a finite SSE job.
    for path in read_urls(graph):
        allowed = accounts.alice.get(API + path)
        assert allowed.status_code == 200, (path, allowed.text)
        denied = accounts.bob.get(API + path)
        assert denied.status_code == 404, (path, denied.text)
        assert "private-video" not in denied.text and "private-frame" not in denied.text
    writes = [
        ("patch", f"/requirements/{graph.requirement}", {"description": "Stolen"}),
        ("patch", f"/gaps/{graph.gap}", {"status": "dismissed"}),
        ("post", f"/projects/{graph.project}/analyses", None),
        ("post", f"/projects/{graph.project}/completion-plans", {"analysis_id": graph.analysis}),
        ("post", f"/completion-tasks/{graph.task}/submissions", {"asset_id": graph.asset}),
        ("post", f"/completion-tasks/{graph.task}/generations", generation_body(graph)),
        ("post", f"/jobs/{graph.job}/retry", None),
    ]
    for method, path, body in writes:
        response = accounts.bob.request(
            method, API + path, json=body, headers={"Idempotency-Key": "private-boundary"},
        )
        assert response.status_code == 404, (path, response.text)
    upload = accounts.bob.post(
        f"{API}/projects/{graph.project}/assets",
        files={"file": ("attempt.mp4", b"not-a-video", "video/mp4")},
    )
    assert upload.status_code == 404
    with SessionLocal() as db:
        assert len(db.scalars(select(Job)).all()) == 1


def test_cross_project_asset_and_analysis_references_are_rejected(accounts):
    alice = seed_project(accounts.alice)
    bob = seed_project(accounts.bob)
    for browser, own, foreign in (
        (accounts.alice, alice, bob), (accounts.bob, bob, alice),
    ):
        assert browser.patch(
            f"{API}/projects/{own.project}", json={"primary_asset_id": foreign.asset},
        ).status_code == 404
        assert browser.post(
            f"{API}/completion-tasks/{own.task}/submissions", json={"asset_id": foreign.asset},
        ).status_code == 404
        assert browser.post(
            f"{API}/projects/{own.project}/completion-plans", json={"analysis_id": foreign.analysis},
        ).status_code == 404


def test_renaming_project_preserves_current_analysis(accounts):
    graph = seed_project(accounts.alice)
    before = accounts.alice.get(f"{API}/projects/{graph.project}").json()
    changed = accounts.alice.patch(
        f"{API}/projects/{graph.project}", json={"title": "新的项目名称"},
    )
    assert changed.status_code == 200
    assert changed.json()["title"] == "新的项目名称"
    assert changed.json()["revision"] == before["revision"]
    assert changed.json()["latest_analysis_id"] == graph.analysis
    assert accounts.alice.get(f"{API}/analyses/{graph.analysis}").json()["stale"] is False


def test_legacy_unowned_projects_are_hidden_until_explicitly_assigned(accounts):
    project_id = create_project(accounts.alice)
    with SessionLocal() as db:
        # Explicit SQL NULL also bypasses test-fixture defaults for old tests.
        db.execute(update(Project).where(Project.id == project_id).values(owner_id=None))
        db.commit()
    for browser in (accounts.alice, accounts.bob):
        assert browser.get(f"{API}/projects").json() == []
        assert browser.get(f"{API}/projects/{project_id}").status_code == 404
        assert browser.patch(f"{API}/projects/{project_id}", json={"title": "Claim"}).status_code == 404
        assert browser.delete(f"{API}/projects/{project_id}").status_code == 404


def test_deletion_hides_complete_project_graph_without_removing_other_projects(accounts):
    graph = seed_project(accounts.alice)
    other_project = create_project(accounts.alice, "Keep this")
    response = accounts.alice.delete(f"{API}/projects/{graph.project}")
    assert response.status_code == 200, response.text
    assert response.json() == {"id": graph.project, "deleted": True}
    assert [p["id"] for p in accounts.alice.get(f"{API}/projects").json()] == [other_project]
    for path in read_urls(graph):
        assert accounts.alice.get(API + path).status_code == 404, path
    assert accounts.alice.patch(
        f"{API}/projects/{graph.project}", json={"title": "Restore accidentally"},
    ).status_code == 404
    assert accounts.alice.post(f"{API}/jobs/{graph.job}/retry").status_code == 404
    assert accounts.alice.post(
        f"{API}/completion-tasks/{graph.task}/generations",
        json=generation_body(graph), headers={"Idempotency-Key": "after-delete"},
    ).status_code == 404
    assert accounts.alice.delete(f"{API}/projects/{graph.project}").status_code == 404
    with SessionLocal() as db:
        assert db.get(Project, graph.project).deleted_at
        assert db.get(Asset, graph.asset) is not None
    assert storage.path(graph.original_key).read_bytes() == b"private-video"


@pytest.mark.parametrize("status", ["queued", "running"])
def test_deletion_refuses_in_flight_work(accounts, status):
    graph = seed_project(accounts.alice)
    with SessionLocal() as db:
        db.get(Job, graph.job).status = status
        db.commit()
    response = accounts.alice.delete(f"{API}/projects/{graph.project}")
    assert response.status_code == 409
    assert accounts.alice.get(f"{API}/projects/{graph.project}").status_code == 200
    with SessionLocal() as db:
        assert db.get(Project, graph.project).deleted_at is None
        assert db.get(Job, graph.job).status == status


def test_registration_login_hashing_and_cookie_protection(accounts):
    from app.models import User

    me = accounts.alice.get(f"{API}/auth/me").json()
    assert me["username"] == "alice" and me["id"]
    assert set(me) == {"id", "username"}
    with SessionLocal() as db:
        user = db.get(User, me["id"])
        assert user.password_hash != PASSWORD
        assert PASSWORD not in user.password_hash
    with TestClient(app, headers=MUTATION_HEADERS) as browser:
        duplicate = browser.post(
            f"{API}/auth/register", json={"username": "ALICE", "password": PASSWORD},
        )
        assert duplicate.status_code == 409
        assert browser.get(f"{API}/auth/me").status_code == 401
        rejected = browser.post(
            f"{API}/auth/login", json={"username": "alice", "password": "wrong-password"},
        )
        assert rejected.status_code == 401
        assert browser.get(f"{API}/auth/me").status_code == 401
        response = browser.post(
            f"{API}/auth/login", json={"username": "ALICE", "password": PASSWORD},
        )
        assert response.status_code == 200
        cookie = response.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=" in cookie
        assert PASSWORD not in cookie and "alice" not in cookie
        assert browser.get(f"{API}/auth/me").json() == me


@pytest.mark.parametrize("payload", [
    {"username": "ab", "password": PASSWORD},
    {"username": "a" * 33, "password": PASSWORD},
    {"username": "bad name", "password": PASSWORD},
    {"username": "中文名字", "password": PASSWORD},
    {"username": "valid", "password": "short"},
    {"username": "valid", "password": "x" * 129},
])
def test_registration_rejects_invalid_credentials(client, payload):
    with TestClient(app, headers=MUTATION_HEADERS) as browser:
        response = browser.post(f"{API}/auth/register", json=payload)
        assert response.status_code == 422
        assert browser.get(f"{API}/auth/me").status_code == 401


def test_logout_revokes_replayed_cookie(accounts):
    old_cookies = dict(accounts.alice.cookies)
    assert accounts.alice.post(f"{API}/auth/logout").status_code == 200
    assert accounts.alice.get(f"{API}/auth/me").status_code == 401
    with TestClient(app, headers=MUTATION_HEADERS) as replay:
        replay.cookies.update(old_cookies)
        assert replay.get(f"{API}/auth/me").status_code == 401
    assert accounts.bob.get(f"{API}/auth/me").status_code == 200


def test_session_tokens_are_hashed_and_expired_sessions_cannot_access_media(accounts):
    from app.auth import COOKIE_NAME
    from app.models import AuthSession

    graph = seed_project(accounts.alice)
    token = accounts.alice.cookies[COOKIE_NAME]
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    with SessionLocal() as db:
        session = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash))
        assert session is not None
        assert session.token_hash != token
        assert token not in repr({column.name: getattr(session, column.name)
                                  for column in AuthSession.__table__.columns})
        session.expires_at = time.time() - 1
        db.commit()
    assert accounts.alice.get(f"{API}/auth/me").status_code == 401
    assert accounts.alice.get(f"{API}/assets/{graph.asset}/media/original").status_code == 401
    assert accounts.alice.get(f"{API}/jobs/{graph.job}/events").status_code == 401
    assert accounts.bob.get(f"{API}/auth/me").status_code == 200


def test_password_change_invalidates_existing_sessions_and_old_password(accounts):
    with TestClient(app, headers=MUTATION_HEADERS) as second_device:
        assert second_device.post(
            f"{API}/auth/login", json={"username": "alice", "password": PASSWORD},
        ).status_code == 200
        old_cookies = dict(accounts.alice.cookies)
        wrong = accounts.alice.post(
            f"{API}/auth/password",
            json={"current_password": "wrong-password", "new_password": "replacement-password"},
        )
        assert wrong.status_code == 400
        assert second_device.get(f"{API}/auth/me").status_code == 200
        changed = accounts.alice.post(
            f"{API}/auth/password",
            json={"current_password": PASSWORD, "new_password": "replacement-password"},
        )
        assert changed.status_code == 200, changed.text
        assert second_device.get(f"{API}/auth/me").status_code == 401
        second_device.cookies.clear()
        second_device.cookies.update(old_cookies)
        assert second_device.get(f"{API}/auth/me").status_code == 401
        assert second_device.post(
            f"{API}/auth/login", json={"username": "alice", "password": PASSWORD},
        ).status_code == 401
        assert second_device.post(
            f"{API}/auth/login", json={"username": "alice", "password": "replacement-password"},
        ).status_code == 200


def test_mutations_require_ajax_header_even_with_valid_session(accounts):
    project_id = create_project(accounts.alice)
    with TestClient(app) as direct_form:
        direct_form.cookies.update(dict(accounts.alice.cookies))
        assert direct_form.get(f"{API}/auth/me").status_code == 200
        requests = [
            ("post", "/auth/register", {"username": "newuser", "password": PASSWORD}),
            ("post", "/auth/login", {"username": "alice", "password": PASSWORD}),
            ("post", "/auth/logout", None),
            ("post", "/auth/password", {"current_password": PASSWORD, "new_password": "replacement-password"}),
            ("post", "/projects", {"title": "Blocked", "intent": "Blocked"}),
            ("patch", f"/projects/{project_id}", {"title": "Blocked"}),
            ("delete", f"/projects/{project_id}", None),
        ]
        for method, path, body in requests:
            response = direct_form.request(method, API + path, json=body)
            assert response.status_code == 403, (path, response.text)
        assert direct_form.get(f"{API}/projects/{project_id}").status_code == 200
