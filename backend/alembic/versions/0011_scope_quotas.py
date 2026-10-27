"""Add tenant/project quota config and usage, and project_id on agent usage.

Revision ID: 0011_scope_quotas
Revises: 0010_memory_items
Create Date: 2026-10-27
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0011_scope_quotas"
down_revision = "0010_memory_items"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_quota_usage",
        sa.Column("project_id", sa.String(26), nullable=True),
    )
    op.execute(
        """
        UPDATE agent_quota_usage
        SET project_id = (
            SELECT agents.project_id
            FROM agents
            WHERE agents.id = agent_quota_usage.agent_id
        )
        """
    )
    op.create_foreign_key(
        "fk_agent_quota_usage_project_id",
        "agent_quota_usage",
        "projects",
        ["project_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_agent_quota_usage_project_id",
        "agent_quota_usage",
        ["project_id"],
    )

    op.create_table(
        "tenant_quota_configs",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("period", sa.String(16), nullable=False),
        sa.Column("max_tokens", sa.Integer(), nullable=True),
        sa.Column("max_cost_usd", sa.Float(), nullable=True),
        sa.Column("enforce", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", name="uq_tenant_quota_configs_tenant"),
    )
    op.create_table(
        "project_quota_configs",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("project_id", sa.String(26), nullable=False),
        sa.Column("period", sa.String(16), nullable=False),
        sa.Column("max_tokens", sa.Integer(), nullable=True),
        sa.Column("max_cost_usd", sa.Float(), nullable=True),
        sa.Column("enforce", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_project_quota_configs_project_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("project_id", name="uq_project_quota_configs_project"),
    )
    op.create_index(
        "ix_project_quota_configs_tenant_id",
        "project_quota_configs",
        ["tenant_id"],
    )

    op.create_table(
        "tenant_quota_usage",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("period", sa.String(16), nullable=False),
        sa.Column("period_key", sa.String(32), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("run_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "period_key", name="uq_tenant_quota_usage_period"
        ),
    )
    op.create_index(
        "ix_tenant_quota_usage_tenant_id", "tenant_quota_usage", ["tenant_id"]
    )

    op.create_table(
        "project_quota_usage",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("project_id", sa.String(26), nullable=False),
        sa.Column("period", sa.String(16), nullable=False),
        sa.Column("period_key", sa.String(32), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("run_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_project_quota_usage_project_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "project_id", "period_key", name="uq_project_quota_usage_period"
        ),
    )
    op.create_index(
        "ix_project_quota_usage_tenant_id", "project_quota_usage", ["tenant_id"]
    )
    op.create_index(
        "ix_project_quota_usage_project_id", "project_quota_usage", ["project_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_project_quota_usage_project_id", table_name="project_quota_usage")
    op.drop_index("ix_project_quota_usage_tenant_id", table_name="project_quota_usage")
    op.drop_table("project_quota_usage")
    op.drop_index("ix_tenant_quota_usage_tenant_id", table_name="tenant_quota_usage")
    op.drop_table("tenant_quota_usage")
    op.drop_index(
        "ix_project_quota_configs_tenant_id", table_name="project_quota_configs"
    )
    op.drop_table("project_quota_configs")
    op.drop_table("tenant_quota_configs")
    op.drop_index("ix_agent_quota_usage_project_id", table_name="agent_quota_usage")
    op.drop_constraint(
        "fk_agent_quota_usage_project_id", "agent_quota_usage", type_="foreignkey"
    )
    op.drop_column("agent_quota_usage", "project_id")
