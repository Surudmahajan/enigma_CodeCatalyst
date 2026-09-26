import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, JSONType, UUIDPrimaryKey
from app.core.time import utcnow


class AuditLog(UUIDPrimaryKey, Base):
    """Append-only record of important business actions.

    ``details`` holds identifiers and changed field names/values of business
    records; never passwords, tokens or message bodies.
    """

    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_entity", "entity_type", "entity_id"),)

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    details: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    request_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
