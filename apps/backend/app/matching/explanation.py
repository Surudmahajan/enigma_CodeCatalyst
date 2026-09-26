"""Deterministic match explanations built only from structured evaluation data.

Every sentence here is derived from a computed value in ``MatchEvaluation``;
nothing is inferred or invented. An optional AI layer (ai/explanations.py)
may rephrase ``summary`` for readability, but that text is stored separately
and validated against these facts.
"""

from typing import Any

from app.assessment.economic import Direction
from app.matching import components as c
from app.matching.engine import MatchEvaluation
from app.matching.types import RequirementProfile, ResourceProfile

DISCLAIMER = ("Potential opportunity based on the information provided by both organizations. It is not a guarantee "
              "that the exchange is technically, legally or commercially feasible; confirm specifications, "
              "regulatory requirements and logistics before committing.")

COMPONENT_LABELS = {
    "material": "Material", "quantity": "Quantity", "location": "Distance", "timing": "Timing",
    "processing": "Processing", "economic": "Economic", "environmental": "Environmental",
}


def level(score: float | None) -> str:
    if score is None:
        return "Not assessed"
    return "High" if score >= 0.75 else "Moderate" if score >= 0.5 else "Low"


def _num(value: float, unit: str = "") -> str:
    text = f"{value:,.0f}" if abs(value) >= 10 else f"{value:,.1f}"
    return f"{text} {unit}".strip()


def _unit_abbrev(unit: str) -> str:
    return {"tonne": "t", "m3": "m³"}.get(unit, unit)


