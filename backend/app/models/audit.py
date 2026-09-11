"""Append-only audit trail for privileged Run control actions."""

from __future__ import annotations

from typing import Any

from sqlalchemy import ForeignKey, Index, JSON, String
from sqlalchemy.orm import Mapped, mapped_column
from ulid import ULID

from app.db.base import Base
from app.models.agent import DEFAULT_TENANT_ID


def _ulid() -> str:
    return str(ULID())


class RunAuditEvent(Base):
    """Who cancelled or resumed a run, and with what context.

    Rows are append-only governance records. They survive working-memory
    erasure (messages/checkpoints) so operators can still answer
    "who cancelled this?" after a GDPR wipe of transcript data.
    """

    __tablename__ = "run_audit_events"
    __table_args__ = (
        Index("ix_run_audit_events_tenant_id", "tenant_id"),
        Index("ix_run_audit_events_run_id", "run_id"),
        Index("ix_run_audit_events_tenant_created", "tenant_id", "created_at"),
        Index("ix_run_audit_events_run_created", "run_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=_ulid)
    tenant_id: Mapped[str] = mapped_column(
        String(64), default=DEFAULT_TENANT_ID, nullable=False
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_subject: Mapped[str] = mapped_column(String(256), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
