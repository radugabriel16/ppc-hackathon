"""Application settings loaded from environment variables and Docker secrets.

Secrets (DB passwords, S3 keys, etc.) are read from files under `secrets_dir`
(mounted at /run/secrets by the `init` container), never from plain env vars.
"""
from functools import lru_cache
from pathlib import Path

from pydantic import Field, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


def _read_secret(secrets_dir: str, name: str, default: str = "") -> str:
    path = Path(secrets_dir) / name
    if path.is_file():
        return path.read_text().strip()
    return default


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    role: str = Field(default="files", alias="ROLE")  # ingest | files | worker
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    secrets_dir: str = Field(default="/run/secrets", alias="SECRETS_DIR")

    catalog_db_host: str = Field(default="catalog-db", alias="CATALOG_DB_HOST")
    catalog_db_port: int = Field(default=5432, alias="CATALOG_DB_PORT")
    catalog_db_name: str = Field(default="filegrid_catalog", alias="CATALOG_DB_NAME")
    catalog_db_user: str = Field(default="filegrid", alias="CATALOG_DB_USER")

    storage_db_host: str = Field(default="storage-db", alias="STORAGE_DB_HOST")
    storage_db_port: int = Field(default=5432, alias="STORAGE_DB_PORT")
    storage_db_name: str = Field(default="filegrid_storage", alias="STORAGE_DB_NAME")
    storage_db_user: str = Field(default="filegrid", alias="STORAGE_DB_USER")

    history_db_host: str = Field(default="history-db", alias="HISTORY_DB_HOST")
    history_db_port: int = Field(default=5432, alias="HISTORY_DB_PORT")
    history_db_name: str = Field(default="filegrid_history", alias="HISTORY_DB_NAME")

    def history_db_url(self, role: str = "reader"):
        from sqlalchemy import URL

        if role not in ("reader", "writer", "admin"):
            raise ValueError("Unknown history database role")
        return URL.create(
            "postgresql+psycopg",
            username="history_admin" if role == "admin" else f"filegrid_history_{role}",
            password=self.storage_secret(
                "history_db_password" if role == "admin" else f"history_db_{role}_password"
            ),
            host=self.history_db_host, port=self.history_db_port,
            database=self.history_db_name,
        )

    s3_endpoint_url: str = Field(default="http://seaweedfs:8333", alias="S3_ENDPOINT_URL")
    s3_region: str = Field(default="us-east-1", alias="S3_REGION")
    s3_bucket: str = Field(default="filegrid", alias="S3_BUCKET")

    ftp_host: str = Field(default="ftp", alias="FTP_HOST")
    ftp_port: int = Field(default=21, alias="FTP_PORT")
    ftp_user: str = Field(default="filegrid", alias="FTP_USER")

    storage_io_timeout_seconds: float = Field(default=5, gt=0, le=60)
    storage_operation_timeout_seconds: float = Field(default=30, gt=0, le=3600)
    storage_max_concurrency: int = Field(default=32, gt=0)
    storage_circuit_failure_threshold: int = Field(default=3, gt=0)
    storage_circuit_reset_seconds: float = Field(default=15, gt=0)

    session_cookie_name: str = Field(default="filegrid_session", alias="SESSION_COOKIE_NAME")
    session_ttl_seconds: int = Field(default=28800, alias="SESSION_TTL_SECONDS", gt=0)
    app_origin: HttpUrl = Field(default="https://localhost", alias="APP_ORIGIN")

    policies_path: str = Field(default="/app/config/policies.yaml", alias="POLICIES_PATH")

    worker_batch_size: int = Field(default=25, gt=0, le=1000)
    integrity_scrub_interval_seconds: int = Field(default=86400, gt=0)
    integrity_scrub_bytes_per_second: int = Field(default=5 * 1024 * 1024, gt=0)
    stuck_file_after_seconds: int = Field(default=3600, gt=0)
    worker_retry_seconds: int = Field(default=300, gt=0)
    worker_max_attempts: int = Field(default=3, gt=0)
    meter_gap_window_seconds: int = Field(default=3600, gt=0)
    meter_active_seconds: int = Field(default=300, gt=0)
    meter_gap_readings_limit: int = Field(default=1000, ge=2, le=10000)
    reminder_after_hours: int = Field(default=24, gt=0)
    reminder_period_hours: int = Field(default=24, gt=0)
    smtp_host: str = "mailpit"
    smtp_port: int = Field(default=1025, gt=0, le=65535)
    smtp_timeout_seconds: float = Field(default=10, gt=0, le=60)
    reminder_from: str = "filegrid@filegrid.local"
    reminder_to: str = "operations@filegrid.local"

    def _secret(self, name: str, default: str = "") -> str:
        return _read_secret(self.secrets_dir, name, default)

    def storage_secret(self, name: str) -> str:
        value = (Path(self.secrets_dir) / name).read_text().strip()
        if not value:
            raise ValueError(f"Storage secret {name} is empty")
        return value

    @property
    def catalog_db_password(self) -> str:
        return self._secret("catalog_db_password", "dev-catalog-password")

    @property
    def storage_db_password(self) -> str:
        return self._secret("storage_db_password", "dev-storage-password")

    @property
    def catalog_db_dsn(self) -> str:
        return (
            f"postgresql+psycopg://{self.catalog_db_user}:{self.catalog_db_password}"
            f"@{self.catalog_db_host}:{self.catalog_db_port}/{self.catalog_db_name}"
        )

    @property
    def storage_db_dsn(self) -> str:
        return (
            f"postgresql+psycopg://{self.storage_db_user}:{self.storage_db_password}"
            f"@{self.storage_db_host}:{self.storage_db_port}/{self.storage_db_name}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
