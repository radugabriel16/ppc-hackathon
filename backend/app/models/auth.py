"""Application user and session models (cookie-based auth, section 6)."""
import uuid
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, String, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPkMixin
from app.models.enums import UserRole


class AppUser(UUIDPkMixin, Base):
    __tablename__ = "app_users"

    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole, name="user_role"), nullable=False)


class UserSession(UUIDPkMixin, Base):
    __tablename__ = "user_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    csrf_token: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, index=True)
