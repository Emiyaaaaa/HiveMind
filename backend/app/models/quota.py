"""Tenant, project, and agent quota configuration and usage counters."""

from __future__ import annotations

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from ulid import ULID

from app.db.base import Base
from app.models.agent import DEFAULT_TENANT_ID


def _ulid() -> str:
    return str(ULID())


class TenantQuotaConfig(Base):
    """Token/cost limits for one organization. One row per tenant."""

    __tablename__ = "tenant_quota_configs"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_tenant_quota_configs_tenant"),
    )

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=_ulid)
    tenant_id: Mapped[str] = mapped_column(
        String(64), default=DEFAULT_TENANT_ID, nullable=False
    )
    period: Mapped[str] = mapped_column(String(16), nullable=False, default="month")
    max_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    enforce: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ProjectQuotaConfig(Base):
    """Token/cost limits for one project. One row per project."""

    __tablename__ = "project_quota_configs"
    __table_args__ = (
        UniqueConstraint("project_id", name="uq_project_quota_configs_project"),
        Index("ix_project_quota_configs_tenant_id", "tenant_id"),
    )

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=_ulid)
    tenant_id: Mapped[str] = mapped_column(
        String(64), default=DEFAULT_TENANT_ID, nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    period: Mapped[str] = mapped_column(String(16), nullable=False, default="month")
    max_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    enforce: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class TenantQuotaUsage(Base):
    """Accumulated token/cost usage for one tenant in one quota period bucket."""

    __tablename__ = "tenant_quota_usage"
    __table_args__ = (
        UniqueConstraint("tenant_id", "period_key", name="uq_tenant_quota_usage_period"),
        Index("ix_tenant_quota_usage_tenant_id", "tenant_id"),
    )

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=_ulid)
    tenant_id: Mapped[str] = mapped_column(
        String(64), default=DEFAULT_TENANT_ID, nullable=False
    )
    period: Mapped[str] = mapped_column(String(16), nullable=False, default="month")
    period_key: Mapped[str] = mapped_column(String(32), nullable=False)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    run_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ProjectQuotaUsage(Base):
    """Accumulated token/cost usage for one project in one quota period bucket."""

    __tablename__ = "project_quota_usage"
    __table_args__ = (
        UniqueConstraint("project_id", "period_key", name="uq_project_quota_usage_period"),
        Index("ix_project_quota_usage_tenant_id", "tenant_id"),
        Index("ix_project_quota_usage_project_id", "project_id"),
    )

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=_ulid)
    tenant_id: Mapped[str] = mapped_column(
        String(64), default=DEFAULT_TENANT_ID, nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    period: Mapped[str] = mapped_column(String(16), nullable=False, default="month")
    period_key: Mapped[str] = mapped_column(String(32), nullable=False)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    run_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class AgentQuotaUsage(Base):
    """Accumulated token/cost usage for one agent in one quota period bucket."""

    __tablename__ = "agent_quota_usage"
    __table_args__ = (
        UniqueConstraint("agent_id", "period_key", name="uq_agent_quota_usage_period"),
        Index("ix_agent_quota_usage_tenant_id", "tenant_id"),
        Index("ix_agent_quota_usage_project_id", "project_id"),
        Index("ix_agent_quota_usage_agent_id", "agent_id"),
    )

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=_ulid)
    tenant_id: Mapped[str] = mapped_column(
        String(64), default=DEFAULT_TENANT_ID, nullable=False
    )
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
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
