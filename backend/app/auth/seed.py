"""Create missing demo accounts without changing existing credentials or data."""
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import PASSWORD_HASH
from app.core.settings import get_settings
from app.models.auth import AppUser
from app.models.enums import UserRole


def seed_users(db: Session) -> None:
    for username, role in (("operator", UserRole.OPERATOR), ("manager", UserRole.MANAGER)):
        if db.scalar(select(AppUser.id).where(AppUser.username == username)) is not None:
            continue
        password = (
            Path(get_settings().secrets_dir) / f"{username}_password"
        ).read_text().strip()
        if not password:
            raise ValueError(f"{username}_password must not be empty")
        db.add(
            AppUser(
                id=uuid.uuid5(uuid.NAMESPACE_URL, f"filegrid:user-{username}"),
                username=username,
                password_hash=PASSWORD_HASH.hash(password),
                role=role,
            )
        )
    db.commit()
