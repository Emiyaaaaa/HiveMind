"""Standalone worker loop.

Run with ``python -m app.worker``. Each iteration leases the next run job
from the shared Redis queue, executes it to completion (or cancellation),
``XACK``s the queue and moves on. Failures inside a single run are
surfaced through ``RunStatus.FAILED`` and never bring the loop down; a
crash before ACK leaves the entry in the consumer group's pending list so
another consumer can ``XAUTOCLAIM`` it once the idle timeout elapses.

Within one process, ``Settings.worker_concurrency`` caps how many jobs run
at once (back-pressure via a semaphore before the next lease is taken).
Across processes, multiple workers compete on the same Redis stream
consumer group safely.
"""

from __future__ import annotations

import asyncio
import signal

from app.adapters import EchoAdapter, LangGraphAdapter  # noqa: F401 - register
from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging
from app.core.telemetry import setup_telemetry, shutdown_telemetry, trace_worker_job
from app.db.base import Base
from app.db.session import engine
from app.events import get_event_bus
from app.worker.cancel import get_cancel_registry
from app.worker.executor import RunExecutor
from app.worker.monitor import run_queue_monitor
from app.worker.queue import JobLease, JobQueue, get_job_queue

logger = get_logger("worker.runner")


async def _ensure_schema() -> None:
    # Mirrors the FastAPI lifespan bootstrap so the worker can run against
    # a fresh SQLite file without alembic in dev.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _process_lease(
    executor: RunExecutor, queue: JobQueue, lease: JobLease
) -> None:
    """Drive a single leased job to its terminal state and ACK on the queue.

    ACK boundary:

    * Normal return of ``execute`` -> ACK. ``RunExecutor.execute`` catches
      adapter exceptions internally and writes ``RunStatus.FAILED``, so a
      clean return always means the DB row is in a terminal state.
    * ``asyncio.CancelledError`` -> ACK and re-raise. The executor wrote a
      terminal status before propagating; not ACKing would let another
      consumer re-execute an already-cancelled run.
    * Any other exception -> deliberately *no* ACK so the entry stays in
      the consumer group's pending list. ``XAUTOCLAIM`` on a later loop
      will re-deliver it (or DLQ it once the retry budget is exhausted).
    """
    job = lease.job
    logger.info(
        "job.received",
        run_id=job.run_id,
        adapter=job.adapter,
        deliveries=lease.delivery_count,
    )
    try:
        await trace_worker_job(
            adapter=job.adapter,
            run_id=job.run_id,
            trace_context=job.trace_context,
            coro=executor.execute(job.run_id, job.adapter),
        )
    except asyncio.CancelledError:
        logger.info("job.cancelled", run_id=job.run_id)
        await queue.ack(lease)
        raise
    except Exception:
        logger.exception("job.failed", run_id=job.run_id)
        return
    await queue.ack(lease)
    logger.info("job.completed", run_id=job.run_id)


async def _consume_loop(
    *,
    executor: RunExecutor,
    queue: JobQueue,
    stop: asyncio.Event,
    concurrency: int,
) -> None:
    """Pull leases from the queue and run up to ``concurrency`` jobs at once."""
    slots = asyncio.Semaphore(concurrency)
    in_flight: set[asyncio.Task[None]] = set()

    async def _run_job(lease: JobLease) -> None:
        try:
            await _process_lease(executor, queue, lease)
        finally:
            slots.release()

    consumer = queue.consume()
    aiter = consumer.__aiter__()
    try:
        while True:
            if stop.is_set():
                break

            await slots.acquire()
            if stop.is_set():
                slots.release()
                break

            try:
                lease = await aiter.__anext__()
            except StopAsyncIteration:
                slots.release()
                break
            except Exception:
                slots.release()
                raise

            task = asyncio.create_task(_run_job(lease))
            in_flight.add(task)
            task.add_done_callback(in_flight.discard)
    finally:
        aclose = getattr(consumer, "aclose", None)
        if aclose is not None:
            await aclose()
        if in_flight:
            logger.info("worker.draining", pending=len(in_flight))
            await asyncio.gather(*in_flight, return_exceptions=True)

async def run_forever() -> None:
    setup_logging()
    setup_telemetry()
    settings = get_settings()
    concurrency = settings.worker_concurrency
    logger.info("worker.starting", concurrency=concurrency)
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

    monitor_task: asyncio.Task[None] | None = None
    if settings.job_queue_monitor_enabled:
        monitor_task = asyncio.create_task(
            run_queue_monitor(queue, stop, settings=settings)
        )

    try:
        await _consume_loop(
            executor=executor,
            queue=queue,
            stop=stop,
            concurrency=concurrency,
        )
    finally:
        if monitor_task is not None:
            stop.set()
            await monitor_task
        logger.info("worker.shutting_down")
        await queue.aclose()
        await cancel_registry.aclose()
        await bus.aclose()
        await engine.dispose()
        shutdown_telemetry()


def main() -> None:
    asyncio.run(run_forever())


if __name__ == "__main__":  # pragma: no cover - entrypoint
    main()
