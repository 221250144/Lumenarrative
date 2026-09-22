from copy import deepcopy

import pytest

from app.services.media.shot_boundaries import select_shot_boundaries
from app.services.media.views import merge_short_shots


@pytest.mark.parametrize("duration,points,expected", [
    (2, [(0.2, 1), (1, 0.4), (1.9, 1)], [1]),
    (3, [(1, 0.4), (1.2, 0.9)], [1.2]),
    (3, [(1, 0.9), (1.2, 0.4)], [1]),
    (2, [(0.5, 0.3), (1, 0.3), (1.5, 0.3)], [0.5, 1, 1.5]),
    (1, [(0.499999, 1), (0.5, 0.2)], [0.5]),
    (0.4, [(0.1, 1), (0.2, 1), (0.3, 1)], []),
    (0.5, [(0.25, 1)], []),
    (0.72, [(0.16, 1), (0.28, 1), (0.48, 1), (0.56, 1)], []),
    (2, [(0.2, 1), (0.4, 1), (0.6, 1), (0.8, 1), (1.0, 1), (1.2, 1), (1.4, 1), (1.6, 1), (1.8, 1)], [0.6, 1.2]),
])
def test_minimum_length_boundaries_keep_stronger_cuts_and_cover_edges(duration, points, expected):
    source = [{"time_s": time, "score": score, "type": "hard_cut"} for time, score in points]
    before = deepcopy(source)
    result = select_shot_boundaries(source, 0, duration)
    assert [boundary["time_s"] for boundary in result] == expected
    assert source == before
    edges = [0, *expected, duration]
    assert len(edges) == 2 or all(round(b - a, 6) >= 0.5 for a, b in zip(edges, edges[1:]))
    assert sum(b - a for a, b in zip(edges, edges[1:])) == pytest.approx(duration)


def shot(id, start, end, *, score=0, asset="asset", summary="", observed=True):
    return {
        "id": id, "asset_id": asset, "index": 99,
        "start_s": start, "end_s": end, "boundary_score": score,
        "boundary_type": "hard_cut", "thumbnail_url": f"/frame/{id}",
        "summary": summary, "evidence_ids": ["shared", "evidence-" + id], "observed": observed,
    }


def test_display_merging_preserves_mapping_summary_and_longer_thumbnail_without_mutation():
    source = [shot("a", 0, 1, summary="Arrival"), shot("b", 1, 1.1, score=0.2, summary="Close detail", observed=False), shot("c", 1.1, 3, score=0.8, summary="Wide scene")]
    original = deepcopy(source)
    result = merge_short_shots(source)
    assert source == original
    assert [(item["start_s"], item["end_s"]) for item in result] == [(0, 1.1), (1.1, 3)]
    assert [item["index"] for item in result] == [1, 2]
    assert result[0]["id"] == "a" and result[0]["source_shot_ids"] == ["a", "b"]
    assert result[0]["thumbnail_url"] == "/frame/a"
    assert result[0]["summary"] == "Arrival；Close detail"
    assert result[0]["evidence_ids"] == ["shared", "evidence-a", "evidence-b"]
    assert result[0]["observed"] is False
    assert result[1]["source_shot_ids"] == ["c"]
    result[0]["evidence_ids"].append("new")
    assert source == original


def test_display_short_leading_shot_uses_following_long_thumbnail():
    source = [shot("short", 0, 0.1), shot("long", 0.1, 2)]
    result = merge_short_shots(source)
    assert len(result) == 1
    assert result[0]["id"] == "short"
    assert result[0]["thumbnail_url"] == "/frame/long"
    assert result[0]["source_shot_ids"] == ["short", "long"]


def test_display_does_not_bridge_different_assets_or_missing_video_intervals():
    source = [shot("a", 0, 0.1), shot("b", 0.1, 1, asset="different"), shot("c", 2, 3, asset="different")]
    result = merge_short_shots(source)
    assert [(item["start_s"], item["end_s"]) for item in result] == [(0, 0.1), (0.1, 1), (2, 3)]
    assert [item["source_shot_ids"] for item in result] == [["a"], ["b"], ["c"]]


def test_display_merge_is_idempotent_and_preserves_under_half_second_whole_clip():
    source = [shot("a", 0, 0.1, summary="same"), shot("b", 0.1, 0.4, summary="same")]
    once = merge_short_shots(source)
    assert merge_short_shots(once) == once
    assert once[0]["summary"] == "same"
    assert (once[0]["start_s"], once[0]["end_s"]) == (0, 0.4)
    assert merge_short_shots([]) == []
