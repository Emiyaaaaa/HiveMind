"""Quota status and configuration payloads shared by every scope."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class QuotaConfigWrite(BaseModel):
    """Upsert body for a tenant or project quota."""

    period: str = "month"
    max_tokens: int | None = Field(default=None, ge=0)
    max_cost_usd: float | None = Field(default=None, ge=0)
    enforce: bool = True


class QuotaStatus(BaseModel):
    """Current period usage against one tenant, project, or agent quota."""

    scope: Literal["tenant", "project", "agent"]
    scope_id: str
    tenant_id: str | None = None
    project_id: str | None = None
    agent_id: str | None = None
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
