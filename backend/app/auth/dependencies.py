"""Cookie authentication and reusable role authorization dependencies."""
from collections.abc import Callable
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import parse_session_cookie, tokens_match
from app.core.db import get_catalog_db
from app.core.settings import get_settings
from app.models.auth import AppUser, UserSession
from app.models.enums import UserRole

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def get_current_session(
    request: Request, db: Session = Depends(get_catalog_db)
) -> UserSession:
    session_id = parse_session_cookie(
        request.cookies.get(get_settings().session_cookie_name)
    )
    session = None
    if session_id is not None:
        session = db.scalar(
            select(UserSession).where(
                UserSession.id == session_id,
                UserSession.expires_at > datetime.now(timezone.utc),
            )
        )
    if session is None:
        raise HTTPException(
            status_code=401,
            detail={"code": "UNAUTHENTICATED", "message": "A valid session is required"},
        )
    if request.method not in SAFE_METHODS and not tokens_match(
        request.headers.get("X-CSRF-Token", ""), session.csrf_token
    ):
        raise HTTPException(
            status_code=403,
            detail={"code": "CSRF_REJECTED", "message": "Invalid CSRF token"},
        )
    return session


def get_current_user(
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_catalog_db),
) -> AppUser:
    user = db.get(AppUser, session.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Session user no longer exists")
    return user


def require_role(role: UserRole) -> Callable:
    def check_role(user: AppUser = Depends(get_current_user)) -> AppUser:
        if user.role != role:
            raise HTTPException(
                status_code=403,
                detail={"code": "FORBIDDEN", "message": "Insufficient permissions"},
            )
        return user

    return check_role
