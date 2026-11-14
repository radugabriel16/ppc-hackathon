"""ORM model for the separate storage-db (BYTEA content only, no business data)."""
import uuid
from datetime import datetime

from sqlalchemy import LargeBinary, TIMESTAMP, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class StorageDbBase(DeclarativeBase):
    pass


class FileContent(StorageDbBase):
    __tablename__ = "file_contents"

    file_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now(), index=True
    )
