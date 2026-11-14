"""Index bounded raw statistics queries; no aggregate tables exist."""
from alembic import op

revision = "0003_stats_indexes"
down_revision = "0002_alerts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_meter_readings_interval_start", "meter_readings", ["interval_start"])
    op.create_index("ix_outages_started_at", "outages", ["started_at"])


def downgrade() -> None:
    op.drop_index("ix_outages_started_at", table_name="outages")
    op.drop_index("ix_meter_readings_interval_start", table_name="meter_readings")
