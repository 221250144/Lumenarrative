"""Semantic citation repair is bounded and must retain the original context."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.providers.models import CompatibleProvider
from app.schemas import VlogReviewOutput


@pytest.fixture
def review_context():
    shots = [
        {
            "id": f"shot-{index}", "asset_id": "vlog", "index": index,
            "start_s": float(index * 2), "end_s": float((index + 1) * 2),
            "summary": summary, "observed": True,
            "evidence_ids": [f"evidence-{index}"],
        }
        for index, summary in enumerate(["进入市场", "坐在餐桌前", "离开餐厅"])
    ]
    evidence = [
        {
            "id": shot["evidence_ids"][0], "asset_id": "vlog",
            "shot_id": shot["id"], "source_start_s": shot["start_s"],
            "source_end_s": shot["end_s"], "action": shot["summary"],
            "evidence_type": "visual", "provenance": {"provider": "test"},
        }
        for shot in shots
    ]
    coverage = {
        "visual_complete": True, "audio_complete": False,
        "ranges": [{"asset_id": "vlog", "start_s": 0.0, "end_s": 6.0}],
        "failed_ranges": [],
    }
    good = {
        "summary": "从进入市场到用餐后离开的日常记录。",
        "vlog_type": "日常 Vlog",
        "chapters": [{
            "title": "市场与用餐", "shot_ids": [shot["id"] for shot in shots],
            "summary": "按顺序呈现市场和用餐画面。",
        }],
        "findings": [{
            "kind": "transition", "title": "市场与餐桌之间缺少空间交代",
            "observation": "进入市场后，下一镜头直接坐在餐桌前。",
            "impact": "观众不清楚餐桌是否位于市场内。",
            "missing_information": "市场与用餐场所的空间关系",
            "anchor_shot_id": "shot-0", "related_shot_id": "shot-1",
            "evidence_ids": ["evidence-0", "evidence-1"],
            "priority": "should", "confidence": "high", "audio_dependent": False,
            "recommendation": {
                "kind": "reshoot", "instruction": "补拍从市场走入用餐场所入口的镜头。",
                "shot_scale": "中景", "subject_action": "从市场走到用餐场所入口",
                "duration_s": 4.0, "insert_position": "after",
                "acceptance_checks": ["入口镜头交代市场与餐桌的空间关系"],
            },
        }],
    }
    # Invalid examples below deliberately remain schema-valid: this regression
    # concerns references to actual observations, not JSON/schema repairs.
    good = VlogReviewOutput.model_validate(good).model_dump()
    return {
        "project": SimpleNamespace(intent="记录逛市场到吃饭的过程", style="自然日常"),
        "shots": shots, "evidence": evidence, "coverage": coverage, "good": good,
    }


def stub_outputs(monkeypatch, outputs):
    calls = []

    def generate(self, instruction, payload, schema, images=()):
        calls.append({
            "instruction": instruction, "payload": deepcopy(payload),
            "schema": schema, "images": images,
        })
        if len(calls) > len(outputs):
            pytest.fail("Vlog 语义引用校验不得无限重试")
        return deepcopy(outputs[len(calls) - 1])

    monkeypatch.setattr(CompatibleProvider, "generate_structured", generate)
    return calls


def call_review(context):
    return CompatibleProvider().review_vlog(
        context["project"], context["shots"], context["evidence"], context["coverage"]
    )


def test_valid_review_needs_only_one_structured_generation(monkeypatch, review_context):
    good = review_context["good"]
    calls = stub_outputs(monkeypatch, [good])
    assert call_review(review_context) == good
    assert len(calls) == 1 and calls[0]["schema"] is VlogReviewOutput
    assert "previous_review" not in calls[0]["payload"]
    assert "validation_error" not in calls[0]["payload"]


@pytest.mark.parametrize("invalid_reference,error", [
    ("unrelated_shot", "诊断证据不属于锚点或相关镜头"),
    ("unknown_evidence", "诊断引用了不存在的证据"),
    ("unknown_anchor", "诊断引用了不存在的镜头锚点"),
])
def test_invalid_reference_gets_one_repair_with_original_review_and_error(
    monkeypatch, review_context, invalid_reference, error
):
    good = review_context["good"]
    bad = deepcopy(good)
    if invalid_reference == "unrelated_shot":
        bad["findings"][0]["evidence_ids"] = ["evidence-0", "evidence-2"]
    elif invalid_reference == "unknown_evidence":
        bad["findings"][0]["evidence_ids"] = ["evidence-0", "invented-evidence"]
    else:
        bad["findings"][0]["anchor_shot_id"] = "invented-shot"
    VlogReviewOutput.model_validate(bad)
    calls = stub_outputs(monkeypatch, [bad, good])
    result = call_review(review_context)
    assert result == good and len(calls) == 2
    original_payload, repair_payload = [call["payload"] for call in calls]
    assert repair_payload["previous_review"] == bad
    assert error in repair_payload["validation_error"]
    for key, original_value in original_payload.items():
        assert repair_payload[key] == original_value
    assert repair_payload["shots"] == review_context["shots"]
    assert repair_payload["coverage"] == review_context["coverage"]
    assert {item["id"] for item in repair_payload["evidence"]} == {
        "evidence-0", "evidence-1", "evidence-2"
    }
    assert all(call["schema"] is VlogReviewOutput for call in calls)
    assert all(not call["images"] for call in calls)
    assert "previous_review" not in original_payload


def test_two_invalid_reviews_raise_without_dropping_citations_or_retrying_again(
    monkeypatch, review_context
):
    first = deepcopy(review_context["good"])
    first["findings"][0]["evidence_ids"] = ["evidence-0", "evidence-2"]
    second = deepcopy(review_context["good"])
    second["findings"][0]["evidence_ids"] = ["evidence-0", "still-invented"]
    calls = stub_outputs(monkeypatch, [first, second])
    with pytest.raises(ValueError, match="不存在的证据"):
        call_review(review_context)
    assert len(calls) == 2
    assert calls[1]["payload"]["previous_review"] == first
    assert "锚点或相关镜头" in calls[1]["payload"]["validation_error"]
    # Retaining a valid citation beside the invalid one must not make either
    # result acceptable by silently filtering out the ungrounded references.
    assert first["findings"][0]["evidence_ids"] == ["evidence-0", "evidence-2"]
    assert second["findings"][0]["evidence_ids"] == ["evidence-0", "still-invented"]
