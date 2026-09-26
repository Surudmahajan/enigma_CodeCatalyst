"""Plain, immutable inputs for the matching engine.

The engine operates only on these dataclasses — never on ORM objects — so
every calculation is deterministic, reproducible from ``assessment_snapshot``
and unit-testable without a database.
"""

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any


@dataclass(frozen=True)
class GeoPoint:
    lat: float
    lon: float


@dataclass(frozen=True)
class MeasuredValue:
    key: str
    name: str
    unit: str | None
    value: float | None
    text: str | None = None


@dataclass(frozen=True)
class TypicalRange:
    key: str
    name: str
    unit: str | None
    low: float | None
    high: float | None


@dataclass(frozen=True)
class ApplicationRule:
    application_key: str
    application_name: str
    rules: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class ResourceProfile:
    id: str
    organization_id: str
    organization_name: str
    name: str
    description: str | None
    material_id: str | None
    material_name: str | None
    category: str | None
    subcategory: str | None
    quantity: float
    unit: str
    frequency: str
    available_from: date
    available_until: date | None
    location: GeoPoint | None
    processing_required: bool
    processing_types: tuple[str, ...]
    current_disposition: str
    currency: str
    disposal_cost_per_unit: float | None = None
    asking_price_per_unit: float | None = None
    processing_cost_per_unit: float | None = None
    measured: dict[str, MeasuredValue] = field(default_factory=dict)       # confirmed values only
    typical: dict[str, TypicalRange] = field(default_factory=dict)         # knowledge-base fallback
    applications: dict[str, ApplicationRule] = field(default_factory=dict)  # from the material's KB entries
    embedding: tuple[float, ...] | None = None


@dataclass(frozen=True)
class ConstraintSpec:
    key: str
    name: str
    unit: str | None
    min: float | None
    max: float | None
    text: str | None
    importance: str  # REQUIRED | PREFERRED | OPTIONAL


@dataclass(frozen=True)
class RequirementProfile:
    id: str
    organization_id: str
    organization_name: str
    name: str
    description: str | None
    material_id: str | None
    material_name: str | None
    category: str | None
    subcategory: str | None
    intended_application_key: str | None
    intended_application_name: str | None
    quantity: float
    unit: str
    frequency: str
    required_from: date
    required_until: date | None
    location: GeoPoint | None
    currency: str
    max_distance_km: float | None = None
    processing_capabilities: tuple[str, ...] = ()
    acceptable_categories: tuple[str, ...] = ()
    excluded_material_ids: tuple[str, ...] = ()
    virgin_material_price_per_unit: float | None = None
    max_price_per_unit: float | None = None
    constraints: tuple[ConstraintSpec, ...] = ()
    embedding: tuple[float, ...] | None = None


@dataclass(frozen=True)
class FactorRef:
    """An emission factor as used in a calculation (copied into the snapshot)."""

    id: str
    key: str
    value: float
    unit: str
    source: str
    version: str
    geography: str
    is_demo_value: bool


@dataclass(frozen=True)
class EnvironmentalFactors:
    transport: FactorRef | None = None
    virgin_production: FactorRef | None = None   # for the material the demander would otherwise buy
    disposal: FactorRef | None = None            # for the provider's current disposition
    processing: FactorRef | None = None


@dataclass(frozen=True)
class MatchingParameters:
    """Resolved from the active ``MatchingConfig`` row. Defaults mirror seed v1.0."""

    version: str = "1.0"
    weights: dict[str, float] = field(default_factory=lambda: {
        "material": 0.30, "quantity": 0.20, "location": 0.15, "timing": 0.10,
        "processing": 0.10, "economic": 0.10, "environmental": 0.05,
    })
    default_max_distance_km: float = 300.0
    candidate_radius_km: float = 2500.0
    open_ended_horizon_days: int = 365
    min_overall_score: float = 0.35
    semantic_candidate_threshold: float = 0.35
    semantic_only_score_cap: float = 0.60
    blocker_score_cap: float = 0.55
    quantity_supply_utilization_weight: float = 0.30
    importance_weights: dict[str, float] = field(default_factory=lambda: {
        "REQUIRED": 1.0, "PREFERRED": 0.6, "OPTIONAL": 0.3,
    })
    transport_cost_per_tonne_km: float | None = None
    transport_cost_currency: str = "INR"
    transport_cost_is_demo: bool = False
    substitution_ratio: float = 1.0
    match_ttl_days: int = 30

    @classmethod
    def from_config(cls, version: str, weights: dict[str, float], parameters: dict[str, Any]) -> "MatchingParameters":
        known = {f for f in cls.__dataclass_fields__ if f not in ("version", "weights")}
        return cls(version=version, weights=dict(weights), **{k: v for k, v in parameters.items() if k in known})


def to_jsonable(obj: Any) -> Any:
    """Serialize engine dataclasses for ``assessment_snapshot``."""
    if hasattr(obj, "__dataclass_fields__"):
        return to_jsonable(asdict(obj))
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, date):
        return obj.isoformat()
    return obj
