from copy import deepcopy

import pytest

from app.services.diagnosis.vlog import build_vlog_diagnosis, select_key_evidence


@pytest.fixture
def vlog():
    shots = [
        {
            "id": f"shot-{i}",
            "asset_id": "vlog",
            "index": i,
            "start_s": i * 10.0,
            "end_s": (i + 1) * 10.0,
            "summary": summary,
            "evidence_ids": [f"e-{i}-a", f"e-{i}-b"],
            "observed": True,
        }
        for i, summary in enumerate(["走进市场", "坐在餐桌前", "展示食物", "离开"])
    ]
    evidence = [
        {
            "id": f"e-{i}-{suffix}",
            "asset_id": "vlog",
            "shot_id": shot["id"],
            "source_start_s": shot["start_s"] + offset,
            "source_end_s": shot["start_s"] + offset + 3,
            "action": shot["summary"],
            "evidence_type": "visual",
        }
        for i, shot in enumerate(shots)
        for suffix, offset in [("a", 1), ("b", 2)]
    ]
    coverage = {
        "visual_complete": True,
        "audio_complete": True,
        "ranges": [
            {
                "asset_id": "vlog",
                "start_s": 0.0,
                "end_s": 40.0,
                "visual_status": "sampled",
                "audio_status": "analyzed",
            }
        ],
        "failed_ranges": [],
    }
    finding = {
        "kind": "transition",
        "title": "从市场跳到餐桌，缺少地点交代",
        "observation": "前一镜头在市场行走，下一镜头直接坐到餐桌前。",
        "impact": "观众不容易理解两处空间是否为同一地点。",
        "missing_information": "市场与餐桌所在场所的关系",
        "anchor_shot_id": "shot-0",
        "related_shot_id": "shot-1",
        "evidence_ids": ["e-0-a", "e-0-b", "e-1-a", "e-1-b"],
        "priority": "should",
        "confidence": "high",
        "audio_dependent": False,
        "recommendation": {
            "kind": "reshoot",
            "instruction": "补拍从市场走向餐桌所在入口的镜头。",
            "shot_scale": "中景",
            "subject_action": "从市场走向入口",
            "duration_s": 3.0,
            "insert_position": "after",
            "acceptance_checks": ["可辨认市场与入口的空间关系"],
        },
    }
    return {
        "review": {"findings": [finding]},
        "shots": shots,
        "evidence": evidence,
        "coverage": coverage,
    }


def test_two_shot_comparison_retains_one_key_citation_each(vlog):
    result = build_vlog_diagnosis(**vlog)
    req, match, gap = (
        result[key][0] for key in ("requirements", "matches", "gaps")
    )
    assert req["id"] == match["requirement_id"] == gap["requirement_id"]
    assert gap["evidence_ids"] == match["evidence_ids"] == ["e-0-a", "e-1-a"]
    assert req["origin"] == "model_suggested" and not req["user_confirmed"]
    assert req["priority"] == "should" and not gap["optional"]
    assert gap["status"] == "needs_review" and not gap["uncertain"]
    assert gap["anchor"]["asset_id"] == "vlog"
    assert gap["anchor"]["insert_at_s"] == 10
    assert len(gap["searched_ranges"]) == 2
    assert (
        gap["recommendation"]["instruction"]
        == "补拍从市场走向餐桌所在入口的镜头。"
    )


def test_key_citations_prioritize_anchor_even_if_listed_last(vlog):
    vlog["review"]["findings"][0]["evidence_ids"] = ["e-1-b", "e-1-a", "e-0-a"]
    assert build_vlog_diagnosis(**vlog)["gaps"][0]["evidence_ids"] == [
        "e-0-a", "e-1-b"
    ]


@pytest.mark.parametrize(
    "field,value",
    [
        ("anchor_shot_id", "unknown"),
        ("related_shot_id", "unknown"),
        ("related_shot_id", "shot-0"),
    ],
)
def test_unknown_or_self_referencing_anchor_is_rejected(vlog, field, value):
    vlog["review"]["findings"][0][field] = value
    with pytest.raises(ValueError):
        build_vlog_diagnosis(**vlog)


def test_unknown_citations_are_validated_before_display_limit_and_dedup(vlog):
    invalid = deepcopy(vlog["review"]["findings"][0])
    invalid["evidence_ids"].append("does-not-exist")
    invalid["confidence"] = "low"
    vlog["review"]["findings"].append(invalid)
    with pytest.raises(ValueError, match="不存在的证据"):
        build_vlog_diagnosis(**vlog)
    with pytest.raises(ValueError, match="不存在的证据"):
        select_key_evidence(vlog["evidence"], ["e-0-a", "e-1-a", "bad"])


