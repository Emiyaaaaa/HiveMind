"""Temporal worker process loop."""

from __future__ import annotations

import asyncio

from temporalio.worker import Worker

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.telemetry import set_worker_utilization
from app.worker.executor import RunExecutor
from app.worker.temporal.activities import (
    bind_run_executor,
    execute_run_segment,
    finalize_cancelled,
)
from app.worker.temporal.client import get_temporal_client
from app.worker.temporal.workflows import RunWorkflow

logger = get_logger("worker.temporal.worker")


async def run_temporal_worker(
    *,
    executor: RunExecutor,
    stop: asyncio.Event,
    concurrency: int,
) -> None:
    settings = get_settings()
    bind_run_executor(
        executor,
        heartbeat_seconds=float(settings.temporal_activity_heartbeat_seconds),
    )
    client = await get_temporal_client()
    set_worker_utilization(in_flight=0, capacity=concurrency)
    logger.info(
        "temporal.worker.starting",
        task_queue=settings.temporal_task_queue,
        concurrency=concurrency,
    )
    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[RunWorkflow],
        activities=[execute_run_segment, finalize_cancelled],
        max_concurrent_activities=concurrency,
    )
    async with worker:
        await stop.wait()
    logger.info("temporal.worker.stopped")
