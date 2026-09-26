import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Numeric, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, UUIDPrimaryKey, str_enum
from app.core.time import utcnow


class FactorScope(StrEnum):
    TRANSPORT = "TRANSPORT"                  # kgCO2e per tonne-km
    VIRGIN_PRODUCTION = "VIRGIN_PRODUCTION"  # kgCO2e per tonne of virgin material displaced
    DISPOSAL = "DISPOSAL"                    # kgCO2e per tonne under the current disposition
    PROCESSING = "PROCESSING"                # kgCO2e per tonne processed


class EmissionFactor(UUIDPrimaryKey, Base):
    """Versioned emission factor with explicit provenance.

    Factors are never invented at calculation time: the environmental
    assessment only uses rows from this table, and every result lists the
    factor ids, sources and versions it used. ``is_demo_value`` marks
    illustrative factors that must be replaced before real-world reporting.
    """

    __tablename__ = "emission_factors"
    __table_args__ = (
        CheckConstraint("value >= 0", name="value_nonneg"),
        CheckConstraint("valid_until IS NULL OR valid_until >= valid_from", name="validity_order"),
    )

    key: Mapped[str] = mapped_column(String(80), index=True)
    scope: Mapped[FactorScope] = mapped_column(str_enum(FactorScope), index=True)
    # Optional selectors: which material/application/disposition this factor applies to.
    material_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("materials.id"))
    application_type_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("application_types.id"))
    disposition: Mapped[str | None] = mapped_column(String(32))
    value: Mapped[Decimal] = mapped_column(Numeric(14, 6))
    unit: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(Text)
    geography: Mapped[str] = mapped_column(String(80))
    methodology: Mapped[str] = mapped_column(Text)
    version: Mapped[str] = mapped_column(String(32))
    valid_from: Mapped[date] = mapped_column(Date)
    valid_until: Mapped[date | None] = mapped_column(Date)
    is_demo_value: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    material = relationship("Material", lazy="joined")
    application_type = relationship("ApplicationType", lazy="joined")
