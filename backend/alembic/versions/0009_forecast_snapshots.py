"""Persist real daily model results instead of recomputing two years on every click."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0009_forecast_snapshots"
down_revision = "0008_history_demo_indexes"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "forecast_snapshots",
        sa.Column("asset_id", sa.Uuid(), sa.ForeignKey("network_assets.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("origin", sa.Date(), primary_key=True),
        sa.Column("result", JSONB(), nullable=False),
    )


def downgrade():
    op.drop_table("forecast_snapshots")
