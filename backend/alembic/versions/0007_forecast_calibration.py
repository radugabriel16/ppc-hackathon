"""Track history-calibrated defaults separately from explicit capacity overrides."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0007_forecast_calibration"
down_revision = "0006_operational_forecasts"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("segment_thresholds", sa.Column(
        "source", sa.String(32), nullable=False, server_default="UNCONFIGURED",
    ))
    op.add_column("segment_thresholds", sa.Column("calibration", JSONB(), nullable=True))
    op.execute("""
        UPDATE segment_thresholds t SET source='MANUAL'
        WHERE daily_energy_kwh != 400 OR EXISTS (
            SELECT 1 FROM audit_events a
            WHERE a.action='SEGMENT_THRESHOLD_UPDATED' AND a.entity_id=t.segment_id
        )
    """)


def downgrade():
    op.drop_column("segment_thresholds", "calibration")
    op.drop_column("segment_thresholds", "source")
