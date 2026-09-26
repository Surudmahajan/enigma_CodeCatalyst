"""Component evaluators of the matching pipeline.

Each evaluator is a pure function returning a score in [0, 1] (or ``None``
when it cannot be computed from the available data), a categorical outcome
and human-readable evidence built only from the input data. See
docs/matching-engine.md for the rationale behind every formula.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import StrEnum

from app.ai.embeddings import cosine
from app.materials import units
from app.matching.geo import haversine_km
from app.matching.types import ConstraintSpec, MatchingParameters, RequirementProfile, ResourceProfile


class HardFailure(StrEnum):
    UNIT_FAMILY_MISMATCH = "UNIT_FAMILY_MISMATCH"
    MATERIAL_EXCLUDED = "MATERIAL_EXCLUDED"
    NOT_RELATED = "NOT_RELATED"
    NO_TIMING_OVERLAP = "NO_TIMING_OVERLAP"
    BEYOND_MAX_DISTANCE = "BEYOND_MAX_DISTANCE"
    REQUIRED_PROPERTY_FAILED = "REQUIRED_PROPERTY_FAILED"
    BELOW_THRESHOLD = "BELOW_THRESHOLD"


@dataclass
class Failure:
    code: HardFailure
    message: str


def _fmt(value: float | None, unit: str | None = None) -> str:
    if value is None:
        return "n/a"
    text = f"{value:,.0f}" if abs(value) >= 100 else f"{value:,.2f}".rstrip("0").rstrip(".")
    return f"{text} {unit}".strip() if unit and unit != "%" else f"{text}{unit or ''}"


# --- Property constraints -----------------------------------------------------------------

class PropertyOutcome(StrEnum):
    PASS = "PASS"                  # measured value satisfies the constraint
    FAIL = "FAIL"                  # measured value violates the constraint
    LIKELY = "LIKELY"              # no measurement; typical range entirely within bounds
    UNCERTAIN = "UNCERTAIN"        # no measurement; typical range straddles a bound
    LIKELY_FAIL = "LIKELY_FAIL"    # no measurement; typical range entirely outside bounds
    UNKNOWN = "UNKNOWN"            # no measurement and no knowledge-base range


OUTCOME_CREDIT = {
    PropertyOutcome.PASS: 1.0, PropertyOutcome.LIKELY: 0.8, PropertyOutcome.UNCERTAIN: 0.5,
    PropertyOutcome.UNKNOWN: 0.5, PropertyOutcome.LIKELY_FAIL: 0.1, PropertyOutcome.FAIL: 0.0,
}


@dataclass
class PropertyCheck:
    key: str
    name: str
    importance: str
    outcome: PropertyOutcome
    credit: float
    constraint: str
    observed: str
    measured: bool


def _bounds_text(c: ConstraintSpec) -> str:
    if c.min is not None and c.max is not None:
        return f"{_fmt(c.min, c.unit)}–{_fmt(c.max, c.unit)}"
    if c.min is not None:
        return f"≥ {_fmt(c.min, c.unit)}"
    if c.max is not None:
        return f"≤ {_fmt(c.max, c.unit)}"
    return f"= {c.text}"


def _within(value: float, c: ConstraintSpec) -> bool:
    return (c.min is None or value >= c.min) and (c.max is None or value <= c.max)


def _soft_credit(value: float, c: ConstraintSpec) -> float:
    """Distance-to-bound credit for failed PREFERRED/OPTIONAL constraints.

    Linear decay reaching zero at 50 % relative deviation from the violated
    bound. A per-property function can replace this later (spec §16).
    """
    bound = c.min if c.min is not None and value < c.min else c.max
    if bound is None:
        return 0.0
    deviation = abs(value - bound) / max(abs(bound), 1e-9)
    return max(0.0, 1.0 - deviation * 2)


def evaluate_constraint(c: ConstraintSpec, resource: ResourceProfile) -> PropertyCheck:
    measured = resource.measured.get(c.key)
    typical = resource.typical.get(c.key)
    constraint = _bounds_text(c)
    if measured is not None and (measured.value is not None or measured.text is not None):
        if c.text is not None and measured.text is not None:
            ok = measured.text.strip().lower() == c.text.strip().lower()
            observed = measured.text
        elif measured.value is not None:
            ok = _within(measured.value, c)
            observed = _fmt(measured.value, c.unit)
        else:
            ok, observed = False, "incomparable value"
        if ok:
            return PropertyCheck(c.key, c.name, c.importance, PropertyOutcome.PASS, 1.0, constraint, observed, True)
        credit = 0.0 if c.importance == "REQUIRED" or measured.value is None else _soft_credit(measured.value, c)
        return PropertyCheck(c.key, c.name, c.importance, PropertyOutcome.FAIL, credit, constraint, observed, True)
    if typical is not None and (typical.low is not None or typical.high is not None):
        lo = typical.low if typical.low is not None else typical.high
        hi = typical.high if typical.high is not None else typical.low
        observed = f"typically {_fmt(lo)}–{_fmt(hi, c.unit)} (not measured)"
        if _within(lo, c) and _within(hi, c):
            outcome = PropertyOutcome.LIKELY
        elif (c.min is not None and hi < c.min) or (c.max is not None and lo > c.max):
            outcome = PropertyOutcome.LIKELY_FAIL
        else:
            outcome = PropertyOutcome.UNCERTAIN
        return PropertyCheck(c.key, c.name, c.importance, outcome, OUTCOME_CREDIT[outcome], constraint, observed, False)
    return PropertyCheck(c.key, c.name, c.importance, PropertyOutcome.UNKNOWN, OUTCOME_CREDIT[PropertyOutcome.UNKNOWN],
                         constraint, "not provided", False)


@dataclass
class PropertyResult:
    score: float | None
    checks: list[PropertyCheck]
    failures: list[Failure]


def evaluate_properties(constraints: tuple[ConstraintSpec, ...] | list[ConstraintSpec], resource: ResourceProfile,
                        params: MatchingParameters) -> PropertyResult:
    checks = [evaluate_constraint(c, resource) for c in constraints]
    failures = [
        Failure(HardFailure.REQUIRED_PROPERTY_FAILED,
                f"{ch.name} is {ch.observed}; the requirement needs {ch.constraint}.")
        for ch in checks if ch.importance == "REQUIRED" and ch.outcome == PropertyOutcome.FAIL
    ]
    if not checks:
        return PropertyResult(None, [], failures)
    total_weight = sum(params.importance_weights.get(ch.importance, 0.3) for ch in checks)
    score = sum(params.importance_weights.get(ch.importance, 0.3) * ch.credit for ch in checks) / total_weight
    return PropertyResult(round(score, 4), checks, failures)


# --- Material compatibility ----------------------------------------------------------------

class MaterialBasis(StrEnum):
    EXACT_MATERIAL = "EXACT_MATERIAL"
    APPLICATION = "APPLICATION"
    SUBCATEGORY = "SUBCATEGORY"
    CATEGORY = "CATEGORY"
    SEMANTIC = "SEMANTIC"
    NONE = "NONE"


IDENTITY_SCORES = {
    MaterialBasis.EXACT_MATERIAL: 1.0,
    MaterialBasis.APPLICATION: 0.9,
    MaterialBasis.SUBCATEGORY: 0.8,
    MaterialBasis.CATEGORY: 0.65,
}


@dataclass
class MaterialResult:
    score: float
    basis: MaterialBasis
    identity_score: float
    semantic_similarity: float | None
    application_checks: list[PropertyCheck]
    properties: PropertyResult
    evidence: list[str]
    failures: list[Failure] = field(default_factory=list)

    @property
    def is_hidden_match(self) -> bool:
        # Anything other than an exact canonical-material match is a discovery the
        # parties would not find by comparing material names.
        return self.basis != MaterialBasis.EXACT_MATERIAL


def _application_fit(resource: ResourceProfile, requirement: RequirementProfile,
                     params: MatchingParameters) -> tuple[bool, list[PropertyCheck], str | None]:
    """Layer 4: does the resource's material serve the demander's intended application?"""
    key = requirement.intended_application_key
    if not key or key not in resource.applications:
        return False, [], None
    app_rule = resource.applications[key]
    specs = [
        ConstraintSpec(key=r["property_key"], name=r.get("name", r["property_key"]), unit=r.get("unit"),
                       min=r.get("min"), max=r.get("max"), text=None, importance=r.get("importance", "REQUIRED"))
        for r in app_rule.rules
    ]
    checks = [evaluate_constraint(s, resource) for s in specs]
    blocked = next((c for c in checks if c.importance == "REQUIRED" and c.outcome == PropertyOutcome.FAIL), None)
    if blocked:
        return False, checks, (f"{resource.material_name} can serve {app_rule.application_name}, but its "
                               f"{blocked.name} ({blocked.observed}) is outside the screening rule {blocked.constraint}.")
    return True, checks, app_rule.application_name


def evaluate_material(resource: ResourceProfile, requirement: RequirementProfile,
                      params: MatchingParameters) -> MaterialResult:
    evidence: list[str] = []
    failures: list[Failure] = []

    if resource.material_id and resource.material_id in requirement.excluded_material_ids:
        failures.append(Failure(HardFailure.MATERIAL_EXCLUDED,
                                f"{requirement.organization_name} explicitly excludes {resource.material_name}."))

    # Layers 1-4: structured identity (exact, application, subcategory, category).
    basis = MaterialBasis.NONE
    app_ok, app_checks, app_note = _application_fit(resource, requirement, params)
    if resource.material_id and resource.material_id == requirement.material_id:
        basis = MaterialBasis.EXACT_MATERIAL
        evidence.append(f"Same normalized material: {resource.material_name}.")
    elif app_ok:
        basis = MaterialBasis.APPLICATION
        evidence.append(f"{resource.material_name} is a known input for {app_note}, which is what "
                        f"{requirement.organization_name} needs the material for.")
    elif resource.subcategory and resource.subcategory == requirement.subcategory:
        basis = MaterialBasis.SUBCATEGORY
        evidence.append(f"Same material family ({resource.subcategory}).")
    elif resource.category and (resource.category == requirement.category
                                or resource.category in requirement.acceptable_categories):
        basis = MaterialBasis.CATEGORY
        evidence.append(f"Material category {resource.category} is accepted by the requirement.")
    if app_note and not app_ok:
        evidence.append(app_note)
    if basis == MaterialBasis.EXACT_MATERIAL and app_ok and app_note:
        evidence.append(f"Also a known input for {app_note}.")

    # Layer 5: semantic similarity (retrieval aid only).
    semantic = cosine(resource.embedding, requirement.embedding)
    identity = IDENTITY_SCORES.get(basis, 0.0)
    if basis == MaterialBasis.NONE:
        if semantic is not None and semantic >= params.semantic_candidate_threshold:
            basis = MaterialBasis.SEMANTIC
            evidence.append(f"Descriptions are semantically similar ({semantic:.0%}); no structured material "
                            "link exists, so this needs manual technical review.")
        else:
            failures.append(Failure(HardFailure.NOT_RELATED, "No material, category, application or semantic link."))
    base = max(identity, min(semantic or 0.0, params.semantic_only_score_cap))

    # Layer 3: the demander's own property constraints.
    properties = evaluate_properties(requirement.constraints, resource, params)
    failures.extend(properties.failures)
    if properties.score is None:
        score = base
    else:
        score = 0.5 * base + 0.5 * properties.score
        passed = [c for c in properties.checks if c.outcome == PropertyOutcome.PASS]
        if passed and len(passed) == len(properties.checks):
            evidence.append("All stated technical constraints are met by measured values.")
    return MaterialResult(round(score, 4), basis, identity, semantic, app_checks, properties, evidence, failures)


# --- Quantity -------------------------------------------------------------------------------

class QuantityOutcome(StrEnum):
    FULL_COVERAGE = "FULL_COVERAGE"
    EXCESS_SUPPLY = "EXCESS_SUPPLY"
    PARTIAL_COVERAGE = "PARTIAL_COVERAGE"
    INSUFFICIENT_SUPPLY = "INSUFFICIENT_SUPPLY"


@dataclass
class QuantityResult:
    score: float
    outcome: QuantityOutcome
    supply: float                 # base units per basis
    demand: float
    exchanged: float              # min(supply, demand): the quantity the exchange would move
    basis: str                    # "per month" | "one-time"
    base_unit: str
    demand_coverage: float
    supply_utilization: float
    evidence: list[str]


def evaluate_quantity(resource: ResourceProfile, requirement: RequirementProfile,
                      params: MatchingParameters) -> QuantityResult | Failure:
    if not units.same_family(resource.unit, requirement.unit):
        return Failure(HardFailure.UNIT_FAMILY_MISMATCH,
                       f"Supply is measured in {resource.unit} but demand in {requirement.unit}; they are not comparable.")
    s = units.normalize(resource.quantity, resource.unit, resource.frequency)
    d = units.normalize(requirement.quantity, requirement.unit, requirement.frequency)
    evidence: list[str] = []
    if s.one_time and d.one_time:
        supply, demand, basis = s.amount, d.amount, "one-time"
    elif not s.one_time and not d.one_time:
        supply, demand, basis = s.per_month, d.per_month, "per month"
    elif s.one_time:
        supply, demand, basis = s.amount, d.per_month, "per month"
        evidence.append("One-time supply lot compared against one month of recurring demand.")
    else:
        supply, demand, basis = s.per_month, d.amount, "per month"
        evidence.append("Recurring supply compared against a one-time demand; delivery could span several months.")
    assert supply is not None and demand is not None
    exchanged = min(supply, demand)
    coverage = exchanged / demand if demand else 0.0
    utilization = exchanged / supply if supply else 0.0
    if supply >= demand * 1.05:
        outcome = QuantityOutcome.EXCESS_SUPPLY
    elif supply >= demand * 0.95:
        outcome = QuantityOutcome.FULL_COVERAGE
    elif supply >= demand * 0.25:
        outcome = QuantityOutcome.PARTIAL_COVERAGE
    else:
        outcome = QuantityOutcome.INSUFFICIENT_SUPPLY
    u = params.quantity_supply_utilization_weight
    score = (1 - u) * coverage + u * utilization
    bu = s.base_unit.value
    evidence.insert(0, f"Available supply {_fmt(supply, bu)} {basis}; demand {_fmt(demand, bu)} {basis}.")
    evidence.append(f"Covers {coverage:.0%} of the demand and would use {utilization:.0%} of the available supply.")
    return QuantityResult(round(score, 4), outcome, supply, demand, exchanged, basis, bu, round(coverage, 4),
                          round(utilization, 4), evidence)


# --- Timing ---------------------------------------------------------------------------------

class TimingOutcome(StrEnum):
    FULL_OVERLAP = "FULL_OVERLAP"
    PARTIAL_OVERLAP = "PARTIAL_OVERLAP"
    NO_OVERLAP = "NO_OVERLAP"


@dataclass
class TimingResult:
    score: float
    outcome: TimingOutcome
    overlap_days: int
    required_days: int
    overlap_start: date | None
    overlap_end: date | None
    evidence: list[str]


def evaluate_timing(resource: ResourceProfile, requirement: RequirementProfile, params: MatchingParameters,
                    today: date) -> TimingResult | Failure:
    horizon = timedelta(days=params.open_ended_horizon_days)
    req_start = max(requirement.required_from, today)
    req_end = requirement.required_until or (req_start + horizon)
    sup_start = max(resource.available_from, today)
    sup_end = resource.available_until or (max(sup_start, req_end) + horizon)
    if req_end < req_start:
        return Failure(HardFailure.NO_TIMING_OVERLAP, "The requirement window has already ended.")
    start, end = max(req_start, sup_start), min(req_end, sup_end)
    required_days = (req_end - req_start).days + 1
    overlap_days = max(0, (end - start).days + 1)
    if overlap_days == 0:
        return Failure(HardFailure.NO_TIMING_OVERLAP,
                       f"Supply window ({resource.available_from}–{resource.available_until or 'open'}) does not "
                       f"overlap the requirement window ({requirement.required_from}–"
                       f"{requirement.required_until or 'open'}).")
    score = min(1.0, overlap_days / required_days)
    outcome = TimingOutcome.FULL_OVERLAP if score >= 0.999 else TimingOutcome.PARTIAL_OVERLAP
    evidence = [f"Supply is available for {score:.0%} of the required period ({start} to {end})."]
    if requirement.required_until is None:
        evidence.append(f"Open-ended requirement assessed over a {params.open_ended_horizon_days}-day horizon.")
    return TimingResult(round(score, 4), outcome, overlap_days, required_days, start, end, evidence)


# --- Location / logistics -------------------------------------------------------------------

@dataclass
class LocationResult:
    score: float | None
    distance_km: float | None
    max_distance_km: float
    limit_source: str  # "REQUIREMENT" | "PLATFORM_DEFAULT"
    evidence: list[str]


def evaluate_location(resource: ResourceProfile, requirement: RequirementProfile,
                      params: MatchingParameters) -> LocationResult | Failure:
    explicit = requirement.max_distance_km
    max_d = explicit or params.default_max_distance_km
    source = "REQUIREMENT" if explicit else "PLATFORM_DEFAULT"
    if resource.location is None or requirement.location is None:
        return LocationResult(None, None, max_d, source, ["Facility coordinates missing; distance not assessed."])
    distance = haversine_km(resource.location, requirement.location)
    if explicit and distance > explicit:
        return Failure(HardFailure.BEYOND_MAX_DISTANCE,
                       f"Approximately {distance:,.0f} km apart; the requirement accepts at most {explicit:,.0f} km.")
    score = max(0.0, 1.0 - distance / max_d)
    evidence = [f"Approximately {distance:,.0f} km apart (straight-line; road distance will be longer)."]
    if distance > max_d:
        evidence.append(f"Beyond the {max_d:,.0f} km reference distance, so logistics feasibility is low.")
    return LocationResult(round(score, 4), round(distance, 1), max_d, source, evidence)


# --- Processing -----------------------------------------------------------------------------

class ProcessingOutcome(StrEnum):
    DIRECT_USE = "DIRECT_USE"
    DEMANDER_CAN_PROCESS = "DEMANDER_CAN_PROCESS"
    PROCESSING_ARRANGED = "PROCESSING_ARRANGED"
    PARTIAL_CAPABILITY = "PARTIAL_CAPABILITY"
    UNSPECIFIED = "UNSPECIFIED"
    NO_CAPABILITY = "NO_CAPABILITY"


PROCESSING_SCORES = {
    ProcessingOutcome.DIRECT_USE: 1.0,
    ProcessingOutcome.DEMANDER_CAN_PROCESS: 0.85,
    ProcessingOutcome.PROCESSING_ARRANGED: 0.65,
    ProcessingOutcome.PARTIAL_CAPABILITY: 0.55,
    ProcessingOutcome.UNSPECIFIED: 0.5,
    ProcessingOutcome.NO_CAPABILITY: 0.2,
}


@dataclass
class ProcessingResult:
    score: float
    outcome: ProcessingOutcome
    is_blocker: bool
    evidence: list[str]


def evaluate_processing(resource: ResourceProfile, requirement: RequirementProfile) -> ProcessingResult:
    if not resource.processing_required:
        return ProcessingResult(1.0, ProcessingOutcome.DIRECT_USE, False, ["Suitable for direct use (no processing declared)."])
    needed = {p.strip().lower() for p in resource.processing_types if p.strip()}
    capable = {p.strip().lower() for p in requirement.processing_capabilities if p.strip()}
    label = ", ".join(sorted(needed)) or "unspecified processing"
    if needed and needed <= capable:
        outcome, note = ProcessingOutcome.DEMANDER_CAN_PROCESS, f"Requires {label}, which the demander can perform."
    elif resource.processing_cost_per_unit is not None:
        outcome = ProcessingOutcome.PROCESSING_ARRANGED
        note = f"Requires {label}; the provider has declared a processing cost, so processing can be arranged."
    elif needed and needed & capable:
        outcome = ProcessingOutcome.PARTIAL_CAPABILITY
        note = f"Requires {label}; the demander covers only {', '.join(sorted(needed & capable))}."
    elif not needed and capable:
        outcome = ProcessingOutcome.UNSPECIFIED
        note = "Processing is required but not specified; the demander has some processing capability."
    else:
        outcome = ProcessingOutcome.NO_CAPABILITY
        note = f"Requires {label}, and the demander has not declared a matching capability. Manual review needed."
    blocker = outcome == ProcessingOutcome.NO_CAPABILITY
    return ProcessingResult(PROCESSING_SCORES[outcome], outcome, blocker, [note])
