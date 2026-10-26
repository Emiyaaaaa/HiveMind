"""Temporal client used by the Python API (queue mode) and tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError

from app.core.config import get_settings
from app.core.logging import get_logger
from app.worker.queue import JobLease, RunJob
from app.worker.temporal.constants import (
    SIGNAL_CANCEL,
    SIGNAL_RESUME,
    WORKFLOW_NAME,
    workflow_id_for_run,
)
from app.worker.temporal.workflows import RunWorkflow

logger = get_logger("worker.temporal.client")

_client: Client | None = None


def reset_temporal_client() -> None:
    """Drop the cached client. Tests only."""
    global _client
    _client = None


def set_temporal_client(client: Client | None) -> None:
    """Inject a client (WorkflowEnvironment in tests)."""
    global _client
    _client = client


async def get_temporal_client() -> Client:
    global _client
    if _client is not None:
        return _client
    settings = get_settings()
    logger.info(
        "temporal.connect",
        target=settings.temporal_target,
        namespace=settings.temporal_namespace,
    )
    _client = await Client.connect(
        settings.temporal_target,
        namespace=settings.temporal_namespace,
    )
    return _client


def _job_payload(job: RunJob) -> dict[str, Any]:
    settings = get_settings()
    payload = job.to_dict()
    payload["_heartbeat_seconds"] = settings.temporal_activity_heartbeat_seconds
    payload["_start_to_close_seconds"] = settings.temporal_activity_start_to_close_seconds
    payload["_max_attempts"] = settings.temporal_activity_max_attempts
    return payload


async def start_or_resume_run(job: RunJob) -> None:
    """Start ``RunWorkflow`` or signal ``resume`` if it is already running."""
    settings = get_settings()
    client = await get_temporal_client()
    workflow_id = workflow_id_for_run(job.run_id)
    payload = _job_payload(job)
    try:
        await client.start_workflow(
            RunWorkflow.run,
            payload,
            id=workflow_id,
            task_queue=settings.temporal_task_queue,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
        )
        logger.info("temporal.workflow.started", run_id=job.run_id, workflow_id=workflow_id)
    except WorkflowAlreadyStartedError:
        handle = client.get_workflow_handle(workflow_id)
        await handle.signal(RunWorkflow.resume, payload)
        logger.info("temporal.workflow.signaled_resume", run_id=job.run_id)


async def signal_cancel(run_id: str) -> None:
    """Ask a running workflow to finalize as cancelled. Missing workflows are ignored."""
    client = await get_temporal_client()
    workflow_id = workflow_id_for_run(run_id)
    handle = client.get_workflow_handle(workflow_id)
    try:
        await handle.signal(RunWorkflow.cancel)
        logger.info("temporal.workflow.signaled_cancel", run_id=run_id)
    except RPCError:
        logger.info("temporal.workflow.cancel_skipped", run_id=run_id, workflow_id=workflow_id)


class TemporalJobQueue:
    """JobQueue-compatible façade backed by Temporal workflows."""

    async def enqueue(self, job: RunJob) -> None:
        await start_or_resume_run(job)

    async def cancel_run(self, run_id: str) -> None:
        await signal_cancel(run_id)

    def consume(self) -> AsyncIterator[JobLease]:
        raise RuntimeError("TemporalJobQueue does not support consume()")
        yield  # pragma: no cover

    async def ack(self, lease: JobLease) -> None:  # pragma: no cover - unused
        return None

    async def aclose(self) -> None:
        return None


# Re-export for callers that need the workflow type name.
__all__ = [
    "WORKFLOW_NAME",
    "TemporalJobQueue",
    "get_temporal_client",
    "reset_temporal_client",
    "set_temporal_client",
    "signal_cancel",
    "start_or_resume_run",
]
