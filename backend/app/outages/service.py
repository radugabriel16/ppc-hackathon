from sqlalchemy.orm import Session

from app.files.schemas import OutageRecordMetadata
from app.models.files import File
from app.models.outages import Outage


def link_outage(db: Session, file: File, metadata: OutageRecordMetadata) -> None:
    db.add(
        Outage(
            asset_id=metadata.asset_id,
            file_id=file.id,
            started_at=metadata.started_at,
            severity=metadata.severity,
            description=metadata.description,
        )
    )
