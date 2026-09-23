"""Semantic citation repair is bounded and must retain the original context."""

from copy import deepcopy
import json
from types import SimpleNamespace
from uuid import uuid4

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
    model_good = deepcopy(good)
    model_good["chapters"][0]["shot_ids"] = ["shot_1", "shot_2", "shot_3"]
    model_good["findings"][0].update({
        "anchor_shot_id": "shot_1", "related_shot_id": "shot_2",
        "evidence_ids": ["evidence_1", "evidence_2"],
    })
    return {
        "project": SimpleNamespace(intent="记录逛市场到吃饭的过程", style="自然日常"),
        "shots": shots, "evidence": evidence, "coverage": coverage, "good": good, "model_good": model_good,
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
    calls = stub_outputs(monkeypatch, [review_context["model_good"]])
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
    bad = deepcopy(review_context["model_good"])
    if invalid_reference == "unrelated_shot":
        bad["findings"][0]["evidence_ids"] = ["evidence_1", "evidence_3"]
    elif invalid_reference == "unknown_evidence":
        bad["findings"][0]["evidence_ids"] = ["evidence_1", "invented-evidence"]
    else:
        bad["findings"][0]["anchor_shot_id"] = "invented-shot"
    VlogReviewOutput.model_validate(bad)
    calls = stub_outputs(monkeypatch, [bad, review_context["model_good"]])
    result = call_review(review_context)
    assert result == good and len(calls) == 2
    original_payload, repair_payload = [call["payload"] for call in calls]
    assert repair_payload["previous_review"] == bad
    assert error in repair_payload["validation_error"]
    for key, original_value in original_payload.items():
        assert repair_payload[key] == original_value
    assert [item["id"] for item in repair_payload["shots"]] == ["shot_1", "shot_2", "shot_3"]
    assert repair_payload["coverage"]["ranges"] == [{"asset_id": "asset_1", "start_s": 0.0, "end_s": 6.0}]
    assert {item["id"] for item in repair_payload["evidence"]} == {
        "evidence_1", "evidence_2", "evidence_3"
    }
    assert all(call["schema"] is VlogReviewOutput for call in calls)
    assert all(not call["images"] for call in calls)
    assert "previous_review" not in original_payload


def test_two_invalid_reviews_raise_without_dropping_citations_or_retrying_again(
    monkeypatch, review_context
):
    first = deepcopy(review_context["model_good"])
    first["findings"][0]["evidence_ids"] = ["evidence_1", "evidence_3"]
    second = deepcopy(review_context["model_good"])
    second["findings"][0]["evidence_ids"] = ["evidence_1", "still-invented"]
    calls = stub_outputs(monkeypatch, [first, second])
    with pytest.raises(ValueError, match="连续两次未能正确关联镜头与证据"):
        call_review(review_context)
    assert len(calls) == 2
    assert calls[1]["payload"]["previous_review"] == first
    assert "锚点或相关镜头" in calls[1]["payload"]["validation_error"]
    # Retaining a valid citation beside the invalid one must not make either
    # result acceptable by silently filtering out the ungrounded references.
    assert first["findings"][0]["evidence_ids"] == ["evidence_1", "evidence_3"]
    assert second["findings"][0]["evidence_ids"] == ["evidence_1", "still-invented"]


def test_uuid_context_uses_only_short_refs_then_restores_exact_ids_without_mutation(monkeypatch, review_context):
    context = deepcopy(review_context)
    shot_ids = {f"shot-{index}": str(uuid4()) for index in range(3)}
    evidence_ids = {f"evidence-{index}": str(uuid4()) for index in range(3)}
    asset_id = str(uuid4())
    for shot in context["shots"]:
        shot["id"], shot["asset_id"] = shot_ids[shot["id"]], asset_id
        shot["evidence_ids"] = [evidence_ids[value] for value in shot["evidence_ids"]]
        shot["thumbnail_url"] = f"/api/assets/{asset_id}/frame"
    for item in context["evidence"]:
        item["id"], item["shot_id"], item["asset_id"] = evidence_ids[item["id"]], shot_ids[item["shot_id"]], asset_id
    context["coverage"]["ranges"][0]["asset_id"] = asset_id
    context["coverage"]["cached_asset_ids"] = [asset_id]
    # Deliberately unsorted input must still produce timeline-based aliases.
    context["shots"].reverse()
    context["evidence"].reverse()
    before = deepcopy(context)
    calls = stub_outputs(monkeypatch, [context["model_good"]])
    result = call_review(context)
    finding = result["findings"][0]
    assert finding["anchor_shot_id"] == shot_ids["shot-0"]
    assert finding["related_shot_id"] == shot_ids["shot-1"]
    assert finding["evidence_ids"] == [evidence_ids["evidence-0"], evidence_ids["evidence-1"]]
    assert result["chapters"][0]["shot_ids"] == list(shot_ids.values())
    encoded = json.dumps(calls[0]["payload"])
    assert all(value not in encoded for value in [*shot_ids.values(), *evidence_ids.values(), asset_id])
    assert "thumbnail_url" not in encoded and "provenance" not in encoded
    assert context == before


@pytest.mark.parametrize("bad_reference", ["evidence_02", "EVIDENCE_2", "evidence-2", "evidence_2 ", "SENSITIVE_PRIVATE_UUID"])
def test_unknown_alias_is_not_guessed_and_repair_has_exact_safe_field_hint(monkeypatch, review_context, caplog, bad_reference):
    bad = deepcopy(review_context["model_good"])
    bad["findings"][0]["evidence_ids"][1] = bad_reference
    calls = stub_outputs(monkeypatch, [bad, review_context["model_good"]])
    assert call_review(review_context) == review_context["good"]
    diagnostic = json.loads(calls[1]["payload"]["validation_error"])
    assert diagnostic["path"] == "findings.0.evidence_ids.1"
    assert diagnostic["code"] == "unknown_evidence"
    assert diagnostic["allowed_evidence_by_shot"] == {"shot_1": ["evidence_1"], "shot_2": ["evidence_2"]}
    assert bad_reference not in calls[1]["payload"]["validation_error"]
    assert bad_reference not in caplog.text


def test_chapter_aliases_are_validated_even_when_no_findings(monkeypatch, review_context):
    bad = deepcopy(review_context["model_good"])
    bad["findings"] = []
    bad["chapters"][0]["shot_ids"][1] = "unknown-private-shot"
    good = deepcopy(review_context["model_good"])
    good["findings"] = []
    calls = stub_outputs(monkeypatch, [bad, good])
    result = call_review(review_context)
    assert result["findings"] == [] and result["chapters"][0]["shot_ids"] == ["shot-0", "shot-1", "shot-2"]
    diagnostic = json.loads(calls[1]["payload"]["validation_error"])
    assert diagnostic["path"] == "chapters.0.shot_ids.1" and diagnostic["code"] == "unknown_shot"


def test_extra_same_shot_citation_is_repaired_not_silently_removed(monkeypatch, review_context):
    bad = deepcopy(review_context["model_good"])
    bad["findings"][0]["evidence_ids"].append("evidence_1")
    calls = stub_outputs(monkeypatch, [bad, review_context["model_good"]])
    assert call_review(review_context) == review_context["good"]
    assert json.loads(calls[1]["payload"]["validation_error"])["path"] == "findings.0.evidence_ids.2"
    assert calls[1]["payload"]["previous_review"]["findings"][0]["evidence_ids"] == ["evidence_1", "evidence_2", "evidence_1"]


@pytest.mark.parametrize("invalid", ["range", "asset", "index"])
def test_aliases_do_not_bypass_original_range_asset_or_index_validation(monkeypatch, review_context, invalid):
    if invalid == "range":
        review_context["evidence"][0]["source_end_s"] = 99
    elif invalid == "asset":
        review_context["evidence"][0]["asset_id"] = "other-asset"
    else:
        review_context["shots"][0]["evidence_ids"] = []
    calls = stub_outputs(monkeypatch, [review_context["model_good"], review_context["model_good"]])
    with pytest.raises(ValueError, match="连续两次未能正确关联"):
        call_review(review_context)
    assert len(calls) == 2
