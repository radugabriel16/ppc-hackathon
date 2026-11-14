"""Application settings loaded from environment variables and Docker secrets.

Secrets (DB passwords, S3 keys, etc.) are read from files under `secrets_dir`
(mounted at /run/secrets by the `init` container), never from plain env vars.
"""
from functools import lru_cache
from pathlib import Path

from pydantic import Field
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

    s3_endpoint_url: str = Field(default="http://seaweedfs:8333", alias="S3_ENDPOINT_URL")
    s3_region: str = Field(default="us-east-1", alias="S3_REGION")
    s3_bucket: str = Field(default="filegrid", alias="S3_BUCKET")

    ftp_host: str = Field(default="ftp", alias="FTP_HOST")
    ftp_port: int = Field(default=21, alias="FTP_PORT")
    ftp_user: str = Field(default="filegrid", alias="FTP_USER")

    session_cookie_name: str = Field(default="filegrid_session", alias="SESSION_COOKIE_NAME")
    session_ttl_seconds: int = Field(default=28800, alias="SESSION_TTL_SECONDS")

    policies_path: str = Field(default="/app/config/policies.yaml", alias="POLICIES_PATH")

    def _secret(self, name: str, default: str = "") -> str:
        return _read_secret(self.secrets_dir, name, default)

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
