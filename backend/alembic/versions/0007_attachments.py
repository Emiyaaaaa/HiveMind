"""Add attachments table for multimodal file persistence.

Revision ID: 0007_attachments
Revises: 0006_threads
Create Date: 2026-09-04
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0007_attachments"
down_revision = "0006_threads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "attachments",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("run_id", sa.String(26), nullable=True),
        sa.Column("message_id", sa.String(26), nullable=True),
        sa.Column("media_type", sa.String(128), nullable=False),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name="fk_attachments_run_id", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["messages.id"],
            name="fk_attachments_message_id",
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_attachments_tenant_id", "attachments", ["tenant_id"])
    op.create_index("ix_attachments_run_id", "attachments", ["run_id"])
    op.create_index("ix_attachments_message_id", "attachments", ["message_id"])
    op.create_index(
        "ix_attachments_storage_key", "attachments", ["storage_key"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_attachments_storage_key", table_name="attachments")
    op.drop_index("ix_attachments_message_id", table_name="attachments")
    op.drop_index("ix_attachments_run_id", table_name="attachments")
    op.drop_index("ix_attachments_tenant_id", table_name="attachments")
    op.drop_table("attachments")
