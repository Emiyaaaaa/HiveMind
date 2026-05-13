"""Per-run cancellation signalling.

The API server writes a sentinel key in Redis; the worker polls the same
key before each adapter step. The in-memory implementation supports the
legacy inline mode where the API process owns the executor task.
"""

from __future__ import annotations

from typing import Protocol

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger("worker.cancel")


class CancelRegistry(Protocol):
    async def request_cancel(self, run_id: str) -> None: ...

    async def is_cancelled(self, run_id: str) -> bool: ...

    async def clear(self, run_id: str) -> None: ...

    async def aclose(self) -> None: ...


class InMemoryCancelRegistry:
    def __init__(self) -> None:
        self._cancelled: set[str] = set()

    async def request_cancel(self, run_id: str) -> None:
        self._cancelled.add(run_id)

    async def is_cancelled(self, run_id: str) -> bool:
        return run_id in self._cancelled

    async def clear(self, run_id: str) -> None:
        self._cancelled.discard(run_id)

    async def aclose(self) -> None:  # pragma: no cover - nothing to do
        return None


class RedisCancelRegistry:
    def __init__(self, url: str, prefix: str, ttl_seconds: int) -> None:
        import redis.asyncio as redis

        self._redis = redis.from_url(url, decode_responses=True)
        self._prefix = prefix
        self._ttl = ttl_seconds

    def _key(self, run_id: str) -> str:
        return f"{self._prefix}{run_id}"

    async def request_cancel(self, run_id: str) -> None:
        await self._redis.set(self._key(run_id), "1", ex=self._ttl)

    async def is_cancelled(self, run_id: str) -> bool:
        return bool(await self._redis.exists(self._key(run_id)))

    async def clear(self, run_id: str) -> None:
        await self._redis.delete(self._key(run_id))

    async def aclose(self) -> None:
        await self._redis.aclose()


_registry: CancelRegistry | None = None


def get_cancel_registry() -> CancelRegistry:
    global _registry
    if _registry is not None:
        return _registry

    settings = get_settings()
    if settings.redis_url and settings.worker_mode == "queue":
        logger.info("cancel_registry.redis", prefix=settings.cancel_key_prefix)
        _registry = RedisCancelRegistry(
            settings.redis_url,
            settings.cancel_key_prefix,
            settings.cancel_ttl_seconds,
        )
    else:
        logger.info("cancel_registry.in_memory")
        _registry = InMemoryCancelRegistry()
    return _registry
