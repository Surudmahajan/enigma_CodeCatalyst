import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, UUIDPrimaryKey, str_enum
from app.core.time import utcnow


class ScanStatus(StrEnum):
    NOT_SCANNED = "NOT_SCANNED"   # no scanner configured
    CLEAN = "CLEAN"
    INFECTED = "INFECTED"


class Document(UUIDPrimaryKey, Base):
    """Metadata for a file held in object storage (never stored in PostgreSQL).

    Private by default: visible to the uploading organization, plus the
    parties of the conversation or connected match it is attached to.
    """

    __tablename__ = "documents"
    __table_args__ = (CheckConstraint("file_size > 0", name="size_positive"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    uploaded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("conversations.id"), index=True)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("resources.id"), index=True)
    requirement_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("requirements.id"), index=True)
    file_name: Mapped[str] = mapped_column(String(255))       # sanitized display name
    file_type: Mapped[str] = mapped_column(String(100))       # detected from content, not trusted from the client
    storage_key: Mapped[str] = mapped_column(String(255), unique=True)
    file_size: Mapped[int] = mapped_column(BigInteger)
    checksum_sha256: Mapped[str] = mapped_column(String(64))
    scan_status: Mapped[ScanStatus] = mapped_column(str_enum(ScanStatus), default=ScanStatus.NOT_SCANNED)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
