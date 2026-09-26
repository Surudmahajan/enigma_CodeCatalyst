"""SYMBIO matching engine: evaluates one Resource × Requirement pair.

Pipeline (spec §15, master prompt §25):

    1. Eligibility / hard constraints  (unit family, exclusions, timing, max distance,
                                        REQUIRED properties, material relatedness)
    2. Material compatibility           (exact → application → category → semantic)
    3. Property compatibility           (REQUIRED / PREFERRED / OPTIONAL)
    4. Quantity compatibility           (normalized per-month coverage, partial allowed)
    5. Timing compatibility             (interval overlap)
    6. Geographic feasibility           (Haversine distance decay)
    7. Processing feasibility
    8. Economic assessment              (transparent line items; may be unavailable)
    9. Environmental assessment         (versioned factors; may be unavailable)
   10. Composite opportunity score      (configurable weights, renormalized over
                                        available components, capped by blockers)
   11. Data confidence + explanation

Hard constraints are never converted into a low score: a failed mandatory
condition makes the pair ineligible, with explicit reasons.
"""

from dataclasses import dataclass, field
from datetime import date

from app.assessment.economic import EconomicAssessment, EconomicStatus, assess_economics
from app.assessment.economic import VERSION as ECONOMIC_VERSION
from app.assessment.environmental import EnvironmentalAssessment, EnvironmentalStatus, assess_environment
from app.assessment.environmental import VERSION as ENVIRONMENTAL_VERSION
from app.matching import components as c
from app.matching.types import EnvironmentalFactors, MatchingParameters, RequirementProfile, ResourceProfile

METHODOLOGY_VERSION = f"economic-{ECONOMIC_VERSION}+environmental-{ENVIRONMENTAL_VERSION}"


@dataclass
class MatchEvaluation:
    eligible: bool
    failures: list[c.Failure] = field(default_factory=list)
    material: c.MaterialResult | None = None
    quantity: c.QuantityResult | None = None
    timing: c.TimingResult | None = None
    location: c.LocationResult | None = None
    processing: c.ProcessingResult | None = None
    economic: EconomicAssessment | None = None
    environmental: EnvironmentalAssessment | None = None
    scores: dict[str, float | None] = field(default_factory=dict)
    overall_score: float = 0.0
    caps_applied: list[str] = field(default_factory=list)
    confidence: float = 0.0
    confidence_level: str = "LOW"
    confidence_gaps: list[str] = field(default_factory=list)
    feasibility: str = "LOW"
    requires_manual_review: bool = False
    match_type: str | None = None
    is_hidden_match: bool = False


def composite_score(scores: dict[str, float | None], weights: dict[str, float]) -> float:
    """Weighted mean over the components that could be computed.

    Unavailable components (``None``) are excluded and the remaining weights
    renormalized, instead of inventing a value for them.
    """
    available = {k: v for k, v in scores.items() if v is not None and weights.get(k, 0) > 0}
    total = sum(weights[k] for k in available)
    if total == 0:
        return 0.0
    return sum(weights[k] * v for k, v in available.items()) / total


def _confidence(ev: MatchEvaluation, resource: ResourceProfile, requirement: RequirementProfile) -> None:
    """Data confidence: how complete and trustworthy the inputs are.

    Reported separately from compatibility, because an 85 % score built on
    complete measured data is not equivalent to 85 % built on assumptions.
    Each check is (weight, credit in [0, 1], gap message shown when credit < 1).
    """
    checks: list[tuple[float, float, str]] = [
        (1.0, float(resource.material_id is not None), "The provider has not linked a normalized material."),
    ]
    constraint_checks = ev.material.properties.checks if ev.material else []
    if constraint_checks:
        measured_share = sum(1 for ch in constraint_checks if ch.measured) / len(constraint_checks)
        checks.append((2.0, measured_share, "Some technical constraints are not backed by measured values."))
    else:
        checks.append((1.0, 0.0, "The demander stated no technical constraints to verify."))
    checks.append((1.0, float(ev.location is not None and ev.location.distance_km is not None),
                   "Facility coordinates are missing, so distance is unknown."))
    checks.append((1.0, float(ev.economic is not None and ev.economic.status == EconomicStatus.COMPLETE),
                   "Economic inputs are incomplete."))
    env_ok = (ev.environmental is not None and ev.environmental.status == EnvironmentalStatus.COMPLETE
              and not ev.environmental.uses_demo_factors)
    checks.append((1.0, float(env_ok), "Environmental figures rely on incomplete or illustrative factors."))
    if ev.material and ev.material.basis == c.MaterialBasis.SEMANTIC:
        checks.append((2.0, 0.0, "The material link is based only on text similarity."))

    total = sum(weight for weight, _, _ in checks)
    earned = sum(weight * credit for weight, credit, _ in checks)
    gaps = [gap for _, credit, gap in checks if credit < 1.0]
    if ev.location is not None and ev.location.distance_km is not None:
        gaps.append("Transport estimate uses straight-line distance and is approximate.")
    ev.confidence = round(earned / total, 4)
    ev.confidence_level = "HIGH" if ev.confidence >= 0.75 else "MEDIUM" if ev.confidence >= 0.45 else "LOW"
    ev.confidence_gaps = gaps


