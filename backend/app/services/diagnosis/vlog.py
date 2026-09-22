"""Normalize a Vlog review without expanding observations into invented evidence."""

import math

from app.models import uid


_CONFIDENCE = {"low": 0, "medium": 1, "high": 2}
_MISSING_KINDS = {"missing_context", "missing_action", "missing_result"}
_EPSILON = 0.001


def _interval(item, start_key="source_start_s", end_key="source_end_s"):
    start, end = item.get(start_key), item.get(end_key)
    if (
        isinstance(start, bool)
        or isinstance(end, bool)
        or not isinstance(start, (int, float))
        or not isinstance(end, (int, float))
        or not math.isfinite(start)
        or not math.isfinite(end)
        or not 0 <= start < end
    ):
        raise ValueError("诊断引用的时间范围无效")
    return start, end


def _index(items, name):
    indexed = {}
    for item in items:
        item_id = item.get("id")
        if not item_id or item_id in indexed:
            raise ValueError(f"{name} ID 缺失或重复")
        indexed[item_id] = item
    return indexed


def _overlap(left, right):
    return min(left[1], right[1]) > max(left[0], right[0])


def select_key_evidence(evidence, ids, limit=2):
    """Return at most two cited IDs, keeping one per shot/overlapping interval.

    Caller order expresses relevance. Unknown citations are rejected even when
    they appear after the display limit; no unreferenced evidence is added.
    Legacy evidence without a shot ID is deduplicated by original asset/time.
    """
    by_id = _index(evidence, "证据")
    candidates = []
    for evidence_id in dict.fromkeys(ids):
        if evidence_id not in by_id:
            raise ValueError("诊断引用了不存在的证据")
        item = by_id[evidence_id]
        _interval(item)
        candidates.append(item)
    selected = []
    for item in candidates:
        if len(selected) >= max(0, min(2, limit)):
            break
        duplicate = any(
            old["asset_id"] == item["asset_id"]
            and (
                (item.get("shot_id") and item["shot_id"] == old.get("shot_id"))
                or _overlap(_interval(item), _interval(old))
            )
            for old in selected
        )
        if not duplicate:
            selected.append(item)
    return [item["id"] for item in selected]


def _shot_incomplete(shot, coverage):
    if not shot.get("observed", False):
        return True
    bounds = _interval(shot, "start_s", "end_s")
    failures = coverage.get("failed_ranges", [])
    if any(
        failed.get("asset_id") == shot["asset_id"]
        and _overlap(bounds, _interval(failed, "start_s", "end_s"))
        for failed in failures
    ):
        return True
    if not coverage.get("visual_complete", False) and not failures:
        # A global failure without localized ranges cannot be cleared by a
        # model's confidence or by a previous human confirmation.
        return True
    ranges = coverage.get("ranges", [])
    if not ranges:
        return False
    cursor = bounds[0]
    for start, end in sorted(
        _interval(item, "start_s", "end_s")
        for item in ranges
        if item.get("asset_id") == shot["asset_id"]
        and item.get("visual_status") not in ("failed", "unavailable", "unobserved")
    ):
        if start > cursor + _EPSILON:
            break
        cursor = max(cursor, end)
        if cursor >= bounds[1] - _EPSILON:
            return False
    return True


def _validate_finding(finding, shots_by_id, evidence_by_id, primary_asset_id):
    anchor_id = finding["anchor_shot_id"]
    related_id = finding.get("related_shot_id")
    if anchor_id not in shots_by_id or (
        related_id is not None and related_id not in shots_by_id
    ):
        raise ValueError("诊断引用了不存在的镜头锚点")
    if related_id == anchor_id:
        raise ValueError("相关镜头必须与锚点镜头不同")
    involved = [shots_by_id[anchor_id]]
    if related_id is not None:
        involved.append(shots_by_id[related_id])
    if any(shot["asset_id"] != primary_asset_id for shot in involved):
        raise ValueError("诊断锚点必须属于主 Vlog")
    allowed = {shot["id"] for shot in involved}
    for evidence_id in finding["evidence_ids"]:
        item = evidence_by_id.get(evidence_id)
        if item is None:
            raise ValueError("诊断引用了不存在的证据")
        if item.get("asset_id") != primary_asset_id:
            raise ValueError("诊断证据不属于主 Vlog")
        if item.get("shot_id") not in allowed:
            raise ValueError("诊断证据不属于锚点或相关镜头")
        shot = shots_by_id[item["shot_id"]]
        if evidence_id not in shot["evidence_ids"]:
            raise ValueError("诊断证据与镜头索引不一致")
        start, end = _interval(item)
        shot_start, shot_end = _interval(shot, "start_s", "end_s")
        if start < shot_start - _EPSILON or end > shot_end + _EPSILON:
            raise ValueError("诊断证据时间超出所属镜头")
    return involved


