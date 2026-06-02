"""Add per-step cost_usd for token/cost accounting."""

from alembic import op
import sqlalchemy as sa

revision = "0002_step_cost_usd"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("steps", sa.Column("cost_usd", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("steps", "cost_usd")
