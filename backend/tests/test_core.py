from types import SimpleNamespace
import pytest
from app.services.media.pipeline import windows
from app.services.diagnosis.engine import (
    validate_evidence,
    validate_matches,
    diagnose,
    merge_evidence,
)
from app.services.planning.engine import select_budget
from app.services.editing.render import validate_timeline
from app.providers.storage import storage


def test_source_time_and_overlapping_windows():
    assert windows(19) == [(0.0, 8.0), (6.0, 14.0), (12.0, 19)]
    value = {"source_start_s": 6.2, "source_end_s": 7.9, "action": "可见动作"}
    assert (
        validate_evidence(value, "asset", 19, {"start_s": 6, "end_s": 14})[
            "source_start_s"
        ]
        == 6.2
    )
    with pytest.raises(ValueError):
        validate_evidence(
            {**value, "source_end_s": 20}, "asset", 19, {"start_s": 6, "end_s": 14}
        )
    with pytest.raises(ValueError):
        validate_evidence(
            {**value, "source_start_s": float("nan")},
            "asset",
            19,
            {"start_s": 6, "end_s": 14},
        )


def test_repeated_action_at_different_time_is_not_merged():
    def e(a, b):
        return {
            "asset_id": "a",
            "source_start_s": a,
            "source_end_s": b,
            "action": "倒水",
            "provenance": {"windows": [[a, b]]},
        }

    assert len(merge_evidence([e(0, 2), e(7, 9)])) == 2
    merged = merge_evidence([e(0, 8), e(6, 14)])
    assert len(merged) == 1 and merged[0]["source_end_s"] == 14
    assert merged[0]["provenance"]["windows"] == [[0, 8], [6, 14]]


def test_unknown_references_and_false_support_rejected():
    req = [{"id": "r", "accepted_evidence_types": ["visual"]}]
    ev = [{"id": "e", "evidence_type": "audio"}]
    m = {
        "requirement_id": "r",
        "evidence_ids": ["bad"],
        "sufficiency": "supported",
        "semantic_match": "related",
        "usability": "usable",
    }
    with pytest.raises(ValueError):
        validate_matches([m], req, ev)
    with pytest.raises(ValueError):
        validate_matches([{**m, "evidence_ids": ["e"]}], req, ev)
    with pytest.raises(ValueError):
        validate_matches([m, m], req, ev)


def test_incomplete_coverage_and_optional_suggestions():
    r = {
        "id": "r",
        "description": "清晰操作",
        "priority": "must",
        "origin": "user_explicit",
        "user_confirmed": True,
        "accepted_evidence_types": ["visual", "audio"],
    }
    m = {
        "requirement_id": "r",
        "evidence_ids": [],
        "sufficiency": "not_found",
        "reason": "未找到",
        "alternative_edit": "",
    }
    coverage = {"visual_complete": False, "audio_complete": False, "ranges": []}
    g = diagnose([r], [m], coverage)[0]
    assert (
        g["uncertain"] and g["status"] == "needs_review" and g["severity"] == "review"
    )
    r["origin"] = "model_suggested"
    r["user_confirmed"] = False
    assert diagnose([r], [m], coverage)[0]["optional"]


def test_budget_marginal_coverage_and_zero_budget():
    candidates = [
        {"id": "a", "gap_ids": ["g"], "estimated_effort_min": 5, "weight": 3},
        {"id": "b", "gap_ids": ["g"], "estimated_effort_min": 8, "weight": 3},
        {"id": "c", "gap_ids": ["h"], "estimated_effort_min": 3, "weight": 2},
        {
            "id": "d",
            "gap_ids": ["i"],
            "estimated_effort_min": 1,
            "weight": 10,
            "needs_confirmation": True,
        },
    ]
    selected, covered, spent = select_budget(candidates, 8)
    assert set(selected) == {"a", "c"} and covered == {"g", "h"} and spent == 8
    assert select_budget(candidates, 0) == ([], set(), 0)


def test_edl_limits_and_missing_asset(tmp_path):
    p = storage.path("validation.mp4")
    p.write_bytes(b"test")
    asset = SimpleNamespace(status="ready", duration_s=5, storage_key="validation.mp4")
    assert (
        validate_timeline(
            [{"asset_id": "a", "source_in_s": 1, "source_out_s": 4}], {"a": asset}
        )
        == 3
    )
    for clip in [
        {"asset_id": "other", "source_in_s": 0, "source_out_s": 2},
        {"asset_id": "a", "source_in_s": 4, "source_out_s": 2},
        {"asset_id": "a", "source_in_s": 0, "source_out_s": 6},
    ]:
        with pytest.raises(ValueError):
            validate_timeline([clip], {"a": asset})
    with pytest.raises(ValueError):
        storage.path("../private.file")
