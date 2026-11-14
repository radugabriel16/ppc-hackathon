"""Initial catalog-db schema: all tables from PHASE1.md section 3.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-11-14
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)

ENUM_TYPES = {
    "asset_type": ["SUBSTATION", "TRANSFORMER", "LINE_SEGMENT"],
    "client_type": ["RESIDENTIAL", "COMMERCIAL", "INDUSTRIAL"],
    "case_status": ["OPEN", "CLOSED"],
    "file_category": ["METER_READING", "OUTAGE_RECORD", "CONNECTION_DOCUMENT", "DRONE_VIDEO"],
    "storage_backend": ["db", "ftp", "s3"],
    "file_status": ["STAGING", "VERIFYING", "READY", "FAILED", "CORRUPT"],
    "issue_severity": ["LOW", "MEDIUM", "HIGH", "CRITICAL"],
    "issue_status": ["OPEN", "IN_PROGRESS", "RESOLVED"],
    "user_role": ["OPERATOR", "MANAGER"],
}


def _enum(name: str) -> postgresql.ENUM:
    return postgresql.ENUM(*ENUM_TYPES[name], name=name, create_type=False)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    for name, values in ENUM_TYPES.items():
        values_sql = ", ".join(f"'{v}'" for v in values)
        op.execute(f"CREATE TYPE {name} AS ENUM ({values_sql})")

    op.create_table(
        "app_users",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("password_hash", sa.String(256), nullable=False),
        sa.Column("role", _enum("user_role"), nullable=False),
        sa.UniqueConstraint("username", name="uq_app_users_username"),
    )

    op.create_table(
        "regions",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("center", Geometry("POINT", srid=4326), nullable=True),
        sa.Column("bounds", postgresql.JSONB, nullable=True),
        sa.UniqueConstraint("code", name="uq_regions_code"),
    )

    op.create_table(
        "network_assets",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("region_id", UUID, sa.ForeignKey("regions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("type", _enum("asset_type"), nullable=False),
        sa.Column("geometry", Geometry(srid=4326), nullable=False),
        sa.Column("rated_capacity_kw", sa.Numeric, nullable=True),
        sa.UniqueConstraint("code", name="uq_network_assets_code"),
        sa.CheckConstraint(
            "rated_capacity_kw IS NULL OR rated_capacity_kw > 0",
            name="ck_network_assets_rated_capacity_positive",
        ),
    )
    op.create_index("ix_network_assets_region_id", "network_assets", ["region_id"])

    op.create_table(
        "clients",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("region_id", UUID, sa.ForeignKey("regions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("external_code", sa.String(64), nullable=False),
        sa.Column("name_enc", sa.LargeBinary, nullable=False),
        sa.Column("email_enc", sa.LargeBinary, nullable=False),
        sa.Column("location", Geometry("POINT", srid=4326), nullable=True),
        sa.Column("client_type", _enum("client_type"), nullable=False),
        sa.UniqueConstraint("external_code", name="uq_clients_external_code"),
    )
    op.create_index("ix_clients_region_id", "clients", ["region_id"])

    op.create_table(
        "document_types",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("required_for_connection", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("code", name="uq_document_types_code"),
    )

    op.create_table(
        "files",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("region_id", UUID, sa.ForeignKey("regions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("category", _enum("file_category"), nullable=False),
        sa.Column("original_name", sa.String(512), nullable=False),
        sa.Column("media_type", sa.String(128), nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_backend", _enum("storage_backend"), nullable=False),
        sa.Column("storage_locator", sa.String(1024), nullable=False),
        sa.Column("fallback_used", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("status", _enum("file_status"), nullable=False, server_default="STAGING"),
        sa.Column("encrypted", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("encryption_key_id", sa.String(128), nullable=True),
        sa.Column("uploaded_by", UUID, sa.ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("ready_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_verified_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_files_region_id", "files", ["region_id"])
    op.create_index("ix_files_category", "files", ["category"])
    op.create_index("ix_files_status", "files", ["status"])

    op.create_table(
        "connection_cases",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("client_id", UUID, sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", _enum("case_status"), nullable=False, server_default="OPEN"),
        sa.Column("opened_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("due_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_connection_cases_client_id", "connection_cases", ["client_id"])

    op.create_table(
        "client_documents",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "case_id", UUID, sa.ForeignKey("connection_cases.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "document_type_id",
            UUID,
            sa.ForeignKey("document_types.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("file_id", UUID, sa.ForeignKey("files.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("uploaded_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.UniqueConstraint("file_id", name="uq_client_documents_file_id"),
    )
    op.create_index("ix_client_documents_case_id", "client_documents", ["case_id"])

    op.create_table(
        "meters",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("external_code", sa.String(64), nullable=False),
        sa.Column(
            "asset_id", UUID, sa.ForeignKey("network_assets.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("client_id", UUID, sa.ForeignKey("clients.id", ondelete="SET NULL"), nullable=True),
        sa.UniqueConstraint("external_code", name="uq_meters_external_code"),
    )
    op.create_index("ix_meters_asset_id", "meters", ["asset_id"])
    op.create_index("ix_meters_client_id", "meters", ["client_id"])

    op.create_table(
        "meter_readings",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("meter_id", UUID, sa.ForeignKey("meters.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("reading_key", sa.String(256), nullable=False),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("interval_start", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("interval_end", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("energy_kwh", sa.Numeric, nullable=False),
        sa.Column("file_id", UUID, sa.ForeignKey("files.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("received_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.UniqueConstraint("meter_id", "reading_key", name="uq_meter_readings_meter_reading_key"),
        sa.UniqueConstraint("file_id", name="uq_meter_readings_file_id"),
        sa.CheckConstraint("interval_end > interval_start", name="ck_meter_readings_interval_order"),
        sa.CheckConstraint("energy_kwh >= 0", name="ck_meter_readings_energy_non_negative"),
    )
    op.create_index(
        "ix_meter_readings_meter_interval_end", "meter_readings", ["meter_id", "interval_end"]
    )

    op.create_table(
        "outages",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "asset_id", UUID, sa.ForeignKey("network_assets.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("file_id", UUID, sa.ForeignKey("files.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("ended_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("severity", sa.String(32), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.UniqueConstraint("file_id", name="uq_outages_file_id"),
    )
    op.create_index("ix_outages_asset_id", "outages", ["asset_id"])

    op.create_table(
        "video_inspections",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "asset_id", UUID, sa.ForeignKey("network_assets.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("file_id", UUID, sa.ForeignKey("files.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("recorded_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.UniqueConstraint("file_id", name="uq_video_inspections_file_id"),
    )
    op.create_index("ix_video_inspections_asset_id", "video_inspections", ["asset_id"])

    op.create_table(
        "map_issues",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "asset_id", UUID, sa.ForeignKey("network_assets.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "video_inspection_id",
            UUID,
            sa.ForeignKey("video_inspections.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("video_offset_seconds", sa.Integer, nullable=True),
        sa.Column("location", Geometry("POINT", srid=4326), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("severity", _enum("issue_severity"), nullable=False),
        sa.Column("status", _enum("issue_status"), nullable=False, server_default="OPEN"),
        sa.Column("assigned_team_label", sa.String(128), nullable=True),
        sa.Column("created_by", UUID, sa.ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
    )
    op.create_index("ix_map_issues_asset_id", "map_issues", ["asset_id"])

    op.create_table(
        "user_sessions",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("user_id", UUID, sa.ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("csrf_token", sa.String(128), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])
    op.create_index("ix_user_sessions_expires_at", "user_sessions", ["expires_at"])

    op.create_table(
        "audit_events",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("actor_id", UUID, sa.ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", UUID, nullable=True),
        sa.Column("occurred_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("details", postgresql.JSONB, nullable=True),
    )
    op.create_index("ix_audit_events_actor_id", "audit_events", ["actor_id"])
    op.create_index("ix_audit_events_occurred_at", "audit_events", ["occurred_at"])

    op.create_table(
        "upload_sessions",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("category", _enum("file_category"), nullable=False),
        sa.Column("file_name", sa.String(512), nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("chunk_size", sa.BigInteger, nullable=False),
        sa.Column("total_parts", sa.Integer, nullable=False),
        sa.Column("s3_upload_id", sa.String(256), nullable=True),
        sa.Column("file_id", UUID, sa.ForeignKey("files.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="PENDING"),
        sa.Column("metadata", postgresql.JSONB, nullable=True),
        sa.Column("created_by", UUID, sa.ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
    )
    op.create_index("ix_upload_sessions_expires_at", "upload_sessions", ["expires_at"])

    op.create_table(
        "upload_parts",
        sa.Column(
            "upload_id", UUID, sa.ForeignKey("upload_sessions.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("part_number", sa.Integer, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("etag", sa.String(256), nullable=True),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("received_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("upload_id", "part_number", name="pk_upload_parts"),
    )

    op.create_table(
        "scenario_runs",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("profile", sa.String(64), nullable=False),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("ended_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("counters", postgresql.JSONB, nullable=True),
    )

    op.create_table(
        "storage_operations",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("category", _enum("file_category"), nullable=False),
        sa.Column("storage", _enum("storage_backend"), nullable=False),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("bytes", sa.BigInteger, nullable=False),
        sa.Column("duration_ms", sa.Integer, nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column(
            "scenario_run_id",
            UUID,
            sa.ForeignKey("scenario_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("occurred_at", sa.TIMESTAMP(timezone=True), nullable=False),
    )
    op.create_index("ix_storage_operations_category", "storage_operations", ["category"])
    op.create_index("ix_storage_operations_storage", "storage_operations", ["storage"])
    op.create_index("ix_storage_operations_occurred_at", "storage_operations", ["occurred_at"])

    op.create_table(
        "reminders",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "case_id", UUID, sa.ForeignKey("connection_cases.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("sent_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("missing_types", postgresql.JSONB, nullable=False),
    )
    op.create_index("ix_reminders_case_id", "reminders", ["case_id"])


def downgrade() -> None:
    op.drop_table("reminders")
    op.drop_table("storage_operations")
    op.drop_table("scenario_runs")
    op.drop_table("upload_parts")
    op.drop_table("upload_sessions")
    op.drop_table("audit_events")
    op.drop_table("user_sessions")
    op.drop_table("map_issues")
    op.drop_table("video_inspections")
    op.drop_table("outages")
    op.drop_table("meter_readings")
    op.drop_table("meters")
    op.drop_table("client_documents")
    op.drop_table("connection_cases")
    op.drop_table("files")
    op.drop_table("document_types")
    op.drop_table("clients")
    op.drop_table("network_assets")
    op.drop_table("regions")
    op.drop_table("app_users")

    for name in ENUM_TYPES:
        op.execute(f"DROP TYPE IF EXISTS {name}")
