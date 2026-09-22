from pathlib import Path
from typing import Protocol
from app.config import settings


class StorageAdapter(Protocol):
    def path(self, key: str) -> Path: ...


class LocalStorage:
    def path(self, key: str) -> Path:
        root = settings.data_dir.resolve()
        target = (root / key).resolve()
        if not target.is_relative_to(root):
            raise ValueError("非法素材路径")
        return target


storage = LocalStorage()
