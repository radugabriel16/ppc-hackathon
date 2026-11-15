"""Bounded catalog queries and demo provenance (history has independent migrations)."""
from alembic import op
import sqlalchemy as sa

revision = "0008_history_demo_indexes"
down_revision = "0007_forecast_calibration"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "demo_seed_entities",
        sa.Column("kind", sa.String(32), primary_key=True),
        sa.Column("id", sa.Uuid(), primary_key=True),
    )
    op.execute("""
        CREATE INDEX ix_files_created_id ON files(created_at DESC,id);
        CREATE INDEX ix_files_region_created_id ON files(region_id,created_at DESC,id);
        CREATE INDEX ix_files_category_created_id ON files(category,created_at DESC,id);
        CREATE INDEX ix_files_subregion_created_id ON files(subregion_id,created_at DESC,id);
        CREATE INDEX ix_readings_end_id ON meter_readings(interval_end DESC,id);
        CREATE INDEX ix_readings_meter_end_id ON meter_readings(meter_id,interval_end DESC,id);
        CREATE INDEX ix_readings_meter_start ON meter_readings(meter_id,interval_start);
        CREATE INDEX ix_cases_opened_id ON connection_cases(opened_at,id);
        CREATE INDEX ix_cases_status_id ON connection_cases(status,id);
        CREATE INDEX ix_meters_subregion_code ON meters(subregion_id,external_code);
        CREATE INDEX ix_issues_operational_created ON map_issues(created_at DESC,id)
            WHERE NOT is_historical;
        CREATE INDEX ix_issues_operational_region_created ON map_issues(region_id,created_at DESC,id)
            WHERE NOT is_historical;
        CREATE INDEX ix_issues_operational_segment_created ON map_issues(subregion_id,created_at DESC,id)
            WHERE NOT is_historical;
    """)


def downgrade():
    for name in (
        "ix_files_created_id", "ix_files_region_created_id", "ix_files_category_created_id",
        "ix_files_subregion_created_id", "ix_readings_end_id", "ix_readings_meter_end_id",
        "ix_readings_meter_start", "ix_cases_opened_id", "ix_cases_status_id",
        "ix_meters_subregion_code", "ix_issues_operational_created",
        "ix_issues_operational_region_created", "ix_issues_operational_segment_created",
    ):
        op.execute(f"DROP INDEX {name}")
    op.drop_table("demo_seed_entities")
