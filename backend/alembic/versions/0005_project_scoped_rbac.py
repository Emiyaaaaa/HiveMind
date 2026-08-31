"""Add projects and persist the project scope on agents and runs.

Revision ID: 0005_project_scoped_rbac
Revises: 0004_tenant_id
Create Date: 2026-08-31
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0005_project_scoped_rbac"
down_revision = "0004_tenant_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.String(1024), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "name", name="uq_projects_tenant_name"),
    )
    op.create_index("ix_projects_tenant_id", "projects", ["tenant_id"])
    op.add_column("agents", sa.Column("project_id", sa.String(26), nullable=True))
    op.create_foreign_key(
        "fk_agents_project_id", "agents", "projects", ["project_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index("ix_agents_project_id", "agents", ["project_id"])
    op.add_column("runs", sa.Column("project_id", sa.String(26), nullable=True))
    op.create_index("ix_runs_project_id", "runs", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_runs_project_id", table_name="runs")
    op.drop_column("runs", "project_id")
    op.drop_index("ix_agents_project_id", table_name="agents")
    op.drop_constraint("fk_agents_project_id", "agents", type_="foreignkey")
    op.drop_column("agents", "project_id")
    op.drop_index("ix_projects_tenant_id", table_name="projects")
    op.drop_table("projects")
