import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.materials.schemas import ApplicationTypeOut, MaterialSummary
from app.materials.units import Frequency, QuantityUnit
from app.matching.models import ConfidenceLevel, Feasibility, MatchStatus, MatchType
from app.organizations.schemas import LocationPrivate, LocationPublic, OrganizationPublic


class ComponentScores(BaseModel):
    material: float
    quantity: float
    location: float | None
    timing: float
    processing: float
    economic: float | None
    environmental: float | None


class CounterpartContact(BaseModel):
    """Revealed only after a connection is accepted."""

    legal_name: str
    business_email: str | None
    business_phone: str | None
    website: str | None
    facility_name: str
    facility_location: LocationPrivate


class ListingView(BaseModel):
    """Listing details as visible to the viewer (own side: full; counterpart: limited until connected)."""

    id: uuid.UUID
    kind: Literal["RESOURCE", "REQUIREMENT"]
    name: str
    material: MaterialSummary | None
    intended_application: ApplicationTypeOut | None = None
    quantity: Decimal
    unit: QuantityUnit
    frequency: Frequency
    window_start: date
    window_end: date | None
    processing_required: bool | None = None
    processing_types: list[str] = []
    location: LocationPublic
    status: str
    description: str | None = None           # connected or own side only
    commercial_terms: dict[str, Any] | None = None  # prices etc.; connected or own side only


class MatchSummary(BaseModel):
    id: uuid.UUID
    status: MatchStatus
    my_side: Literal["PROVIDER", "DEMANDER"]
    counterpart: OrganizationPublic
    my_listing_id: uuid.UUID
    my_listing_name: str
    counterpart_listing_name: str
    material_name: str | None
    overall_score: float
    confidence_level: ConfidenceLevel
    feasibility: Feasibility
    match_type: MatchType
    is_hidden_match: bool
    requires_manual_review: bool
    distance_km: float | None
    demand_coverage: float
    supply_utilization: float
    headline: str
    top_strengths: list[str]
    top_considerations: list[str]
    is_new: bool
    stale_reason: str | None
    updated_at: datetime
    expires_at: datetime | None


class MatchDetail(MatchSummary):
    scores: ComponentScores
    confidence: float
    explanation: dict[str, Any]
    economic: dict[str, Any] | None
    environmental: dict[str, Any] | None
    resource: ListingView
    requirement: ListingView
    counterpart_contact: CounterpartContact | None
    connection: dict[str, Any] | None
    exchange_id: uuid.UUID | None
    allowed_actions: list[str]
    matching_version: str
    methodology_version: str
    last_evaluated_at: datetime
    created_at: datetime


class RejectRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=200)


class SearchRequest(BaseModel):
    resource_id: uuid.UUID | None = None
    requirement_id: uuid.UUID | None = None
