import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, JSONType, Timestamps, UUIDPrimaryKey, str_enum
from app.core.time import utcnow


class MatchStatus(StrEnum):
    DISCOVERED = "DISCOVERED"
    VIEWED = "VIEWED"
    INTERESTED = "INTERESTED"
    CONNECTION_REQUESTED = "CONNECTION_REQUESTED"
    CONNECTED = "CONNECTED"
    NEGOTIATING = "NEGOTIATING"
    ACTIVE_EXCHANGE = "ACTIVE_EXCHANGE"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class MatchType(StrEnum):
    EXACT_MATERIAL = "EXACT_MATERIAL"   # same canonical material
    APPLICATION = "APPLICATION"         # different material, compatible for the demander's application
    CATEGORY = "CATEGORY"               # same/accepted material category
    SEMANTIC = "SEMANTIC"               # only semantic similarity: candidate for manual review


class Feasibility(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ConfidenceLevel(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class MatchingConfig(UUIDPrimaryKey, Base):
    """Versioned, configurable scoring parameters (weights are data, not code).

    Exactly one row is active. Changing weights means creating a new version,
    so historical matches remain reproducible via ``Match.matching_version``.
    """

    __tablename__ = "matching_configs"

    version: Mapped[str] = mapped_column(String(32), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    weights: Mapped[dict[str, float]] = mapped_column(JSONType)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONType)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Match(UUIDPrimaryKey, Timestamps, Base):
    """A time-sensitive candidate opportunity between one Resource and one Requirement.

    Not permanent truth: it is re-evaluated when inputs change, and
    ``assessment_snapshot`` records the exact inputs behind the current scores.
    """

    __tablename__ = "matches"
    __table_args__ = (
        UniqueConstraint("resource_id", "requirement_id", name="uq_match_pair"),
        CheckConstraint("overall_score >= 0 AND overall_score <= 1", name="overall_range"),
        CheckConstraint("provider_org_id <> demander_org_id", name="distinct_orgs"),
        Index("ix_matches_provider_status", "provider_org_id", "status"),
        Index("ix_matches_demander_status", "demander_org_id", "status"),
    )

    resource_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("resources.id"), index=True)
    requirement_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("requirements.id"), index=True)
    provider_org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"))
    demander_org_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"))

    matching_version: Mapped[str] = mapped_column(String(32))
    methodology_version: Mapped[str] = mapped_column(String(64))

    material_score: Mapped[float] = mapped_column(Float)
    quantity_score: Mapped[float] = mapped_column(Float)
    location_score: Mapped[float | None] = mapped_column(Float)
    timing_score: Mapped[float] = mapped_column(Float)
    processing_score: Mapped[float] = mapped_column(Float)
    economic_score: Mapped[float | None] = mapped_column(Float)
    environmental_score: Mapped[float | None] = mapped_column(Float)
    overall_score: Mapped[float] = mapped_column(Float, index=True)
    confidence: Mapped[float] = mapped_column(Float)
    confidence_level: Mapped[ConfidenceLevel] = mapped_column(str_enum(ConfidenceLevel))
    feasibility: Mapped[Feasibility] = mapped_column(str_enum(Feasibility))
    requires_manual_review: Mapped[bool] = mapped_column(Boolean, default=False)
    match_type: Mapped[MatchType] = mapped_column(str_enum(MatchType))
    is_hidden_match: Mapped[bool] = mapped_column(Boolean, default=False)

    distance_km: Mapped[Decimal | None] = mapped_column(Numeric(10, 1))
    demand_coverage: Mapped[float] = mapped_column(Float)
    supply_utilization: Mapped[float] = mapped_column(Float)

    explanation: Mapped[dict[str, Any]] = mapped_column(JSONType)
    assessment_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONType)

    status: Mapped[MatchStatus] = mapped_column(str_enum(MatchStatus), default=MatchStatus.DISCOVERED, index=True)
    stale_reason: Mapped[str | None] = mapped_column(String(255))
    rejected_by_org_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("organizations.id"))
    provider_viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    demander_viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_interested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    demander_interested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    resource = relationship("Resource", lazy="joined")
    requirement = relationship("Requirement", lazy="joined")
    provider_org = relationship("Organization", foreign_keys=[provider_org_id], lazy="joined")
    demander_org = relationship("Organization", foreign_keys=[demander_org_id], lazy="joined")
