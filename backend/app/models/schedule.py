"""Recurring Run schedules claimed by the worker sweeper."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from ulid import ULID

from app.db.base import Base
from app.models.agent import DEFAULT_TENANT_ID


def _ulid() -> str:
    return str(ULID())


class RunSchedule(Base):
    """A cron or interval template that creates Runs when due.

    Exactly one of ``cron`` / ``interval_seconds`` is set. The worker sweeper
    claims rows where ``enabled`` and ``next_run_at <= now``.
    """

    __tablename__ = "run_schedules"
    __table_args__ = (
        Index("ix_run_schedules_tenant_id", "tenant_id"),
        Index("ix_run_schedules_due", "enabled", "next_run_at"),
    )

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=_ulid)
    tenant_id: Mapped[str] = mapped_column(
        String(64), default=DEFAULT_TENANT_ID, nullable=False
    )
    project_id: Mapped[str | None] = mapped_column(String(26), nullable=True)
    agent_id: Mapped[str] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    cron: Mapped[str | None] = mapped_column(String(128), nullable=True)
    interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    input: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    adapter: Mapped[str | None] = mapped_column(String(64), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    next_run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_run_id: Mapped[str | None] = mapped_column(String(26), nullable=True)

    agent: Mapped["Agent"] = relationship()  # noqa: F821
