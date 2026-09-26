import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, JSONType, UUIDPrimaryKey, str_enum
from app.core.time import utcnow


class MetricType(StrEnum):
    WASTE_DIVERTED = "WASTE_DIVERTED"
    VIRGIN_MATERIAL_AVOIDED = "VIRGIN_MATERIAL_AVOIDED"
    TRANSPORT_EMISSIONS = "TRANSPORT_EMISSIONS"
    PROCESSING_EMISSIONS = "PROCESSING_EMISSIONS"
    NET_CO2E = "NET_CO2E"
    ECONOMIC_VALUE = "ECONOMIC_VALUE"
    ENERGY_RECOVERED = "ENERGY_RECOVERED"
    OTHER = "OTHER"


class ImpactSource(StrEnum):
    """Separates estimates from confirmed outcomes."""

    SYSTEM_ESTIMATE = "SYSTEM_ESTIMATE"      # calculated by the platform from agreed terms
    USER_INPUT = "USER_INPUT"                # calculated from quantities reported by the parties
    VERIFIED_OUTCOME = "VERIFIED_OUTCOME"    # confirmed by a platform verifier


class ImpactRecord(UUIDPrimaryKey, Base):
    """A versioned, explainable impact figure for a completed exchange.

    ``inputs`` and ``assumptions`` store exactly how the value was produced
    (calculation method + version, quantities, distance, factor ids).
    """

    __tablename__ = "impact_records"

    exchange_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("exchanges.id"), index=True)
    match_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("matches.id"), index=True)
    provider_org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    demander_org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    metric_type: Mapped[MetricType] = mapped_column(str_enum(MetricType), index=True)
    value: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    unit: Mapped[str] = mapped_column(String(32))
    calculation_method: Mapped[str] = mapped_column(String(64))
    methodology_version: Mapped[str] = mapped_column(String(64))
    source_type: Mapped[ImpactSource] = mapped_column(str_enum(ImpactSource))
    uses_demo_factors: Mapped[bool] = mapped_column(default=False)
    assumptions: Mapped[list[str]] = mapped_column(JSONType, default=list)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    verified_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
