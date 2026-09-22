import os
from pathlib import Path
import select
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.config import Settings, settings
from app.services.concurrency import resource_slot


def test_eight_slots_are_shared_between_threads(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    release = threading.Event()
    full = threading.Event()
    mutex = threading.Lock()
    active, peak = 0, 0

    def use_slot():
        nonlocal active, peak
        with resource_slot("model", 8):
            with mutex:
                active += 1
                peak = max(peak, active)
                if active == 8:
                    full.set()
            try:
                assert release.wait(5)
            finally:
                with mutex:
                    active -= 1

    with ThreadPoolExecutor(max_workers=16) as pool:
        tasks = [pool.submit(use_slot) for _ in range(16)]
        try:
            assert full.wait(5), "Eight concurrent callers never acquired slots"
        finally:
            release.set()
        for task in tasks:
            task.result()
    assert peak == 8 and active == 0


def test_exceptions_release_the_slot(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    with pytest.raises(RuntimeError):
        with resource_slot("model", 1):
            raise RuntimeError("injected failure")
    with resource_slot("model", 1):
        pass


def test_slot_is_shared_across_processes_and_released_on_crash(tmp_path):
    code = (
        "from app.services.concurrency import resource_slot; import sys\n"
        "with resource_slot('model', 1):\n"
        " print('acquired', flush=True)\n"
        " sys.stdin.readline()\n"
    )
    environment = {**os.environ, "DATA_DIR": str(tmp_path),
                   "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    children = []
    try:
        for _ in range(2):
            child = subprocess.Popen([sys.executable, "-u", "-c", code],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, env=environment)
            children.append(child)
            if len(children) == 1:
                assert select.select([child.stdout], [], [], 10)[0]
                assert child.stdout.readline() == b"acquired\n"
        first, second = children
        assert not select.select([second.stdout], [], [], 0.3)[0]
        first.kill()
        first.wait(timeout=5)
        assert select.select([second.stdout], [], [], 10)[0]
        assert second.stdout.readline() == b"acquired\n"
        second.communicate(input=b"done\n", timeout=5)
        assert second.returncode == 0
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=5)


@pytest.mark.parametrize("field,value", [("model_concurrency", 0), ("model_concurrency", 33),
                                       ("media_concurrency", 0), ("ffmpeg_threads", 0)])
def test_invalid_limits_fail_configuration(field, value):
    with pytest.raises(ValueError):
        Settings(_env_file=None, **{field: value})
