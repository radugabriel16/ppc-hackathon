"""Import every ORM model so `Base.metadata` is complete for Alembic and tests."""
from app.models.base import Base  # noqa: F401
from app.models.geography import NetworkAsset, Region  # noqa: F401
from app.models.clients import Client, ClientDocument, ConnectionCase, DocumentType  # noqa: F401
from app.models.files import File  # noqa: F401
from app.models.metering import Meter, MeterReading  # noqa: F401
from app.models.outages import Outage  # noqa: F401
from app.models.inspections import VideoInspection  # noqa: F401
from app.models.issues import MapIssue  # noqa: F401
from app.models.auth import AppUser, UserSession  # noqa: F401
from app.models.audit import AuditEvent  # noqa: F401
from app.models.uploads import UploadPart, UploadSession  # noqa: F401
from app.models.jobs import ScenarioRun, StorageOperation  # noqa: F401
from app.models.reminders import Reminder  # noqa: F401
from app.models.alerts import Alert  # noqa: F401

__all__ = [
    "Base",
    "Region",
    "NetworkAsset",
    "Client",
    "ConnectionCase",
    "DocumentType",
    "ClientDocument",
    "File",
    "Meter",
    "MeterReading",
    "Outage",
    "VideoInspection",
    "MapIssue",
    "AppUser",
    "UserSession",
    "AuditEvent",
    "UploadSession",
    "UploadPart",
    "StorageOperation",
    "ScenarioRun",
    "Reminder",
    "Alert",
]
