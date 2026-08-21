"""Add tenant_id to agents and runs for multi-tenant isolation.

Revision ID: 0004_tenant_id
Revises: 0003_agent_versions
Create Date: 2026-08-21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_tenant_id"
down_revision = "0003_agent_versions"
branch_labels = None
depends_on = None

_DEFAULT = "default"


def _drop_agents_name_unique() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for uc in inspector.get_unique_constraints("agents"):
        cols = list(uc.get("column_names") or [])
        if cols == ["name"]:
            op.drop_constraint(uc["name"], "agents", type_="unique")
            return
    # Fallback for dialects that only expose the unique as an index.
    for ix in inspector.get_indexes("agents"):
        if ix.get("unique") and list(ix.get("column_names") or []) == ["name"]:
            op.drop_index(ix["name"], table_name="agents")
            return


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column(
            "tenant_id",
            sa.String(64),
            nullable=False,
            server_default=_DEFAULT,
        ),
    )
    op.add_column(
        "runs",
        sa.Column(
            "tenant_id",
            sa.String(64),
            nullable=False,
            server_default=_DEFAULT,
        ),
    )

    _drop_agents_name_unique()
    op.create_unique_constraint(
        "uq_agents_tenant_name", "agents", ["tenant_id", "name"]
    )

    op.create_index("ix_agents_tenant_id", "agents", ["tenant_id"])
    op.create_index("ix_runs_tenant_id", "runs", ["tenant_id"])
    op.create_index(
        "ix_runs_tenant_created", "runs", ["tenant_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_runs_tenant_created", table_name="runs")
    op.drop_index("ix_runs_tenant_id", table_name="runs")
    op.drop_index("ix_agents_tenant_id", table_name="agents")
    op.drop_constraint("uq_agents_tenant_name", "agents", type_="unique")
    op.create_unique_constraint("agents_name_key", "agents", ["name"])
    op.drop_column("runs", "tenant_id")
    op.drop_column("agents", "tenant_id")
