"""Standalone worker loop.

Run with ``python -m app.worker``. Each iteration pops a run job off the
shared Redis queue, executes it to completion (or cancellation), and moves
on. Failures inside a single run are surfaced through ``RunStatus.FAILED``
and never bring the loop down.

The worker is intentionally single-process and concurrency-safe through
Redis: multiple workers can compete on the same queue with ``BRPOP``.
"""

from __future__ import annotations

import asyncio
import signal

from app.adapters import EchoAdapter, LangGraphAdapter  # noqa: F401 - register
from app.core.logging import get_logger, setup_logging
from app.db.base import Base
from app.db.session import engine
from app.events import get_event_bus
from app.worker.cancel import get_cancel_registry
from app.worker.executor import RunExecutor
from app.worker.queue import RunJob, get_job_queue

logger = get_logger("worker.runner")


async def _ensure_schema() -> None:
    # Mirrors the FastAPI lifespan bootstrap so the worker can run against
    # a fresh SQLite file without alembic in dev.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _process_job(executor: RunExecutor, job: RunJob) -> None:
    logger.info("job.received", run_id=job.run_id, adapter=job.adapter)
    try:
        await executor.execute(job.run_id, job.adapter)
        logger.info("job.completed", run_id=job.run_id)
    except asyncio.CancelledError:
        logger.info("job.cancelled", run_id=job.run_id)
        raise
    except Exception:
        logger.exception("job.failed", run_id=job.run_id)


async def run_forever() -> None:
    setup_logging()
    logger.info("worker.starting")
    await _ensure_schema()

    bus = get_event_bus()
    cancel_registry = get_cancel_registry()
    queue = get_job_queue()

    executor = RunExecutor(bus=bus, cancel_registry=cancel_registry)

    stop = asyncio.Event()

    def _request_stop(*_: object) -> None:
        logger.info("worker.stop_requested")
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:  # pragma: no cover - Windows
            signal.signal(sig, lambda *_: _request_stop())

    try:
        async for job in queue.consume():
            if stop.is_set():
                break
            await _process_job(executor, job)
    finally:
        logger.info("worker.shutting_down")
        await queue.aclose()
        await cancel_registry.aclose()
        await bus.aclose()
        await engine.dispose()


def main() -> None:
    asyncio.run(run_forever())


if __name__ == "__main__":  # pragma: no cover - entrypoint
    main()