def build_vlog_diagnosis(review, shots, evidence, coverage, overrides=None):
    """Create compatible requirement/match/gap rows from localized findings.

    All model references are validated before duplicate findings or extra
    evidence are removed. Stable issue keys preserve manual decisions while
    uncertainty remains derived from this analysis's actual coverage.
    """
    findings = review["findings"]
    result = {"requirements": [], "matches": [], "gaps": []}
    if not findings:
        return result
    if not shots:
        raise ValueError("诊断缺少主 Vlog 镜头")
    shots_by_id = _index(shots, "镜头")
    evidence_by_id = _index(evidence, "证据")
    primary_asset_id = shots[0]["asset_id"]
    for shot in shots:
        _interval(shot, "start_s", "end_s")

    issues = {}
    for finding in findings:
        involved = _validate_finding(
            finding, shots_by_id, evidence_by_id, primary_asset_id
        )
        issue_key = f"{primary_asset_id}:{finding['anchor_shot_id']}:{finding['kind']}"
        rank = (
            _CONFIDENCE[finding["confidence"]],
            bool(finding["evidence_ids"]),
            bool(finding.get("related_shot_id")),
            len(finding["observation"]),
        )
        previous = issues.get(issue_key)
        priority = finding["priority"]
        if previous and previous["finding"]["priority"] == "should":
            priority = "should"
        if previous and previous["rank"] >= rank:
            previous["finding"]["priority"] = priority
            continue
        issues[issue_key] = {
            "finding": {**finding, "priority": priority},
            "involved": involved,
            "rank": rank,
        }

    for issue_key, issue in list(issues.items())[:5]:
        finding, involved = issue["finding"], issue["involved"]
        anchor = involved[0]
        # Always give the anchor and comparison shot an opportunity to appear;
        # repeated citations from one shot cannot crowd out the other shot.
        ordered_ids = [
            evidence_id
            for shot in involved
            for evidence_id in finding["evidence_ids"]
            if evidence_by_id[evidence_id]["shot_id"] == shot["id"]
        ]
        evidence_ids = select_key_evidence(evidence, ordered_ids)
        incomplete = any(_shot_incomplete(shot, coverage) for shot in involved)
        absence_incomplete = finding["kind"] in _MISSING_KINDS and (
            not coverage.get("visual_complete", False)
            or any(_shot_incomplete(shot, coverage) for shot in shots)
        )
        audio_unknown = finding["audio_dependent"] and not coverage.get(
            "audio_complete", False
        )
        limitations = []
        if incomplete:
            limitations.append("相关镜头尚未完整分析，不能断言所需画面不存在")
        if absence_incomplete:
            limitations.append("主 Vlog 仍有未完成分析的片段，所需内容可能出现在其他镜头中")
        if audio_unknown:
            limitations.append("音频尚未完成识别，不能断言旁白、对话或声音信息缺失")
        if finding["confidence"] == "low":
            limitations.append("该观点置信度较低，需要对照原片复核")
        if not evidence_ids:
            limitations.append("该观点没有可引用的观察证据，需要对照原片复核")
        uncertain = bool(limitations)
        optional = finding["priority"] == "optional"
        recommendation = dict(finding["recommendation"])
        position = recommendation["insert_position"]
        if position not in ("before", "after", "replace"):
            raise ValueError("诊断建议的插入位置无效")
        insert_at_s = anchor["end_s"] if position == "after" else anchor["start_s"]
        is_reedit = recommendation["kind"] == "reedit"
        reason = finding["observation"]
        if limitations:
            reason = "；".join(limitations) + "。待核实的观察：" + reason
        requirement_id = uid()
        requirement = {
            "id": requirement_id,
            "description": finding["missing_information"],
            "priority": finding["priority"],
            "origin": "model_suggested",
            "user_confirmed": False,
            "accepted_evidence_types": ["visual", "audio"]
            if finding["audio_dependent"]
            else ["visual"],
            "dependencies": [],
        }
        match = {
            "id": uid(),
            "requirement_id": requirement_id,
            "evidence_ids": evidence_ids,
            "semantic_match": "related" if evidence_ids else "uncertain",
            "sufficiency": "uncertain"
            if uncertain
            else "not_found"
            if finding["kind"] in _MISSING_KINDS
            else "partial",
            "usability": "unknown"
            if not evidence_ids
            else "limited"
            if uncertain
            else "usable",
            "reason": reason,
            "alternative_edit": recommendation["instruction"] if is_reedit else "",
            "continuity_issue": reason if finding["kind"] == "transition" else "",
        }
        corrections = overrides or {}
        override = corrections.get(issue_key)
        if override is None:
            override = corrections.get(finding["title"])
        if override is None:
            override = corrections.get(finding["missing_information"], {})
        gap = {
            "id": uid(),
            "requirement_id": requirement_id,
            "issue_key": issue_key,
            "kind": finding["kind"],
            "type": "transition_issue"
            if finding["kind"] == "transition"
            else "missing_content"
            if finding["kind"] in _MISSING_KINDS and not uncertain
            else "insufficient_expression",
            "description": finding["title"],
            "observation": finding["observation"],
            "reason": reason,
            "impact": finding["impact"],
            "missing_information": finding["missing_information"],
            "priority": finding["priority"],
            "confidence": finding["confidence"],
            "audio_dependent": finding["audio_dependent"],
            "severity": "optional" if optional else "review" if uncertain else "should",
            "status": override.get("status", "needs_review"),
            "human_reason": override.get("reason", ""),
            "optional": optional,
            "uncertain": uncertain,
            "uncertainty_reasons": limitations,
            "evidence_ids": evidence_ids,
            "searched_ranges": [
                {
                    "asset_id": shot["asset_id"],
                    "shot_id": shot["id"],
                    "start_s": shot["start_s"],
                    "end_s": shot["end_s"],
                    "visual_status": "partial"
                    if _shot_incomplete(shot, coverage)
                    else "sampled",
                }
                for shot in involved
            ],
            "anchor": {
                "asset_id": primary_asset_id,
                "shot_id": anchor["id"],
                "related_shot_id": finding.get("related_shot_id"),
                "start_s": anchor["start_s"],
                "end_s": anchor["end_s"],
                "insert_at_s": insert_at_s,
            },
            "recommendation": recommendation,
            "alternative_edit": {
                "feasible": is_reedit,
                "reason": recommendation["instruction"]
                if is_reedit
                else "当前证据未证明能仅靠现有素材修复",
            },
        }
        result["requirements"].append(requirement)
        result["matches"].append(match)
        result["gaps"].append(gap)
    return result
