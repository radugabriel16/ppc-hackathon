"""Shared enums used across SQLAlchemy models, Pydantic schemas and policy config."""
import enum


class FileCategory(str, enum.Enum):
    METER_READING = "METER_READING"
    OUTAGE_RECORD = "OUTAGE_RECORD"
    CONNECTION_DOCUMENT = "CONNECTION_DOCUMENT"
    DRONE_VIDEO = "DRONE_VIDEO"


class StorageBackend(str, enum.Enum):
    db = "db"
    ftp = "ftp"
    s3 = "s3"


class FileStatus(str, enum.Enum):
    STAGING = "STAGING"
    VERIFYING = "VERIFYING"
    READY = "READY"
    FAILED = "FAILED"
    CORRUPT = "CORRUPT"


class AssetType(str, enum.Enum):
    SUBSTATION = "SUBSTATION"
    TRANSFORMER = "TRANSFORMER"
    LINE_SEGMENT = "LINE_SEGMENT"


class ClientType(str, enum.Enum):
    RESIDENTIAL = "RESIDENTIAL"
    COMMERCIAL = "COMMERCIAL"
    INDUSTRIAL = "INDUSTRIAL"


class CaseStatus(str, enum.Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class IssueSeverity(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class IssueStatus(str, enum.Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"


class UserRole(str, enum.Enum):
    OPERATOR = "OPERATOR"
    MANAGER = "MANAGER"
