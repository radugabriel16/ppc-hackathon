"""S3 streaming and multipart operations (ETags are opaque, not SHA-256)."""
from collections.abc import Iterator, Sequence
from typing import BinaryIO

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.core.settings import Settings
from app.storage.base import (
    CHUNK_SIZE,
    Health,
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
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=object_key(key))
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
