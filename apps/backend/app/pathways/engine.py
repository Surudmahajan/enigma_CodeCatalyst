"""Process Pathway Engine: Seller → Processor → Processed product → Buyer (one processor hop).

It wraps the existing matching engine instead of duplicating it:

1. Input check     raw resource vs the method's input constraints   (components.evaluate_constraint)
2. Capacity        processor available capacity vs the input the buyer needs
3. Output profile  a *synthetic* resource at the processor: output material, method
                   output specification, quantity × yield, available after processing time
4. Buyer match     output profile vs buyer requirement              (engine.evaluate_pair)
5. Pathway economics / environment over both logistics legs, with every input labelled
6. Composite score (engine.composite_score) + explicit blockers + explanation

Every figure carries its provenance: user-provided, processor-declared, demo
assumption or system-calculated. Nothing here is a market price.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from app.assessment.environmental import environmental_score
from app.materials import units
from app.matching import components as c
from app.matching.engine import MatchEvaluation, composite_score, evaluate_pair
from app.matching.geo import haversine_km
from app.matching.types import (
    ApplicationRule,
    ConstraintSpec,
    EnvironmentalFactors,
    GeoPoint,
    MatchingParameters,
    MeasuredValue,
    RequirementProfile,
    ResourceProfile,
)

VERSION = "pathway-1.0"

# Starting weights for the pathway composite (renormalized over available components).
PATHWAY_WEIGHTS = {"technical": 0.30, "quantity": 0.10, "capacity": 0.15, "logistics": 0.15, "timing": 0.05,
                   "economic": 0.20, "environmental": 0.05}
VIABLE_THRESHOLD = 0.70
WEAK_THRESHOLD = 0.45
NEGATIVE_ECONOMICS_CAP = 0.55
MIN_CAPACITY_SHARE = 0.25  # below this share of the needed input, capacity is treated as insufficient


@dataclass(frozen=True)
class MethodSpec:
    id: str
    key: str
    name: str
    steps: tuple[str, ...]
    input_constraints: tuple[ConstraintSpec, ...]
    output_material_id: str
    output_material_name: str
    output_category: str | None
    output_subcategory: str | None
    output_properties: dict[str, MeasuredValue]
    output_applications: dict[str, ApplicationRule]
    expected_yield: float
    processing_time_days: int
    indicative_cost_per_tonne: float | None
    source_note: str | None = None


@dataclass(frozen=True)
class ProcessorSpec:
    capability_id: str
    organization_id: str
    organization_name: str
    city: str
    location: GeoPoint | None
    capacity_per_month: float
    available_capacity_per_month: float
    cost_per_tonne: float | None
    cost_is_demo: bool
    max_input_distance_km: float | None
    currency: str = "INR"


@dataclass
class PathwayResult:
    status: str                      # VIABLE | WEAK | INSUFFICIENT_DATA | NOT_VIABLE
    overall_score: float
    scores: dict[str, float | None]
    input_quantity: float            # tonnes/month of raw material routed to the processor
    output_quantity: float           # tonnes/month of product delivered to the buyer
    basis: str
    distance_to_processor_km: float | None
    distance_to_buyer_km: float | None
    capacity_status: str
    economics: dict[str, Any]
    environment: dict[str, Any]
    input_checks: list[dict[str, Any]]
    output_checks: list[dict[str, Any]]
    strengths: list[str] = field(default_factory=list)
    considerations: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    buyer_evaluation: MatchEvaluation | None = None


# One comparison basis for every route (direct or processed): the pathway weights above, logistics as
# total route distance against twice the single-leg reference distance, the same negative-economics cap.
# The stored match score uses the *matching* weights and single-leg distance decay, so it is never
# compared with a pathway score directly (see service._recommend).
ROUTE_BASIS = (f"{VERSION} route score: technical, quantity, capacity, logistics (total route km vs "
               "2 × reference distance), timing, economic and environmental, weighted identically for direct and "
               "processed routes; components that cannot be assessed are excluded on both sides.")


def route_logistics_score(total_km: float | None, params: MatchingParameters) -> float | None:
    if total_km is None:
        return None
    return round(max(0.0, 1 - total_km / (2 * params.default_max_distance_km)), 4)


def route_score(scores: dict[str, float | None], negative_economics: bool) -> float:
    overall = composite_score(scores, PATHWAY_WEIGHTS)
    if negative_economics:
        overall = min(overall, NEGATIVE_ECONOMICS_CAP)
    return round(overall, 4)


def direct_route_score(*, material: float | None, quantity: float | None, distance_km: float | None,
                       timing: float | None, economic: float | None, environmental: float | None,
                       negative_economics: bool, params: MatchingParameters) -> float:
    """A direct (raw) sale scored on the same route basis as a processed pathway (no capacity leg)."""
    return route_score({"technical": material, "quantity": quantity, "capacity": None,
                        "logistics": route_logistics_score(distance_km, params), "timing": timing,
                        "economic": economic, "environmental": environmental}, negative_economics)


def _check_dict(ch: c.PropertyCheck) -> dict[str, Any]:
    return {"property_key": ch.key, "name": ch.name, "importance": ch.importance, "outcome": ch.outcome.value,
            "constraint": ch.constraint, "observed": ch.observed, "measured": ch.measured}


def output_profile(rp: ResourceProfile, method: MethodSpec, processor: ProcessorSpec, input_per_basis: float,
                   one_time: bool) -> ResourceProfile:
    """The processed product as a virtual listing at the processor's facility."""
    return ResourceProfile(
        id=f"{rp.id}:{method.key}:{processor.capability_id}", organization_id=processor.organization_id,
        organization_name=processor.organization_name, name=method.output_material_name, description=None,
        material_id=method.output_material_id, material_name=method.output_material_name,
        category=method.output_category, subcategory=method.output_subcategory,
        quantity=input_per_basis * method.expected_yield, unit="tonne",
        frequency="ONE_TIME" if one_time else "MONTH",
        available_from=rp.available_from + timedelta(days=method.processing_time_days),
        available_until=rp.available_until, location=processor.location, processing_required=False,
        processing_types=(), current_disposition=rp.current_disposition, currency=rp.currency,
        measured=method.output_properties, typical={}, applications=method.output_applications, embedding=None,
    )


