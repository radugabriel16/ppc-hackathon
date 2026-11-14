"""Offline national border, clipped operational areas and spatial assignment."""
from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geometry

revision = "0005_region_geometry"
down_revision = "0004_worker_maintenance"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "national_boundaries",
        sa.Column("code", sa.String(2), primary_key=True),
        sa.Column("geometry", Geometry("MULTIPOLYGON", srid=4326), nullable=False),
    )
    op.add_column("regions", sa.Column("geometry", Geometry("MULTIPOLYGON", srid=4326)))
    op.create_table(
        "subregions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("region_id", sa.Uuid(), sa.ForeignKey("regions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(32), unique=True, nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("geometry", Geometry("MULTIPOLYGON", srid=4326), nullable=False),
        sa.CheckConstraint("NOT ST_IsEmpty(geometry) AND ST_IsValid(geometry)", name="ck_subregions_valid"),
    )
    op.create_index("ix_subregions_region_id", "subregions", ["region_id"])
    for table in ("network_assets", "meters", "files", "map_issues"):
        op.add_column(table, sa.Column(
            "subregion_id", sa.Uuid(), sa.ForeignKey("subregions.id", ondelete="SET NULL"),
        ))
        op.create_index(f"ix_{table}_subregion_id", table, ["subregion_id"])
    op.execute("""
        CREATE FUNCTION covered_subregion(p geometry, parent uuid DEFAULT NULL)
        RETURNS uuid LANGUAGE sql STABLE AS $$
            SELECT id FROM subregions
            WHERE (parent IS NULL OR region_id=parent) AND ST_Covers(geometry,p)
            ORDER BY code LIMIT 1
        $$;
        CREATE FUNCTION assign_geography() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_TABLE_NAME='network_assets' THEN
                NEW.subregion_id := covered_subregion(ST_PointOnSurface(NEW.geometry),NEW.region_id);
            ELSIF TG_TABLE_NAME='meters' THEN
                SELECT subregion_id INTO NEW.subregion_id FROM network_assets WHERE id=NEW.asset_id;
            ELSIF TG_TABLE_NAME='map_issues' THEN
                NEW.subregion_id := covered_subregion(NEW.location);
            ELSE
                SELECT covered_subregion(ST_PointOnSurface(geometry),id)
                INTO NEW.subregion_id FROM regions WHERE id=NEW.region_id;
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER assign_asset_geography BEFORE INSERT OR UPDATE OF geometry,region_id
            ON network_assets FOR EACH ROW EXECUTE FUNCTION assign_geography();
        CREATE TRIGGER assign_meter_geography BEFORE INSERT OR UPDATE OF asset_id
            ON meters FOR EACH ROW EXECUTE FUNCTION assign_geography();
        CREATE TRIGGER assign_issue_geography BEFORE INSERT OR UPDATE OF location
            ON map_issues FOR EACH ROW EXECUTE FUNCTION assign_geography();
        CREATE TRIGGER assign_file_geography BEFORE INSERT OR UPDATE OF region_id
            ON files FOR EACH ROW EXECUTE FUNCTION assign_geography();

        CREATE FUNCTION assign_linked_file(source text, target uuid) RETURNS void
        LANGUAGE plpgsql AS $$
        BEGIN
            IF source='meter_readings' THEN
                UPDATE files f SET subregion_id=m.subregion_id
                FROM meter_readings l JOIN meters m ON m.id=l.meter_id
                WHERE f.id=l.file_id AND (target IS NULL OR f.id=target)
                  AND f.subregion_id IS DISTINCT FROM m.subregion_id;
            ELSIF source IN ('outages','video_inspections') THEN
                EXECUTE format('UPDATE files f SET subregion_id=a.subregion_id
                    FROM %I l JOIN network_assets a ON a.id=l.asset_id
                    WHERE f.id=l.file_id AND ($1 IS NULL OR f.id=$1)
                    AND f.subregion_id IS DISTINCT FROM a.subregion_id',source) USING target;
            ELSIF source='client_documents' THEN
                UPDATE files f SET subregion_id=covered_subregion(
                    coalesce(c.location,ST_PointOnSurface(r.geometry)),c.region_id)
                FROM client_documents l JOIN connection_cases cc ON cc.id=l.case_id
                JOIN clients c ON c.id=cc.client_id JOIN regions r ON r.id=c.region_id
                WHERE f.id=l.file_id AND (target IS NULL OR f.id=target);
            END IF;
        END $$;
        CREATE FUNCTION assign_file_link() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            PERFORM assign_linked_file(TG_TABLE_NAME,NEW.file_id);
            RETURN NEW;
        END $$;
    """)
    for table in ("meter_readings", "outages", "video_inspections", "client_documents"):
        op.execute(f"""
            CREATE TRIGGER assign_file_link AFTER INSERT OR UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION assign_file_link()
        """)
    from fixtures.geography import seed_geography
    seed_geography(op.get_bind())


def downgrade():
    for table in ("meter_readings", "outages", "video_inspections", "client_documents"):
        op.execute(f"DROP TRIGGER assign_file_link ON {table}")
    for table, trigger in (
        ("network_assets", "assign_asset_geography"), ("meters", "assign_meter_geography"),
        ("map_issues", "assign_issue_geography"), ("files", "assign_file_geography"),
    ):
        op.execute(f"DROP TRIGGER {trigger} ON {table}")
    op.execute("DROP FUNCTION assign_file_link(), assign_linked_file(text,uuid), assign_geography(), covered_subregion(geometry,uuid)")
    for table in ("network_assets", "meters", "files", "map_issues"):
        op.drop_column(table, "subregion_id")
    op.drop_table("subregions")
    op.drop_column("regions", "geometry")
    op.drop_table("national_boundaries")