@pytest.mark.parametrize(
    "change",
    [
        "foreign_asset", "unrelated_shot", "unindexed_citation",
        "outside_shot", "nonfinite_time",
    ],
)
def test_cross_asset_unrelated_or_invalid_time_evidence_is_rejected(vlog, change):
    item = vlog["evidence"][0]
    if change == "foreign_asset":
        item["asset_id"] = "uploaded-supplement"
    elif change == "unrelated_shot":
        vlog["review"]["findings"][0]["evidence_ids"].append("e-2-a")
    elif change == "unindexed_citation":
        vlog["shots"][0]["evidence_ids"].remove("e-0-a")
    elif change == "outside_shot":
        item["source_end_s"] = 10.1
    else:
        item["source_start_s"] = float("nan")
    with pytest.raises(ValueError):
        build_vlog_diagnosis(**vlog)


def test_related_anchor_from_another_asset_is_rejected(vlog):
    vlog["shots"][1]["asset_id"] = "supplement"
    with pytest.raises(ValueError, match="主 Vlog"):
        build_vlog_diagnosis(**vlog)


def test_overlapping_legacy_windows_are_not_repeated_links(vlog):
    items = deepcopy(vlog["evidence"])
    for item in items:
        item.pop("shot_id")
    assert select_key_evidence(items, ["e-0-a", "e-0-b", "e-1-a"]) == [
        "e-0-a", "e-1-a"
    ]
    assert select_key_evidence(items, ["e-0-a", "e-1-a", "e-2-a"], limit=20) == [
        "e-0-a", "e-1-a"
    ]


def test_distinct_nonoverlapping_evidence_from_same_shot_is_still_one_link(vlog):
    vlog["evidence"][1]["source_start_s"] = 6
    vlog["evidence"][1]["source_end_s"] = 9
    assert select_key_evidence(vlog["evidence"], ["e-0-a", "e-0-b", "e-1-a"]) == [
        "e-0-a", "e-1-a"
    ]


def test_unrecognized_audio_never_becomes_a_confirmed_absence(vlog):
    finding = vlog["review"]["findings"][0]
    finding["audio_dependent"] = True
    finding["kind"] = "missing_context"
    finding["observation"] = "没有听到介绍地点的旁白。"
    vlog["coverage"]["audio_complete"] = False
    result = build_vlog_diagnosis(
        **vlog,
        overrides={
            "vlog:shot-0:missing_context": {
                "status": "confirmed", "reason": "我已看过画面"
            }
        },
    )
    gap, match = result["gaps"][0], result["matches"][0]
    assert gap["status"] == "confirmed" and gap["uncertain"]
    assert gap["type"] == "insufficient_expression"
    assert match["sufficiency"] == "uncertain"
    assert "不能断言旁白" in gap["reason"]
    assert result["requirements"][0]["accepted_evidence_types"] == ["visual", "audio"]


@pytest.mark.parametrize(
    "failure",
    [
        "unobserved", "overlapping_failure", "missing_coverage",
        "global_unlocalized_failure",
    ],
)
def test_related_visual_coverage_limits_are_retained(vlog, failure):
    if failure == "unobserved":
        vlog["shots"][1]["observed"] = False
    elif failure == "overlapping_failure":
        vlog["coverage"]["visual_complete"] = False
        vlog["coverage"]["failed_ranges"] = [
            {"asset_id": "vlog", "start_s": 15, "end_s": 20}
        ]
    elif failure == "missing_coverage":
        vlog["coverage"]["ranges"][0]["end_s"] = 16
    else:
        vlog["coverage"]["visual_complete"] = False
    gap = build_vlog_diagnosis(**vlog)["gaps"][0]
    assert gap["uncertain"] and gap["severity"] == "review"
    assert any("相关镜头" in reason for reason in gap["uncertainty_reasons"])


@pytest.mark.parametrize("kind", ["transition", "redundant"])
def test_unrelated_failed_shot_does_not_downgrade_observed_comparison(vlog, kind):
    vlog["review"]["findings"][0]["kind"] = kind
    vlog["coverage"]["visual_complete"] = False
    vlog["coverage"]["failed_ranges"] = [
        {"asset_id": "vlog", "start_s": 30, "end_s": 40}
    ]
    assert not build_vlog_diagnosis(**vlog)["gaps"][0]["uncertain"]


