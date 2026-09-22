"""Single-host resource limits shared by API threads and Celery processes.

The OS releases flock locks on close/process exit, so a killed worker cannot
leave a stale lease. Every process must use the same DATA_DIR and limits.
This is a local-filesystem limiter, not a distributed multi-host semaphore.
"""

from contextlib import contextmanager
import fcntl
import os
import re
import threading
import time

from app.config import settings


@contextmanager
def try_resource_slot(name: str):
    """A nonblocking single-owner lock, also usable after a crashed worker exits."""
    if not re.fullmatch(r"[a-z][a-z0-9_-]*", name):
        raise ValueError("Invalid resource concurrency configuration")
    folder = settings.data_dir.resolve() / ".resource-slots" / name
    folder.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(folder / "0.lock", os.O_CREAT | os.O_RDWR | os.O_CLOEXEC, 0o600)
    acquired = False
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except BlockingIOError:
            pass
        yield acquired
    finally:
        if acquired:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


@contextmanager
def resource_slot(name: str, limit: int):
    if not re.fullmatch(r"[a-z][a-z0-9_-]*", name) or not 1 <= limit <= 32:
        raise ValueError("Invalid resource concurrency configuration")
    folder = settings.data_dir.resolve() / ".resource-slots" / name
    folder.mkdir(parents=True, exist_ok=True)
    # Different callers try different slots first; only a nonblocking OS lock
    # grants access. Never unlink active lock files (that would split the lock).
    offset = (os.getpid() + threading.get_ident()) % limit
    held = None
    try:
        while held is None:
            for i in range(limit):
                path = folder / f"{(offset + i) % limit}.lock"
                descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC, 0o600)
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    os.close(descriptor)
                    continue
                except BaseException:
                    os.close(descriptor)
                    raise
                held = descriptor
                break
            if held is None:
                time.sleep(0.05)
        yield
    finally:
        if held is not None:
            fcntl.flock(held, fcntl.LOCK_UN)
            os.close(held)
