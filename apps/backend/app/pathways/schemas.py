import uuid
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.organizations.schemas import OrganizationPublic

PathwayStatus = Literal["VIABLE", "WEAK", "NOT_VIABLE"]


class PathwayParty(BaseModel):
    organization: OrganizationPublic
    listing_id: uuid.UUID | None = None
    listing_name: str | None = None


class DirectComparison(BaseModel):
    """The raw material sold straight to the same buyer, for side-by-side comparison."""

    eligible: bool
    overall_score: float | None
    reason: str | None


class DirectPathway(BaseModel):
    match_id: uuid.UUID
    buyer: PathwayParty
    status: str
    overall_score: float
    feasibility: str
    distance_km: float | None
    demand_coverage: float
    match_type: str
    strengths: list[str]
    considerations: list[str]


class ProcessedPathway(BaseModel):
    id: str
    status: PathwayStatus
    overall_score: float
    scores: dict[str, float | None]
    method: dict[str, Any]
    processor: PathwayParty
    processor_capacity: dict[str, Any]
    buyer: PathwayParty
    buyer_wants: Literal["RAW", "PROCESSED"]
    input_quantity_t: float
    output_quantity_t: float
    basis: str
    distance_to_processor_km: float | None
    distance_to_buyer_km: float | None
    capacity_status: str
    economics: dict[str, Any]
    environment: dict[str, Any]
    input_checks: list[dict[str, Any]]
    output_checks: list[dict[str, Any]]
    strengths: list[str]
    considerations: list[str]
    blockers: list[str]
    direct_to_same_buyer: DirectComparison
    buyer_match_id: uuid.UUID | None = Field(
        description="An existing opportunity with this buyer, through which the normal connection flow can start")


class Transformation(BaseModel):
    method_key: str
    method_name: str
    steps: list[str]
    output_material: str
    expected_yield: float
    processing_time_days: int
    input_status: Literal["COMPATIBLE", "NEEDS_DATA", "INCOMPATIBLE"]
    processors_found: int


class PathwayReport(BaseModel):
    resource_id: uuid.UUID
    resource_name: str
    material: str | None
    supply: str
    direct: list[DirectPathway]
    processed: list[ProcessedPathway]
    transformations: list[Transformation]
    recommendation: str
    version: str
    disclaimer: str


class ProcessingMethodOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key: str
    name: str
    description: str | None
    processing_steps: list[str]
    expected_yield: float
    processing_time_days: int
    indicative_cost_per_tonne: Decimal | None
    source_note: str | None


class CapabilityIn(BaseModel):
    method_key: str
    facility_id: uuid.UUID
    capacity_per_month: Decimal = Field(ge=0)
    available_capacity_per_month: Decimal = Field(ge=0)
    processing_cost_per_tonne: Decimal | None = Field(default=None, ge=0)
    max_input_distance_km: Decimal | None = Field(default=None, gt=0)
    notes: str | None = Field(default=None, max_length=1000)


class CapabilityOut(BaseModel):
    id: uuid.UUID
    method_key: str
    method_name: str
    facility_id: uuid.UUID
    capacity_per_month: Decimal
    available_capacity_per_month: Decimal
    processing_cost_per_tonne: Decimal | None
    cost_is_demo: bool
    max_input_distance_km: Decimal | None