def evaluate_pair(resource: ResourceProfile, requirement: RequirementProfile, params: MatchingParameters,
                  factors: EnvironmentalFactors, today: date) -> MatchEvaluation:
    ev = MatchEvaluation(eligible=False)

    quantity = c.evaluate_quantity(resource, requirement, params)
    if isinstance(quantity, c.Failure):
        ev.failures.append(quantity)
        return ev  # incomparable units: nothing else is meaningful
    ev.quantity = quantity

    ev.material = c.evaluate_material(resource, requirement, params)
    ev.failures.extend(ev.material.failures)

    timing = c.evaluate_timing(resource, requirement, params, today)
    if isinstance(timing, c.Failure):
        ev.failures.append(timing)
    else:
        ev.timing = timing

    location = c.evaluate_location(resource, requirement, params)
    if isinstance(location, c.Failure):
        ev.failures.append(location)
    else:
        ev.location = location

    ev.processing = c.evaluate_processing(resource, requirement)
    if ev.failures:
        return ev

    distance = ev.location.distance_km if ev.location else None
    ev.economic = assess_economics(resource, requirement, quantity.exchanged, quantity.base_unit, quantity.basis,
                                   distance, params)
    ev.environmental = assess_environment(resource, quantity.exchanged, quantity.base_unit, quantity.basis, distance,
                                          resource.processing_required, factors, params)

    ev.scores = {
        "material": ev.material.score,
        "quantity": quantity.score,
        "location": ev.location.score if ev.location else None,
        "timing": ev.timing.score if ev.timing else None,
        "processing": ev.processing.score,
        "economic": ev.economic.score,
        "environmental": ev.environmental.score,
    }
    overall = composite_score(ev.scores, params.weights)

    blockers = []
    if ev.processing.is_blocker:
        blockers.append("processing")
    if ev.economic.direction and ev.economic.direction.value == "NEGATIVE_POTENTIAL":
        blockers.append("economics")
    if blockers and overall > params.blocker_score_cap:
        overall = params.blocker_score_cap
        ev.caps_applied.append(f"Capped at {params.blocker_score_cap:.0%} because of: {', '.join(blockers)}.")
    if ev.material.basis == c.MaterialBasis.SEMANTIC and overall > params.semantic_only_score_cap:
        overall = params.semantic_only_score_cap
        ev.caps_applied.append(f"Capped at {params.semantic_only_score_cap:.0%}: material link is text similarity only.")
    ev.overall_score = round(overall, 4)

    uncertain_required = any(
        ch.importance == "REQUIRED" and ch.outcome in (c.PropertyOutcome.UNCERTAIN, c.PropertyOutcome.UNKNOWN,
                                                       c.PropertyOutcome.LIKELY_FAIL)
        for ch in ev.material.properties.checks
    )
    ev.requires_manual_review = bool(blockers) or ev.material.basis == c.MaterialBasis.SEMANTIC or uncertain_required
    if blockers or ev.overall_score < 0.5:
        ev.feasibility = "LOW"
    elif ev.overall_score >= 0.75 and not ev.requires_manual_review:
        ev.feasibility = "HIGH"
    else:
        ev.feasibility = "MEDIUM"

    basis = ev.material.basis
    ev.match_type = {c.MaterialBasis.EXACT_MATERIAL: "EXACT_MATERIAL", c.MaterialBasis.APPLICATION: "APPLICATION",
                     c.MaterialBasis.SEMANTIC: "SEMANTIC"}.get(basis, "CATEGORY")
    ev.is_hidden_match = ev.material.is_hidden_match
    _confidence(ev, resource, requirement)
    ev.eligible = ev.overall_score >= params.min_overall_score
    if not ev.eligible:
        ev.failures.append(c.Failure(c.HardFailure.BELOW_THRESHOLD,
                                     f"Overall score {ev.overall_score:.0%} is below the surfacing threshold "
                                     f"{params.min_overall_score:.0%}."))
    return ev
