import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.common.listing_schemas import ListingCommonOut, PropertyValueIn, PropertyValueOut
from app.common.listings import ListingStatus
from app.materials.models import PhysicalState
from app.materials.units import Frequency, QuantityUnit
from app.resources.models import CurrentDisposition

_money = {"ge": 0, "max_digits": 14, "decimal_places": 2}


class ResourceBase(BaseModel):
    material_id: uuid.UUID | None = Field(default=None, description="Canonical material (see /materials)")
    name: str = Field(min_length=2, max_length=200, examples=["Granulated blast furnace slag"])
    description: str | None = Field(default=None, max_length=4000)
    quantity_available: Decimal = Field(gt=0, max_digits=16, decimal_places=3, examples=[2000])
    unit: QuantityUnit = QuantityUnit.TONNE
    frequency: Frequency = Frequency.MONTH
    availability_start: date
    availability_end: date | None = None
    physical_state: PhysicalState = PhysicalState.SOLID
    processing_required: bool = False
    processing_types: list[str] = Field(default_factory=list, max_length=10)
    processing_description: str | None = Field(default=None, max_length=2000)
    storage_notes: str | None = Field(default=None, max_length=2000)
    current_use: str | None = Field(default=None, max_length=2000)
    current_disposition: CurrentDisposition = CurrentDisposition.DISPOSAL
    currency: str = Field(default="INR", pattern=r"^[A-Z]{3}$")
    disposal_cost_per_unit: Decimal | None = Field(default=None, **_money)
    asking_price_per_unit: Decimal | None = Field(default=None, **_money)
    processing_cost_per_unit: Decimal | None = Field(default=None, **_money)


class ResourceCreate(ResourceBase):
    facility_id: uuid.UUID
    properties: list[PropertyValueIn] = Field(default_factory=list, max_length=50)
    publish: bool = Field(default=False, description="Publish immediately (ACTIVE) instead of saving a DRAFT")


class ResourceUpdate(BaseModel):
    facility_id: uuid.UUID | None = None
    material_id: uuid.UUID | None = None
    name: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    quantity_available: Decimal | None = Field(default=None, gt=0, max_digits=16, decimal_places=3)
    unit: QuantityUnit | None = None
    frequency: Frequency | None = None
    availability_start: date | None = None
    availability_end: date | None = None
    physical_state: PhysicalState | None = None
    processing_required: bool | None = None
    processing_types: list[str] | None = Field(default=None, max_length=10)
    processing_description: str | None = None
    storage_notes: str | None = None
    current_use: str | None = None
    current_disposition: CurrentDisposition | None = None
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    disposal_cost_per_unit: Decimal | None = Field(default=None, **_money)
    asking_price_per_unit: Decimal | None = Field(default=None, **_money)
    processing_cost_per_unit: Decimal | None = Field(default=None, **_money)
    properties: list[PropertyValueIn] | None = Field(
        default=None, max_length=50, description="Replaces all user-entered property values when provided"
    )


class ResourceOut(ListingCommonOut):
    quantity_available: Decimal
    unit: QuantityUnit
    frequency: Frequency
    availability_start: date
    availability_end: date | None
    physical_state: PhysicalState
    processing_required: bool
    processing_types: list[str]
    processing_description: str | None
    storage_notes: str | None
    current_use: str | None
    current_disposition: CurrentDisposition
    disposal_cost_per_unit: Decimal | None
    asking_price_per_unit: Decimal | None
    processing_cost_per_unit: Decimal | None
    properties: list[PropertyValueOut]
    created_at: datetime
    updated_at: datetime


class ResourceStatusChange(BaseModel):
    status: ListingStatus
