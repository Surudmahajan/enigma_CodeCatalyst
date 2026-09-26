import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.exchanges.models import ExchangeStatus
from app.materials.units import Frequency, QuantityUnit
from app.organizations.schemas import OrganizationPublic


class ExchangeCreate(BaseModel):
    agreed_quantity: Decimal = Field(gt=0, max_digits=16, decimal_places=3, examples=[1500])
    unit: QuantityUnit = QuantityUnit.TONNE
    agreed_frequency: Frequency = Frequency.MONTH
    agreed_price_per_unit: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    currency: str = Field(default="INR", pattern=r"^[A-Z]{3}$")
    delivery_terms: dict[str, Any] = Field(default_factory=dict,
                                           examples=[{"incoterm": "FCA", "transport": "Road, tipper trucks"}])
    start_date: date
    end_date: date | None = None
    notes: str | None = Field(default=None, max_length=2000)
    upstream_exchange_id: uuid.UUID | None = Field(default=None, description="For multi-step chains (A → B → C)")

    @model_validator(mode="after")
    def _dates(self) -> "ExchangeCreate":
        if self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class ExchangeUpdate(BaseModel):
    agreed_quantity: Decimal | None = Field(default=None, gt=0, max_digits=16, decimal_places=3)
    agreed_frequency: Frequency | None = None
    agreed_price_per_unit: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    delivery_terms: dict[str, Any] | None = None
    start_date: date | None = None
    end_date: date | None = None
    notes: str | None = Field(default=None, max_length=2000)
    status: ExchangeStatus | None = Field(default=None, description="Optional explicit lifecycle transition")
    status_reason: str | None = Field(default=None, max_length=500)
    delivered_quantity: Decimal | None = Field(default=None, ge=0, max_digits=16, decimal_places=3)


class ExchangeComplete(BaseModel):
    delivered_quantity: Decimal | None = Field(
        default=None, ge=0, max_digits=16, decimal_places=3,
        description="Actual total quantity delivered; recorded as a user-reported outcome for impact tracking")
    note: str | None = Field(default=None, max_length=500)


class ExchangeReason(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class ExchangeOut(BaseModel):
    id: uuid.UUID
    match_id: uuid.UUID
    status: ExchangeStatus
    allowed_transitions: list[ExchangeStatus]
    my_side: str
    provider: OrganizationPublic
    demander: OrganizationPublic
    resource_id: uuid.UUID
    requirement_id: uuid.UUID
    resource_name: str
    requirement_name: str
    upstream_exchange_id: uuid.UUID | None
    agreed_quantity: Decimal
    unit: QuantityUnit
    agreed_frequency: Frequency
    agreed_price_per_unit: Decimal | None
    currency: str
    delivery_terms: dict[str, Any]
    start_date: date
    end_date: date | None
    notes: str | None
    delivered_quantity: Decimal | None
    status_reason: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
