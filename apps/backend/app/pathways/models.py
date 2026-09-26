"""Processing knowledge: reusable transformation methods and which organizations can run them.

A processor is an ordinary Organization with one or more ProcessorCapability rows —
there is no second identity system. Pathways themselves are computed on demand
(see engine.py) from these rows plus live listings, so they never go stale.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Integer, Numeric, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, JSONType, UUIDPrimaryKey
from app.core.time import utcnow


class ProcessingMethod(UUIDPrimaryKey, Base):
    """Input material --(steps)--> output material.

    ``input_constraints``: rules the raw material must meet, same shape as
    MaterialApplication rules ``{"property_key", "min", "max", "importance"}``.
    ``output_properties``: the declared specification of the product,
    ``{"property_key": value}`` — a method specification, labelled as such in results.
    """

    __tablename__ = "processing_methods"
    __table_args__ = (
        CheckConstraint("expected_yield > 0 AND expected_yield <= 1", name="yield_range"),
        CheckConstraint("processing_time_days >= 0", name="time_nonneg"),
    )

    key: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text)
    input_material_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("materials.id"), index=True)
    output_material_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("materials.id"))
    processing_steps: Mapped[list[str]] = mapped_column(JSONType, default=list)
    input_constraints: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    output_properties: Mapped[dict[str, float]] = mapped_column(JSONType, default=dict)
    expected_yield: Mapped[float] = mapped_column(Float, default=1.0)
    processing_time_days: Mapped[int] = mapped_column(Integer, default=0)
    # Indicative cost used when a processor has not declared its own (always labelled an estimate).
    indicative_cost_per_tonne: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    quality_requirements: Mapped[str | None] = mapped_column(Text)
    source_note: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    input_material = relationship("Material", foreign_keys=[input_material_id], lazy="joined")
    output_material = relationship("Material", foreign_keys=[output_material_id], lazy="joined")


class ProcessorCapability(UUIDPrimaryKey, Base):
    """An organization's ability to run a processing method at a facility."""

    __tablename__ = "processor_capabilities"
    __table_args__ = (
        CheckConstraint("capacity_per_month >= 0", name="capacity_nonneg"),
        CheckConstraint("available_capacity_per_month >= 0", name="available_nonneg"),
        CheckConstraint("available_capacity_per_month <= capacity_per_month", name="available_le_capacity"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    facility_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("facilities.id"))
    method_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("processing_methods.id"), index=True)
    capacity_per_month: Mapped[Decimal] = mapped_column(Numeric(14, 2))           # tonnes of input
    available_capacity_per_month: Mapped[Decimal] = mapped_column(Numeric(14, 2))  # tonnes of input
    processing_cost_per_tonne: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    cost_is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    max_input_distance_km: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    organization = relationship("Organization", lazy="joined")
    facility = relationship("Facility", lazy="joined")
    method = relationship("ProcessingMethod", lazy="joined")
