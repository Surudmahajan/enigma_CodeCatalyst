import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Numeric, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, JSONType, Timestamps, UUIDPrimaryKey, str_enum
from app.core.state_machine import StateMachine
from app.materials.units import Frequency, QuantityUnit


class ExchangeStatus(StrEnum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


_E = ExchangeStatus
EXCHANGE_LIFECYCLE = StateMachine[ExchangeStatus]("exchange", {
    _E.PLANNED: [_E.IN_PROGRESS, _E.PAUSED, _E.CANCELLED],
    _E.IN_PROGRESS: [_E.COMPLETED, _E.PAUSED, _E.CANCELLED, _E.FAILED],
    _E.PAUSED: [_E.IN_PROGRESS, _E.CANCELLED],
    _E.COMPLETED: [],
    _E.CANCELLED: [],
    _E.FAILED: [],
})
OPEN_EXCHANGE_STATUSES = frozenset({_E.PLANNED, _E.IN_PROGRESS, _E.PAUSED})


class Exchange(UUIDPrimaryKey, Timestamps, Base):
    """The actual commercial/operational relationship that follows a match.

    ``upstream_exchange_id`` allows chaining (Provider A -> Processor B ->
    Demander C) without changing the schema later.
    """

    __tablename__ = "exchanges"
    __table_args__ = (
        CheckConstraint("agreed_quantity > 0", name="quantity_positive"),
        CheckConstraint("end_date IS NULL OR end_date >= start_date", name="date_order"),
        CheckConstraint("delivered_quantity IS NULL OR delivered_quantity >= 0", name="delivered_nonneg"),
    )

    match_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("matches.id"), index=True)
    provider_org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    demander_org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    resource_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("resources.id"))
    requirement_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("requirements.id"))
    upstream_exchange_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("exchanges.id"))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))

    agreed_quantity: Mapped[Decimal] = mapped_column(Numeric(16, 3))
    unit: Mapped[QuantityUnit] = mapped_column(str_enum(QuantityUnit))
    agreed_frequency: Mapped[Frequency] = mapped_column(str_enum(Frequency))
    agreed_price_per_unit: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    delivery_terms: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)

    status: Mapped[ExchangeStatus] = mapped_column(str_enum(ExchangeStatus), default=ExchangeStatus.PLANNED, index=True)
    delivered_quantity: Mapped[Decimal | None] = mapped_column(Numeric(16, 3))
    status_reason: Mapped[str | None] = mapped_column(String(500))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    match = relationship("Match", lazy="joined")
    provider_org = relationship("Organization", foreign_keys=[provider_org_id], lazy="joined")
    demander_org = relationship("Organization", foreign_keys=[demander_org_id], lazy="joined")
