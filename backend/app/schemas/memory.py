"""Memory item request/response schemas."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class MemoryCreate(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    kind: str = "fact"
    scope: str | None = None
    agent_id: str | None = None
    thread_id: str | None = None
    project_id: str | None = None
    user_id: str | None = None
    expires_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryRead(BaseModel):
    id: str
    tenant_id: str
    project_id: str | None
    agent_id: str | None
    thread_id: str | None
    user_id: str | None
    scope: str
    kind: str
    content: str
    source_run_id: str | None
    metadata: dict[str, Any]
    expires_at: datetime | None
    created_at: datetime
    score: float | None = None


def memory_read(item: Any, score: float | None = None) -> MemoryRead:
    return MemoryRead(
        id=item.id,
        tenant_id=item.tenant_id,
        project_id=item.project_id,
        agent_id=item.agent_id,
        thread_id=item.thread_id,
        user_id=item.user_id,
        scope=item.scope,
        kind=item.kind,
        content=item.content,
        source_run_id=item.source_run_id,
        metadata=dict(item.metadata_ or {}),
        expires_at=item.expires_at,
        created_at=item.created_at,
        score=score,
    )
