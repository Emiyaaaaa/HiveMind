from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None
    adapter: str = "echo"
    config: dict[str, Any] = Field(default_factory=dict)
    project_id: str | None = None


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
    tenant_id: str
    project_id: str | None
    name: str
    description: str | None
    adapter: str
    config: dict[str, Any]
    version: int
    created_at: datetime
    updated_at: datetime


class AgentQuotaStatus(BaseModel):
    """Current period usage against the agent's configured token/cost quota."""

    agent_id: str
    active: bool
    enforce: bool = False
    period: Literal["day", "week", "month"] | None = None
    period_key: str | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None
    max_tokens: int | None = None
    max_cost_usd: float | None = None
    used_tokens: int = 0
    used_tokens_in: int = 0
    used_tokens_out: int = 0
    used_cost_usd: float = 0.0
    run_count: int = 0
    remaining_tokens: int | None = None
    remaining_cost_usd: float | None = None
    exceeded: bool = False


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