@pytest.mark.parametrize("kind", ["missing_context", "missing_action", "missing_result"])
def test_missing_information_requires_coverage_beyond_the_anchor(vlog, kind):
    vlog["review"]["findings"][0]["kind"] = kind
    vlog["coverage"]["visual_complete"] = False
    vlog["coverage"]["failed_ranges"] = [
        {"asset_id": "vlog", "start_s": 30, "end_s": 40}
    ]
    issue_key = f"vlog:shot-0:{kind}"
    result = build_vlog_diagnosis(
        **vlog, overrides={issue_key: {"status": "confirmed"}}
    )
    gap = result["gaps"][0]
    assert gap["status"] == "confirmed" and gap["uncertain"]
    assert gap["type"] == "insufficient_expression"
    assert result["matches"][0]["sufficiency"] == "uncertain"
    assert "所需内容可能出现在其他镜头中" in gap["reason"]


def test_missing_citations_remain_uncertain_without_fabricated_links(vlog):
    vlog["review"]["findings"][0]["evidence_ids"] = []
    gap = build_vlog_diagnosis(**vlog)["gaps"][0]
    assert gap["uncertain"] and gap["evidence_ids"] == []


def test_duplicate_issue_keeps_specific_observation_and_preserves_priority(vlog):
    finding = vlog["review"]["findings"][0]
    vague = deepcopy(finding)
    vague.update(observation="转场不好。", confidence="low", priority="should")
    finding["priority"] = "optional"
    vlog["review"]["findings"] = [vague, finding]
    before = deepcopy(vlog)
    result = build_vlog_diagnosis(**vlog)
    assert (
        len(result["gaps"])
        == len(result["matches"])
        == len(result["requirements"])
        == 1
    )
    gap = result["gaps"][0]
    assert gap["observation"] == finding["observation"]
    assert gap["confidence"] == "high" and not gap["optional"]
    assert vlog == before


@pytest.mark.parametrize(
    "position,time", [("before", 10), ("after", 20), ("replace", 10)]
)
def test_insertion_time_is_computed_from_anchor(vlog, position, time):
    finding = vlog["review"]["findings"][0]
    finding["anchor_shot_id"], finding["related_shot_id"] = "shot-1", "shot-0"
    finding["recommendation"]["insert_position"] = position
    gap = build_vlog_diagnosis(**vlog)["gaps"][0]
    assert gap["anchor"]["insert_at_s"] == time
    assert gap["anchor"]["start_s"] == 10 and gap["anchor"]["end_s"] == 20


def test_stable_manual_override_wins_and_legacy_title_is_supported(vlog):
    title = vlog["review"]["findings"][0]["title"]
    overrides = {
        title: {"status": "dismissed", "reason": "旧标题修正"},
        "vlog:shot-0:transition": {"status": "confirmed", "reason": "确实需要补拍"},
    }
    gap = build_vlog_diagnosis(**vlog, overrides=overrides)["gaps"][0]
    assert gap["status"] == "confirmed" and gap["human_reason"] == "确实需要补拍"
    assert gap["issue_key"] == "vlog:shot-0:transition"
    overrides.pop(gap["issue_key"])
    assert (
        build_vlog_diagnosis(**vlog, overrides=overrides)["gaps"][0]["status"]
        == "dismissed"
    )
    legacy_description = vlog["review"]["findings"][0]["missing_information"]
    assert (
        build_vlog_diagnosis(
            **vlog, overrides={legacy_description: {"status": "confirmed"}}
        )["gaps"][0]["status"]
        == "confirmed"
    )


def test_optional_reedit_keeps_concrete_existing_material_instruction(vlog):
    finding = vlog["review"]["findings"][0]
    finding["kind"] = "redundant"
    finding["priority"] = "optional"
    finding["confidence"] = "low"
    finding["recommendation"]["kind"] = "reedit"
    finding["recommendation"]["instruction"] = "将市场走路镜头缩短到人物进入画面时。"
    gap = build_vlog_diagnosis(**vlog)["gaps"][0]
    assert gap["optional"] and gap["uncertain"] and gap["severity"] == "optional"
    assert gap["alternative_edit"] == {
        "feasible": True, "reason": finding["recommendation"]["instruction"]
    }


def test_zero_findings_is_a_valid_result(vlog):
    vlog["review"]["findings"] = []
    assert build_vlog_diagnosis(**vlog) == {"requirements": [], "matches": [], "gaps": []}


def test_total_findings_are_capped_even_for_unvalidated_callers(vlog):
    finding = vlog["review"]["findings"][0]
    alternatives = []
    for shot in vlog["shots"]:
        for kind in ("missing_context", "redundant"):
            alternatives.append(
                {
                    **deepcopy(finding),
                    "kind": kind,
                    "anchor_shot_id": shot["id"],
                    "related_shot_id": None,
                    "evidence_ids": [shot["evidence_ids"][0]],
                }
            )
    vlog["review"]["findings"] = alternatives
    assert len(build_vlog_diagnosis(**vlog)["gaps"]) == 5