def _money_item(key: str, label: str, amount: float, provenance: str, provided_by: str, formula: str) -> dict:
    return {"key": key, "label": label, "amount": round(amount, 2), "provenance": provenance,
            "provided_by": provided_by, "formula": formula}


def evaluate_processed_pathway(rp: ResourceProfile, method: MethodSpec, processor: ProcessorSpec,
                               qp: RequirementProfile, params: MatchingParameters, factors: EnvironmentalFactors,
                               today: date) -> PathwayResult | None:
    """Evaluate Seller → Processor → Buyer. Returns None when the pathway is not applicable at all
    (non-mass stream, or the buyer's need is unrelated to the processed product)."""
    if units.unit_family(rp.unit) != units.UnitFamily.MASS:
        return None
    supply = units.normalize(rp.quantity, rp.unit, rp.frequency)
    one_time = supply.one_time
    supply_t = supply.amount if one_time else float(supply.per_month or 0)
    blockers: list[str] = []
    strengths: list[str] = []
    considerations: list[str] = []

    # 1. Input compatibility with the method.
    input_checks = [c.evaluate_constraint(spec, rp) for spec in method.input_constraints]
    for ch in input_checks:
        if ch.importance == "REQUIRED" and ch.outcome == c.PropertyOutcome.FAIL:
            blockers.append(f"{ch.name} of the raw material ({ch.observed}) is outside what {method.name} accepts "
                            f"({ch.constraint}).")
        elif ch.outcome in (c.PropertyOutcome.UNKNOWN, c.PropertyOutcome.UNCERTAIN, c.PropertyOutcome.LIKELY_FAIL):
            considerations.append(f"{ch.name} of the raw material should be confirmed for {method.name} "
                                  f"(needs {ch.constraint}; {ch.observed}).")
    if input_checks and not blockers:
        strengths.append(f"Raw material properties are compatible with {method.name}.")

    # 2. Capacity: how much input the buyer needs vs what the processor can take.
    demand = units.normalize(qp.quantity, qp.unit, qp.frequency)
    demand_t = demand.amount if demand.one_time else float(demand.per_month or 0)
    input_needed = min(supply_t, demand_t / method.expected_yield) if units.unit_family(qp.unit) == units.UnitFamily.MASS else supply_t
    available = processor.available_capacity_per_month
    routed_input = min(input_needed, available)
    capacity_share = available / input_needed if input_needed else 0.0
    if available <= 0 or capacity_share < MIN_CAPACITY_SHARE:
        capacity_status = "INSUFFICIENT"
        blockers.append(f"{processor.organization_name} has {available:,.0f} t/month of available capacity; "
                        f"this pathway needs about {input_needed:,.0f} t/month.")
    elif capacity_share < 1:
        capacity_status = "PARTIAL"
        considerations.append(f"Processor capacity covers {capacity_share:.0%} of the input this buyer needs "
                              f"({available:,.0f} of {input_needed:,.0f} t/month).")
    else:
        capacity_status = "SUFFICIENT"
        strengths.append(f"{processor.organization_name} has sufficient available capacity "
                         f"({available:,.0f} t/month for {input_needed:,.0f} t/month needed).")
    capacity_score = max(0.0, min(1.0, capacity_share))

    # 3. Leg 1 logistics (seller → processor).
    d1 = haversine_km(rp.location, processor.location) if rp.location and processor.location else None
    if d1 is not None and processor.max_input_distance_km and d1 > processor.max_input_distance_km:
        blockers.append(f"The processor accepts feedstock from up to {processor.max_input_distance_km:,.0f} km; "
                        f"the seller is about {d1:,.0f} km away.")

    # 4. The processed product vs the buyer requirement (existing matching engine).
    product = output_profile(rp, method, processor, max(routed_input, 1e-6), one_time)
    ev = evaluate_pair(product, qp, params, factors, today)
    unrelated = {c.HardFailure.UNIT_FAMILY_MISMATCH, c.HardFailure.NOT_RELATED}
    if any(f.code in unrelated for f in ev.failures) or (ev.material and ev.material.basis == c.MaterialBasis.NONE):
        return None  # buyer does not need anything like the processed product
    output_checks = [_check_dict(ch) for ch in (ev.material.properties.checks if ev.material else [])]
    hard = [f for f in ev.failures if f.code != c.HardFailure.BELOW_THRESHOLD]
    for failure in hard:
        blockers.append(f"Processed output vs buyer: {failure.message}")
    if ev.material and not hard:
        if ev.material.basis == c.MaterialBasis.EXACT_MATERIAL:
            strengths.append(f"The processed output ({method.output_material_name}) is exactly the material "
                             f"{qp.organization_name} requires.")
        else:
            strengths.append(f"The processed output ({method.output_material_name}) fits {qp.organization_name}'s need.")
        if output_checks and all(ch["outcome"] == "PASS" for ch in output_checks):
            strengths.append("The method's output specification meets every technical constraint of the buyer.")
    d2 = ev.location.distance_km if ev.location else None

    out_t = ev.quantity.exchanged if ev.quantity else routed_input * method.expected_yield
    in_t = out_t / method.expected_yield
    basis = "per lot" if one_time else "per month"

    # 5a. Pathway economics (both legs, processing, avoided purchase and disposal).
    items: list[dict] = []
    missing: list[str] = []
    currency = qp.currency
    benefits = 0
    if rp.currency != qp.currency:
        missing.append("common currency")
    else:
        if qp.virgin_material_price_per_unit is not None:
            price = qp.virgin_material_price_per_unit / units.UNITS[units.QuantityUnit(qp.unit)].factor_to_base
            items.append(_money_item("avoided_purchase", "Buyer's avoided purchase of the equivalent material",
                                     out_t * price, "User-provided", "buyer", f"{out_t:,.0f} t × {price:,.0f} {currency}/t"))
            benefits += 1
        else:
            missing.append("buyer's current material price")
        if rp.disposal_cost_per_unit is not None and rp.current_disposition in ("DISPOSAL", "STORAGE"):
            price = rp.disposal_cost_per_unit / units.UNITS[units.QuantityUnit(rp.unit)].factor_to_base
            items.append(_money_item("avoided_disposal", "Seller's avoided disposal/storage cost", in_t * price,
                                     "User-provided", "seller", f"{in_t:,.0f} t × {price:,.0f} {currency}/t"))
            benefits += 1
        cost = processor.cost_per_tonne if processor.cost_per_tonne is not None else method.indicative_cost_per_tonne
        if cost is not None:
            provenance = ("Demo assumption" if processor.cost_is_demo or processor.cost_per_tonne is None
                          else "Processor-declared")
            items.append(_money_item("processing", f"Processing ({', '.join(method.steps)})", -in_t * cost, provenance,
                                     "processor", f"{in_t:,.0f} t × {cost:,.0f} {currency}/t"))
        else:
            missing.append("processing cost")
        rate = params.transport_cost_per_tonne_km
        if rate is not None and params.transport_cost_currency == currency:
            label = "Demo assumption" if params.transport_cost_is_demo else "Platform assumption"
            if d1 is not None:
                items.append(_money_item("transport_to_processor", "Transport seller → processor", -in_t * d1 * rate,
                                         label, "platform", f"{in_t:,.0f} t × {d1:,.0f} km × {rate:,.2f} {currency}/t·km"))
            else:
                missing.append("distance seller → processor")
            if d2 is not None:
                items.append(_money_item("transport_to_buyer", "Transport processor → buyer", -out_t * d2 * rate,
                                         label, "platform", f"{out_t:,.0f} t × {d2:,.0f} km × {rate:,.2f} {currency}/t·km"))
            else:
                missing.append("distance processor → buyer")
        else:
            missing.append("transport rate")
    # Economics are ASSESSED only when every input the pathway depends on exists: at least one benefit
    # (buyer's avoided purchase or seller's avoided disposal), the processing cost, and transport for both
    # legs. Otherwise they are INSUFFICIENT_DATA: no score, no net value, no direction — never invented.
    gross = sum(i["amount"] for i in items if i["amount"] > 0)
    net = sum(i["amount"] for i in items)
    if benefits == 0 and "common currency" not in missing:
        missing.append("seller's disposal cost (or the buyer's current material price)")
    economic_status = "ASSESSED" if (benefits > 0 and not missing and gross > 0) else "INSUFFICIENT_DATA"
    if economic_status == "INSUFFICIENT_DATA":
        economic_score, direction, gross_out, net_out = None, None, None, None
        considerations.append("Economics not assessed — missing: " + ", ".join(missing) + ". This pathway is not "
                              "shown as viable until these inputs exist.")
    else:
        ratio = net / gross
        economic_score = round(max(0.0, min(1.0, 0.5 + 0.5 * ratio)), 4)
        direction = "POSITIVE_POTENTIAL" if ratio > 0.1 else "NEGATIVE_POTENTIAL" if ratio < -0.1 else "UNCERTAIN"
        gross_out, net_out = round(gross, 2), round(net, 2)
        # Texts carry no amounts: the net could reveal a counterparty's private price (see service redaction).
        if direction == "POSITIVE_POTENTIAL":
            strengths.append("Potentially economically viable: estimated benefits exceed processing and transport costs.")
        elif direction == "NEGATIVE_POTENTIAL":
            considerations.append("Known costs exceed estimated benefits — mainly processing and transport.")
        else:
            considerations.append("Estimated benefits and costs are roughly balanced; economics are uncertain.")
    if any(i["provenance"] == "Demo assumption" for i in items):
        considerations.append("Processing and/or transport costs are demo assumptions, not quotes.")
    economics = {"version": VERSION, "status": economic_status, "currency": currency, "basis": basis,
                 "line_items": items, "gross_benefit": gross_out, "net_value": net_out, "direction": direction,
                 "missing_inputs": missing}

    # 5b. Environment (versioned factors only; unavailable if a factor is missing).
    diverted = in_t if rp.current_disposition in ("DISPOSAL", "STORAGE") else 0.0
    virgin = out_t * params.substitution_ratio
    used, env_missing, uses_demo = [], [], False
    transport_kg = None
    if factors.transport and d1 is not None and d2 is not None:
        transport_kg = (in_t * d1 + out_t * d2) * factors.transport.value
        used.append(factors.transport)
    else:
        env_missing.append("transport factor or distance")
    processing_kg = None
    if factors.processing:
        processing_kg = in_t * factors.processing.value
        used.append(factors.processing)
    else:
        env_missing.append("processing emission factor")
    net_kg, env_score = None, None
    if factors.virgin_production and transport_kg is not None:
        used.append(factors.virgin_production)
        baseline = virgin * factors.virgin_production.value
        if factors.disposal and diverted:
            baseline += diverted * factors.disposal.value
            used.append(factors.disposal)
        symbiosis = transport_kg + (processing_kg or 0.0)
        net_kg = baseline - symbiosis
        if baseline > 0:
            env_score = environmental_score(diverted / in_t if in_t else 0.0, net_kg / baseline)
    else:
        env_missing.append("virgin material production factor")
    uses_demo = any(f.is_demo_value for f in used)
    environment = {"waste_diverted_t": round(diverted, 1), "virgin_material_avoided_t": round(virgin, 1),
                   "transport_kgco2e": round(transport_kg, 1) if transport_kg is not None else None,
                   "processing_kgco2e": round(processing_kg, 1) if processing_kg is not None else None,
                   "net_benefit_kgco2e": round(net_kg, 1) if net_kg is not None else None,
                   "uses_demo_factors": uses_demo, "missing_inputs": env_missing,
                   "factors": [{"key": f.key, "version": f.version, "source": f.source} for f in used]}
    if diverted:
        strengths.append(f"Diverts about {diverted:,.0f} t {basis} of by-product from {rp.current_disposition.lower()}.")

    # 6. Logistics score over both legs (two legs → twice the single-leg reference distance).
    total_km = (d1 or 0) + (d2 or 0) if d1 is not None and d2 is not None else None
    logistics_score = route_logistics_score(total_km, params)
    if total_km is not None and logistics_score is not None:
        route = f"≈{d1:,.0f} km to the processor + ≈{d2:,.0f} km to the buyer"
        if logistics_score >= 0.7:
            strengths.append(f"Short route: {route}.")
        elif logistics_score >= 0.3:
            considerations.append(f"Moderate route ({route}); transport is a significant cost.")
        else:
            considerations.append(f"Long route ({route}) increases logistics cost and emissions.")
    if method.processing_time_days:
        considerations.append(f"{method.name} takes about {method.processing_time_days} days before first delivery.")

    technical_parts = [ch.credit for ch in input_checks] + ([ev.material.score] if ev.material else [])
    scores = {
        "technical": round(sum(technical_parts) / len(technical_parts), 4) if technical_parts else None,
        "quantity": ev.quantity.score if ev.quantity else None,
        "capacity": round(capacity_score, 4),
        "logistics": round(logistics_score, 4) if logistics_score is not None else None,
        "timing": ev.timing.score if ev.timing else None,
        "economic": economic_score,
        "environmental": env_score,
    }
    overall = route_score(scores, direction == "NEGATIVE_POTENTIAL")
    if blockers:
        status = "NOT_VIABLE"
    elif economic_status == "INSUFFICIENT_DATA":
        status = "INSUFFICIENT_DATA"  # technically possible, but viability cannot be confirmed without economics
    elif overall >= VIABLE_THRESHOLD:
        status = "VIABLE"
    elif overall >= WEAK_THRESHOLD:
        status = "WEAK"
    else:
        status = "NOT_VIABLE"
    return PathwayResult(status=status, overall_score=round(overall, 4), scores=scores, input_quantity=round(in_t, 1),
                         output_quantity=round(out_t, 1), basis=basis,
                         distance_to_processor_km=round(d1, 1) if d1 is not None else None,
                         distance_to_buyer_km=round(d2, 1) if d2 is not None else None,
                         capacity_status=capacity_status, economics=economics, environment=environment,
                         input_checks=[_check_dict(ch) for ch in input_checks], output_checks=output_checks,
                         strengths=strengths, considerations=considerations, blockers=blockers, buyer_evaluation=ev)
