"""Add per-step cost_usd for token/cost accounting."""

from alembic import op
import sqlalchemy as sa

revision = "0002_step_cost_usd"
down_revision = "0001"
branch_labels = None
depends_on = None


def _has_cost_usd() -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(column["name"] == "cost_usd" for column in inspector.get_columns("steps"))


def upgrade() -> None:
    # The initial schema (0001) already creates steps.cost_usd, so guard the
    # add to keep the chain idempotent for databases created from either point.
    if not _has_cost_usd():
        op.add_column("steps", sa.Column("cost_usd", sa.Float(), nullable=True))


def downgrade() -> None:
    if _has_cost_usd():
        op.drop_column("steps", "cost_usd")
