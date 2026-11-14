"""Start a new operational epoch without deleting issue or meter history."""
from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geometry

revision = "0006_operational_forecasts"
down_revision = "0005_region_geometry"
branch_labels = None
depends_on = None


def upgrade():
    issue_type = sa.Enum(
        "OUTAGE_REPORT", "OUTAGE_VIDEO", "DRONE_DETECTED", "ML_FORECAST",
        "MISSING_DOCUMENTS", name="issue_type",
    )
    issue_type.create(op.get_bind())
    op.add_column("map_issues", sa.Column("is_historical", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("map_issues", sa.Column("type", issue_type, nullable=False, server_default="OUTAGE_REPORT"))
    op.add_column("map_issues", sa.Column("title", sa.Text(), nullable=False, server_default="Outage report"))
    for name, table in (
        ("region_id", "regions"), ("file_id", "files"), ("meter_id", "meters"),
        ("client_id", "clients"), ("case_id", "connection_cases"),
    ):
        op.add_column("map_issues", sa.Column(name, sa.Uuid(), sa.ForeignKey(f"{table}.id")))
        op.create_index(f"ix_map_issues_{name}", "map_issues", [name])
    op.add_column("map_issues", sa.Column("forecast_date", sa.Date()))
    op.create_index("ix_map_issues_is_historical", "map_issues", ["is_historical"])
    op.execute("""
        UPDATE map_issues i SET is_historical=true,
            region_id=coalesce(s.region_id,a.region_id),
            title='Historical outage report: ' || a.name,
            description=coalesce(nullif(i.description,''),'Historical operator outage report')
        FROM network_assets a LEFT JOIN subregions s ON s.id=a.subregion_id
        WHERE a.id=i.asset_id;
        CREATE UNIQUE INDEX uq_forecast_issue_segment_date
            ON map_issues(subregion_id,forecast_date) WHERE type='ML_FORECAST';
        CREATE UNIQUE INDEX uq_missing_documents_issue_case
            ON map_issues(case_id) WHERE type='MISSING_DOCUMENTS' AND NOT is_historical;
    """)
    op.add_column("meters", sa.Column("location", Geometry("POINT", srid=4326)))
    op.execute("""
        UPDATE meters m SET location=ST_PointOnSurface(a.geometry)
            FROM network_assets a WHERE a.id=m.asset_id;
        CREATE OR REPLACE FUNCTION assign_geography() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_TABLE_NAME='network_assets' THEN
                NEW.subregion_id := covered_subregion(ST_PointOnSurface(NEW.geometry),NEW.region_id);
            ELSIF TG_TABLE_NAME='meters' THEN
                IF NEW.location IS NULL THEN
                    SELECT ST_PointOnSurface(geometry) INTO NEW.location
                    FROM network_assets WHERE id=NEW.asset_id;
                END IF;
                SELECT covered_subregion(NEW.location,region_id) INTO NEW.subregion_id
                FROM network_assets WHERE id=NEW.asset_id;
            ELSIF TG_TABLE_NAME='map_issues' THEN
                NEW.subregion_id := covered_subregion(NEW.location);
                SELECT region_id INTO NEW.region_id FROM subregions WHERE id=NEW.subregion_id;
                IF NEW.region_id IS NULL THEN
                    SELECT region_id INTO NEW.region_id FROM network_assets WHERE id=NEW.asset_id;
                END IF;
            ELSE
                SELECT covered_subregion(ST_PointOnSurface(geometry),id)
                INTO NEW.subregion_id FROM regions WHERE id=NEW.region_id;
            END IF;
            RETURN NEW;
        END $$;
        DROP TRIGGER assign_meter_geography ON meters;
        CREATE TRIGGER assign_meter_geography BEFORE INSERT OR UPDATE OF asset_id,location
            ON meters FOR EACH ROW EXECUTE FUNCTION assign_geography();
    """)
    op.create_table(
        "segment_thresholds",
        sa.Column("segment_id", sa.Uuid(), sa.ForeignKey("subregions.id"), primary_key=True),
        sa.Column("daily_energy_kwh", sa.Numeric(), nullable=False),
        sa.CheckConstraint("daily_energy_kwh > 0", name="ck_segment_threshold_positive"),
    )
    op.create_table(
        "forecast_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("region_id", sa.Uuid(), sa.ForeignKey("regions.id")),
        sa.Column("segment_id", sa.Uuid(), sa.ForeignKey("subregions.id")),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("app_users.id")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("result", sa.dialects.postgresql.JSONB()),
        sa.Column("error", sa.String()),
    )
    from fixtures.meters import seed_meters
    seed_meters(op.get_bind())


def downgrade():
    # Removing the epoch flag would expose historical issues as operational again.
    raise RuntimeError("Operational epoch migration is forward-only; restore a database backup to roll back")
