"""Durable worker cursors, file recovery and reminder deduplication."""
from alembic import op
import sqlalchemy as sa

revision = "0004_worker_maintenance"
down_revision = "0003_stats_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("files", sa.Column("maintenance_at", sa.TIMESTAMP(timezone=True)))
    op.add_column("files", sa.Column("maintenance_attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("files", sa.Column("failure_reason", sa.String(128)))
    op.add_column("files", sa.Column("cleaned_at", sa.TIMESTAMP(timezone=True)))
    op.create_index("ix_files_scrub_due", "files", ["last_verified_at", "id"],
                    postgresql_where=sa.text("status = 'READY'"))
    op.create_table(
        "worker_state",
        sa.Column("name", sa.String(64), primary_key=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("cursor", sa.Uuid()),
    )
    op.create_table(
        "meter_gaps",
        sa.Column("meter_id", sa.Uuid(), sa.ForeignKey("meters.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("region_id", sa.Uuid(), sa.ForeignKey("regions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("missing", sa.Integer(), nullable=False),
        sa.Column("active_until", sa.TIMESTAMP(timezone=True), nullable=False),
    )
    op.create_index("ix_meter_gaps_region_id", "meter_gaps", ["region_id"])
    op.create_index("ix_meter_gaps_active_until", "meter_gaps", ["active_until"])
    op.create_table(
        "reminder_deliveries",
        sa.Column("kind", sa.String(32), primary_key=True),
        sa.Column("entity_id", sa.Uuid(), primary_key=True),
        sa.Column("period_start", sa.TIMESTAMP(timezone=True), primary_key=True),
        sa.Column("attempted_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("reminder_deliveries")
    op.drop_table("meter_gaps")
    op.drop_table("worker_state")
    op.drop_index("ix_files_scrub_due", table_name="files")
    for column in ("cleaned_at", "failure_reason", "maintenance_attempts", "maintenance_at"):
        op.drop_column("files", column)
