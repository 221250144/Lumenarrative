from copy import deepcopy

from app.services.media.shot_boundaries import MIN_SHOT_DURATION_S, select_shot_boundaries


def merge_short_shots(shots, min_duration=MIN_SHOT_DURATION_S):
    """Return display-only merged shots without modifying any analysis snapshot.

    Each group keeps its first source ID and carries all original IDs for chapter
    and evidence navigation. Never bridge different assets or a gap in coverage.
    Historical rows without cut scores use deterministic chronological ties.
    """
    if not shots:
        return []
    groups, contiguous = [], []

    def flush():
        if not contiguous:
            return
        boundaries = [{"time_s": shot["start_s"], "score": shot.get("boundary_score", 0.0)}
                      for shot in contiguous[1:]]
        retained = {round(boundary["time_s"] * 1_000_000) for boundary in select_shot_boundaries(
            boundaries, contiguous[0]["start_s"], contiguous[-1]["end_s"], min_duration,
        )}
        current = []
        for shot in contiguous:
            if current and round(shot["start_s"] * 1_000_000) in retained:
                groups.append(current)
                current = []
            current.append(shot)
        if current:
            groups.append(current)
        contiguous.clear()

    for shot in shots:
        if contiguous and (
            shot.get("asset_id") != contiguous[-1].get("asset_id")
            or round(shot["start_s"] * 1_000_000) != round(contiguous[-1]["end_s"] * 1_000_000)
        ):
            flush()
        contiguous.append(shot)
    flush()
    result = []
    for index, group in enumerate(groups, 1):
        merged = deepcopy(group[0])
        merged["index"] = index
        merged["end_s"] = group[-1]["end_s"]
        merged["source_shot_ids"] = list(dict.fromkeys(
            source_id for shot in group for source_id in (shot.get("source_shot_ids") or [shot["id"]])
        ))
        if any("summary" in shot for shot in group):
            merged["summary"] = "；".join(dict.fromkeys(shot["summary"] for shot in group if shot.get("summary")))
        if any("evidence_ids" in shot for shot in group):
            merged["evidence_ids"] = list(dict.fromkeys(eid for shot in group for eid in shot.get("evidence_ids", [])))
        if any("observed" in shot for shot in group):
            merged["observed"] = all(shot.get("observed", False) for shot in group)
        representative = max(group, key=lambda shot: shot["end_s"] - shot["start_s"])
        for field in ("thumbnail_url", "thumbnail_key"):
            if field in representative:
                merged[field] = representative[field]
        result.append(merged)
    return result


def asset_shots(asset):
    """Public shot metadata, without storage paths or model-only sampling windows."""
    return [
        {
            "id": shot["id"], "asset_id": asset.id, "index": shot["index"],
            "start_s": shot["start_s"], "end_s": shot["end_s"],
            "boundary_type": shot["boundary_type"],
            "thumbnail_url": f"/api/v1/assets/{asset.id}/frame?at={shot['keyframes'][len(shot['keyframes']) // 2]['time_s']}",
        }
        for shot in asset.meta.get("scene_shots", [])
    ]
