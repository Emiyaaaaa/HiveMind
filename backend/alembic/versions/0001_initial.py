"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-13
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agents",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("description", sa.String(1024), nullable=True),
        sa.Column("adapter", sa.String(64), nullable=False),
        sa.Column("config", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "runs",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column(
            "agent_id",
            sa.String(26),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("adapter", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, index=True),
        sa.Column("input", sa.JSON, nullable=False),
        sa.Column("output", sa.JSON, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("metadata", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "steps",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(26),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("index", sa.Integer, nullable=False),
        sa.Column("node", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("input", sa.JSON, nullable=False),
        sa.Column("output", sa.JSON, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("tokens_in", sa.Integer, nullable=True),
        sa.Column("tokens_out", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_steps_run_index", "steps", ["run_id", "index"])

    op.create_table(
        "messages",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(26),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "step_id",
            sa.String(26),
            sa.ForeignKey("steps.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("index", sa.Integer, nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("name", sa.String(128), nullable=True),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("tool_call_id", sa.String(128), nullable=True),
        sa.Column("extra", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_messages_run_index", "messages", ["run_id", "index"])

    op.create_table(
        "tool_calls",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column(
            "step_id",
            sa.String(26),
            sa.ForeignKey("steps.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("arguments", sa.JSON, nullable=False),
        sa.Column("result", sa.JSON, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_tool_calls_step", "tool_calls", ["step_id"])

    op.create_table(
        "checkpoints",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(26),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("index", sa.Integer, nullable=False),
        sa.Column("label", sa.String(128), nullable=True),
        sa.Column("state", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_checkpoints_run_index", "checkpoints", ["run_id", "index"])


def downgrade() -> None:
    op.drop_index("ix_checkpoints_run_index", table_name="checkpoints")
    op.drop_table("checkpoints")
    op.drop_index("ix_tool_calls_step", table_name="tool_calls")
    op.drop_table("tool_calls")
    op.drop_index("ix_messages_run_index", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_steps_run_index", table_name="steps")
    op.drop_table("steps")
    op.drop_table("runs")
    op.drop_table("agents")
