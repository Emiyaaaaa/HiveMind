"""Per-run pub/sub event bus with a durable replay log.

The bus has two implementations selected at runtime:

* `InMemoryEventBus` – per-process asyncio queues plus an in-process event
  log. Suitable for single-node development and for tests.
* `RedisEventBus` – Redis pub/sub for live delivery and a Redis Stream per
  run for `Last-Event-ID` replay. Enabled when `AGENTFLOW_REDIS_URL` is set.

Both implementations expose the same async interface and are interchangeable.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Any, Protocol

from app.core.config import get_settings
from app.core.logging import get_logger
from app.schemas.run import RunEvent

logger = get_logger("events")

EventRecord = tuple[str, RunEvent]

# Cap live fan-out queues so a slow SSE client cannot retain unbounded
# token.delta traffic in memory.
_SUBSCRIBE_QUEUE_MAXSIZE = 1_024


def _stream_id_key(event_id: str) -> tuple[int, int] | str:
    """Parse a Redis Stream ID (`ms-seq`) for ordered comparison."""
    ms_str, _, seq_str = event_id.partition("-")
    if not seq_str:
        return event_id
    try:
        return (int(ms_str), int(seq_str))
    except ValueError:
        return event_id


def is_after(entry_id: str, after_id: str | None) -> bool:
    """Return True when ``entry_id`` should be delivered after ``after_id``.

    Supports in-memory monotonic integers and Redis Stream IDs (`ms-seq`).
    """
    if after_id is None or after_id == "":
        return True
    if "-" in entry_id or "-" in after_id:
        left = _stream_id_key(entry_id)
        right = _stream_id_key(after_id)
        if isinstance(left, tuple) and isinstance(right, tuple):
            return left > right
    try:
        return int(entry_id) > int(after_id)
    except ValueError:
        return entry_id > after_id


# Backwards-compatible alias used by older call sites / tests.
_is_after = is_after


def _normalize_event_id(raw: Any) -> str:
    if raw is None:
        return ""
    text = str(raw).strip()
    return text


def _decode_envelope(payload: dict[str, Any]) -> EventRecord:
    if "event" in payload:
        event = RunEvent(**payload["event"])
        return _normalize_event_id(payload.get("id")), event
    return "", RunEvent(**payload)


class EventBus(Protocol):
    async def publish(self, event: RunEvent, *, persist: bool = True) -> str: ...

    def replay(
        self, run_id: str, after_id: str | None = None
    ) -> AsyncIterator[EventRecord]: ...

    @asynccontextmanager
    def subscribe(self, run_id: str) -> AsyncIterator[asyncio.Queue[EventRecord]]: ...

    async def aclose(self) -> None: ...


class InMemoryEventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[EventRecord]]] = defaultdict(set)
        self._log: dict[str, list[EventRecord]] = defaultdict(list)
        self._seq: dict[str, int] = defaultdict(int)
        self._lock = asyncio.Lock()

    async def publish(self, event: RunEvent, *, persist: bool = True) -> str:
        async with self._lock:
            if persist:
                self._seq[event.run_id] += 1
                event_id = str(self._seq[event.run_id])
                record = (event_id, event)
                self._log[event.run_id].append(record)
            else:
                event_id = ""
                record = (event_id, event)
            queues = list(self._subscribers.get(event.run_id, ()))
        for queue in queues:
            self._enqueue(queue, record)
        return event_id

    @staticmethod
    def _enqueue(queue: asyncio.Queue[EventRecord], record: EventRecord) -> None:
        try:
            queue.put_nowait(record)
        except asyncio.QueueFull:
            # Drop the oldest frame so live streams stay current.
            with suppress(asyncio.QueueEmpty):
                queue.get_nowait()
            with suppress(asyncio.QueueFull):
                queue.put_nowait(record)

    async def replay(
        self, run_id: str, after_id: str | None = None
    ) -> AsyncIterator[EventRecord]:
        for event_id, event in self._log.get(run_id, ()):
            if is_after(event_id, after_id):
                yield event_id, event

    @asynccontextmanager
    async def subscribe(self, run_id: str) -> AsyncIterator[asyncio.Queue[EventRecord]]:
        queue: asyncio.Queue[EventRecord] = asyncio.Queue(
            maxsize=_SUBSCRIBE_QUEUE_MAXSIZE
        )
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
    """Redis-backed pub/sub with a per-run stream for replay."""

    def __init__(self, url: str) -> None:
        import redis.asyncio as redis  # local import

        self._redis = redis.from_url(url, decode_responses=True)
        settings = get_settings()
        self._channel_prefix = settings.event_channel_prefix
        self._stream_suffix = settings.event_stream_suffix
        self._stream_max_len = settings.event_stream_max_len

    def _channel(self, run_id: str) -> str:
        return f"{self._channel_prefix}{run_id}"

    def _stream(self, run_id: str) -> str:
        return f"{self._channel_prefix}{run_id}{self._stream_suffix}"

    async def publish(self, event: RunEvent, *, persist: bool = True) -> str:
        # Serialize once; stream payload and pub/sub envelope share the body.
        event_dict = event.model_dump(mode="json")
        event_json = json.dumps(event_dict, separators=(",", ":"))
        event_id = ""

        if persist:
            event_id = await self._redis.xadd(
                self._stream(event.run_id),
                {"payload": event_json},
                maxlen=self._stream_max_len,
                approximate=True,
            )

        envelope = json.dumps(
            {"id": event_id or None, "event": event_dict},
            separators=(",", ":"),
        )
        await self._redis.publish(self._channel(event.run_id), envelope)
        return event_id

    async def replay(
        self, run_id: str, after_id: str | None = None
    ) -> AsyncIterator[EventRecord]:
        stream = self._stream(run_id)
        start = f"({after_id}" if after_id else "-"
        entries = await self._redis.xrange(stream, min=start, max="+")
        for entry_id, fields in entries:
            raw = fields.get("payload")
            if raw is None:
                continue
            try:
                yield entry_id, RunEvent(**json.loads(raw))
            except Exception:  # pragma: no cover - defensive
                logger.exception("event_replay_decode_failed", run_id=run_id)

    @asynccontextmanager
    async def subscribe(self, run_id: str) -> AsyncIterator[asyncio.Queue[EventRecord]]:
        pubsub = self._redis.pubsub()
        queue: asyncio.Queue[EventRecord] = asyncio.Queue(
            maxsize=_SUBSCRIBE_QUEUE_MAXSIZE
        )
        channel = self._channel(run_id)
        await pubsub.subscribe(channel)

        async def reader() -> None:
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                try:
                    payload = json.loads(message["data"])
                    record = _decode_envelope(payload)
                    try:
                        queue.put_nowait(record)
                    except asyncio.QueueFull:
                        with suppress(asyncio.QueueEmpty):
                            queue.get_nowait()
                        with suppress(asyncio.QueueFull):
                            queue.put_nowait(record)
                except Exception:  # pragma: no cover - defensive
                    logger.exception("event_decode_failed")

        task = asyncio.create_task(reader())
        try:
            yield queue
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            with suppress(Exception):
                await pubsub.unsubscribe(channel)
            with suppress(Exception):
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
