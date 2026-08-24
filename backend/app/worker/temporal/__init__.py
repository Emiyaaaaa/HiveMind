"""Temporal backend for ultra-long Runs.

A ``RunWorkflow`` owns the run across adapter segments and human-approval
pauses. Adapter execution stays in ``RunExecutor``; Temporal supplies durable
timers, signals, and activity retry after a worker crash.
"""

from app.worker.temporal.constants import (
    ACTIVITY_EXECUTE_SEGMENT,
    ACTIVITY_FINALIZE_CANCELLED,
    SIGNAL_CANCEL,
    SIGNAL_RESUME,
    WORKFLOW_NAME,
    workflow_id_for_run,
)

__all__ = [
    "ACTIVITY_EXECUTE_SEGMENT",
    "ACTIVITY_FINALIZE_CANCELLED",
    "SIGNAL_CANCEL",
    "SIGNAL_RESUME",
    "WORKFLOW_NAME",
    "workflow_id_for_run",
]
