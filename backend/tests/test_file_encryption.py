import io
import uuid

import pytest

from app.documents.encryption import (
    FRAME,
    MAGIC,
    SEGMENT_SIZE,
    DocumentKey,
    IntegrityError,
    decrypt,
    encrypt,
)

pytestmark = pytest.mark.anyio
KEY = DocumentKey("test-key", bytes(range(32)))
FILE_ID = uuid.uuid4()


async def chunks(data):
    for offset in range(0, len(data), 7001):
        yield data[offset:offset + 7001]


def ciphertext(data):
    target = io.BytesIO()
    encrypt(io.BytesIO(data), target, KEY, FILE_ID)
    return target.getvalue()


@pytest.mark.parametrize("size", [0, 1, SEGMENT_SIZE, SEGMENT_SIZE + 17, 2 * SEGMENT_SIZE])
async def test_segmented_roundtrip_preserves_exact_bytes(size):
    plaintext = (bytes(range(256)) * (size // 256 + 1))[:size]
    stored = ciphertext(plaintext)
    assert stored != plaintext
    assert b"".join([part async for part in decrypt(chunks(stored), KEY, FILE_ID)]) == plaintext


@pytest.mark.parametrize("mutation", ["flip", "truncate", "remove_final", "append", "swap", "flag"])
async def test_authenticated_framing_rejects_tampering(mutation):
    stored = bytearray(ciphertext(b"x" * (SEGMENT_SIZE + 17)))
    header = len(MAGIC) + 8
    first_end = header + FRAME.size + SEGMENT_SIZE + 16
    if mutation == "flip":
        stored[header + FRAME.size + 10] ^= 1
    elif mutation == "truncate":
        del stored[-1:]
    elif mutation == "remove_final":
        del stored[first_end:]
    elif mutation == "append":
        stored.extend(b"extra")
    elif mutation == "swap":
        stored = stored[:header] + stored[first_end:] + stored[header:first_end]
    else:
        stored[header + FRAME.size - 1] = 1
    with pytest.raises(IntegrityError):
        _ = [part async for part in decrypt(chunks(bytes(stored)), KEY, FILE_ID)]


async def test_ciphertext_cannot_be_substituted_between_files_or_keys():
    stored = ciphertext(b"private original")
    for key, file_id in ((KEY, uuid.uuid4()), (DocumentKey("other", b"x" * 32), FILE_ID)):
        with pytest.raises(IntegrityError):
            _ = [part async for part in decrypt(chunks(stored), key, file_id)]
