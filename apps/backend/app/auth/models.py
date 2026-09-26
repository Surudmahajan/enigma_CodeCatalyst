import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, UUIDPrimaryKey, str_enum
from app.core.time import utcnow


class RefreshToken(UUIDPrimaryKey, Base):
    """Server-side record of issued refresh tokens, enabling rotation and logout.

    Only a SHA-256 hash of the token id (jti) is stored.
    """

    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    jti_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UserTokenPurpose(StrEnum):
    PASSWORD_RESET = "PASSWORD_RESET"
    EMAIL_VERIFICATION = "EMAIL_VERIFICATION"


class UserToken(UUIDPrimaryKey, Base):
    """Single-use tokens for password reset and email verification (hash only)."""

    __tablename__ = "user_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    purpose: Mapped[UserTokenPurpose] = mapped_column(str_enum(UserTokenPurpose))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
