"""One adapter, limiter and breaker per backend in each application process."""
from app.core.db import get_storage_engine
from app.core.settings import Settings
from app.models.enums import StorageBackend
from app.storage.base import Storage
from app.storage.db import DbStorage
from app.storage.ftp import FtpStorage
from app.storage.resilience import ManagedStorage
from app.storage.s3 import S3Storage


def create_storages(settings: Settings) -> dict[StorageBackend, ManagedStorage]:
    adapters: dict[StorageBackend, Storage] = {
        StorageBackend.db: DbStorage(get_storage_engine()),
        StorageBackend.ftp: FtpStorage(
            settings.ftp_host,
            settings.ftp_port,
            settings.ftp_user,
            settings.storage_secret("ftp_password"),
            settings.storage_io_timeout_seconds,
        ),
        StorageBackend.s3: S3Storage(settings),
    }
    return {
        backend: ManagedStorage(
            backend,
            adapter,
            concurrency=settings.storage_max_concurrency,
            timeout=settings.storage_operation_timeout_seconds,
            failure_threshold=settings.storage_circuit_failure_threshold,
            reset_seconds=settings.storage_circuit_reset_seconds,
            record_operations=True,
        )
        for backend, adapter in adapters.items()
    }
