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
from collections.abc import Awaitable

# Importing the package registers the built-in adapters as a side effect.
from app.adapters import load_adapter_plugins
from app.core.config import get_settings, jobs_backend
from app.core.logging import get_logger, setup_logging
from app.core.telemetry import (
    set_worker_utilization,
    setup_telemetry,
    shutdown_telemetry,
    trace_worker_job,
)
from app.db.base import Base
from app.db.session import engine
from app.events import get_event_bus
from app.runtime.webhooks import get_webhook_dispatcher
from app.worker.cancel import get_cancel_registry
from app.worker.executor import RunExecutor
from app.worker.monitor import run_queue_monitor
from app.worker.queue import JobLease, JobQueue, get_job_queue
from app.worker.retention import run_retention_sweeper
from app.worker.schedules import run_schedule_sweeper
from app.worker.temporal.worker import run_temporal_worker

logger = get_logger("worker.runner")


async def _ensure_schema() -> None:
    # Mirrors the FastAPI lifespan bootstrap so the worker can run against
    # a fresh SQLite file without alembic in dev.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _process_lease(
    executor: RunExecutor, queue: JobQueue, lease: JobLease
) -> None:
    """Execute one leased segment and ACK its completed or skipped delivery.

    ACK boundary:

    * Normal return of ``execute`` -> ACK. The segment finished, paused, or
      was safely skipped on redelivery. Adapter exceptions are recorded as
      ``RunStatus.FAILED`` before the executor returns.
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


class _StopRequested(Exception):
    """The worker stopped while an operation was still waiting."""


async def _await_or_stop[T](
    awaitable: Awaitable[T], stop_task: asyncio.Task[bool]
) -> T:
    """Interrupt a wait on shutdown, preserving a result returned in the race."""
    operation = asyncio.ensure_future(awaitable)
    try:
        await asyncio.wait((operation, stop_task), return_when=asyncio.FIRST_COMPLETED)
        if not operation.done():
            operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)
            if operation.cancelled():
                raise _StopRequested
        # An operation that finished with shutdown (including one that
        # returned during cancellation) still owns its result or exception.
        return operation.result()
    finally:
        if not operation.done():
            operation.cancel()
        await asyncio.gather(operation, return_exceptions=True)


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

    def _report_utilization() -> None:
        set_worker_utilization(in_flight=len(in_flight), capacity=concurrency)

    _report_utilization()

    async def _run_job(lease: JobLease) -> None:
        try:
            await _process_lease(executor, queue, lease)
        finally:
            slots.release()

    consumer = queue.consume()
    aiter = consumer.__aiter__()
    stop_task = asyncio.create_task(stop.wait(), name="worker.stop")
    try:
        while True:
            if stop.is_set():
                break

            try:
                await _await_or_stop(slots.acquire(), stop_task)
            except _StopRequested:
                break
            if stop.is_set():
                slots.release()
                break

            try:
                lease = await _await_or_stop(aiter.__anext__(), stop_task)
            except (_StopRequested, StopAsyncIteration):
                slots.release()
                break
            except BaseException:
                slots.release()
                raise

            # Even if stop was set while receiving the lease, finish this
            # already-owned job so destructive queue reads do not lose it.
            task = asyncio.create_task(_run_job(lease))
            in_flight.add(task)

            def _on_job_done(done: asyncio.Task[None]) -> None:
                in_flight.discard(done)
                _report_utilization()

            task.add_done_callback(_on_job_done)
            _report_utilization()
    finally:
        stop_task.cancel()
        await asyncio.gather(stop_task, return_exceptions=True)
        try:
            aclose = getattr(consumer, "aclose", None)
            if aclose is not None:
                await aclose()
        finally:
            if in_flight:
                logger.info("worker.draining", pending=len(in_flight))
                await asyncio.gather(*in_flight, return_exceptions=True)


async def run_forever() -> None:
    setup_logging()
    load_adapter_plugins()
    setup_telemetry()
    settings = get_settings()
    concurrency = settings.worker_concurrency
    logger.info("worker.starting", concurrency=concurrency)
    await _ensure_schema()

    bus = get_event_bus()
    get_webhook_dispatcher()  # validates AGENTFLOW_WEBHOOK_URLS at boot
    cancel_registry = get_cancel_registry()
    queue = get_job_queue()
    backend = jobs_backend()

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
    retention_task: asyncio.Task[None] | None = None
    schedule_task: asyncio.Task[None] | None = None
    if settings.job_queue_monitor_enabled and backend != "temporal":
        monitor_task = asyncio.create_task(
            run_queue_monitor(queue, stop, settings=settings)
        )
    if settings.data_retention_tenant_ttl_days > 0:
        retention_task = asyncio.create_task(
            run_retention_sweeper(stop, settings=settings)
        )
    schedule_task = asyncio.create_task(
        run_schedule_sweeper(stop, settings=settings)
    )

    try:
        if backend == "temporal":
            await run_temporal_worker(
                executor=executor, stop=stop, concurrency=concurrency
            )
        else:
            await _consume_loop(
                executor=executor,
                queue=queue,
                stop=stop,
                concurrency=concurrency,
            )
    finally:
        stop.set()
        if monitor_task is not None:
            await monitor_task
        if retention_task is not None:
            await retention_task
        if schedule_task is not None:
            await schedule_task
        logger.info("worker.shutting_down")
        # Flush in-flight webhook deliveries before tearing down the loop.
        await get_webhook_dispatcher().aclose()
        await queue.aclose()
        await cancel_registry.aclose()
        await bus.aclose()
        await engine.dispose()
        shutdown_telemetry()


def main() -> None:
    asyncio.run(run_forever())


if __name__ == "__main__":  # pragma: no cover - entrypoint
    main()
