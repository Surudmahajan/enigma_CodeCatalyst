"""Schemas shared by Resource and Requirement APIs."""

import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.common.listings import ListingStatus, PropertyImportance, ValueSource
from app.materials.schemas import MaterialSummary
from app.organizations.schemas import LocationPublic


class PropertyValueIn(BaseModel):
    """A measured/declared value on a Resource, e.g. ``{"property_key": "sio2_pct", "value_numeric": 52}``."""

    property_key: str = Field(max_length=64)
    value_numeric: Decimal | None = None
    value_text: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def _one_value(self) -> "PropertyValueIn":
        if (self.value_numeric is None) == (self.value_text is None):
            raise ValueError("Provide exactly one of value_numeric or value_text.")
        return self


class PropertyValueOut(BaseModel):
    id: uuid.UUID
    property_key: str
    property_name: str
    unit: str | None
    value_numeric: Decimal | None
    value_text: str | None
    source: ValueSource
    confirmed: bool
    confidence: float | None


class PropertyConstraintIn(BaseModel):
    """A demander's constraint, e.g. SiO2 >= 45 (REQUIRED)."""

    property_key: str = Field(max_length=64)
    min_value: Decimal | None = None
    max_value: Decimal | None = None
    text_value: str | None = Field(default=None, max_length=255)
    importance: PropertyImportance = PropertyImportance.REQUIRED

    @model_validator(mode="after")
    def _has_bound(self) -> "PropertyConstraintIn":
        if self.min_value is None and self.max_value is None and self.text_value is None:
            raise ValueError("A constraint needs min_value, max_value or text_value.")
        if self.min_value is not None and self.max_value is not None and self.min_value > self.max_value:
            raise ValueError("min_value cannot exceed max_value.")
        return self


class PropertyConstraintOut(BaseModel):
    id: uuid.UUID
    property_key: str
    property_name: str
    unit: str | None
    min_value: Decimal | None
    max_value: Decimal | None
    text_value: str | None
    importance: PropertyImportance


class FacilityRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    location: LocationPublic


class ListingCommonOut(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    facility: FacilityRef
    material: MaterialSummary | None
    name: str
    description: str | None
    status: ListingStatus
    allowed_transitions: list[ListingStatus]
    currency: str

