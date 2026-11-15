"""Index catalog readings in server ingestion order."""
from alembic import op

revision = "0012_meter_readings_received"
down_revision = "0011_customer_cnp"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("ix_meter_readings_received_id", "meter_readings", ["received_at", "id"])
    op.create_index(
        "ix_meter_readings_meter_received_id", "meter_readings",
        ["meter_id", "received_at", "id"],
    )


def downgrade():
    op.drop_index("ix_meter_readings_meter_received_id", table_name="meter_readings")
    op.drop_index("ix_meter_readings_received_id", table_name="meter_readings")
