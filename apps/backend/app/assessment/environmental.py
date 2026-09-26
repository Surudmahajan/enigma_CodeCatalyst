"""Scenario-based environmental assessment.

    Baseline  = provider's current disposition impact + demander's virgin material production
    Symbiosis = transport of the by-product + required processing
    Potential net benefit = Baseline − Symbiosis
    Score = 0.5 × diversion share + 0.5 × CO2e balance (see ``environmental_score``)

Quantity metrics (waste diverted, virgin material avoided) need no factors.
CO2e figures are computed only from stored, versioned ``EmissionFactor``
rows; when a needed factor is missing the CO2e result is reported as
unavailable instead of being estimated. All results are *potential* until an
exchange records verified outcomes.
"""

from dataclasses import dataclass, field
from enum import StrEnum

from app.materials import units
from app.matching.types import EnvironmentalFactors, FactorRef, MatchingParameters, ResourceProfile

METHOD = "symbio.environmental"
VERSION = "1.0"

DIVERTED_DISPOSITIONS = {"DISPOSAL", "STORAGE"}


class EnvironmentalStatus(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"            # quantity metrics only, or CO2e missing a component
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass
class EnvironmentalAssessment:
    method: str
    version: str
    status: EnvironmentalStatus
    period: str
    waste_diverted: float | None
    virgin_material_avoided: float | None
    quantity_unit: str
    transport_kgco2e: float | None
    processing_kgco2e: float | None
    baseline_kgco2e: float | None
    symbiosis_kgco2e: float | None
    net_benefit_kgco2e: float | None
    score: float | None
    uses_demo_factors: bool
    factors_used: list[FactorRef] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    missing_inputs: list[str] = field(default_factory=list)


def environmental_score(diversion_share: float, co2_balance: float) -> float:
    """0.5 × share of the exchanged quantity diverted from disposal
    + 0.5 × CO2e balance, where net/baseline in [-1, 1] maps linearly to [0, 1].

    Only computed when a CO2e balance exists; otherwise the score is unavailable.
    """
    balance = max(0.0, min(1.0, 0.5 + 0.5 * co2_balance))
    return round(0.5 * max(0.0, min(1.0, diversion_share)) + 0.5 * balance, 4)


def assess_environment(resource: ResourceProfile, exchanged: float, base_unit: str, period: str,
                       distance_km: float | None, processing_required: bool, factors: EnvironmentalFactors,
                       params: MatchingParameters) -> EnvironmentalAssessment:
    family = units.unit_family(resource.unit)
    result = EnvironmentalAssessment(METHOD, VERSION, EnvironmentalStatus.INSUFFICIENT_DATA, period, None, None,
                                     base_unit, None, None, None, None, None, None, False)
    if family != units.UnitFamily.MASS:
        result.assumptions.append(f"Material-flow CO2e model applies to mass streams; {family.value.lower()} streams "
                                  "report quantities only.")
        result.virgin_material_avoided = None
        result.waste_diverted = exchanged if resource.current_disposition in DIVERTED_DISPOSITIONS else 0.0
        result.status = EnvironmentalStatus.PARTIAL
        return result

    diverted = exchanged if resource.current_disposition in DIVERTED_DISPOSITIONS else 0.0
    virgin = exchanged * params.substitution_ratio
    result.waste_diverted, result.virgin_material_avoided = round(diverted, 3), round(virgin, 3)
    if resource.current_disposition not in DIVERTED_DISPOSITIONS:
        result.assumptions.append(f"Current disposition is {resource.current_disposition.lower().replace('_', ' ')}, "
                                  "so no waste diversion is claimed.")
    result.assumptions.append(f"Substitution ratio {params.substitution_ratio}: each tonne supplied displaces "
                              f"{params.substitution_ratio} t of virgin material.")
    result.assumptions.append("Baseline transport of virgin material is excluded (conservative).")

    used: list[FactorRef] = []

    def use(f: FactorRef | None) -> FactorRef | None:
        if f is not None:
            used.append(f)
        return f

    transport_f = use(factors.transport)
    if distance_km is not None and transport_f is not None:
        result.transport_kgco2e = round(exchanged * distance_km * transport_f.value, 1)
    else:
        result.missing_inputs.append("transport emission factor" if transport_f is None else "distance")

    if processing_required:
        processing_f = use(factors.processing)
        if processing_f is not None:
            result.processing_kgco2e = round(exchanged * processing_f.value, 1)
        else:
            result.missing_inputs.append("processing emission factor")
            result.assumptions.append("Processing emissions are not included (no factor available).")
    else:
        result.processing_kgco2e = 0.0

    virgin_f = use(factors.virgin_production)
    disposal_f = use(factors.disposal) if diverted > 0 else None
    if virgin_f is None:
        result.missing_inputs.append("virgin material production factor")
    if diverted > 0 and disposal_f is None:
        result.assumptions.append("Avoided disposal emissions are not included (no factor available).")

    result.factors_used = used
    result.uses_demo_factors = any(f.is_demo_value for f in used)
    if result.uses_demo_factors:
        result.assumptions.append("Uses illustrative demo emission factors — not suitable for reporting.")

    if virgin_f is not None and result.transport_kgco2e is not None:
        baseline = virgin * virgin_f.value + (diverted * disposal_f.value if disposal_f else 0.0)
        symbiosis = result.transport_kgco2e + (result.processing_kgco2e or 0.0)
        result.baseline_kgco2e, result.symbiosis_kgco2e = round(baseline, 1), round(symbiosis, 1)
        result.net_benefit_kgco2e = round(baseline - symbiosis, 1)
        if baseline > 0:
            result.score = environmental_score(diverted / exchanged if exchanged else 0.0,
                                               (baseline - symbiosis) / baseline)
        complete = not result.missing_inputs
        result.status = EnvironmentalStatus.COMPLETE if complete else EnvironmentalStatus.PARTIAL
    else:
        result.status = EnvironmentalStatus.PARTIAL
    return result
