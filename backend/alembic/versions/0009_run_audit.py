"""Add run_audit_events for cancel/resume governance trail.

Revision ID: 0009_run_audit
Revises: 0008_agent_quota, 0008_schedules_batches
Create Date: 2026-09-11
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0009_run_audit"
down_revision = ("0008_agent_quota", "0008_schedules_batches")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "run_audit_events",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("run_id", sa.String(26), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("actor_subject", sa.String(256), nullable=False),
        sa.Column("actor_role", sa.String(32), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name="fk_run_audit_events_run_id", ondelete="CASCADE"
        ),
    )
    op.create_index("ix_run_audit_events_tenant_id", "run_audit_events", ["tenant_id"])
    op.create_index("ix_run_audit_events_run_id", "run_audit_events", ["run_id"])
    op.create_index(
        "ix_run_audit_events_tenant_created",
        "run_audit_events",
        ["tenant_id", "created_at"],
    )
    op.create_index(
        "ix_run_audit_events_run_created",
        "run_audit_events",
        ["run_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_run_audit_events_run_created", table_name="run_audit_events")
    op.drop_index("ix_run_audit_events_tenant_created", table_name="run_audit_events")
    op.drop_index("ix_run_audit_events_run_id", table_name="run_audit_events")
    op.drop_index("ix_run_audit_events_tenant_id", table_name="run_audit_events")
    op.drop_table("run_audit_events")
