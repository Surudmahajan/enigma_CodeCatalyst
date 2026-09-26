import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, UUIDPrimaryKey, str_enum
from app.core.state_machine import StateMachine
from app.core.time import utcnow


class ConnectionStatus(StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


_C = ConnectionStatus
CONNECTION_LIFECYCLE = StateMachine[ConnectionStatus]("connection", {
    _C.PENDING: [_C.ACCEPTED, _C.REJECTED, _C.REVOKED, _C.EXPIRED],
    _C.ACCEPTED: [_C.REVOKED],
    _C.REJECTED: [],
    _C.REVOKED: [],
    _C.EXPIRED: [],
})
OPEN_CONNECTION_STATUSES = frozenset({_C.PENDING, _C.ACCEPTED})


class Connection(UUIDPrimaryKey, Base):
    """Mutual authorization for two organizations to communicate about ONE specific match.

    There is no other path to messaging another organization.
    """

    __tablename__ = "connections"
    __table_args__ = (Index("ix_connections_match_status", "match_id", "status"),)

    match_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("matches.id"), index=True)
    initiated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    initiated_by_org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"))
    provider_org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    demander_org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    message: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[ConnectionStatus] = mapped_column(str_enum(ConnectionStatus), default=ConnectionStatus.PENDING,
                                                     index=True)
    responded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    response_note: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    match = relationship("Match", lazy="joined")

    @property
    def recipient_org_id(self) -> uuid.UUID:
        return self.demander_org_id if self.initiated_by_org_id == self.provider_org_id else self.provider_org_id
