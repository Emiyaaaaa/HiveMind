"""Durable per-agent quota usage counters."""

from __future__ import annotations

from sqlalchemy import Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from ulid import ULID

from app.db.base import Base
from app.models.agent import DEFAULT_TENANT_ID


def _ulid() -> str:
    return str(ULID())


class AgentQuotaUsage(Base):
    """Accumulated token/cost usage for one agent in one quota period bucket."""

    __tablename__ = "agent_quota_usage"
    __table_args__ = (
        UniqueConstraint("agent_id", "period_key", name="uq_agent_quota_usage_period"),
        Index("ix_agent_quota_usage_tenant_id", "tenant_id"),
        Index("ix_agent_quota_usage_agent_id", "agent_id"),
    )

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=_ulid)
    tenant_id: Mapped[str] = mapped_column(
        String(64), default=DEFAULT_TENANT_ID, nullable=False
    )
    agent_id: Mapped[str] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    period: Mapped[str] = mapped_column(String(16), nullable=False, default="month")
    period_key: Mapped[str] = mapped_column(String(32), nullable=False)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    run_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
