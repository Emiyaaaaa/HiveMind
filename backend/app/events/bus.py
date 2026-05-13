"""Per-run pub/sub event bus.

The bus has two implementations selected at runtime:

* `InMemoryEventBus` – per-process asyncio queues. Suitable for single-node
  development and for tests.
* `RedisEventBus` – Redis pub/sub channels keyed by `agentflow:run:{id}`.
  Enabled automatically when `AGENTFLOW_REDIS_URL` is configured.

Both implementations expose the same async interface and are interchangeable.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol

from app.core.config import get_settings
from app.core.logging import get_logger
from app.schemas.run import RunEvent

logger = get_logger("events")


class EventBus(Protocol):
    async def publish(self, event: RunEvent) -> None: ...

    @asynccontextmanager
    def subscribe(self, run_id: str) -> AsyncIterator[asyncio.Queue[RunEvent]]: ...

    async def aclose(self) -> None: ...


class InMemoryEventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[RunEvent]]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def publish(self, event: RunEvent) -> None:
        async with self._lock:
            queues = list(self._subscribers.get(event.run_id, ()))
        for queue in queues:
            await queue.put(event)

    @asynccontextmanager
    async def subscribe(self, run_id: str) -> AsyncIterator[asyncio.Queue[RunEvent]]:
        queue: asyncio.Queue[RunEvent] = asyncio.Queue()
        async with self._lock:
            self._subscribers[run_id].add(queue)
        try:
            yield queue
        finally:
            async with self._lock:
                self._subscribers[run_id].discard(queue)
                if not self._subscribers[run_id]:
                    self._subscribers.pop(run_id, None)

    async def aclose(self) -> None:  # pragma: no cover - nothing to do
        return None


class RedisEventBus:
    """Redis-backed pub/sub.

    Imported lazily to keep the in-memory path free of redis dependency for
    unit tests.
    """

    def __init__(self, url: str) -> None:
        import redis.asyncio as redis  # local import

        self._redis = redis.from_url(url, decode_responses=True)

    @staticmethod
    def _channel(run_id: str) -> str:
        return f"agentflow:run:{run_id}"

    async def publish(self, event: RunEvent) -> None:
        await self._redis.publish(
            self._channel(event.run_id),
            event.model_dump_json(),
        )

    @asynccontextmanager
    async def subscribe(self, run_id: str) -> AsyncIterator[asyncio.Queue[RunEvent]]:
        pubsub = self._redis.pubsub()
        queue: asyncio.Queue[RunEvent] = asyncio.Queue()
        await pubsub.subscribe(self._channel(run_id))

        async def reader() -> None:
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                try:
                    payload = json.loads(message["data"])
                    await queue.put(RunEvent(**payload))
                except Exception:  # pragma: no cover - defensive
                    logger.exception("event_decode_failed")

        task = asyncio.create_task(reader())
        try:
            yield queue
        finally:
            task.cancel()
            await pubsub.unsubscribe(self._channel(run_id))
            await pubsub.aclose()

    async def aclose(self) -> None:
        await self._redis.aclose()


_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    """Return a process-wide event bus singleton."""
    global _bus
    if _bus is not None:
        return _bus

    settings = get_settings()
    if settings.redis_url:
        logger.info("event_bus.redis", url=settings.redis_url)
        _bus = RedisEventBus(settings.redis_url)
    else:
        logger.info("event_bus.in_memory")
        _bus = InMemoryEventBus()
    return _bus
