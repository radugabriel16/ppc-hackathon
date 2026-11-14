from sqlalchemy.orm import Session

from app.files.schemas import DroneVideoMetadata
from app.models.files import File
from app.models.inspections import VideoInspection


def link_inspection(db: Session, file: File, metadata: DroneVideoMetadata) -> None:
    db.add(
        VideoInspection(
            asset_id=metadata.asset_id, file_id=file.id, recorded_at=metadata.recorded_at
        )
    )
