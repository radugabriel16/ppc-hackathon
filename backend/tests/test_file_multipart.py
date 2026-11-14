import hashlib
import json
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.core.policy_schema import load_policies
from app.files.multipart import parse_upload

pytestmark = pytest.mark.anyio


def multipart(parts):
    return b"".join(
        b"--test-boundary\r\nContent-Disposition: form-data; name=\"" + name
        + b"\"" + (b'; filename="test.bin"' if name == b"file" else b"")
        + b"\r\n\r\n" + value + b"\r\n"
        for name, value in parts
    ) + b"--test-boundary--\r\n"


def request(body):
    offset = 0

    async def receive():
        nonlocal offset
        chunk = body[offset:offset + 37]
        offset += len(chunk)
        return {"type": "http.request", "body": chunk, "more_body": offset < len(body)}

    return Request({
        "type": "http", "method": "POST", "path": "/api/v1/files",
        "headers": [(b"content-type", b"multipart/form-data; boundary=test-boundary")],
    }, receive)


@pytest.fixture
def config():
    return load_policies(Path(__file__).resolve().parents[2] / "config/policies.yaml")


def metadata(category="OUTAGE_RECORD"):
    return json.dumps({
        "category": category, "assetId": str(uuid.uuid4()),
        "startedAt": "2026-01-01T10:00:00Z", "severity": "HIGH",
    }).encode()


@pytest.mark.parametrize("metadata_first", [True, False])
async def test_streams_hashes_and_accepts_either_part_order(config, metadata_first):
    plaintext = bytes(range(256)) * 100
    parts = [(b"metadata", metadata()), (b"file", plaintext)]
    if not metadata_first:
        parts.reverse()
    async with parse_upload(request(multipart(parts)), config) as upload:
        assert upload.stream.read() == plaintext
        assert upload.sha256.hexdigest() == hashlib.sha256(plaintext).hexdigest()
        assert upload.size == len(plaintext)
        stream = upload.stream
    assert stream.closed


@pytest.mark.parametrize("metadata_first", [True, False])
async def test_category_limit_enforced_without_content_length(config, metadata_first):
    config.categories[next(c for c in config.categories if c.value == "OUTAGE_RECORD")].max_size_bytes = 10
    parts = [(b"metadata", metadata()), (b"file", b"x" * 11)]
    if not metadata_first:
        parts.reverse()
    with pytest.raises(HTTPException) as error:
        async with parse_upload(request(multipart(parts)), config):
            pytest.fail("Oversize upload accepted")
    assert error.value.status_code == 413


@pytest.mark.parametrize("kind", ["truncated", "duplicate", "missing", "meter", "invalid_json"])
async def test_invalid_uploads_rejected(config, kind):
    parts = [(b"metadata", metadata()), (b"file", b"abc")]
    if kind == "duplicate":
        parts.append((b"file", b"again"))
    elif kind == "missing":
        parts.pop()
    elif kind == "meter":
        parts[0] = (b"metadata", metadata("METER_READING"))
    elif kind == "invalid_json":
        parts[0] = (b"metadata", b"{")
    body = multipart(parts)
    if kind == "truncated":
        body = body[:-10]
    with pytest.raises(HTTPException) as error:
        async with parse_upload(request(body), config):
            pytest.fail("Invalid multipart accepted")
    assert error.value.status_code == 422
