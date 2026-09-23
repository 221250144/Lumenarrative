"""Retry only verified failed windows; malformed legacy caches must be ignored."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.config import settings
from app.workflows.pipeline import extract_asset
from test_parallel_extraction import ThreadBoundSession, make_asset, observation


class RecordingProvider:
    name = "partial-cache-test"

    def __init__(self, failed=()):
        self.failed = set(failed)
        self.calls = []

    def analyze_clip(self, asset, shot):
        index = shot["window_index"]
        self.calls.append(index)
        if index in self.failed:
            raise ValueError("模拟窗口失败")
        return [observation(shot), {**observation(shot), "evidence_type": "text", "action": f"字幕 {index}"}]


def run(asset, model, db=None, progress=lambda *_: None, config="config"):
    return extract_asset(db or ThreadBoundSession(), asset, SimpleNamespace(config_hash=config), model, progress)


def transcript(text):
    return SimpleNamespace(data={"start_s": 0.0, "end_s": 0.5, "text": text, "provider": "asr"})


def test_partial_retry_retains_successes_and_refreshes_audio_ids_and_failure_coverage(monkeypatch):
    monkeypatch.setattr(settings, "model_concurrency", 2)
    asset, model = make_asset(4), RecordingProvider({1, 3})
    db = ThreadBoundSession([transcript("旧转写")])
    first, failures, cached = run(asset, model, db)
    assert sorted(model.calls) == [0, 1, 2, 3] and not cached and len(failures) == 2
    old_cache = asset.meta["evidence_cache"]
    saved_cache = deepcopy(old_cache)
    retained = [item for item in first if item["evidence_type"] != "audio"]

    model.calls, model.failed = [], {3}
    db.transcripts = [transcript("当前转写")]
    updates = []
    second, failures, cached = run(asset, model, db, lambda _, done, total: updates.append((done, total)))
    assert sorted(model.calls) == [1, 3] and not cached
    assert [(item["start_s"], item["end_s"]) for item in failures] == [(3, 4)]
    assert updates == [(2, 4), (3, 4), (4, 4)]
    assert old_cache == saved_cache  # Merging must not mutate earlier provenance.
    assert {item["id"] for item in first}.isdisjoint(item["id"] for item in second)
    assert [item["action"] for item in second if item["evidence_type"] == "audio"] == ["当前转写"]
    for old in retained:
        new = next(item for item in second if item["action"] == old["action"])
        assert {key: value for key, value in new.items() if key != "id"} == {
            key: value for key, value in old.items() if key != "id"
        }

    model.calls, model.failed = [], set()
    third, failures, cached = run(asset, model, db)
    assert model.calls == [3] and not failures and not cached and len(third) == 9
    assert len([item for item in third if item["evidence_type"] == "audio"]) == 1
    model.calls = []
    fourth, failures, cached = run(asset, model, db)
    assert cached and not failures and not model.calls and len(fourth) == 9


def test_merged_evidence_is_reused_once_across_successful_windows(monkeypatch):
    monkeypatch.setattr(settings, "model_concurrency", 2)
    asset = make_asset(3, shared_start=True)

    class MergedProvider(RecordingProvider):
        def analyze_clip(self, asset, shot):
            super().analyze_clip(asset, shot)
            return [observation(shot, action="同一动作")]

    model = MergedProvider({2})
    first, failures, _ = run(asset, model)
    assert len(first) == 1 and len(failures) == 1
    old_provenance = deepcopy(first[0]["provenance"])
    model.calls, model.failed = [], set()
    second, failures, cached = run(asset, model)
    assert model.calls == [2] and not cached and not failures and len(second) == 1
    assert second[0]["provenance"]["windows"] == [[0.0, 1.0], [0.0, 2.0], [0.0, 3.0]]
    assert first[0]["provenance"] == old_provenance
    assert first[0]["id"] != second[0]["id"]


@pytest.mark.parametrize("change", ["configuration", "content", "shot_boundary", "shot_id"])
def test_partial_cache_key_changes_force_all_windows_to_be_recomputed(change):
    asset, model = make_asset(3), RecordingProvider({2})
    first, _, _ = run(asset, model)
    config = "config"
    if change == "configuration":
        config = "new-provider-model-or-sampling-config"
    elif change == "content":
        asset.sha256 = "changed-content-hash"
    elif change == "shot_boundary":
        asset.meta["shots"][0]["end_s"] = 0.9
    else:
        asset.meta["shots"][0]["shot_id"] = "new-shot-id"
    model.calls, model.failed = [], set()
    second, failures, cached = run(asset, model, config=config)
    assert sorted(model.calls) == [0, 1, 2] and not cached and not failures
    assert len(second) == 6 and {item["id"] for item in first}.isdisjoint(item["id"] for item in second)


@pytest.mark.parametrize("corruption", [
    "missing_provenance", "unknown_window", "wrong_shot", "wrong_asset",
    "includes_failed_window", "missing_successful_window", "unknown_failure", "wrong_failure_asset",
    "out_of_window_evidence", "duplicate_window_ranges",
])
def test_ambiguous_partial_cache_falls_back_without_cross_window_evidence(corruption):
    asset, model = make_asset(3), RecordingProvider({2})
    if corruption == "duplicate_window_ranges":
        asset.meta["shots"][1]["start_s"] = 0.0
        asset.meta["shots"][1]["end_s"] = 1.0
    run(asset, model)
    cache = asset.meta["evidence_cache"]
    evidence = cache["evidence"][0]
    if corruption == "missing_provenance":
        del evidence["provenance"]
    elif corruption == "unknown_window":
        evidence["provenance"]["windows"] = [[100, 200]]
    elif corruption == "wrong_shot":
        evidence["shot_id"] = "shot-1"
    elif corruption == "wrong_asset":
        evidence["asset_id"] = "other-asset"
    elif corruption == "includes_failed_window":
        evidence["provenance"]["windows"].append([2.0, 3.0])
    elif corruption == "missing_successful_window":
        cache["evidence"] = [item for item in cache["evidence"] if item["shot_id"] != "shot-1"]
    elif corruption == "unknown_failure":
        cache["failed_ranges"][0]["start_s"] = 100
    elif corruption == "wrong_failure_asset":
        cache["failed_ranges"][0]["asset_id"] = "other-asset"
    elif corruption == "out_of_window_evidence":
        evidence["source_end_s"] = 3.0
    model.calls, model.failed = [], set()
    second, failures, cached = run(asset, model)
    assert sorted(model.calls) == [0, 1, 2] and not failures and not cached
    assert len(second) == 6
    assert all(item["asset_id"] == asset.id for item in second)
