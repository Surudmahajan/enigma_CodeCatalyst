"""Transparent economic assessment of a potential exchange.

    potential_net_value = avoided virgin-material purchase
                        + avoided disposal cost
                        - transport cost
                        - processing cost

All money is expressed per assessment basis (per month for recurring
exchanges, per lot for one-time). Every line item states where its input came
from. If neither benefit input exists, the result is INSUFFICIENT_DATA — the
platform never invents prices. The asking price is a transfer between the
two parties, so it does not change the combined system value; it is reported
separately for the negotiation.
"""

from dataclasses import dataclass, field
from enum import StrEnum

from app.materials import units
from app.matching.types import MatchingParameters, RequirementProfile, ResourceProfile

METHOD = "symbio.economic"
VERSION = "1.0"


class Basis(StrEnum):
    USER_PROVIDED = "USER_PROVIDED"
    PLATFORM_ASSUMPTION = "PLATFORM_ASSUMPTION"
    SYSTEM_CALCULATED = "SYSTEM_CALCULATED"


class EconomicStatus(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class Direction(StrEnum):
    POSITIVE_POTENTIAL = "POSITIVE_POTENTIAL"
    UNCERTAIN = "UNCERTAIN"
    NEGATIVE_POTENTIAL = "NEGATIVE_POTENTIAL"


@dataclass
class LineItem:
    key: str
    label: str
    amount: float           # positive = benefit, negative = cost
    basis: Basis
    provided_by: str        # "provider" | "demander" | "platform"
    formula: str


@dataclass
class EconomicAssessment:
    method: str
    version: str
    status: EconomicStatus
    direction: Direction | None
    currency: str
    period: str
    exchanged_quantity: float
    quantity_unit: str
    line_items: list[LineItem]
    gross_benefit: float | None
    net_value: float | None
    score: float | None
    assumptions: list[str] = field(default_factory=list)
    missing_inputs: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _per_base(price_per_unit: float, unit: str) -> float:
    """Convert a price per listing unit into a price per base unit (e.g. per kg -> per tonne)."""
    return price_per_unit / units.UNITS[units.QuantityUnit(unit)].factor_to_base


def assess_economics(resource: ResourceProfile, requirement: RequirementProfile, exchanged: float, base_unit: str,
                     period: str, distance_km: float | None, params: MatchingParameters) -> EconomicAssessment:
    currency = requirement.currency
    result = EconomicAssessment(METHOD, VERSION, EconomicStatus.INSUFFICIENT_DATA, None, currency, period,
                                round(exchanged, 3), base_unit, [], None, None, None)
    q = exchanged
    if resource.currency != requirement.currency:
        result.notes.append(f"Provider prices are in {resource.currency} and demander prices in "
                            f"{requirement.currency}; values are not combined without an agreed exchange rate.")
        result.missing_inputs.append("common currency")
        return result

    benefits = 0
    if requirement.virgin_material_price_per_unit is not None:
        price = _per_base(requirement.virgin_material_price_per_unit, requirement.unit)
        result.line_items.append(LineItem(
            "avoided_purchase", "Avoided virgin material purchase", q * price, Basis.USER_PROVIDED, "demander",
            f"{q:,.1f} {base_unit} × {price:,.2f} {currency}/{base_unit}"))
        benefits += 1
    else:
        result.missing_inputs.append("demander's current virgin material price")
    if resource.disposal_cost_per_unit is not None and resource.current_disposition in ("DISPOSAL", "STORAGE"):
        price = _per_base(resource.disposal_cost_per_unit, resource.unit)
        result.line_items.append(LineItem(
            "avoided_disposal", "Avoided disposal / storage cost", q * price, Basis.USER_PROVIDED, "provider",
            f"{q:,.1f} {base_unit} × {price:,.2f} {currency}/{base_unit}"))
        benefits += 1
    elif resource.current_disposition in ("DISPOSAL", "STORAGE"):
        result.missing_inputs.append("provider's current disposal cost")

    if benefits == 0:
        result.notes.append("No price or disposal-cost inputs were provided, so no economic value is estimated.")
        return result

    family = units.unit_family(resource.unit)
    if family == units.UnitFamily.MASS and distance_km is not None and params.transport_cost_per_tonne_km is not None:
        if params.transport_cost_currency == currency:
            cost = q * distance_km * params.transport_cost_per_tonne_km
            result.line_items.append(LineItem(
                "transport", "Estimated transport cost", -cost, Basis.PLATFORM_ASSUMPTION, "platform",
                f"{q:,.1f} t × {distance_km:,.0f} km × {params.transport_cost_per_tonne_km:,.2f} {currency}/t·km"))
            result.assumptions.append(
                f"Transport priced at {params.transport_cost_per_tonne_km:,.2f} {currency} per tonne-km over straight-line "
                "distance" + (" (platform demo assumption — replace with a freight quote)." if params.transport_cost_is_demo
                              else " (platform assumption)."))
        else:
            result.missing_inputs.append(f"transport rate in {currency}")
    elif family == units.UnitFamily.MASS:
        result.missing_inputs.append("transport cost (distance or rate unavailable)")
    else:
        result.notes.append(f"Transport cost model does not apply to {family.value.lower()} streams; "
                            "connection infrastructure costs must be assessed separately.")

    if resource.processing_required:
        if resource.processing_cost_per_unit is not None:
            price = _per_base(resource.processing_cost_per_unit, resource.unit)
            result.line_items.append(LineItem(
                "processing", "Processing cost", -q * price, Basis.USER_PROVIDED, "provider",
                f"{q:,.1f} {base_unit} × {price:,.2f} {currency}/{base_unit}"))
        else:
            result.missing_inputs.append("processing cost")

    gross = sum(li.amount for li in result.line_items if li.amount > 0)
    net = sum(li.amount for li in result.line_items)
    result.gross_benefit, result.net_value = round(gross, 2), round(net, 2)
    result.status = EconomicStatus.PARTIAL if result.missing_inputs else EconomicStatus.COMPLETE
    ratio = net / gross if gross else 0.0
    result.direction = (Direction.POSITIVE_POTENTIAL if ratio > 0.1
                        else Direction.NEGATIVE_POTENTIAL if ratio < -0.1 else Direction.UNCERTAIN)
    result.score = round(max(0.0, min(1.0, 0.5 + 0.5 * ratio)), 4)

    result.assumptions.append("Assumes one tonne of by-product substitutes one tonne of virgin material."
                              if params.substitution_ratio == 1.0
                              else f"Assumes a substitution ratio of {params.substitution_ratio}.")
    if resource.asking_price_per_unit is not None:
        result.notes.append("The provider's asking price is a transfer between the parties and is excluded from "
                            "combined value; it is negotiated after connecting.")
        if requirement.max_price_per_unit is not None and resource.asking_price_per_unit > requirement.max_price_per_unit:
            result.notes.append("The asking price exceeds the demander's stated maximum price.")
    return result
