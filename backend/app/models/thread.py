"""Conversation threads that group Runs for short-term (L1) memory."""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from ulid import ULID

from app.db.base import Base
from app.models.agent import DEFAULT_TENANT_ID


def _ulid() -> str:
    return str(ULID())


class Thread(Base):
    """A multi-run conversation scoped to a tenant / agent.

    Runs optionally reference a thread via ``Run.thread_id``. Cross-run
    transcripts are assembled by joining messages of all runs in the thread.
    """

    __tablename__ = "threads"
    __table_args__ = (
        Index("ix_threads_tenant_id", "tenant_id"),
        Index("ix_threads_tenant_agent", "tenant_id", "agent_id"),
        Index("ix_threads_project_id", "project_id"),
    )

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=_ulid)
    tenant_id: Mapped[str] = mapped_column(
        String(64), default=DEFAULT_TENANT_ID, nullable=False
    )
    project_id: Mapped[str | None] = mapped_column(String(26), nullable=True)
    agent_id: Mapped[str] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    title: Mapped[str | None] = mapped_column(String(256), nullable=True)

    agent: Mapped["Agent"] = relationship()  # noqa: F821
    runs: Mapped[list["Run"]] = relationship(  # noqa: F821
        back_populates="thread",
        order_by="Run.created_at",
    )
