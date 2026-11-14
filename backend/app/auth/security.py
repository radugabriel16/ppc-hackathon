"""Session signing, password hashing and bounded in-process login throttling."""
from __future__ import annotations

import hashlib
import hmac
import math
import secrets
import time
import uuid
from collections import deque
from functools import lru_cache
from pathlib import Path
from threading import Lock

from fastapi import HTTPException
from pwdlib import PasswordHash

from app.core.settings import get_settings

CSRF_COOKIE_NAME = "filegrid_csrf"
PASSWORD_HASH = PasswordHash.recommended()
DUMMY_PASSWORD_HASH = PASSWORD_HASH.hash(secrets.token_urlsafe(32))


@lru_cache
def get_simulator_token() -> str:
    return get_settings().storage_secret("simulator_token")


@lru_cache
def get_session_key() -> bytes:
    key = (Path(get_settings().secrets_dir) / "session_secret").read_bytes().strip()
    if len(key) < 32:
        raise ValueError("session_secret must contain at least 32 bytes")
    return key


def tokens_match(first: str, second: str) -> bool:
    return hmac.compare_digest(first.encode(), second.encode())


def sign_session_id(session_id: uuid.UUID) -> str:
    signature = hmac.new(get_session_key(), session_id.bytes, hashlib.sha256).hexdigest()
    return f"{session_id}.{signature}"


def parse_session_cookie(cookie: str | None) -> uuid.UUID | None:
    if not cookie or len(cookie) != 101:
        return None
    try:
        session_id = uuid.UUID(cookie[:36])
    except ValueError:
        return None
    if not tokens_match(cookie, sign_session_id(session_id)):
        return None
    return session_id


class LoginRateLimiter:
    def __init__(self, limit: int = 10, window_seconds: int = 60, max_keys: int = 1024):
        self.limit = limit
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self._attempts: dict[str, deque[float]] = {}
        self._lock = Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            for existing in list(self._attempts):
                attempts = self._attempts[existing]
                while attempts and attempts[0] <= now - self.window_seconds:
                    attempts.popleft()
                if not attempts:
                    del self._attempts[existing]
            attempts = self._attempts.get(key)
            if attempts is None:
                if len(self._attempts) >= self.max_keys:
                    self._reject(self.window_seconds)
                attempts = self._attempts.setdefault(key, deque())
            if len(attempts) >= self.limit:
                self._reject(math.ceil(attempts[0] + self.window_seconds - now))
            attempts.append(now)

    @staticmethod
    def _reject(retry_after: int) -> None:
        raise HTTPException(
            status_code=429,
            detail={"code": "LOGIN_RATE_LIMITED", "message": "Too many login attempts"},
            headers={"Retry-After": str(max(1, retry_after))},
        )
