"""Client, connection-case and document-type models."""
import uuid
from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import Boolean, Enum, ForeignKey, String, TIMESTAMP, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPkMixin
from app.models.enums import CaseStatus, ClientType


class Client(UUIDPkMixin, Base):
    __tablename__ = "clients"

    region_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("regions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    external_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name_enc: Mapped[bytes] = mapped_column(nullable=False)
    email_enc: Mapped[bytes] = mapped_column(nullable=False)
    location = mapped_column(Geometry("POINT", srid=4326), nullable=True)
    client_type: Mapped[ClientType] = mapped_column(
        Enum(ClientType, name="client_type"), nullable=False
    )

    cnp_hmac: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    cnp_masked: Mapped[str | None] = mapped_column(String(16))

    cases: Mapped[list["ConnectionCase"]] = relationship(back_populates="client")


class ConnectionCase(UUIDPkMixin, Base):
    __tablename__ = "connection_cases"

    client_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[CaseStatus] = mapped_column(
        Enum(CaseStatus, name="case_status"), nullable=False, default=CaseStatus.OPEN
    )
    opened_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    client: Mapped["Client"] = relationship(back_populates="cases")
    documents: Mapped[list["ClientDocument"]] = relationship(back_populates="case")


class DocumentType(UUIDPkMixin, Base):
    __tablename__ = "document_types"

    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    required_for_connection: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class ClientDocument(UUIDPkMixin, Base):
    __tablename__ = "client_documents"
    __table_args__ = (UniqueConstraint("file_id", name="uq_client_documents_file_id"),)

    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("connection_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_type_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_types.id", ondelete="RESTRICT"), nullable=False
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("files.id", ondelete="RESTRICT"), nullable=False
    )
    superseded_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    uploaded_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)

    case: Mapped["ConnectionCase"] = relationship(back_populates="documents")
