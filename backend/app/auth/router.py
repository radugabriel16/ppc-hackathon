"""Cookie-session login, logout and current identity."""
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_session, get_current_user
from app.auth.security import (
    CSRF_COOKIE_NAME,
    DUMMY_PASSWORD_HASH,
    PASSWORD_HASH,
    parse_session_cookie,
    sign_session_id,
)
from app.core.db import get_catalog_db
from app.core.logging import get_request_id
from app.core.settings import get_settings
from app.models.audit import AuditEvent
from app.models.auth import AppUser, UserSession
from app.models.enums import UserRole

router = APIRouter(prefix="/api/v1", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024, repr=False)


class Me(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    role: UserRole


def check_login_limit(request: Request) -> None:
    # Use the transport peer, not attacker-controlled forwarding headers.
    peer = request.client.host if request.client else "unknown"
    request.app.state.login_rate_limiter.check(peer)


@router.post("/auth/login", response_model=Me, dependencies=[Depends(check_login_limit)])
def login(
    credentials: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_catalog_db),
) -> AppUser:
    user = db.scalar(select(AppUser).where(AppUser.username == credentials.username))
    password_hash = user.password_hash if user else DUMMY_PASSWORD_HASH
    valid = PASSWORD_HASH.verify(credentials.password, password_hash)
    now = datetime.now(timezone.utc)
    db.add(
        AuditEvent(
            actor_id=user.id if user else None,
            action="LOGIN" if valid and user else "LOGIN_FAILED",
            entity_type="app_user",
            entity_id=user.id if user else None,
            occurred_at=now,
            request_id=(get_request_id() or "")[:64] or None,
        )
    )
    if user is None or not valid:
        db.commit()
        raise HTTPException(
            status_code=401,
            detail={"code": "INVALID_CREDENTIALS", "message": "Invalid username or password"},
        )

    settings = get_settings()
    previous_id = parse_session_cookie(request.cookies.get(settings.session_cookie_name))
    if previous_id is not None:
        db.execute(delete(UserSession).where(UserSession.id == previous_id))
    session = UserSession(
        id=uuid.uuid4(),
        user_id=user.id,
        csrf_token=secrets.token_urlsafe(32),
        created_at=now,
        expires_at=now + timedelta(seconds=settings.session_ttl_seconds),
    )
    db.add(session)
    db.commit()
    response.set_cookie(
        settings.session_cookie_name,
        sign_session_id(session.id),
        max_age=settings.session_ttl_seconds,
        secure=True,
        httponly=True,
        samesite="lax",
    )
    response.set_cookie(
        CSRF_COOKIE_NAME,
        session.csrf_token,
        max_age=settings.session_ttl_seconds,
        secure=True,
        httponly=False,
        samesite="lax",
    )
    return user


@router.get("/auth/me", response_model=Me)
def me(user: AppUser = Depends(get_current_user)) -> AppUser:
    return user


@router.post("/auth/logout", status_code=204)
def logout(
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_catalog_db),
) -> Response:
    db.delete(session)
    db.commit()
    response = Response(status_code=204)
    response.delete_cookie(
        get_settings().session_cookie_name, secure=True, httponly=True, samesite="lax"
    )
    response.delete_cookie(CSRF_COOKIE_NAME, secure=True, samesite="lax")
    return response
