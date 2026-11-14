"""Create the S3 bucket once, preserving existing objects on subsequent starts."""
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.core.settings import get_settings


def main() -> None:
    settings = get_settings()
    secrets = Path(settings.secrets_dir)
    client = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        region_name=settings.s3_region,
        aws_access_key_id=(secrets / "s3_access_key_id").read_text().strip(),
        aws_secret_access_key=(secrets / "s3_secret_access_key").read_text().strip(),
        config=Config(
            connect_timeout=5,
            read_timeout=10,
            retries={"mode": "standard", "max_attempts": 5},
            s3={"addressing_style": "path"},
        ),
    )
    try:
        client.head_bucket(Bucket=settings.s3_bucket)
    except ClientError as exc:
        if exc.response["Error"]["Code"] not in {"404", "NoSuchBucket"}:
            raise
        client.create_bucket(Bucket=settings.s3_bucket)
        print("S3 bucket created.")
    else:
        print("S3 bucket already exists.")


if __name__ == "__main__":
    main()
