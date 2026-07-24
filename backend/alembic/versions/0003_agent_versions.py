"""Add agent.version and agent_versions history table."""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op
from ulid import ULID

revision = "0003_agent_versions"
down_revision = "0002_step_cost_usd"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_table(
        "agent_versions",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column(
            "agent_id",
            sa.String(26),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(1024), nullable=True),
        sa.Column("adapter", sa.String(64), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("note", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "agent_id", "version", name="uq_agent_versions_agent_version"
        ),
    )
    op.create_index(
        "ix_agent_versions_agent_id", "agent_versions", ["agent_id"]
    )

    conn = op.get_bind()
    agents = conn.execute(
        sa.text(
            "SELECT id, description, adapter, config, created_at, updated_at "
            "FROM agents"
        )
    ).mappings()
    insert = sa.text(
        "INSERT INTO agent_versions "
        "(id, agent_id, version, description, adapter, config, note, "
        "created_at, updated_at) "
        "VALUES (:id, :agent_id, 1, :description, :adapter, :config, "
        ":note, :created_at, :updated_at)"
    )
    for row in agents:
        config = row["config"]
        if isinstance(config, str):
            config = json.loads(config)
        conn.execute(
            insert,
            {
                "id": str(ULID()),
                "agent_id": row["id"],
                "description": row["description"],
                "adapter": row["adapter"],
                "config": json.dumps(config) if conn.dialect.name == "sqlite" else config,
                "note": "initial",
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            },
        )

    op.alter_column("agents", "version", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_agent_versions_agent_id", table_name="agent_versions")
    op.drop_table("agent_versions")
    op.drop_column("agents", "version")
