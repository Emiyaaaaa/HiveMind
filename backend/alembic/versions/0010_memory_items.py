"""Add memory_items for episodic summaries.

Revision ID: 0010_memory_items
Revises: 0009_run_audit
Create Date: 2026-09-21
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0010_memory_items"
down_revision = "0009_run_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "memory_items",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("project_id", sa.String(26), nullable=True),
        sa.Column("agent_id", sa.String(26), nullable=True),
        sa.Column("thread_id", sa.String(26), nullable=True),
        sa.Column("user_id", sa.String(128), nullable=True),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_run_id", sa.String(26), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_run_id"],
            ["runs.id"],
            name="fk_memory_items_source_run_id",
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_memory_items_tenant", "memory_items", ["tenant_id"])
    op.create_index(
        "ix_memory_items_tenant_thread", "memory_items", ["tenant_id", "thread_id"]
    )
    op.create_index("ix_memory_items_source_run", "memory_items", ["source_run_id"])


def downgrade() -> None:
    op.drop_index("ix_memory_items_source_run", table_name="memory_items")
    op.drop_index("ix_memory_items_tenant_thread", table_name="memory_items")
    op.drop_index("ix_memory_items_tenant", table_name="memory_items")
    op.drop_table("memory_items")
