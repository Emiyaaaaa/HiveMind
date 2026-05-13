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

    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"


@lru_cache
def get_settings() -> Settings:
    return Settings()
