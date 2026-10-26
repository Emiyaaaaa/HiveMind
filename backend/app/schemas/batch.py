from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class BatchItemCreate(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BatchCreate(BaseModel):
    agent_id: str
    items: list[BatchItemCreate] = Field(min_length=1, max_length=100)
    adapter: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    agent_id: str
    status: str
    total: int
    completed: int
    run_ids: list[str]
    created_at: datetime
