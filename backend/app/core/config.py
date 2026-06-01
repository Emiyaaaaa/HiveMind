from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from env vars or .env file."""

    model_config = SettingsConfigDict(
        env_prefix="AGENTFLOW_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = Field(
        default="sqlite+aiosqlite:///./agentflow.db",
        description="SQLAlchemy async URL. Defaults to local SQLite for zero-config dev.",
    )
    redis_url: str | None = Field(
        default=None,
        description="Optional redis URL. When unset, the in-memory event bus is used.",
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    default_adapter: str = Field(
        default="echo",
        description="Adapter key used when a run does not specify one.",
    )

    # When "inline" (default), the FastAPI process executes adapter runs
    # itself as asyncio tasks (legacy behaviour, used by the test suite).
    # When "queue", `RunService.start_run` pushes the run onto the shared
    # Redis job queue and a separate worker process (or the Java API server's
    # producer) is responsible for dispatching execution.
    worker_mode: Literal["inline", "queue"] = "inline"
    worker_concurrency: int = Field(
        default=1,
        ge=1,
        le=64,
        description=(
            "Maximum number of run jobs this worker process executes in parallel. "
            "Scale out with additional worker replicas for more throughput."
        ),
    )

    job_queue_key: str = Field(
        default="agentflow:jobs:runs",
        description=(
            "Redis key the API pushes run jobs to. When `redis_queue_impl` is "
            "`list` it is a LIST consumed with BRPOP; when `streams` it is a "
            "stream consumed with XREADGROUP."
        ),
    )
    redis_queue_impl: Literal["list", "streams"] = Field(
        default="streams",
        description=(
            "Wire protocol for the run job queue. `streams` provides "
            "at-least-once delivery with XACK + XCLAIM-based recovery; "
            "`list` is the legacy LPUSH/BRPOP path kept for rollback."
        ),
    )
    job_stream_group: str = Field(
        default="agentflow-workers",
        description="Consumer group name for the run-job Redis stream.",
    )
    job_stream_consumer: str | None = Field(
        default=None,
        description=(
            "Override the consumer name registered with the stream. "
            "Defaults to `{hostname}:{pid}` when unset."
        ),
    )
    job_stream_block_ms: int = Field(
        default=5_000,
        description="XREADGROUP block timeout in milliseconds.",
    )
    job_stream_claim_idle_ms: int = Field(
        default=60_000,
        description=(
            "How long a pending entry may remain un-ACKed before another "
            "consumer is allowed to XAUTOCLAIM it."
        ),
    )
    job_stream_max_deliveries: int = Field(
        default=5,
        description=(
            "Maximum delivery attempts before a job is routed to the DLQ "
            "stream and XACKed off the main stream."
        ),
    )
    job_dlq_key: str | None = Field(
        default=None,
        description=(
            "Stream key for the dead-letter queue. Defaults to "
            "`{job_queue_key}:dlq` when unset."
        ),
    )
    cancel_key_prefix: str = Field(
        default="agentflow:cancel:",
        description="Redis key prefix the API uses to signal cancel for a run id.",
    )
    cancel_ttl_seconds: int = 86400

    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"


@lru_cache
def get_settings() -> Settings:
    return Settings()
