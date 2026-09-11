"""Add run_schedules and run_batches for timed and fan-out Runs.

Revision ID: 0008_schedules_batches
Revises: 0007_attachments
Create Date: 2026-09-11
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0008_schedules_batches"
down_revision = "0007_attachments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "run_schedules",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("project_id", sa.String(26), nullable=True),
        sa.Column("agent_id", sa.String(26), nullable=False),
        sa.Column("name", sa.String(256), nullable=True),
        sa.Column("cron", sa.String(128), nullable=True),
        sa.Column("interval_seconds", sa.Integer(), nullable=True),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="UTC"),
        sa.Column("input", sa.JSON(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("adapter", sa.String(64), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_id", sa.String(26), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name="fk_run_schedules_agent_id",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_run_schedules_tenant_id", "run_schedules", ["tenant_id"])
    op.create_index("ix_run_schedules_agent_id", "run_schedules", ["agent_id"])
    op.create_index("ix_run_schedules_next_run_at", "run_schedules", ["next_run_at"])
    op.create_index(
        "ix_run_schedules_due", "run_schedules", ["enabled", "next_run_at"]
    )

    op.create_table(
        "run_batches",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("project_id", sa.String(26), nullable=True),
        sa.Column("agent_id", sa.String(26), nullable=False),
        sa.Column("run_ids", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name="fk_run_batches_agent_id",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_run_batches_tenant_id", "run_batches", ["tenant_id"])
    op.create_index("ix_run_batches_agent_id", "run_batches", ["agent_id"])


def downgrade() -> None:
    op.drop_index("ix_run_batches_agent_id", table_name="run_batches")
    op.drop_index("ix_run_batches_tenant_id", table_name="run_batches")
    op.drop_table("run_batches")
    op.drop_index("ix_run_schedules_due", table_name="run_schedules")
    op.drop_index("ix_run_schedules_next_run_at", table_name="run_schedules")
    op.drop_index("ix_run_schedules_agent_id", table_name="run_schedules")
    op.drop_index("ix_run_schedules_tenant_id", table_name="run_schedules")
    op.drop_table("run_schedules")
