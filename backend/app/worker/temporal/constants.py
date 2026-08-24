"""Names shared with the Java Temporal client (untyped workflow stub)."""

WORKFLOW_NAME = "RunWorkflow"
SIGNAL_RESUME = "resume"
SIGNAL_CANCEL = "cancel"
ACTIVITY_EXECUTE_SEGMENT = "execute_run_segment"
ACTIVITY_FINALIZE_CANCELLED = "finalize_cancelled"

_WORKFLOW_ID_PREFIX = "run:"


def workflow_id_for_run(run_id: str) -> str:
    return f"{_WORKFLOW_ID_PREFIX}{run_id}"
