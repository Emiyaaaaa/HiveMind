"""Add threads table and runs.thread_id for L1 conversation memory.

Revision ID: 0006_threads
Revises: 0005_project_scoped_rbac
Create Date: 2026-09-03
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0006_threads"
down_revision = "0005_project_scoped_rbac"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "threads",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("project_id", sa.String(26), nullable=True),
        sa.Column("agent_id", sa.String(26), nullable=False),
        sa.Column("user_id", sa.String(128), nullable=True),
        sa.Column("title", sa.String(256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agents.id"], name="fk_threads_agent_id", ondelete="CASCADE"
        ),
    )
    op.create_index("ix_threads_tenant_id", "threads", ["tenant_id"])
    op.create_index("ix_threads_tenant_agent", "threads", ["tenant_id", "agent_id"])
    op.create_index("ix_threads_project_id", "threads", ["project_id"])
    op.create_index("ix_threads_agent_id", "threads", ["agent_id"])

    op.add_column("runs", sa.Column("thread_id", sa.String(26), nullable=True))
    op.create_foreign_key(
        "fk_runs_thread_id",
        "runs",
        "threads",
        ["thread_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_runs_thread_id", "runs", ["thread_id"])


def downgrade() -> None:
    op.drop_index("ix_runs_thread_id", table_name="runs")
    op.drop_constraint("fk_runs_thread_id", "runs", type_="foreignkey")
    op.drop_column("runs", "thread_id")
    op.drop_index("ix_threads_agent_id", table_name="threads")
    op.drop_index("ix_threads_project_id", table_name="threads")
    op.drop_index("ix_threads_tenant_agent", table_name="threads")
    op.drop_index("ix_threads_tenant_id", table_name="threads")
    op.drop_table("threads")
