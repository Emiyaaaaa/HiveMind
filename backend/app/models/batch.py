"""Fan-out Run batches: many inputs → many independent Runs."""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from ulid import ULID

from app.db.base import Base
from app.models.agent import DEFAULT_TENANT_ID


def _ulid() -> str:
    return str(ULID())


class RunBatch(Base):
    """Ordered list of Run ids created together for one Agent."""

    __tablename__ = "run_batches"
    __table_args__ = (Index("ix_run_batches_tenant_id", "tenant_id"),)

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=_ulid)
    tenant_id: Mapped[str] = mapped_column(
        String(64), default=DEFAULT_TENANT_ID, nullable=False
    )
    project_id: Mapped[str | None] = mapped_column(String(26), nullable=True)
    agent_id: Mapped[str] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True
    )
    run_ids: Mapped[list[Any]] = mapped_column(JSON, default=list)

    agent: Mapped["Agent"] = relationship()  # noqa: F821
