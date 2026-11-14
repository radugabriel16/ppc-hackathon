"""BYTEA storage, bounded to the policy maximum of one MiB."""
from collections.abc import Iterator
from uuid import UUID
from typing import BinaryIO

from sqlalchemy import Engine, text

from app.storage.base import (
    CHUNK_SIZE,
    MAX_DB_SIZE,
    Health,
    InventoryObject,
    InventoryPage,
    StorageNotFound,
    StoredObject,
    check_stream,
    object_key,
)


class DbStorage:
    def __init__(self, engine: Engine):
        self.engine = engine

    def put(self, key: str, stream: BinaryIO, size: int) -> StoredObject:
        key = object_key(key)
        check_stream(stream, size)
        if size > MAX_DB_SIZE:
            raise ValueError("Database objects must not exceed one MiB")
        content = stream.read(size)
        if len(content) != size:
            raise ValueError("Incomplete database upload")
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO file_contents (file_id, content) VALUES (:id, :content) "
                    "ON CONFLICT (file_id) DO UPDATE SET content = EXCLUDED.content"
                ),
                {"id": key, "content": content},
            )
        return StoredObject(key, size)

    def get(self, key: str) -> Iterator[bytes]:
        with self.engine.connect() as conn:
            content = conn.execute(
                text("SELECT content FROM file_contents WHERE file_id = :id"),
                {"id": object_key(key)},
            ).scalar_one_or_none()
        if content is None:
            raise StorageNotFound("Database object does not exist")
        for offset in range(0, len(content), CHUNK_SIZE):
            yield bytes(content[offset : offset + CHUNK_SIZE])

    def delete(self, key: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text("DELETE FROM file_contents WHERE file_id = :id"),
                {"id": object_key(key)},
            )

    def health(self) -> Health:
        with self.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return "ok"

    def inventory(self, cursor: UUID | None, limit: int) -> InventoryPage:
        with self.engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT file_id, created_at FROM file_contents "
                "WHERE (CAST(:cursor AS uuid) IS NULL OR file_id > CAST(:cursor AS uuid)) "
                "ORDER BY file_id LIMIT :limit"
            ), {"cursor": str(cursor) if cursor is not None else None, "limit": limit}).all()
        return InventoryPage(
            [InventoryObject(str(row.file_id), row.created_at) for row in rows],
            rows[-1].file_id if len(rows) == limit else None,
        )
