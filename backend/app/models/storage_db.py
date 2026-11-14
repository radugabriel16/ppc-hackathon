"""ORM model for the separate storage-db (BYTEA content only, no business data)."""
import uuid

from sqlalchemy import LargeBinary
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class StorageDbBase(DeclarativeBase):
    pass


class FileContent(StorageDbBase):
    __tablename__ = "file_contents"

    file_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
