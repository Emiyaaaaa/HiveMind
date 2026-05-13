"""Background worker that executes agent runs.

The worker is the Python-side counterpart of the Java/Spring Boot API
server in ``backend-java/``. The API enqueues run jobs onto a Redis list;
the worker pops them, loads the run from the database, drives the adapter
to completion (emitting events and writing rows), and watches for a
cancellation signal published by the API.

The module also exposes the abstractions the inline mode uses, so the same
adapter-execution code path is exercised both by the FastAPI test suite and
the standalone worker process.
"""

from app.worker.cancel import (
    CancelRegistry,
    InMemoryCancelRegistry,
    RedisCancelRegistry,
    get_cancel_registry,
)
from app.worker.executor import RunExecutor
from app.worker.queue import (
    InMemoryJobQueue,
    JobQueue,
    RedisJobQueue,
    RunJob,
    get_job_queue,
)

__all__ = [
    "CancelRegistry",
    "InMemoryCancelRegistry",
    "InMemoryJobQueue",
    "JobQueue",
    "RedisCancelRegistry",
    "RedisJobQueue",
    "RunExecutor",
    "RunJob",
    "get_cancel_registry",
    "get_job_queue",
]
