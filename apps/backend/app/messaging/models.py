import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, JSONType, Timestamps, UUIDPrimaryKey, str_enum
from app.core.time import utcnow


class ConversationStatus(StrEnum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"   # connection revoked: history stays readable, sending disabled


class MessageType(StrEnum):
    TEXT = "TEXT"
    DOCUMENT = "DOCUMENT"
    SYSTEM = "SYSTEM"
    STRUCTURED_UPDATE = "STRUCTURED_UPDATE"


class Conversation(UUIDPrimaryKey, Timestamps, Base):
    """Private channel scoped to exactly one accepted connection (and therefore one match)."""

    __tablename__ = "conversations"

    match_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("matches.id"), index=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("connections.id"), unique=True)
    status: Mapped[ConversationStatus] = mapped_column(str_enum(ConversationStatus), default=ConversationStatus.ACTIVE)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    participants = relationship("ConversationParticipant", back_populates="conversation", lazy="selectin",
                                cascade="all, delete-orphan")
    match = relationship("Match", lazy="joined")


class ConversationParticipant(UUIDPrimaryKey, Base):
    """Participating organizations. Access resolves through active organization membership,
    so a user never gains access by knowing a conversation id."""

    __tablename__ = "conversation_participants"
    __table_args__ = (UniqueConstraint("conversation_id", "organization_id", name="uq_conversation_org"),)

    conversation_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("conversations.id", ondelete="CASCADE"),
                                                       index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    conversation: Mapped[Conversation] = relationship(back_populates="participants")


class Message(UUIDPrimaryKey, Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_conversation_created", "conversation_id", "created_at"),)

    conversation_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("conversations.id", ondelete="CASCADE"))
    sender_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    sender_organization_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("organizations.id"))
    message_type: Mapped[MessageType] = mapped_column(str_enum(MessageType), default=MessageType.TEXT)
    body: Mapped[str | None] = mapped_column(Text)
    document_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("documents.id"))
    # Client-generated id for idempotent retries from flaky mobile connections.
    client_id: Mapped[str | None] = mapped_column(String(64))
    extra: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    sender = relationship("User", lazy="joined")
    document = relationship("Document", lazy="joined")


class ReadReceipt(UUIDPrimaryKey, Base):
    __tablename__ = "read_receipts"
    __table_args__ = (UniqueConstraint("message_id", "user_id", name="uq_read_receipt"),)

    message_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("messages.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
