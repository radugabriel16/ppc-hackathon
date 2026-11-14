"""Versioned, UUID-bound AES-GCM frames with authenticated final-segment markers."""
from __future__ import annotations

import secrets
import struct
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import BinaryIO
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.settings import Settings

SEGMENT_SIZE = 1024 * 1024
MAGIC = b"FGCM1"
FRAME = struct.Struct(">IB")


class IntegrityError(Exception):
    pass


@dataclass(frozen=True)
class DocumentKey:
    id: str
    value: bytes

    @classmethod
    def load(cls, settings: Settings) -> DocumentKey:
        value = bytes.fromhex(settings.storage_secret("aes_key"))
        key_id = settings.storage_secret("aes_key_id")
        if len(value) != 32 or len(key_id) > 128:
            raise ValueError("Document encryption requires a 256-bit key and a valid key id")
        return cls(key_id, value)


def encrypt(source: BinaryIO, target: BinaryIO, key: DocumentKey, file_id: UUID) -> int:
    cipher = AESGCM(key.value)
    prefix = secrets.token_bytes(8)
    target.write(MAGIC + prefix)
    current = source.read(SEGMENT_SIZE)
    counter = 0
    while True:
        following = source.read(SEGMENT_SIZE)
        final = not following
        header = FRAME.pack(len(current), int(final))
        nonce = prefix + counter.to_bytes(4, "big")
        aad = MAGIC + file_id.bytes + nonce + header
        target.write(header)
        target.write(cipher.encrypt(nonce, current, aad))
        if final:
            return target.tell()
        current = following
        counter += 1


class _Reader:
    def __init__(self, chunks: AsyncIterator[bytes]):
        self.chunks = chunks
        self.buffer = bytearray()

    async def read(self, size: int) -> bytes:
        while len(self.buffer) < size:
            chunk = await anext(self.chunks, None)
            if chunk is None:
                break
            self.buffer.extend(chunk)
        result = bytes(self.buffer[:size])
        del self.buffer[:size]
        return result


async def decrypt(
    chunks: AsyncIterator[bytes], key: DocumentKey, file_id: UUID
) -> AsyncIterator[bytes]:
    reader = _Reader(chunks)
    header = await reader.read(len(MAGIC) + 8)
    if len(header) != len(MAGIC) + 8 or not header.startswith(MAGIC):
        raise IntegrityError("Invalid encrypted object header")
    prefix = header[len(MAGIC):]
    cipher = AESGCM(key.value)
    counter = 0
    while True:
        frame = await reader.read(FRAME.size)
        if len(frame) != FRAME.size:
            raise IntegrityError("Missing encrypted segment")
        size, final = FRAME.unpack(frame)
        if size > SEGMENT_SIZE or final not in (0, 1) or (not final and size != SEGMENT_SIZE):
            raise IntegrityError("Invalid encrypted segment")
        payload = await reader.read(size + 16)
        if len(payload) != size + 16:
            raise IntegrityError("Truncated encrypted segment")
        nonce = prefix + counter.to_bytes(4, "big")
        try:
            plaintext = cipher.decrypt(nonce, payload, MAGIC + file_id.bytes + nonce + frame)
        except InvalidTag as exc:
            raise IntegrityError("Encrypted segment authentication failed") from exc
        if final:
            if await reader.read(1):
                raise IntegrityError("Trailing encrypted data")
            yield plaintext
            return
        yield plaintext
        counter += 1
