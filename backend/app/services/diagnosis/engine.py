import math
from app.models import uid


def validate_evidence(item, asset_id, duration, shot):
    start, end = item["source_start_s"], item["source_end_s"]
    if (
        not all(math.isfinite(x) for x in (start, end))
        or not 0 <= start < end <= duration + 0.001
    ):
        raise ValueError("模型证据时间范围超出原片")
    if start < shot["start_s"] - 0.001 or end > shot["end_s"] + 0.001:
        raise ValueError("模型证据时间范围超出已观察分段")
    return {
        **item,
        "id": uid(),
        "asset_id": asset_id,
        "source_end_s": min(end, duration),
    }


def merge_evidence(items):
    merged = []
    for item in sorted(items, key=lambda e: (e["asset_id"], e["source_start_s"])):
        previous = next(
            (
                x
                for x in reversed(merged)
                if x["asset_id"] == item["asset_id"]
                and x.get("shot_id") == item.get("shot_id")
                and x["action"] == item["action"]
                and x.get("evidence_type") == item.get("evidence_type")
                and min(x["source_end_s"], item["source_end_s"])
                > max(x["source_start_s"], item["source_start_s"])
            ),
            None,
        )
        if previous:
            previous["source_end_s"] = max(
                previous["source_end_s"], item["source_end_s"]
            )
            previous["provenance"]["windows"].extend(item["provenance"]["windows"])
        else:
            merged.append(item)
    return merged


def validate_matches(matches, requirements, evidence):
    reqs = {r["id"]: r for r in requirements}
    evs = {e["id"]: e for e in evidence}
    if len(matches) != len(reqs) or {m["requirement_id"] for m in matches} != set(reqs):
        raise ValueError("模型匹配结果未完整覆盖需求，或包含重复/未知需求")
    for m in matches:
        if any(e not in evs for e in m["evidence_ids"]):
            raise ValueError("模型引用了不存在的证据")
        if m["sufficiency"] == "supported":
            if (
                not m["evidence_ids"]
                or m["semantic_match"] != "related"
                or m["usability"] in ("unusable", "unknown")
            ):
                raise ValueError("充分支持的匹配缺少相关且可用的证据")
            if not any(
                evs[e].get("evidence_type", "visual")
                in reqs[m["requirement_id"]]["accepted_evidence_types"]
                for e in m["evidence_ids"]
            ):
                raise ValueError("匹配引用的证据类型不能满足该需求")
    return matches


def diagnose(requirements, matches, coverage, overrides=None):
    gaps = []
    by_req = {r["id"]: r for r in requirements}
    for match in matches:
        req = by_req[match["requirement_id"]]
        is_reedit = bool(match["alternative_edit"])
        continuity = bool(match.get("continuity_issue"))
        if match["sufficiency"] == "supported" and not is_reedit and not continuity:
            continue
        optional = req["priority"] == "optional" or (
            req["origin"] == "model_suggested" and not req["user_confirmed"]
        )
        incomplete = not coverage["visual_complete"] or (
            "audio" in req["accepted_evidence_types"] and not coverage["audio_complete"]
        )
        uncertain = match["sufficiency"] == "uncertain" or (
            match["sufficiency"] == "not_found" and incomplete
        )
        reason = match.get("continuity_issue") or match["reason"]
        if uncertain:
            reason += "；当前检索覆盖不支持断言该内容不存在，请人工复核。"
        override = (overrides or {}).get(req["description"], {})
        gaps.append(
            {
                "id": uid(),
                "requirement_id": req["id"],
                "type": "transition_issue"
                if continuity or is_reedit
                else "missing_content"
                if match["sufficiency"] == "not_found"
                else "insufficient_expression",
                "severity": "optional"
                if optional
                else "review"
                if uncertain
                else req["priority"],
                "status": override.get("status", "needs_review"),
                "human_reason": override.get("reason", ""),
                "evidence_ids": match["evidence_ids"],
                "searched_ranges": coverage["ranges"],
                "reason": reason,
                "uncertain": uncertain,
                "optional": optional,
                "alternative_edit": {
                    "feasible": is_reedit,
                    "reason": match["alternative_edit"]
                    or "当前证据未证明能仅靠现有素材修复",
                },
                "description": req["description"],
            }
        )
    return gaps
