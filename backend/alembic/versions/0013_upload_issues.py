"""Persist capture metadata and the idempotent upload placement link."""
from alembic import op
import sqlalchemy as sa

revision = "0013_upload_issues"
down_revision = "0012_meter_readings_received"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("files", sa.Column("captured_at", sa.TIMESTAMP(timezone=True)))
    op.add_column("files", sa.Column("description", sa.String(1000)))
    op.add_column("files", sa.Column("placed_issue_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_files_placed_issue", "files", "map_issues", ["placed_issue_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint("uq_files_placed_issue", "files", ["placed_issue_id"])
    op.execute("""
        UPDATE files f SET captured_at=v.recorded_at
        FROM video_inspections v WHERE v.file_id=f.id;
        UPDATE files SET media_type=CASE
            WHEN original_name ~* '[.]mp4$' THEN 'video/mp4'
            WHEN original_name ~* '[.]webm$' THEN 'video/webm'
            WHEN original_name ~* '[.]mov$' THEN 'video/quicktime'
            ELSE media_type END
        WHERE category='DRONE_VIDEO' AND media_type='application/octet-stream';
        UPDATE files f SET captured_at=o.started_at, description=left(o.description,1000)
        FROM outages o WHERE o.file_id=f.id;
        UPDATE files f SET placed_issue_id=(
            SELECT i.id FROM map_issues i WHERE i.file_id=f.id
            AND i.type IN ('DRONE_DETECTED','OUTAGE_VIDEO') AND NOT i.is_historical
            ORDER BY i.created_at,i.id LIMIT 1
        ) WHERE f.category IN ('DRONE_VIDEO','OUTAGE_RECORD');
    """)


def downgrade():
    op.drop_constraint("uq_files_placed_issue", "files", type_="unique")
    op.drop_constraint("fk_files_placed_issue", "files", type_="foreignkey")
    op.drop_column("files", "placed_issue_id")
    op.drop_column("files", "description")
    op.drop_column("files", "captured_at")
