"""Object storage for multimodal attachments (and future memory blobs).

Default backend is a local filesystem under ``AGENTFLOW_ATTACHMENT_STORAGE_DIR``.
The interface is intentionally small so an S3-compatible backend can replace
it without changing Attachment rows (they only store ``storage_key``).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Protocol

from app.core.config import get_settings


class ObjectStore(Protocol):
    async def put(self, key: str, data: bytes, *, media_type: str) -> None: ...

    async def get(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...

    async def exists(self, key: str) -> bool: ...


class LocalObjectStore:
    """Filesystem-backed object store."""

    def __init__(self, root: Path | str | None = None) -> None:
        settings = get_settings()
        self.root = Path(root or settings.attachment_storage_dir).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # Prevent path traversal: only allow relative keys under root.
        safe = Path(key)
        if safe.is_absolute() or ".." in safe.parts:
            raise ValueError(f"invalid storage key: {key!r}")
        path = (self.root / safe).resolve()
        if not str(path).startswith(str(self.root)):
            raise ValueError(f"storage key escapes root: {key!r}")
        return path

    async def put(self, key: str, data: bytes, *, media_type: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    async def get(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise FileNotFoundError(key)
        return path.read_bytes()

    async def delete(self, key: str) -> None:
        path = self._path(key)
        if path.is_file():
            path.unlink()

    async def exists(self, key: str) -> bool:
        return self._path(key).is_file()


_store: ObjectStore | None = None


def get_object_store() -> ObjectStore:
    global _store
    if _store is None:
        _store = LocalObjectStore()
    return _store


def set_object_store(store: ObjectStore | None) -> None:
    """Override the process-wide store (tests)."""
    global _store
    _store = store


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def attachment_storage_key(*, tenant_id: str, attachment_id: str, filename: str) -> str:
    """Stable relative key: ``{tenant}/{id}/{safe_filename}``."""
    safe_name = Path(filename).name or "blob"
    safe_name = "".join(ch if ch.isalnum() or ch in "._-+" else "_" for ch in safe_name)
    return f"{tenant_id}/{attachment_id}/{safe_name}"
