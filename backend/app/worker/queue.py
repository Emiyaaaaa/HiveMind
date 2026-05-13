"""Run-job queue abstractions.

``JobQueue`` defines the contract shared between:

- The FastAPI API server in inline-development mode (in-memory queue).
- The Java API server in production (Redis ``LPUSH``).
- The standalone Python worker process that consumes the queue.

The wire format is intentionally JSON so the same payload can be produced
by either backend without sharing language-specific serialisation.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Protocol

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger("worker.queue")


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

    @classmethod
    def new(cls, *, run_id: str, agent_id: str, adapter: str) -> RunJob:
        return cls(
            run_id=run_id,
            agent_id=agent_id,
            adapter=adapter,
            enqueued_at=datetime.now(UTC).isoformat(),
        )

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, payload: str) -> RunJob:
        data = json.loads(payload)
        return cls(
            run_id=data["run_id"],
            agent_id=data["agent_id"],
            adapter=data["adapter"],
            enqueued_at=data.get("enqueued_at", datetime.now(UTC).isoformat()),
        )


class JobQueue(Protocol):
    async def enqueue(self, job: RunJob) -> None: ...

    async def consume(self) -> AsyncIterator[RunJob]: ...

    async def aclose(self) -> None: ...


class InMemoryJobQueue:
    """Process-local queue, used in tests and inline mode."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[RunJob] = asyncio.Queue()

    async def enqueue(self, job: RunJob) -> None:
        await self._queue.put(job)

    async def consume(self) -> AsyncIterator[RunJob]:
        while True:
            job = await self._queue.get()
            yield job

    async def aclose(self) -> None:  # pragma: no cover - nothing to do
        return None


class RedisJobQueue:
    """Redis-backed queue. ``LPUSH`` produces, ``BRPOP`` consumes (FIFO)."""

    def __init__(self, url: str, key: str) -> None:
        import redis.asyncio as redis  # local import to keep tests light

        self._redis = redis.from_url(url, decode_responses=True)
        self._key = key

    async def enqueue(self, job: RunJob) -> None:
        await self._redis.lpush(self._key, job.to_json())

    async def consume(self) -> AsyncIterator[RunJob]:
        while True:
            result = await self._redis.brpop(self._key, timeout=5)
            if result is None:
                continue
            _, payload = result
            try:
                yield RunJob.from_json(payload)
            except Exception:  # pragma: no cover - defensive
                logger.exception("job_decode_failed", payload=payload)

    async def aclose(self) -> None:
        await self._redis.aclose()


_queue: JobQueue | None = None


def get_job_queue() -> JobQueue:
    """Return a process-wide job queue singleton.

    When ``AGENTFLOW_REDIS_URL`` is configured we use Redis; otherwise we
    fall back to a per-process in-memory queue. The in-memory queue is
    sufficient for tests and for the legacy inline mode.
    """
    global _queue
    if _queue is not None:
        return _queue

    settings = get_settings()
    if settings.redis_url and settings.worker_mode == "queue":
        logger.info("job_queue.redis", url=settings.redis_url, key=settings.job_queue_key)
        _queue = RedisJobQueue(settings.redis_url, settings.job_queue_key)
    else:
        logger.info("job_queue.in_memory")
        _queue = InMemoryJobQueue()
    return _queue
