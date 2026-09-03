"""Thread (L1 short memory) request/response schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.run import MessageRead


class ThreadCreate(BaseModel):
    agent_id: str
    title: str | None = Field(default=None, max_length=256)
    user_id: str | None = Field(default=None, max_length=128)
    project_id: str | None = Field(
        default=None,
        description="Optional; defaults to the agent's project_id when omitted.",
    )


class ThreadRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    project_id: str | None
    agent_id: str
    user_id: str | None
    title: str | None
    created_at: datetime
    updated_at: datetime


class ThreadMessageRead(MessageRead):
    """A message belonging to a run inside a thread."""

    run_id: str


class ThreadMessagePage(BaseModel):
    items: list[ThreadMessageRead]
    next_cursor: str | None = Field(
        default=None,
        description="Opaque cursor for older messages (created_at|index|id).",
    )
    has_more: bool = False
