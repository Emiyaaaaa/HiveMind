"""``JobQueue`` adapter that starts Temporal workflows instead of Redis jobs."""

from __future__ import annotations

from collections.abc import AsyncIterator

from app.worker.queue import JobLease, RunJob
from app.worker.temporal.client import start_or_resume_run


class TemporalJobQueue:
    """Producer-only queue: ``enqueue`` starts or resumes ``RunWorkflow``.

    The Temporal worker polls the task queue; ``consume`` / ``ack`` are unused.
    """

    async def enqueue(self, job: RunJob) -> None:
        await start_or_resume_run(job)

    async def consume(self) -> AsyncIterator[JobLease]:
        raise RuntimeError(
            "Temporal job backend does not use JobQueue.consume; "
            "run the Temporal worker (python -m app.worker)"
        )
        yield  # pragma: no cover - keep AsyncIterator typing

    async def ack(self, lease: JobLease) -> None:  # pragma: no cover - unused
        return None

    async def aclose(self) -> None:
        from app.worker.temporal.client import reset_temporal_client

        reset_temporal_client()
