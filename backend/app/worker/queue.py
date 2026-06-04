"""Run-job queue abstractions.

``JobQueue`` defines the contract shared between:

- The FastAPI API server in inline-development mode (in-memory queue).
- The Java API server in production (Redis stream ``XADD``; LIST ``LPUSH``
  kept as a legacy fallback).
- The standalone Python worker process that consumes the queue.

The wire format is intentionally JSON so the same payload can be produced
by either backend without sharing language-specific serialisation.

Two Redis-backed implementations are available, selected by
``Settings.redis_queue_impl``:

* ``"list"`` — legacy ``LPUSH`` + ``BRPOP``. At-most-once: a job pulled by
  ``BRPOP`` is immediately removed from Redis and a worker crash mid-execute
  loses the job.
* ``"streams"`` — ``XADD`` + ``XREADGROUP`` with explicit ``XACK``. The
  consumer also calls ``XAUTOCLAIM`` on every loop iteration to recover
  pending entries left behind by a dead worker, and routes entries that
  exceed the configured delivery limit to a dead-letter stream. This is
  the production default.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger("worker.queue")


# Stream payload field used by both Java (XADD) and Python (XREADGROUP).
# Keeping a single field lets both sides reuse the existing snake_case JSON
# wire format defined by ``RunJob.to_json``.
_STREAM_PAYLOAD_FIELD = "payload"


@dataclass(frozen=True)
class QueueStats:
    """Point-in-time snapshot of the run-job Redis stream."""

    stream_length: int
    lag_count: int
    pending_count: int
    oldest_lag_seconds: float | None
    oldest_pending_idle_seconds: float | None
    dlq_length: int | None = None

    @property
    def backlog_count(self) -> int:
        return self.lag_count + self.pending_count

    @property
    def consumer_delay_seconds(self) -> float | None:
        """Worst-case wait among undelivered and in-flight-but-un-ACKed jobs."""
        candidates = [
            value
            for value in (self.oldest_lag_seconds, self.oldest_pending_idle_seconds)
            if value is not None
        ]
        return max(candidates) if candidates else None


def _normalize_entry_id(entry_id: str | bytes) -> str:
    if isinstance(entry_id, bytes):
        return entry_id.decode()
    return str(entry_id)


def _entry_age_seconds(entry_id: str | bytes) -> float:
    """Return age in seconds from a Redis stream entry id (``{ms}-{seq}``)."""
    ms = int(_normalize_entry_id(entry_id).split("-", 1)[0])
    now_ms = datetime.now(UTC).timestamp() * 1000
    return max(0.0, (now_ms - ms) / 1000.0)


def _field_value(fields: dict[str | bytes, str | bytes], key: str) -> str | None:
    value = fields.get(key)
    if value is not None:
        return value if isinstance(value, str) else value.decode()
    for field_key, field_value in fields.items():
        normalized = field_key if isinstance(field_key, str) else field_key.decode()
        if normalized == key:
            return field_value if isinstance(field_value, str) else field_value.decode()
    return None


@dataclass
class RunJob:
    """JSON-serialisable run job payload.

    The Java side produces the same JSON shape from
    ``io.agentflow.api.jobs.RunJob``. Field names use snake_case so the
    payload survives without a custom Jackson mapping.
    """

    run_id: str
    agent_id: str
    adapter: str
    enqueued_at: str
    trace_context: dict[str, str] | None = None

    @classmethod
    def new(
        cls,
        *,
        run_id: str,
        agent_id: str,
        adapter: str,
        trace_context: dict[str, str] | None = None,
    ) -> RunJob:
        if trace_context is None:
            from app.core.telemetry import capture_trace_context

            trace_context = capture_trace_context()
        return cls(
            run_id=run_id,
            agent_id=agent_id,
            adapter=adapter,
            enqueued_at=datetime.now(UTC).isoformat(),
            trace_context=trace_context,
        )

    def to_json(self) -> str:
        data = asdict(self)
        if data.get("trace_context") is None:
            data.pop("trace_context", None)
        return json.dumps(data)

    @classmethod
    def from_json(cls, payload: str) -> RunJob:
        data = json.loads(payload)
        trace_context = data.get("trace_context")
        if trace_context is not None and not isinstance(trace_context, dict):
            trace_context = None
        return cls(
            run_id=data["run_id"],
            agent_id=data["agent_id"],
            adapter=data["adapter"],
            enqueued_at=data.get("enqueued_at", datetime.now(UTC).isoformat()),
            trace_context=trace_context,
        )


@dataclass
class JobLease:
    """A job handed out by ``JobQueue.consume`` along with an ACK token.

    The token is opaque to the runner: in-memory queues use ``None``,
    Redis streams use the entry id (``"1700000000000-0"``). The runner must
    pass the lease back to ``JobQueue.ack`` after the run reaches a terminal
    state, or drop it without acking to let the queue redeliver it after
    the claim-idle timeout.
    """

    job: RunJob
    token: str | None = None
    delivery_count: int = 1
    extra: dict[str, Any] = field(default_factory=dict)


class JobQueue(Protocol):
    async def enqueue(self, job: RunJob) -> None: ...

    def consume(self) -> AsyncIterator[JobLease]: ...

    async def ack(self, lease: JobLease) -> None: ...

    async def aclose(self) -> None: ...


class InMemoryJobQueue:
    """Process-local queue, used in tests and inline mode.

    ACK is a no-op because the in-memory implementation cannot survive a
    process crash anyway.
    """

    def __init__(self) -> None:
        self._queue: asyncio.Queue[RunJob] = asyncio.Queue()

    async def enqueue(self, job: RunJob) -> None:
        await self._queue.put(job)

    async def consume(self) -> AsyncIterator[JobLease]:
        while True:
            job = await self._queue.get()
            yield JobLease(job=job, token=None)

    async def ack(self, lease: JobLease) -> None:  # pragma: no cover - trivial
        return None

    async def aclose(self) -> None:  # pragma: no cover - nothing to do
        return None


class RedisJobQueue:
    """Legacy Redis LIST queue. ``LPUSH`` produces, ``BRPOP`` consumes.

    Retained behind ``Settings.redis_queue_impl = "list"`` for operators
    that need to roll back; new deployments should prefer
    ``RedisStreamsJobQueue``. Note that ``BRPOP`` is at-most-once: a worker
    crash after the pop but before the run terminates loses the job.
    """

    def __init__(self, url: str, key: str) -> None:
        import redis.asyncio as redis  # local import to keep tests light

        self._redis = redis.from_url(url, decode_responses=True)
        self._key = key

    async def enqueue(self, job: RunJob) -> None:
        await self._redis.lpush(self._key, job.to_json())

    async def consume(self) -> AsyncIterator[JobLease]:
        while True:
            result = await self._redis.brpop(self._key, timeout=5)
            if result is None:
                continue
            _, payload = result
            try:
                job = RunJob.from_json(payload)
            except Exception:  # pragma: no cover - defensive
                logger.exception("job_decode_failed", payload=payload)
                continue
            yield JobLease(job=job, token=None)

    async def ack(self, lease: JobLease) -> None:  # pragma: no cover - trivial
        # BRPOP already removed the entry; nothing to do.
        return None

    async def aclose(self) -> None:
        await self._redis.aclose()


class RedisStreamsJobQueue:
    """Redis Streams queue with at-least-once delivery semantics.

    Production-grade producer/consumer protocol:

    * ``enqueue`` -> ``XADD <stream> * payload <json>``.
    * ``consume`` -> ``XAUTOCLAIM`` (recover stale entries from dead
      consumers), then ``XREADGROUP`` for new entries. Each delivered entry
      is yielded as a ``JobLease`` whose ``token`` is the stream entry id.
    * ``ack(lease)`` -> ``XACK <stream> <group> <id>``.
    * Entries whose delivery count exceeds ``max_deliveries`` are
      ``XADD``ed to ``dlq_key`` and immediately ``XACK``ed off the main
      stream, so a poison job cannot block the queue indefinitely.

    The consumer group is created lazily on first ``consume`` call so the
    same code path works against a fresh stream (no ``MKSTREAM`` race).
    """

    def __init__(
        self,
        *,
        url: str | None = None,
        redis_client: Any | None = None,
        stream_key: str,
        group: str,
        consumer: str,
        block_ms: int,
        claim_idle_ms: int,
        max_deliveries: int,
        dlq_key: str,
    ) -> None:
        if redis_client is None:
            if url is None:
                raise ValueError("RedisStreamsJobQueue needs either url or redis_client")
            import redis.asyncio as redis  # local import

            redis_client = redis.from_url(url, decode_responses=True)
        self._redis = redis_client
        self._stream = stream_key
        self._group = group
        self._consumer = consumer
        self._block_ms = block_ms
        self._claim_idle_ms = claim_idle_ms
        self._max_deliveries = max_deliveries
        self._dlq = dlq_key
        self._group_ready = False
        self._autoclaim_cursor = "0-0"

    async def _ensure_group(self) -> None:
        if self._group_ready:
            return
        try:
            await self._redis.xgroup_create(
                name=self._stream,
                groupname=self._group,
                id="0",
                mkstream=True,
            )
        except Exception as exc:  # pragma: no cover - exact class is module-local
            # "BUSYGROUP" is fine; anything else surfaces below.
            if "BUSYGROUP" not in str(exc):
                logger.exception("xgroup_create_failed", stream=self._stream)
                raise
        self._group_ready = True

    async def enqueue(self, job: RunJob) -> None:
        await self._ensure_group()
        await self._redis.xadd(
            self._stream,
            {_STREAM_PAYLOAD_FIELD: job.to_json()},
        )

    async def consume(self) -> AsyncIterator[JobLease]:
        await self._ensure_group()

        while True:
            # Yield to the event loop every iteration so a cancelling caller
            # (and unit tests that wrap consume in ``asyncio.wait_for``) can
            # interrupt the loop even if both the claim sweep and the read
            # below return synchronously. In production ``XREADGROUP`` blocks
            # for ``block_ms`` and provides cooperation naturally.
            await asyncio.sleep(0)

            async for lease in self._reap_stale():
                yield lease

            entries = await self._redis.xreadgroup(
                groupname=self._group,
                consumername=self._consumer,
                streams={self._stream: ">"},
                count=1,
                block=self._block_ms,
            )
            if not entries:
                continue

            for _stream, items in entries:
                for entry_id, fields in items:
                    lease = self._decode_entry(entry_id, fields, delivery_count=1)
                    if lease is None:
                        # Malformed entry: ACK so it does not retry forever.
                        await self._redis.xack(self._stream, self._group, entry_id)
                        continue
                    yield lease

    async def ack(self, lease: JobLease) -> None:
        if lease.token is None:  # pragma: no cover - defensive
            return
        await self._redis.xack(self._stream, self._group, lease.token)

    async def aclose(self) -> None:
        await self._redis.aclose()

    async def collect_stats(self) -> QueueStats:
        """Return queue depth, consumer-group lag, and oldest-wait metrics."""
        stream_length = int(await self._redis.xlen(self._stream))
        dlq_length = int(await self._redis.xlen(self._dlq))

        lag_count = 0
        pending_count = 0
        oldest_lag_seconds: float | None = None
        oldest_pending_idle_seconds: float | None = None
        last_delivered_id = "0-0"

        try:
            groups = await self._redis.xinfo_groups(self._stream)
        except Exception:  # pragma: no cover - stream may not exist yet
            groups = []

        group_info = next(
            (row for row in groups if row.get("name") == self._group),
            None,
        )
        if group_info is not None:
            lag_count = int(group_info.get("lag") or 0)
            last_delivered_id = _normalize_entry_id(
                group_info.get("last-delivered-id") or "0-0"
            )

        try:
            pending_summary = await self._redis.xpending(self._stream, self._group)
            pending_count = int(pending_summary.get("pending") or 0)
        except Exception:  # pragma: no cover - group may not exist yet
            pending_count = int(group_info.get("pending") or 0) if group_info else 0

        if pending_count == 0:
            undelivered = await self._redis.xrange(
                self._stream,
                min=f"({last_delivered_id}",
                max="+",
            )
            if undelivered:
                if lag_count == 0:
                    lag_count = len(undelivered)
                oldest_lag_seconds = _entry_age_seconds(undelivered[0][0])
        elif lag_count > 0:
            trailing = await self._redis.xrange(
                self._stream,
                min=f"({last_delivered_id}",
                max="+",
                count=1,
            )
            if trailing:
                oldest_lag_seconds = _entry_age_seconds(trailing[0][0])

        if pending_count > 0:
            try:
                pending_rows = await self._redis.xpending_range(
                    name=self._stream,
                    groupname=self._group,
                    min="-",
                    max="+",
                    count=pending_count,
                )
            except Exception:  # pragma: no cover - defensive
                pending_rows = []
            idle_ms_values = [
                int(row.get("time_since_delivered") if isinstance(row, dict) else row[2])
                for row in pending_rows
                if row is not None
            ]
            if idle_ms_values:
                oldest_pending_idle_seconds = max(idle_ms_values) / 1000.0

        return QueueStats(
            stream_length=stream_length,
            lag_count=lag_count,
            pending_count=pending_count,
            oldest_lag_seconds=oldest_lag_seconds,
            oldest_pending_idle_seconds=oldest_pending_idle_seconds,
            dlq_length=dlq_length,
        )

    # ------------------------------------------------------------------ helpers

    async def _reap_stale(self) -> AsyncIterator[JobLease]:
        """Reclaim pending entries from dead consumers in one XAUTOCLAIM call.

        Each reclaimed entry's pending-list delivery counter is incremented
        by one as a side effect of the claim. Entries past the retry budget
        are forwarded to the DLQ and ACKed off the main stream, so the
        runner never sees a poison job.
        """
        try:
            cursor, claimed, _deleted = await self._redis.xautoclaim(
                name=self._stream,
                groupname=self._group,
                consumername=self._consumer,
                min_idle_time=self._claim_idle_ms,
                start_id=self._autoclaim_cursor,
                count=10,
            )
        except Exception:  # pragma: no cover - defensive
            logger.exception("xautoclaim_failed", stream=self._stream)
            return

        self._autoclaim_cursor = cursor or "0-0"
        if not claimed:
            return

        pending_counts = await self._delivery_counts([entry_id for entry_id, _ in claimed])

        for entry_id, fields in claimed:
            deliveries = pending_counts.get(entry_id, 1)
            if deliveries > self._max_deliveries:
                await self._route_to_dlq(entry_id, fields, deliveries)
                continue

            lease = self._decode_entry(entry_id, fields, delivery_count=deliveries)
            if lease is None:
                await self._redis.xack(self._stream, self._group, entry_id)
                continue
            logger.info(
                "job.reclaimed",
                stream=self._stream,
                entry_id=entry_id,
                deliveries=deliveries,
                run_id=lease.job.run_id,
            )
            yield lease

    async def _delivery_counts(self, entry_ids: list[str]) -> dict[str, int]:
        if not entry_ids:
            return {}
        try:
            rows = await self._redis.xpending_range(
                name=self._stream,
                groupname=self._group,
                min=min(entry_ids),
                max=max(entry_ids),
                count=len(entry_ids),
            )
        except Exception:  # pragma: no cover - defensive
            logger.exception("xpending_range_failed", stream=self._stream)
            return {}
        counts: dict[str, int] = {}
        for row in rows:
            entry_id = row.get("message_id") if isinstance(row, dict) else row[0]
            times_delivered = (
                row.get("times_delivered") if isinstance(row, dict) else row[3]
            )
            if entry_id is not None and times_delivered is not None:
                counts[str(entry_id)] = int(times_delivered)
        return counts

    async def _route_to_dlq(
        self, entry_id: str, fields: dict[str, str], deliveries: int
    ) -> None:
        try:
            dlq_fields = dict(fields)
            dlq_fields["_origin_id"] = entry_id
            dlq_fields["_deliveries"] = str(deliveries)
            await self._redis.xadd(self._dlq, dlq_fields)
        finally:
            await self._redis.xack(self._stream, self._group, entry_id)
        logger.warning(
            "job.dead_lettered",
            stream=self._stream,
            dlq=self._dlq,
            entry_id=entry_id,
            deliveries=deliveries,
        )

    def _decode_entry(
        self, entry_id: str | bytes, fields: dict[str | bytes, str | bytes], *, delivery_count: int
    ) -> JobLease | None:
        entry_id = _normalize_entry_id(entry_id)
        payload = _field_value(fields, _STREAM_PAYLOAD_FIELD)
        if payload is None:
            logger.warning(
                "job.missing_payload_field", stream=self._stream, entry_id=entry_id
            )
            return None
        try:
            job = RunJob.from_json(payload)
        except Exception:
            logger.exception(
                "job_decode_failed", stream=self._stream, entry_id=entry_id
            )
            return None
        return JobLease(job=job, token=entry_id, delivery_count=delivery_count)


# Public API for runner / tests --------------------------------------------------


# A typed alias for the consume callback used by tests.
LeaseHandler = Callable[[JobLease], Awaitable[None]]


_queue: JobQueue | None = None


def _default_consumer_name() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def reset_job_queue() -> None:
    """Drop the cached singleton. Tests only."""
    global _queue
    _queue = None


def get_job_queue() -> JobQueue:
    """Return a process-wide job queue singleton.

    Selection rules:

    * ``AGENTFLOW_REDIS_URL`` unset, or ``worker_mode != "queue"`` -> the
      in-memory queue (sufficient for tests and inline dev).
    * ``redis_queue_impl == "list"`` -> legacy LIST/BRPOP implementation.
    * Otherwise (the default) -> Redis Streams implementation.
    """
    global _queue
    if _queue is not None:
        return _queue

    settings = get_settings()
    if not (settings.redis_url and settings.worker_mode == "queue"):
        logger.info("job_queue.in_memory")
        _queue = InMemoryJobQueue()
        return _queue

    if settings.redis_queue_impl == "list":
        logger.info(
            "job_queue.redis_list", url=settings.redis_url, key=settings.job_queue_key
        )
        _queue = RedisJobQueue(settings.redis_url, settings.job_queue_key)
        return _queue

    consumer = settings.job_stream_consumer or _default_consumer_name()
    dlq_key = settings.job_dlq_key or f"{settings.job_queue_key}:dlq"
    logger.info(
        "job_queue.redis_streams",
        url=settings.redis_url,
        stream=settings.job_queue_key,
        group=settings.job_stream_group,
        consumer=consumer,
        dlq=dlq_key,
    )
    _queue = RedisStreamsJobQueue(
        url=settings.redis_url,
        stream_key=settings.job_queue_key,
        group=settings.job_stream_group,
        consumer=consumer,
        block_ms=settings.job_stream_block_ms,
        claim_idle_ms=settings.job_stream_claim_idle_ms,
        max_deliveries=settings.job_stream_max_deliveries,
        dlq_key=dlq_key,
    )
    return _queue
