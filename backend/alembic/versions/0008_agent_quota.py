"""Add agent_quota_usage for Agent-level token/cost quotas.

Revision ID: 0008_agent_quota
Revises: 0007_attachments
Create Date: 2026-09-11
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0008_agent_quota"
down_revision = "0007_attachments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_quota_usage",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("agent_id", sa.String(26), nullable=False),
        sa.Column("period", sa.String(16), nullable=False),
        sa.Column("period_key", sa.String(32), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("run_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name="fk_agent_quota_usage_agent_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "agent_id", "period_key", name="uq_agent_quota_usage_period"
        ),
    )
    op.create_index(
        "ix_agent_quota_usage_tenant_id", "agent_quota_usage", ["tenant_id"]
    )
    op.create_index(
        "ix_agent_quota_usage_agent_id", "agent_quota_usage", ["agent_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_agent_quota_usage_agent_id", table_name="agent_quota_usage")
    op.drop_index("ix_agent_quota_usage_tenant_id", table_name="agent_quota_usage")
    op.drop_table("agent_quota_usage")
