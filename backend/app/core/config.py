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

    job_queue_key: str = Field(
        default="agentflow:jobs:runs",
        description="Redis LIST key the API pushes run jobs to and the worker BRPOPs from.",
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
