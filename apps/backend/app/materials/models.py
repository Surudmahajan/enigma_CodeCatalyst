"""Normalized material knowledge base.

Matching never relies on free-text names alone (locked principle 7). Listings
point at a canonical ``Material``; technical values reference shared
``PropertyDefinition`` rows, so a provider's "SiO2 = 52 %" and a demander's
"SiO2 >= 45 %" are directly comparable.
"""

import uuid
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Numeric, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, JSONType, Timestamps, UUIDPrimaryKey, str_enum


class PhysicalState(StrEnum):
    SOLID = "SOLID"
    LIQUID = "LIQUID"
    GAS = "GAS"
    SLUDGE = "SLUDGE"
    ENERGY = "ENERGY"
    OTHER = "OTHER"


class PropertyDataType(StrEnum):
    NUMERIC = "NUMERIC"
    TEXT = "TEXT"
    BOOLEAN = "BOOLEAN"


class Material(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "materials"

    canonical_name: Mapped[str] = mapped_column(String(160), unique=True)
    category: Mapped[str] = mapped_column(String(80), index=True)
    subcategory: Mapped[str | None] = mapped_column(String(80), index=True)
    physical_state: Mapped[PhysicalState] = mapped_column(str_enum(PhysicalState))
    description: Mapped[str | None] = mapped_column(Text)
    # Alternative trade names used for classification and search ("GBFS", "BF slag" ...)
    synonyms: Mapped[list[str]] = mapped_column(JSONType, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    properties = relationship("MaterialProperty", back_populates="material", lazy="selectin",
                              cascade="all, delete-orphan")


class PropertyDefinition(UUIDPrimaryKey, Base):
    """A measurable characteristic, e.g. ``sio2_pct`` (SiO2, %)."""

    __tablename__ = "property_definitions"

    key: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    unit: Mapped[str | None] = mapped_column(String(32))
    data_type: Mapped[PropertyDataType] = mapped_column(str_enum(PropertyDataType), default=PropertyDataType.NUMERIC)
    description: Mapped[str | None] = mapped_column(Text)
    # Physically plausible bounds used for input validation (not for matching).
    valid_min: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    valid_max: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    # Alternative spellings recognised by document extraction ("SiO₂", "silica").
    aliases: Mapped[list[str]] = mapped_column(JSONType, default=list)


class MaterialProperty(UUIDPrimaryKey, Base):
    """Typical property range for a material (knowledge base, not a listing value).

    Used only as a clearly-labelled fallback when a listing has no measured
    value, and it lowers match confidence when used.
    """

    __tablename__ = "material_properties"
    __table_args__ = (
        UniqueConstraint("material_id", "property_id", name="uq_material_property"),
        CheckConstraint("typical_min IS NULL OR typical_max IS NULL OR typical_min <= typical_max",
                        name="typical_range"),
    )

    material_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("materials.id", ondelete="CASCADE"), index=True)
    property_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("property_definitions.id", ondelete="CASCADE"))
    typical_min: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    typical_max: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    note: Mapped[str | None] = mapped_column(Text)

    material: Mapped[Material] = relationship(back_populates="properties")
    property: Mapped[PropertyDefinition] = relationship(lazy="joined")


class ApplicationType(UUIDPrimaryKey, Base):
    """An industrial use, e.g. ``cement_blending`` or ``road_subbase``.

    Requirements may declare the application they need material *for*; that is
    how the engine discovers hidden matches between differently named materials.
    """

    __tablename__ = "application_types"

    key: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text)
    applicable_industry_sectors: Mapped[list[str]] = mapped_column(JSONType, default=list)


class MaterialApplication(UUIDPrimaryKey, Base):
    """Curated knowledge that a material can serve an application, subject to
    property conditions.

    ``required_properties`` is a list of
    ``{"property_key": str, "min": float|None, "max": float|None, "importance": "REQUIRED"|...}``.
    """

    __tablename__ = "material_applications"
    __table_args__ = (UniqueConstraint("material_id", "application_type_id", name="uq_material_application"),)

    material_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("materials.id", ondelete="CASCADE"), index=True)
    application_type_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("application_types.id", ondelete="CASCADE"), index=True
    )
    description: Mapped[str | None] = mapped_column(Text)
    required_properties: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    source_note: Mapped[str | None] = mapped_column(Text)

    material: Mapped[Material] = relationship(lazy="joined")
    application_type: Mapped[ApplicationType] = relationship(lazy="joined")
