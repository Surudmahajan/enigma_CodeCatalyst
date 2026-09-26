import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.common.listing_schemas import ListingCommonOut, PropertyConstraintIn, PropertyConstraintOut
from app.common.listings import ListingStatus
from app.materials.schemas import ApplicationTypeOut
from app.materials.units import Frequency, QuantityUnit

_money = {"ge": 0, "max_digits": 14, "decimal_places": 2}


class RequirementBase(BaseModel):
    material_id: uuid.UUID | None = Field(default=None, description="Canonical material, if known")
    intended_application_id: uuid.UUID | None = Field(
        default=None, description="What the material is for (enables hidden matches across material names)"
    )
    name: str = Field(min_length=2, max_length=200, examples=["Slag aggregate for road sub-base"])
    description: str | None = Field(default=None, max_length=4000)
    quantity_required: Decimal = Field(gt=0, max_digits=16, decimal_places=3, examples=[1500])
    unit: QuantityUnit = QuantityUnit.TONNE
    frequency: Frequency = Frequency.MONTH
    required_from: date
    required_until: date | None = None
    max_transport_distance_km: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)
    processing_capabilities: list[str] = Field(default_factory=list, max_length=20)
    acceptable_categories: list[str] = Field(default_factory=list, max_length=20)
    excluded_material_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    currency: str = Field(default="INR", pattern=r"^[A-Z]{3}$")
    virgin_material_price_per_unit: Decimal | None = Field(default=None, **_money)
    max_price_per_unit: Decimal | None = Field(default=None, **_money)
    economic_constraints: str | None = Field(default=None, max_length=2000)


class RequirementCreate(RequirementBase):
    facility_id: uuid.UUID
    property_constraints: list[PropertyConstraintIn] = Field(default_factory=list, max_length=50)
    publish: bool = False


class RequirementUpdate(BaseModel):
    facility_id: uuid.UUID | None = None
    material_id: uuid.UUID | None = None
    intended_application_id: uuid.UUID | None = None
    name: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    quantity_required: Decimal | None = Field(default=None, gt=0, max_digits=16, decimal_places=3)
    unit: QuantityUnit | None = None
    frequency: Frequency | None = None
    required_from: date | None = None
    required_until: date | None = None
    max_transport_distance_km: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)
    processing_capabilities: list[str] | None = Field(default=None, max_length=20)
    acceptable_categories: list[str] | None = Field(default=None, max_length=20)
    excluded_material_ids: list[uuid.UUID] | None = Field(default=None, max_length=50)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    virgin_material_price_per_unit: Decimal | None = Field(default=None, **_money)
    max_price_per_unit: Decimal | None = Field(default=None, **_money)
    economic_constraints: str | None = None
    property_constraints: list[PropertyConstraintIn] | None = Field(default=None, max_length=50)


class RequirementOut(ListingCommonOut):
    intended_application: ApplicationTypeOut | None
    quantity_required: Decimal
    unit: QuantityUnit
    frequency: Frequency
    required_from: date
    required_until: date | None
    max_transport_distance_km: Decimal | None
    processing_capabilities: list[str]
    acceptable_categories: list[str]
    excluded_material_ids: list[uuid.UUID]
    virgin_material_price_per_unit: Decimal | None
    max_price_per_unit: Decimal | None
    economic_constraints: str | None
    property_constraints: list[PropertyConstraintOut]
    created_at: datetime
    updated_at: datetime


class RequirementStatusChange(BaseModel):
    status: ListingStatus
