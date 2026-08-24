"""Durable Run workflow.

The workflow itself does no adapter I/O. Each adapter invocation is one
activity that runs until a terminal status or ``waiting_human``. Human
approval and cancel are Temporal signals, so a paused run holds no worker
slot and survives process restarts.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

from app.worker.temporal.constants import (
    ACTIVITY_EXECUTE_SEGMENT,
    ACTIVITY_FINALIZE_CANCELLED,
    SIGNAL_CANCEL,
    SIGNAL_RESUME,
)

_TERMINAL = frozenset({"succeeded", "failed", "cancelled"})


@workflow.defn(name="RunWorkflow")
class RunWorkflow:
    def __init__(self) -> None:
        self._resume_job: dict[str, Any] | None = None
        self._cancel_requested = False

    @workflow.run
    async def run(self, job: dict[str, Any]) -> str:
        current = job
        heartbeat = timedelta(
            seconds=int(job.get("_heartbeat_seconds") or 30)
        )
        start_to_close = timedelta(
            seconds=int(job.get("_start_to_close_seconds") or 7 * 24 * 3600)
        )
        max_attempts = int(job.get("_max_attempts") or 5)
        retry = RetryPolicy(maximum_attempts=max_attempts)

        while True:
            if self._cancel_requested:
                await self._finalize_cancelled(current)
                return "cancelled"

            result = await workflow.execute_activity(
                ACTIVITY_EXECUTE_SEGMENT,
                current,
                result_type=dict,
                start_to_close_timeout=start_to_close,
                heartbeat_timeout=heartbeat,
                retry_policy=retry,
            )
            status = str(result.get("status", "failed"))
            if status in _TERMINAL:
                return status
            if status != "waiting_human":
                return status

            await workflow.wait_condition(
                lambda: self._cancel_requested or self._resume_job is not None
            )
            if self._cancel_requested:
                await self._finalize_cancelled(current)
                return "cancelled"
            assert self._resume_job is not None
            current = self._resume_job
            self._resume_job = None

    @workflow.signal(name=SIGNAL_RESUME)
    def resume(self, job: dict[str, Any]) -> None:
        self._resume_job = job

    @workflow.signal(name=SIGNAL_CANCEL)
    def cancel(self) -> None:
        self._cancel_requested = True

    async def _finalize_cancelled(self, job: dict[str, Any]) -> None:
        await workflow.execute_activity(
            ACTIVITY_FINALIZE_CANCELLED,
            str(job["run_id"]),
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=RetryPolicy(maximum_attempts=5),
        )
