"""Schemas for Run cancel/resume audit events."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class RunAuditEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    run_id: str
    action: Literal["cancel", "resume"]
    actor_subject: str
    actor_role: str
    detail: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
