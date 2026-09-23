"""Parallel extraction invariants; providers below never call a real model."""

import json
import threading
import time
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.config import settings
from app.workflows.pipeline import extract_asset


class ThreadBoundAsset(SimpleNamespace):
    """Catch accidental worker reads of the original ORM-shaped object."""

    def __getattribute__(self, name):
        owner = object.__getattribute__(self, "__dict__").get("_owner")
        assert owner is None or threading.get_ident() == owner, name
        return super().__getattribute__(name)


class ThreadBoundSession:
    def __init__(self, transcripts=()):
        self.owner = threading.get_ident()
        self.transcripts = list(transcripts)
        self.commits = 0

    def scalars(self, _query):
        assert threading.get_ident() == self.owner
        return SimpleNamespace(all=lambda: self.transcripts)

    def commit(self):
        assert threading.get_ident() == self.owner
        self.commits += 1


def make_asset(count, *, shared_start=False):
    shots = [
        {
            "window_index": index,
            "shot_id": "shared-shot" if shared_start else f"shot-{index}",
            "start_s": 0.0 if shared_start else float(index),
            "end_s": float(index + 1),
            "keyframes": [{"time_s": index + 0.25, "key": f"frame-{index}.jpg"}],
        }
        for index in range(count)
    ]
    return ThreadBoundAsset(
        _owner=threading.get_ident(), id="asset", project_id="project",
        sha256="media-hash", duration_s=float(count), status="ready",
        source_type="edited_video", original_name="test.mp4", storage_key="test.mp4",
        width=320, height=180, has_audio=False, meta={"shots": shots},
    )


def observation(shot, *, action=None):
    return {
        "source_start_s": shot["start_s"], "source_end_s": shot["end_s"],
        "action": action or f"观察窗口 {shot['window_index']}",
        "evidence_type": "visual", "subjects": ["测试图"],
    }


def extract(asset, model, progress=lambda *_: None, db=None):
    return extract_asset(
        db or ThreadBoundSession(), asset, SimpleNamespace(config_hash="config"),
        model, progress,
    )


def test_real_parallelism_obeys_configured_limit_and_caller_only_progress(monkeypatch):
    workers, count = 3, 9
    monkeypatch.setattr(settings, "model_concurrency", workers)
    barrier = threading.Barrier(workers)
    lock = threading.Lock()
    state = {"active": 0, "peak": 0}
    worker_threads = set()
    owner = threading.get_ident()
    updates = []

    class Provider:
        name = "test-concurrency"

        def analyze_clip(self, asset, shot):
            assert isinstance(asset, SimpleNamespace)
            assert not isinstance(asset, ThreadBoundAsset)
            with lock:
                state["active"] += 1
                state["peak"] = max(state["peak"], state["active"])
                worker_threads.add(threading.get_ident())
            try:
                # Every group must actually overlap; merely serial scheduling
                # three worker thread names cannot satisfy this barrier.
                barrier.wait(timeout=2)
                time.sleep(0.01)
                return [observation(shot)]
            finally:
                with lock:
                    state["active"] -= 1

    def progress(stage, completed, total):
        assert threading.get_ident() == owner
        updates.append((stage, completed, total))

    items, failures, cached = extract(make_asset(count), Provider(), progress)
    assert not failures and not cached and len(items) == count
    assert state["peak"] == workers and len(worker_threads) == workers
    assert owner not in worker_threads
    assert [completed for _, completed, _ in updates] == list(range(count + 1))
    assert all(total == count for _, _, total in updates)


def test_reverse_completion_keeps_original_window_merge_order(monkeypatch):
    count = 4
    monkeypatch.setattr(settings, "model_concurrency", count)
    barrier = threading.Barrier(count)
    turns = [threading.Event() for _ in range(count)]
    turns[-1].set()
    finished = []
    lock = threading.Lock()

    class Provider:
        name = "test-reverse-completion"

        def analyze_clip(self, asset, shot):
            index = shot["window_index"]
            barrier.wait(timeout=2)
            assert turns[index].wait(timeout=2)
            with lock:
                finished.append(index)
            if index:
                turns[index - 1].set()
            return [observation(shot, action="同一镜头的同一动作")]

    items, failures, _ = extract(make_asset(count, shared_start=True), Provider())
    assert not failures and finished == [3, 2, 1, 0]
    assert len(items) == 1
    # Equal start times expose accidental completion-order merging: sorting by
    # start time alone cannot restore the correct provenance window order.
    assert items[0]["provenance"]["windows"] == [[0.0, 1.0], [0.0, 2.0], [0.0, 3.0], [0.0, 4.0]]
    assert items[0]["source_end_s"] == 4


