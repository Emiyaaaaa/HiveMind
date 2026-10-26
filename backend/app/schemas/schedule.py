from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ScheduleCreate(BaseModel):
    agent_id: str
    name: str | None = None
    cron: str | None = None
    interval_seconds: int | None = Field(default=None, ge=60)
    timezone: str = "UTC"
    input: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    adapter: str | None = None
    enabled: bool = True

    @model_validator(mode="after")
    def _exactly_one_timing(self) -> ScheduleCreate:
        if (self.cron is None) == (self.interval_seconds is None):
            raise ValueError("Provide exactly one of cron or interval_seconds")
        return self


class ScheduleUpdate(BaseModel):
    name: str | None = None
    cron: str | None = None
    interval_seconds: int | None = Field(default=None, ge=60)
    timezone: str | None = None
    input: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    adapter: str | None = None
    enabled: bool | None = None


class ScheduleTrigger(BaseModel):
    advance: bool = False


class ScheduleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    agent_id: str
    name: str | None
    cron: str | None
    interval_seconds: int | None
    timezone: str
    input: dict[str, Any]
    metadata: dict[str, Any] = Field(validation_alias="metadata_")
    adapter: str | None
    enabled: bool
    next_run_at: datetime
    last_run_at: datetime | None
    last_run_id: str | None
    created_at: datetime
    updated_at: datetime
