"""S3 streaming and multipart operations (ETags are opaque, not SHA-256)."""
from collections.abc import Iterator, Sequence
from typing import BinaryIO
from uuid import UUID

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.core.settings import Settings
from app.storage.base import (
    CHUNK_SIZE,
    Health,
    InventoryObject,
    InventoryPage,
    MultipartPart,
    StorageNotFound,
    StoredObject,
    check_stream,
    object_key,
)


class S3Storage:
    def __init__(self, settings: Settings):
        self.bucket = settings.s3_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.s3_region,
            aws_access_key_id=settings.storage_secret("s3_access_key_id"),
            aws_secret_access_key=settings.storage_secret("s3_secret_access_key"),
            config=Config(
                connect_timeout=settings.storage_io_timeout_seconds,
                read_timeout=settings.storage_io_timeout_seconds,
                retries={"total_max_attempts": 1},
                s3={"addressing_style": "path"},
            ),
        )

    def put(self, key: str, stream: BinaryIO, size: int) -> StoredObject:
        key = object_key(key)
        check_stream(stream, size)
        self.client.put_object(Bucket=self.bucket, Key=key, Body=stream, ContentLength=size)
        return StoredObject(key, size)

    def get(self, key: str) -> Iterator[bytes]:
        yield from self._get(key)

    def get_range(self, key: str, start: int, end: int) -> Iterator[bytes]:
        yield from self._get(key, f"bytes={start}-{end}")

    def _get(self, key: str, byte_range: str | None = None) -> Iterator[bytes]:
        try:
            response = self.client.get_object(
                Bucket=self.bucket, Key=object_key(key),
                **({"Range": byte_range} if byte_range is not None else {}),
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] in {"NoSuchKey", "404", "NotFound"}:
                raise StorageNotFound("S3 object does not exist") from exc
            raise
        body = response["Body"]
        try:
            while chunk := body.read(CHUNK_SIZE):
                yield chunk
        finally:
            body.close()

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=object_key(key))

    def health(self) -> Health:
        self.client.head_bucket(Bucket=self.bucket)
        return "ok"

    def inventory(self, cursor: UUID | None, limit: int) -> InventoryPage:
        arguments = {"Bucket": self.bucket, "MaxKeys": limit}
        if cursor is not None:
            arguments["StartAfter"] = str(cursor)
        response = self.client.list_objects_v2(**arguments)
        objects = [
            InventoryObject(object_key(item["Key"]), item["LastModified"])
            for item in response.get("Contents", [])
        ]
        return InventoryPage(
            objects, UUID(objects[-1].key) if objects and response.get("IsTruncated") else None,
        )

    def create_multipart(self, key: str) -> str:
        response = self.client.create_multipart_upload(Bucket=self.bucket, Key=object_key(key))
        return response["UploadId"]

    def upload_part(
        self, key: str, upload_id: str, part_number: int, stream: BinaryIO, size: int
    ) -> str:
        if not 1 <= part_number <= 10000:
            raise ValueError("S3 part number must be between 1 and 10000")
        check_stream(stream, size)
        response = self.client.upload_part(
            Bucket=self.bucket,
            Key=object_key(key),
            UploadId=upload_id,
            PartNumber=part_number,
            Body=stream,
            ContentLength=size,
        )
        return response["ETag"]

    def complete_multipart(
        self, key: str, upload_id: str, parts: Sequence[MultipartPart]
    ) -> StoredObject:
        if not parts or [part.part_number for part in parts] != list(range(1, len(parts) + 1)):
            raise ValueError("Multipart completion requires ordered, consecutive parts")
        key = object_key(key)
        self.client.complete_multipart_upload(
            Bucket=self.bucket,
            Key=key,
            UploadId=upload_id,
            MultipartUpload={
                "Parts": [
                    {"PartNumber": part.part_number, "ETag": part.etag} for part in parts
                ]
            },
        )
        return StoredObject(key, sum(part.size for part in parts))

    def abort_multipart(self, key: str, upload_id: str) -> None:
        try:
            self.client.abort_multipart_upload(
                Bucket=self.bucket, Key=object_key(key), UploadId=upload_id
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "NoSuchUpload":
                raise