def test_snapshot_and_window_are_read_only_without_mutating_original(monkeypatch):
    monkeypatch.setattr(settings, "model_concurrency", 2)
    asset = make_asset(2)
    original_shots = deepcopy(asset.meta["shots"])
    db = ThreadBoundSession(transcripts=[SimpleNamespace(data={
        "start_s": 0.0, "end_s": 0.5, "text": "测试转写", "provider": "test-asr",
    })])

    class Provider:
        name = "test-snapshot"

        def analyze_clip(self, snapshot, shot):
            assert snapshot is not asset and snapshot.duration_s == 2
            assert not hasattr(snapshot, "_sa_instance_state")
            with pytest.raises(AttributeError):
                snapshot.duration_s = 999
            with pytest.raises(AttributeError):
                del snapshot.id
            with pytest.raises(TypeError):
                snapshot.meta["injected"] = True
            with pytest.raises(TypeError):
                snapshot.meta["shots"][0]["start_s"] = 999
            with pytest.raises(TypeError):
                shot["keyframes"][0]["key"] = "wrong-frame.jpg"
            return [observation(shot)]

    items, failures, _ = extract(asset, Provider(), db=db)
    assert not failures and len(items) == 3
    assert asset.meta["shots"] == original_shots and "injected" not in asset.meta
    assert [item["action"] for item in items if item["evidence_type"] == "audio"] == ["测试转写"]
    assert db.commits == 1


def test_failed_windows_are_atomic_ordered_and_never_reused_as_complete_cache(monkeypatch):
    monkeypatch.setattr(settings, "model_concurrency", 4)
    asset = make_asset(4)
    state = {"fail": True, "calls": 0}
    lock = threading.Lock()

    class Provider:
        name = "test-window-failures"

        def analyze_clip(self, snapshot, shot):
            index = shot["window_index"]
            with lock:
                state["calls"] += 1
            time.sleep((4 - index) * 0.005)
            if state["fail"] and index == 3:
                raise ValueError("模拟窗口请求失败")
            good = observation(shot)
            if state["fail"] and index == 1:
                # The valid first item must not survive the invalid second item.
                return [good, {**good, "source_end_s": shot["end_s"] + 1}]
            return [good]

    provider = Provider()
    items, failures, cached = extract(asset, provider)
    assert not cached and [item["shot_id"] for item in items] == ["shot-0", "shot-2"]
    assert [(item["start_s"], item["end_s"]) for item in failures] == [(1, 2), (3, 4)]
    assert "超出已观察分段" in failures[0]["reason"]
    assert "模拟窗口请求失败" in failures[1]["reason"]
    assert asset.meta["evidence_cache"]["failed_ranges"] == failures
    state["fail"] = False
    recovered, failures, cached = extract(asset, provider)
    assert not cached and not failures and len(recovered) == 4
    assert state["calls"] == 6
    _, failures, cached = extract(asset, provider)
    assert cached and not failures and state["calls"] == 6


def test_complete_cache_skips_workers_and_gives_new_analysis_ids(monkeypatch):
    monkeypatch.setattr(settings, "model_concurrency", 2)
    asset = make_asset(3)
    calls = []
    updates = []
    db = ThreadBoundSession()

    class Provider:
        name = "test-cache"

        def analyze_clip(self, snapshot, shot):
            calls.append(shot["window_index"])
            return [observation(shot)]

    provider = Provider()
    first, failures, cached = extract(asset, provider, db=db)
    assert not cached and not failures and len(calls) == 3
    second, failures, cached = extract(asset, provider, lambda *args: updates.append(args), db)
    assert cached and not failures and len(calls) == 3 and updates == []
    assert db.commits == 1
    assert {item["id"] for item in first}.isdisjoint(item["id"] for item in second)
    assert [{k: v for k, v in item.items() if k != "id"} for item in first] == [
        {k: v for k, v in item.items() if k != "id"} for item in second
    ]


def test_simulated_network_latency_benchmark(monkeypatch):
    """Report synthetic latency only; do not assert real-service speedups."""
    count, latency_s = 16, 0.04
    durations = {}

    class Provider:
        name = "simulated-network-latency"

        def analyze_clip(self, snapshot, shot):
            time.sleep(latency_s)
            return [observation(shot)]

    for concurrency in (1, 8):
        monkeypatch.setattr(settings, "model_concurrency", concurrency)
        started = time.perf_counter()
        items, failures, cached = extract(make_asset(count), Provider())
        durations[concurrency] = time.perf_counter() - started
        assert len(items) == count and not failures and not cached
    print("SIMULATED_NETWORK_LATENCY " + json.dumps({
        "windows": count, "delay_per_window_s": latency_s,
        "serial_1_s": round(durations[1], 4),
        "parallel_8_s": round(durations[8], 4),
        "ratio": round(durations[1] / durations[8], 2),
        "note": "模拟固定网络延迟，不代表百炼真实模型性能",
    }, ensure_ascii=False))
