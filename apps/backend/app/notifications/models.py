import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, JSONType, UUIDPrimaryKey, str_enum
from app.core.time import utcnow


class NotificationType(StrEnum):
    NEW_MATCH = "NEW_MATCH"
    CONNECTION_REQUEST = "CONNECTION_REQUEST"
    CONNECTION_ACCEPTED = "CONNECTION_ACCEPTED"
    CONNECTION_REJECTED = "CONNECTION_REJECTED"
    NEW_MESSAGE = "NEW_MESSAGE"
    RESOURCE_EXPIRING = "RESOURCE_EXPIRING"
    REQUIREMENT_EXPIRING = "REQUIREMENT_EXPIRING"
    LISTING_EXPIRED = "LISTING_EXPIRED"
    EXCHANGE_STATUS_CHANGED = "EXCHANGE_STATUS_CHANGED"


class Notification(UUIDPrimaryKey, Base):
    """In-app notification history (push is best-effort on top of this)."""

    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_created", "user_id", "created_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    organization_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("organizations.id"))
    type: Mapped[NotificationType] = mapped_column(str_enum(NotificationType))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(String(500))
    # Navigation hints for the client, e.g. {"match_id": "..."}; never message content.
    data: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    dedupe_key: Mapped[str | None] = mapped_column(String(120), index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PushToken(UUIDPrimaryKey, Base):
    __tablename__ = "push_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token: Mapped[str] = mapped_column(String(255), unique=True)
    platform: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
