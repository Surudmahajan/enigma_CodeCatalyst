"""Requirement: something an organization needs."""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Numeric, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.listings import ListingStatus, PropertyImportance
from app.core.database import Base, JSONType, Timestamps, UUIDPrimaryKey, str_enum
from app.materials.units import Frequency, QuantityUnit


class Requirement(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "requirements"
    __table_args__ = (
        CheckConstraint("quantity_required > 0", name="quantity_positive"),
        CheckConstraint("required_until IS NULL OR required_until >= required_from", name="required_order"),
        CheckConstraint("max_transport_distance_km IS NULL OR max_transport_distance_km > 0", name="distance_positive"),
        CheckConstraint("virgin_material_price_per_unit IS NULL OR virgin_material_price_per_unit >= 0",
                        name="virgin_price_nonneg"),
        CheckConstraint("max_price_per_unit IS NULL OR max_price_per_unit >= 0", name="max_price_nonneg"),
        Index("ix_requirements_window", "required_from", "required_until"),
        Index("ix_requirements_status_material", "status", "material_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    facility_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("facilities.id"), index=True)
    # Optional: a demander may not know the canonical material, only what it is for.
    material_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("materials.id"), index=True)
    intended_application_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("application_types.id"), index=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))

    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)

    quantity_required: Mapped[Decimal] = mapped_column(Numeric(16, 3))
    unit: Mapped[QuantityUnit] = mapped_column(str_enum(QuantityUnit))
    frequency: Mapped[Frequency] = mapped_column(str_enum(Frequency))
    required_from: Mapped[date] = mapped_column(Date)
    required_until: Mapped[date | None] = mapped_column(Date)

    max_transport_distance_km: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    # Processing the demander can perform itself, e.g. ["grinding", "screening"].
    processing_capabilities: Mapped[list[str]] = mapped_column(JSONType, default=list)
    # Material categories the demander will consider besides `material_id`.
    acceptable_categories: Mapped[list[str]] = mapped_column(JSONType, default=list)
    # Canonical material ids the demander explicitly refuses (hard constraint).
    excluded_material_ids: Mapped[list[str]] = mapped_column(JSONType, default=list)

    currency: Mapped[str] = mapped_column(String(3), default="INR")
    # Current cost of the virgin material this would replace (user-provided).
    virgin_material_price_per_unit: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    max_price_per_unit: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    economic_constraints: Mapped[str | None] = mapped_column(Text)

    status: Mapped[ListingStatus] = mapped_column(str_enum(ListingStatus), default=ListingStatus.DRAFT, index=True)

    embedding: Mapped[list[float] | None] = mapped_column(JSONType)
    embedding_model: Mapped[str | None] = mapped_column(String(80))

    organization = relationship("Organization", lazy="joined")
    facility = relationship("Facility", lazy="joined")
    material = relationship("Material", lazy="joined")
    intended_application = relationship("ApplicationType", lazy="joined")
    property_constraints = relationship("RequirementPropertyConstraint", back_populates="requirement",
                                        lazy="selectin", cascade="all, delete-orphan")


class RequirementPropertyConstraint(UUIDPrimaryKey, Base):
    """E.g. SiO2 >= 45 % (REQUIRED), moisture <= 10 % (PREFERRED)."""

    __tablename__ = "requirement_property_constraints"
    __table_args__ = (
        UniqueConstraint("requirement_id", "property_id", name="uq_requirement_property"),
        CheckConstraint("min_value IS NULL OR max_value IS NULL OR min_value <= max_value", name="range_order"),
    )

    requirement_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("requirements.id", ondelete="CASCADE"), index=True
    )
    property_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("property_definitions.id"))
    min_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    max_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    text_value: Mapped[str | None] = mapped_column(String(255))
    importance: Mapped[PropertyImportance] = mapped_column(
        str_enum(PropertyImportance), default=PropertyImportance.REQUIRED
    )
    note: Mapped[str | None] = mapped_column(Text)

    requirement: Mapped[Requirement] = relationship(back_populates="property_constraints")
    property = relationship("PropertyDefinition", lazy="joined")
