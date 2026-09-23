"""A deletion recommendation has no new clip duration; a reshoot always does."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.schemas import VlogRecommendation, VlogReviewOutput
from app.services.diagnosis.vlog import build_vlog_diagnosis
from app.services.planning.engine import plan_tasks


@pytest.fixture
def recommendation():
    return {
        "kind": "reedit",
        "instruction": "删除2.0–4.0秒重复的街景镜头，让前后画面直接衔接。",
        "shot_scale": "",
        "subject_action": "删去重复街景，不新增镜头",
        "duration_s": 0.0,
        "insert_position": "replace",
        "acceptance_checks": ["重复街景已删除，前后地点仍可辨认"],
    }


@pytest.mark.parametrize("kind,duration", [
    ("reedit", 0), ("reedit", 2.5), ("reshoot", 0.5),
    ("reedit", 30), ("reshoot", 30),
])
def test_valid_duration_is_preserved(recommendation, kind, duration):
    result = VlogRecommendation.model_validate({
        **recommendation, "kind": kind, "duration_s": duration,
    })
    assert result.duration_s == duration


def test_reshoot_zero_reports_specific_duration_error(recommendation):
    with pytest.raises(ValidationError) as raised:
        VlogRecommendation.model_validate({**recommendation, "kind": "reshoot"})
    error = raised.value.errors()[0]
    assert error["loc"] == ("duration_s",)
    assert "reshoot" in error["msg"] and "大于0" in error["msg"]
    assert "不要任意填入默认时长" in error["msg"]


@pytest.mark.parametrize("kind", ["reedit", "reshoot"])
@pytest.mark.parametrize("duration", [-0.1, 30.1, float("nan"), float("inf"), float("-inf")])
def test_invalid_durations_are_rejected(recommendation, kind, duration):
    with pytest.raises(ValidationError):
        VlogRecommendation.model_validate({
            **recommendation, "kind": kind, "duration_s": duration,
        })


def test_zero_duration_deletion_survives_review_diagnosis_and_plan(recommendation):
    source = {
        "summary": "街巷漫步中包含一段重复街景。", "vlog_type": "旅行Vlog",
        "chapters": [{"title": "街巷漫步", "summary": "两段相同街景", "shot_ids": ["shot-0", "shot-1"]}],
        "findings": [{
            "kind": "redundant", "title": "重复街景拖慢节奏",
            "observation": "0.0–2.0秒与2.0–4.0秒呈现相同街景。",
            "impact": "相同内容连续重复，观看节奏停滞。",
            "missing_information": "精简重复街景，保留清楚的地点交代",
            "anchor_shot_id": "shot-1", "related_shot_id": "shot-0",
            "evidence_ids": ["evidence-1", "evidence-0"],
            "priority": "should", "confidence": "high", "audio_dependent": False,
            "recommendation": deepcopy(recommendation),
        }],
    }
    review = VlogReviewOutput.model_validate(source).model_dump()
    shots = [{
        "id": f"shot-{i}", "asset_id": "vlog", "index": i,
        "start_s": float(2 * i), "end_s": float(2 * i + 2),
        "evidence_ids": [f"evidence-{i}"], "observed": True,
    } for i in range(2)]
    evidence = [{
        "id": f"evidence-{i}", "asset_id": "vlog", "shot_id": f"shot-{i}",
        "source_start_s": float(2 * i), "source_end_s": float(2 * i + 2),
        "action": "沿相同街巷向前行走", "subjects": ["街巷"], "evidence_type": "visual",
    } for i in range(2)]
    coverage = {"visual_complete": True, "audio_complete": True, "failed_ranges": []}
    diagnosis = build_vlog_diagnosis(review, shots, evidence, coverage)
    gap = diagnosis["gaps"][0]
    assert gap["recommendation"] == recommendation
    assert gap["alternative_edit"]["feasible"]
    gap["status"] = "confirmed"
    plan = plan_tasks(diagnosis["gaps"], diagnosis["requirements"], evidence, budget=10)
    assert len(plan["tasks"]) == 1
    task = plan["tasks"][0]
    assert task["type"] == "reedit" and task["selected"]
    assert task["recommendation"] == recommendation
    assert task["instruction"] == recommendation["instruction"]
    assert task["shooting_min"] == 0 and task["prompt"] == ""
