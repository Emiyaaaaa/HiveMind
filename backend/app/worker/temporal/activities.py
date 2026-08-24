"""Temporal activities that drive ``RunExecutor``.

Heartbeats keep the activity lease alive for multi-hour adapter work. When
heartbeats stop, Temporal times the activity out and retries; the executor
then resumes from the latest checkpoint.
"""

from __future__ import annotations

import asyncio
from typing import Any

from temporalio import activity

from app.core.logging import get_logger
from app.models import Run, RunStatus
from app.worker.executor import RunExecutor
from app.worker.queue import RunJob
from app.worker.temporal.constants import (
    ACTIVITY_EXECUTE_SEGMENT,
    ACTIVITY_FINALIZE_CANCELLED,
)

logger = get_logger("worker.temporal.activities")

_executor: RunExecutor | None = None
_heartbeat_seconds: float = 10.0


def bind_run_executor(executor: RunExecutor, *, heartbeat_seconds: float = 10.0) -> None:
    """Attach the process-wide executor used by Temporal activities."""
    global _executor, _heartbeat_seconds
    _executor = executor
    _heartbeat_seconds = max(1.0, heartbeat_seconds)


def _require_executor() -> RunExecutor:
    if _executor is None:
        raise RuntimeError("Temporal activities are not bound to a RunExecutor")
    return _executor


async def _heartbeat_loop() -> None:
    interval = max(1.0, _heartbeat_seconds / 3.0)
    try:
        while True:
            activity.heartbeat("running")
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        return


@activity.defn(name=ACTIVITY_EXECUTE_SEGMENT)
async def execute_run_segment(job_payload: dict[str, Any]) -> dict[str, str]:
    job = RunJob.from_mapping(job_payload)
    executor = _require_executor()
    activity.heartbeat("starting")
    beater = asyncio.create_task(_heartbeat_loop())
    try:
        await executor.execute(job.run_id, job.adapter)
    except asyncio.CancelledError:
        # The executor cancels and finalises the run as CANCELLED.
        # Treat this as a normal activity completion so the workflow can
        # reach a terminal state without Temporal retry noise.
        logger.info("temporal.activity.cancelled", run_id=job.run_id)
    finally:
        beater.cancel()
        try:
            await beater
        except (asyncio.CancelledError, Exception):
            pass

    status = await _load_status(executor, job.run_id)
    return {"status": status}


@activity.defn(name=ACTIVITY_FINALIZE_CANCELLED)
async def finalize_cancelled(run_id: str) -> dict[str, str]:
    executor = _require_executor()
    from app.services.run_service import RunService

    async with executor.session_factory() as session:
        service = RunService(
            session=session,
            bus=executor.bus,
            session_factory=executor.session_factory,
        )
        run = await session.get(Run, run_id)
        if run is None:
            return {"status": "missing"}
        if run.status in (
            RunStatus.SUCCEEDED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        ):
            return {"status": run.status.value}
        await service._finalize(run_id, RunStatus.CANCELLED, error="cancelled")
        return {"status": RunStatus.CANCELLED.value}


async def _load_status(executor: RunExecutor, run_id: str) -> str:
    async with executor.session_factory() as session:
        run = await session.get(Run, run_id)
        if run is None:
            return RunStatus.FAILED.value
        return run.status.value
