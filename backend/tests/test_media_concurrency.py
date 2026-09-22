"""FFmpeg resource budgets apply across API/worker processes and file scopes."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import multiprocessing
from pathlib import Path
import subprocess
import threading
from types import SimpleNamespace

import pytest

from app.config import settings
from app.services.media import pipeline


def _media_process(root, executable, ready, start, results):
    """Independent worker imports and uses the production cross-process gate."""
    settings.data_dir = Path(root)
    settings.ffmpeg_bin = executable
    settings.ffmpeg_threads = 4
    settings.media_concurrency = 2
    ready.put(True)
    if not start.wait(15):
        raise RuntimeError("media test start barrier timed out")
    try:
        pipeline.run([executable, "-i", "source.mp4", "output.mp4"], timeout=10)
        results.put(None)
    except Exception as error:
        results.put(repr(error))
        raise


def test_ffmpeg_arguments_bound_each_input_output_and_filter(monkeypatch):
    monkeypatch.setattr(settings, "ffmpeg_threads", 4)
    monkeypatch.setattr(settings, "media_concurrency", 2)
    calls, slots = [], []

    @contextmanager
    def gate(name, limit):
        slots.append((name, limit))
        yield

    def capture(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(pipeline, "resource_slot", gate)
    monkeypatch.setattr(pipeline.subprocess, "run", capture)
    original = [
        settings.ffmpeg_bin, "-threads", "99", "-i", "source.mp4",
        "-threads:v", "22", "-f", "lavfi", "-i", "anullsrc",
        "-filter_threads", "0", "-filter_complex_threads", "0",
        "-c:v", "libx264", "output.mp4",
    ]
    assert pipeline.run(original, timeout=17) == ("ok", "")
    command, kwargs = calls[0]
    assert original[1:3] == ["-threads", "99"]  # callers may reuse their command
    assert slots == [("ffmpeg", 2)]
    assert kwargs == {"capture_output": True, "text": True, "timeout": 17}
    assert command[1:5] == ["-filter_threads", "4", "-filter_complex_threads", "4"]
    for index, argument in enumerate(command):
        if argument == "-i":
            assert command[index - 2:index] == ["-threads", "4"]
    assert command[-3:] == ["-threads", "4", "output.mp4"]
    assert command.count("-threads") == 3
    assert not {"99", "22", "-threads:v"}.intersection(command)


def test_preprocessing_serializes_same_asset_but_allows_other_assets(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    first_started, other_started, release = threading.Event(), threading.Event(), threading.Event()
    mutex = threading.Lock()
    active = set()
    seen = []

    def processing(asset, progress):
        with mutex:
            assert asset.id not in active, "Two writers entered the same asset directory"
            active.add(asset.id)
            seen.append(asset.id)
        (first_started if asset.id == "same" else other_started).set()
        try:
            assert release.wait(5)
            return asset.id
        finally:
            with mutex:
                active.remove(asset.id)

    monkeypatch.setattr(pipeline, "_preprocess", processing)
    with ThreadPoolExecutor(max_workers=3) as pool:
        first = pool.submit(pipeline.preprocess, SimpleNamespace(id="same"), None)
        try:
            assert first_started.wait(5)
            second = pool.submit(pipeline.preprocess, SimpleNamespace(id="same"), None)
            other = pool.submit(pipeline.preprocess, SimpleNamespace(id="other"), None)
            assert other_started.wait(5), "Unrelated assets were unnecessarily serialized"
        finally:
            release.set()
        assert first.result(timeout=5) == second.result(timeout=5) == "same"
        assert other.result(timeout=5) == "other"
    assert seen.count("same") == 2


def test_ffprobe_skips_media_slot_and_keeps_arguments(monkeypatch):
    def forbidden_slot(*args):
        raise AssertionError("FFprobe must not consume a media slot")

    command = [settings.ffprobe_bin, "-show_format", "source.mp4"]

    def capture(args, **kwargs):
        assert args == command
        assert kwargs["timeout"] == 30
        return SimpleNamespace(returncode=0, stdout='{"format": {}}', stderr="")

    monkeypatch.setattr(pipeline, "resource_slot", forbidden_slot)
    monkeypatch.setattr(pipeline.subprocess, "run", capture)
    assert pipeline.run(command, 30) == ('{"format": {}}', "")


def test_failed_subprocess_releases_media_slot(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "media_concurrency", 1)
    monkeypatch.setattr(settings, "ffmpeg_threads", 4)
    calls = 0
    lock = threading.Lock()

    def fails_then_succeeds(args, **kwargs):
        nonlocal calls
        with lock:
            calls += 1
            current = calls
        if current == 1:
            raise subprocess.TimeoutExpired(args, kwargs["timeout"])
        return SimpleNamespace(returncode=0, stdout="recovered", stderr="")

    monkeypatch.setattr(pipeline.subprocess, "run", fails_then_succeeds)
    command = [settings.ffmpeg_bin, "-i", "source.mp4", "output.mp4"]
    with pytest.raises(subprocess.TimeoutExpired):
        pipeline.run(command, 1)
    with ThreadPoolExecutor(max_workers=1) as pool:
        assert pool.submit(pipeline.run, command).result(timeout=5) == ("recovered", "")


def test_media_limit_is_shared_across_independent_worker_processes(tmp_path):
    executable = tmp_path / "ffmpeg-test"
    # The short child process represents heavy FFmpeg work. Appending each JSON
    # record in one write records actual process overlap without a mock gate.
    executable.write_text('''#!/usr/bin/env python3
import json, os, pathlib, time
log = pathlib.Path(__file__).with_name("media-events.jsonl")
def event(kind):
    fd = os.open(str(log), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, (json.dumps({"event": kind, "pid": os.getpid()}) + "\\n").encode())
    finally:
        os.close(fd)
event("start")
time.sleep(0.2)
event("end")
''')
    executable.chmod(0o700)
    context = multiprocessing.get_context("spawn")
    ready, results, start = context.Queue(), context.Queue(), context.Event()
    workers = [context.Process(target=_media_process, args=(str(tmp_path), str(executable), ready, start, results)) for _ in range(4)]
    try:
        for worker in workers:
            worker.start()
        for _ in workers:
            assert ready.get(timeout=20)
        start.set()
        for worker in workers:
            worker.join(timeout=20)
            assert worker.exitcode == 0
        assert [results.get(timeout=2) for _ in workers] == [None] * 4
    finally:
        start.set()
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=5)
    active, maximum = set(), 0
    for line in (tmp_path / "media-events.jsonl").read_text().splitlines():
        event = json.loads(line)
        if event["event"] == "start":
            active.add(event["pid"])
            maximum = max(maximum, len(active))
        else:
            active.remove(event["pid"])
    assert not active
    assert maximum == 2
