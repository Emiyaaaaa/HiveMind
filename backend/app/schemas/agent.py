from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None
    adapter: str = "echo"
    config: dict[str, Any] = Field(default_factory=dict)


class AgentUpdate(BaseModel):
    """Partial update. Bumps ``version`` when adapter/config/description change."""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    adapter: str | None = None
    config: dict[str, Any] | None = None
    note: str | None = Field(
        default=None,
        max_length=512,
        description="Optional note stored on the new version snapshot.",
    )


class AgentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None
    adapter: str
    config: dict[str, Any]
    version: int
    created_at: datetime
    updated_at: datetime


class AgentVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    agent_id: str
    version: int
    description: str | None
    adapter: str
    config: dict[str, Any]
    note: str | None
    created_at: datetime


class AgentVersionDiff(BaseModel):
    from_version: int
    to_version: int
    adapter: dict[str, Any] | None = None
    description: dict[str, Any] | None = None
    config: dict[str, Any]