def build_explanation(ev: MatchEvaluation, resource: ResourceProfile, requirement: RequirementProfile) -> dict[str, Any]:
    assert ev.material and ev.quantity and ev.processing and ev.economic and ev.environmental
    q, m, p = ev.quantity, ev.material, ev.processing
    unit = _unit_abbrev(q.base_unit)
    per = "/month" if q.basis == "per month" else " (one-time)"
    strengths: list[str] = []
    considerations: list[str] = []

    # Material
    passed = [ch for ch in m.properties.checks if ch.outcome == c.PropertyOutcome.PASS]
    if m.basis == c.MaterialBasis.EXACT_MATERIAL:
        strengths.append(f"Same material ({resource.material_name})")
    elif m.basis == c.MaterialBasis.APPLICATION:
        strengths.append(f"Hidden match: {resource.material_name} is a known input for "
                         f"{requirement.intended_application_name}")
    elif m.basis in (c.MaterialBasis.CATEGORY, c.MaterialBasis.SUBCATEGORY):
        strengths.append(f"Related material ({resource.material_name or resource.name}) in an accepted category")
    if m.properties.checks and len(passed) == len(m.properties.checks):
        strengths.append("Material properties compatible with every stated constraint")
    for ch in m.properties.checks:
        if ch.outcome == c.PropertyOutcome.FAIL:
            considerations.append(f"{ch.name} {ch.observed} misses the {ch.importance.lower()} target {ch.constraint}")
        elif ch.outcome in (c.PropertyOutcome.UNCERTAIN, c.PropertyOutcome.UNKNOWN, c.PropertyOutcome.LIKELY_FAIL):
            considerations.append(f"{ch.name} needs confirmation ({ch.observed}; target {ch.constraint})")
        elif ch.outcome == c.PropertyOutcome.LIKELY:
            considerations.append(f"{ch.name} is likely compatible but not measured (target {ch.constraint})")
    if m.basis == c.MaterialBasis.SEMANTIC:
        considerations.append("Material link is based on description similarity only — technical review required")

    # Quantity
    if q.outcome in (c.QuantityOutcome.FULL_COVERAGE, c.QuantityOutcome.EXCESS_SUPPLY):
        strengths.append("Quantity sufficient for the full demand")
    elif q.outcome == c.QuantityOutcome.PARTIAL_COVERAGE:
        considerations.append(f"Partial coverage: supply meets {q.demand_coverage:.0%} of the demand")
    else:
        considerations.append(f"Supply covers only {q.demand_coverage:.0%} of the demand")

    # Timing
    if ev.timing and ev.timing.outcome == c.TimingOutcome.FULL_OVERLAP:
        strengths.append("Timing compatible")
    elif ev.timing:
        considerations.append(f"Supply covers {ev.timing.score:.0%} of the required period")

    # Location
    if ev.location and ev.location.distance_km is not None:
        d = ev.location.distance_km
        if ev.location.score is not None and ev.location.score >= 0.6:
            strengths.append(f"Nearby: about {d:,.0f} km apart")
        elif ev.location.score == 0:
            considerations.append(f"Long distance (about {d:,.0f} km) reduces logistics feasibility")
        considerations.append("Transport cost requires confirmation")
    else:
        considerations.append("Facility locations incomplete — distance not assessed")

    # Processing
    if p.outcome == c.ProcessingOutcome.DIRECT_USE:
        strengths.append("Direct use without processing")
    else:
        considerations.append("Processing required before use" if not p.is_blocker
                              else "Processing required but no matching capability — manual review")

    # Economic
    econ = ev.economic
    if econ.direction == Direction.POSITIVE_POTENTIAL:
        strengths.append("Potentially economically viable")
    elif econ.direction == Direction.NEGATIVE_POTENTIAL:
        considerations.append("Known costs currently exceed the estimated benefits")
    elif econ.direction is None:
        considerations.append("Economic value not estimated (price inputs missing)")

    # Environmental
    env = ev.environmental
    if env.net_benefit_kgco2e is not None and env.net_benefit_kgco2e > 0:
        strengths.append(f"Potential environmental benefit (about {_num(env.net_benefit_kgco2e / 1000, 't')} CO2e"
                         f"{per} net)")
    elif env.waste_diverted:
        strengths.append(f"Potential waste diversion of {_num(env.waste_diverted, unit)}{per}")
    if env.net_benefit_kgco2e is not None and env.net_benefit_kgco2e <= 0:
        considerations.append("Transport and processing emissions offset the estimated CO2e savings")
    if env.uses_demo_factors:
        considerations.append("Environmental figures use illustrative demo factors")

    # Summary paragraph (factual template).
    provider, demander = resource.organization_name, requirement.organization_name
    material_label = resource.material_name or resource.name
    if m.basis == c.MaterialBasis.APPLICATION:
        opening = (f"{provider}'s {material_label} is a different material from what {demander} listed, but it is a "
                   f"known input for {requirement.intended_application_name}, which {demander} needs.")
    elif m.basis == c.MaterialBasis.SEMANTIC:
        opening = (f"{provider}'s {resource.name} appears related to {demander}'s requirement based on the "
                   "descriptions, but no structured material link exists yet.")
    elif m.properties.checks and len(passed) == len(m.properties.checks):
        opening = f"{provider}'s {material_label} has properties compatible with {demander}'s stated requirements."
    else:
        opening = f"{provider}'s {material_label} is a potential fit for {demander}'s requirement."
    lines = [
        opening,
        f"Available supply: {_num(q.supply, unit)}{per}. Potential demand: {_num(q.demand, unit)}{per}.",
        f"Potential coverage: {q.supply_utilization:.0%} of the supply would be used, meeting "
        f"{q.demand_coverage:.0%} of the demand.",
    ]
    if ev.location and ev.location.distance_km is not None:
        lines.append(f"Approximate distance: {ev.location.distance_km:,.0f} km.")
    main = next((x for x in considerations if not x.startswith("Transport cost")), None)
    if main:
        lines.append(f"Main consideration: {main[0].lower() + main[1:]}.")

    components: dict[str, Any] = {}
    evidence_map = {
        "material": m.evidence, "quantity": q.evidence, "timing": ev.timing.evidence if ev.timing else [],
        "location": ev.location.evidence if ev.location else [], "processing": p.evidence,
        "economic": econ.notes + [f"Missing: {x}" for x in econ.missing_inputs],
        "environmental": env.assumptions[:2] + [f"Missing: {x}" for x in env.missing_inputs],
    }
    headline_map = {
        "material": level(ev.scores.get("material")),
        "quantity": f"{q.supply_utilization:.0%} of supply · {q.demand_coverage:.0%} of demand",
        "location": f"{ev.location.distance_km:,.0f} km" if ev.location and ev.location.distance_km is not None
        else "Not assessed",
        "timing": {"FULL_OVERLAP": "Compatible", "PARTIAL_OVERLAP": "Partial overlap"}.get(
            ev.timing.outcome.value if ev.timing else "", "Not assessed"),
        "processing": {"DIRECT_USE": "Direct use", "DEMANDER_CAN_PROCESS": "Moderate",
                       "PROCESSING_ARRANGED": "Moderate", "PARTIAL_CAPABILITY": "Moderate",
                       "UNSPECIFIED": "Needs clarification", "NO_CAPABILITY": "Manual review"}[p.outcome.value],
        "economic": {Direction.POSITIVE_POTENTIAL: "Potentially viable", Direction.UNCERTAIN: "Uncertain",
                     Direction.NEGATIVE_POTENTIAL: "Costs may exceed benefits"}.get(econ.direction, "Insufficient data"),
        "environmental": ("Potential benefit" if (env.net_benefit_kgco2e or 0) > 0 or (env.waste_diverted or 0) > 0
                          else "Not assessed" if env.score is None else "Limited benefit"),
    }
    for key, label in COMPONENT_LABELS.items():
        score = ev.scores.get(key)
        components[key] = {"label": label, "score": score, "level": level(score), "headline": headline_map[key],
                           "evidence": evidence_map[key]}

    return {
        "headline": "Potential opportunity",
        "summary": " ".join(lines),
        "strengths": strengths,
        "considerations": considerations,
        "components": components,
        "match_type": ev.match_type,
        "is_hidden_match": ev.is_hidden_match,
        "feasibility": ev.feasibility,
        "requires_manual_review": ev.requires_manual_review,
        "confidence": {"score": ev.confidence, "level": ev.confidence_level, "gaps": ev.confidence_gaps},
        "caps_applied": ev.caps_applied,
        "property_checks": [
            {"property_key": ch.key, "name": ch.name, "importance": ch.importance, "outcome": ch.outcome.value,
             "constraint": ch.constraint, "observed": ch.observed, "measured": ch.measured}
            for ch in m.properties.checks
        ],
        "disclaimer": DISCLAIMER,
    }
