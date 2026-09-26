"""Resource: something an organization can provide (by-product, residue, surplus, energy stream)."""

import uuid
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
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

from app.common.listings import ListingStatus, ValueSource
from app.core.database import Base, JSONType, Timestamps, UUIDPrimaryKey, str_enum
from app.materials.models import PhysicalState
from app.materials.units import Frequency, QuantityUnit


class CurrentDisposition(StrEnum):
    """What happens to the resource today (the environmental baseline)."""

    DISPOSAL = "DISPOSAL"            # landfill / incineration without recovery
    STORAGE = "STORAGE"              # stockpiled on site
    INTERNAL_USE = "INTERNAL_USE"
    LOW_VALUE_USE = "LOW_VALUE_USE"
    OTHER = "OTHER"


class Resource(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "resources"
    __table_args__ = (
        CheckConstraint("quantity_available > 0", name="quantity_positive"),
        CheckConstraint("availability_end IS NULL OR availability_end >= availability_start", name="availability_order"),
        CheckConstraint("disposal_cost_per_unit IS NULL OR disposal_cost_per_unit >= 0", name="disposal_cost_nonneg"),
        CheckConstraint("asking_price_per_unit IS NULL OR asking_price_per_unit >= 0", name="asking_price_nonneg"),
        CheckConstraint("processing_cost_per_unit IS NULL OR processing_cost_per_unit >= 0", name="processing_cost_nonneg"),
        Index("ix_resources_availability", "availability_start", "availability_end"),
        Index("ix_resources_status_material", "status", "material_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    facility_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("facilities.id"), index=True)
    material_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("materials.id"), index=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))

    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)

    # Declared supply: `quantity_available` `unit` per `frequency` (or a one-time lot).
    quantity_available: Mapped[Decimal] = mapped_column(Numeric(16, 3))
    unit: Mapped[QuantityUnit] = mapped_column(str_enum(QuantityUnit))
    frequency: Mapped[Frequency] = mapped_column(str_enum(Frequency))
    availability_start: Mapped[date] = mapped_column(Date)
    availability_end: Mapped[date | None] = mapped_column(Date)

    physical_state: Mapped[PhysicalState] = mapped_column(str_enum(PhysicalState))
    processing_required: Mapped[bool] = mapped_column(Boolean, default=False)
    processing_types: Mapped[list[str]] = mapped_column(JSONType, default=list)  # e.g. ["grinding", "drying"]
    processing_description: Mapped[str | None] = mapped_column(Text)
    storage_notes: Mapped[str | None] = mapped_column(Text)
    current_use: Mapped[str | None] = mapped_column(Text)
    current_disposition: Mapped[CurrentDisposition] = mapped_column(
        str_enum(CurrentDisposition), default=CurrentDisposition.DISPOSAL
    )

    # Optional user-provided economics (never fabricated; absent => "insufficient data").
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    disposal_cost_per_unit: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    asking_price_per_unit: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    processing_cost_per_unit: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))

    status: Mapped[ListingStatus] = mapped_column(str_enum(ListingStatus), default=ListingStatus.DRAFT, index=True)

    # Semantic retrieval aid (see ai/embeddings.py). JSON float list; pgvector column in production.
    embedding: Mapped[list[float] | None] = mapped_column(JSONType)
    embedding_model: Mapped[str | None] = mapped_column(String(80))

    organization = relationship("Organization", lazy="joined")
    facility = relationship("Facility", lazy="joined")
    material = relationship("Material", lazy="joined")
    property_values = relationship("ResourcePropertyValue", back_populates="resource", lazy="selectin",
                                   cascade="all, delete-orphan")


class ResourcePropertyValue(UUIDPrimaryKey, Base):
    __tablename__ = "resource_property_values"
    __table_args__ = (UniqueConstraint("resource_id", "property_id", name="uq_resource_property"),)

    resource_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("resources.id", ondelete="CASCADE"), index=True)
    property_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("property_definitions.id"))
    value_numeric: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    value_text: Mapped[str | None] = mapped_column(String(255))
    source: Mapped[ValueSource] = mapped_column(str_enum(ValueSource), default=ValueSource.USER_INPUT)
    # AI-extracted values stay unconfirmed (ignored by matching) until a user confirms them.
    confirmed: Mapped[bool] = mapped_column(Boolean, default=True)
    confidence: Mapped[float | None] = mapped_column(Float)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)

    resource: Mapped[Resource] = relationship(back_populates="property_values")
    property = relationship("PropertyDefinition", lazy="joined")
