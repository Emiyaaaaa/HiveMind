"""Episodic memory items (L2). One summary row per finished Run."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from ulid import ULID

from app.db.base import Base
from app.models.agent import DEFAULT_TENANT_ID


def _ulid() -> str:
    return str(ULID())


class MemoryItem(Base):
    """A scoped memory row. M2 writes ``kind=episode``; other kinds are manual."""

    __tablename__ = "memory_items"
    __table_args__ = (
        Index("ix_memory_items_tenant", "tenant_id"),
        Index("ix_memory_items_tenant_thread", "tenant_id", "thread_id"),
        Index("ix_memory_items_source_run", "source_run_id"),
    )

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=_ulid)
    tenant_id: Mapped[str] = mapped_column(
        String(64), default=DEFAULT_TENANT_ID, nullable=False
    )
    project_id: Mapped[str | None] = mapped_column(String(26), nullable=True)
    agent_id: Mapped[str | None] = mapped_column(String(26), nullable=True)
    thread_id: Mapped[str | None] = mapped_column(String(26), nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"), nullable=True
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
