"""Unit tests for the pure matching engine — no database involved.

Covers the seven mandatory scenarios from the product brief (§58) plus the
component formulas (quantity, timing, distance, properties, scoring,
economic and environmental calculations).
"""

from dataclasses import replace
from datetime import date, timedelta

import pytest

from app.ai.embeddings import embed, listing_text
from app.assessment.economic import Direction, EconomicStatus
from app.materials import units
from app.matching import components as c
from app.matching.engine import composite_score, evaluate_pair
from app.matching.explanation import build_explanation
from app.matching.geo import haversine_km
from app.matching.types import (
    ApplicationRule,
    ConstraintSpec,
    EnvironmentalFactors,
    FactorRef,
    GeoPoint,
    MatchingParameters,
    MeasuredValue,
    RequirementProfile,
    ResourceProfile,
    TypicalRange,
)

TODAY = date(2026, 10, 1)
PUNE = GeoPoint(18.52, 73.85)
NEAR_82KM = GeoPoint(19.2575, 73.85)   # ~82 km due north
CHENNAI = GeoPoint(13.08, 80.27)       # ~900+ km away
PARAMS = MatchingParameters(transport_cost_per_tonne_km=4.0, transport_cost_is_demo=True)
FACTORS = EnvironmentalFactors(
    transport=FactorRef("f1", "transport.road", 0.1, "kgCO2e/t-km", "test", "1", "IN", True),
    virgin_production=FactorRef("f2", "virgin.aggregate", 5.0, "kgCO2e/t", "test", "1", "IN", True),
    disposal=FactorRef("f3", "disposal.landfill.inert", 1.2, "kgCO2e/t", "test", "1", "IN", True),
)


def slag(**kw) -> ResourceProfile:
    base = ResourceProfile(
        id="r1", organization_id="abc", organization_name="ABC Steel", name="BOF steel slag",
        description="Weathered steel slag from LD converter", material_id="m-steel-slag", material_name="Steel Slag",
        category="Metallurgical slag", subcategory="Steel slag", quantity=2000, unit="tonne", frequency="MONTH",
        available_from=TODAY, available_until=TODAY + timedelta(days=365), location=PUNE,
        processing_required=True, processing_types=("crushing",), current_disposition="DISPOSAL", currency="INR",
        disposal_cost_per_unit=350, processing_cost_per_unit=120,
        measured={"free_lime_pct": MeasuredValue("free_lime_pct", "Free lime", "%", 2.5),
                  "moisture_pct": MeasuredValue("moisture_pct", "Moisture", "%", 6)},
        typical={"cao_pct": TypicalRange("cao_pct", "Lime (CaO)", "%", 40, 52)},
        applications={"road_subbase": ApplicationRule("road_subbase", "Road base / sub-base", (
            {"property_key": "free_lime_pct", "name": "Free lime", "unit": "%", "max": 4, "importance": "REQUIRED"},))},
    )
    return replace(base, **kw)


def demand(**kw) -> RequirementProfile:
    base = RequirementProfile(
        id="q1", organization_id="xyz", organization_name="XYZ Construction", name="Slag aggregate for sub-base",
        description="Granular sub-base material for highway project", material_id="m-steel-slag",
        material_name="Steel Slag", category="Metallurgical slag", subcategory="Steel slag",
        intended_application_key="road_subbase", intended_application_name="Road base / sub-base",
        quantity=1500, unit="tonne", frequency="MONTH", required_from=TODAY, required_until=TODAY + timedelta(days=300),
        location=NEAR_82KM, currency="INR", processing_capabilities=("crushing", "screening"),
        virgin_material_price_per_unit=900,
        constraints=(ConstraintSpec("free_lime_pct", "Free lime", "%", None, 4, None, "REQUIRED"),
                     ConstraintSpec("moisture_pct", "Moisture", "%", None, 10, None, "PREFERRED")),
    )
    return replace(base, **kw)


def run(resource, requirement, params=PARAMS, factors=FACTORS):
    return evaluate_pair(resource, requirement, params, factors, TODAY)


# --- The seven required scenarios -----------------------------------------------------------

def test_case1_exact_material_sufficient_quantity_nearby_is_high_compatibility():
    ev = run(slag(processing_required=False, processing_types=()), demand())
    assert ev.eligible
    assert ev.match_type == "EXACT_MATERIAL"
    assert ev.overall_score >= 0.8
    assert ev.feasibility == "HIGH"


def test_case2_same_category_but_required_property_mismatch_is_incompatible():
    wet = slag(measured={"free_lime_pct": MeasuredValue("free_lime_pct", "Free lime", "%", 7.5)})
    ev = run(wet, demand())
    assert not ev.eligible
    assert c.HardFailure.REQUIRED_PROPERTY_FAILED in [f.code for f in ev.failures]
    assert "Free lime" in ev.failures[0].message


def test_case3_supply_less_than_demand_is_partial_coverage():
    ev = run(slag(quantity=900), demand())
    assert ev.eligible
    assert ev.quantity.outcome == c.QuantityOutcome.PARTIAL_COVERAGE
    assert ev.quantity.demand_coverage == pytest.approx(0.6)
    assert ev.quantity.supply_utilization == 1.0


def test_case4_non_overlapping_dates_is_not_viable():
    later = demand(required_from=TODAY + timedelta(days=400), required_until=TODAY + timedelta(days=500))
    ev = run(slag(), later)
    assert not ev.eligible
    assert c.HardFailure.NO_TIMING_OVERLAP in [f.code for f in ev.failures]


def test_case5_processing_required_without_capability_needs_manual_review():
    ev = run(slag(processing_cost_per_unit=None), demand(processing_capabilities=()))
    assert ev.processing.outcome == c.ProcessingOutcome.NO_CAPABILITY
    assert ev.requires_manual_review
    assert ev.feasibility == "LOW"
    assert ev.overall_score <= PARAMS.blocker_score_cap


def test_case6_extremely_distant_reduces_economic_and_environmental_feasibility():
    near = run(slag(), demand())
    far = run(slag(), demand(location=CHENNAI))
    assert far.location.distance_km > 900
    assert far.scores["location"] == 0
    assert far.economic.score < near.economic.score
    assert far.environmental.score < near.environmental.score
    assert far.overall_score < near.overall_score


def test_case7_different_material_names_compatible_via_application_is_hidden_match():
    # The demander asked for natural aggregate; the provider lists steel slag.
    requirement = demand(material_id="m-natural-aggregate", material_name="Natural Aggregate",
                         category="Natural mineral", subcategory="Aggregate", name="Crushed stone for sub-base",
                         description="Crushed stone GSB material")
    ev = run(slag(), requirement)
    assert ev.eligible
    assert ev.match_type == "APPLICATION"
    assert ev.is_hidden_match
    explanation = build_explanation(ev, slag(), requirement)
    assert explanation["strengths"][0].startswith("Hidden match")
    assert "different material" in explanation["summary"]


def test_application_rule_failure_blocks_hidden_match():
    requirement = demand(material_id="m-natural-aggregate", category="Natural mineral", subcategory="Aggregate",
                         constraints=())
    high_lime = slag(measured={"free_lime_pct": MeasuredValue("free_lime_pct", "Free lime", "%", 9)})
    ev = run(high_lime, requirement)
    assert ev.match_type != "APPLICATION"


def test_unrelated_material_is_not_a_candidate():
    heat = slag(material_id="m-heat", material_name="Low-grade Waste Heat", category="Energy stream",
                subcategory="Waste heat", name="Hot water", description="80C cooling water", applications={},
                embedding=None)
    ev = run(heat, demand(constraints=()))
    assert not ev.eligible
    assert c.HardFailure.NOT_RELATED in [f.code for f in ev.failures]


def test_semantic_only_match_is_capped_and_flagged_for_review():
    r = slag(material_id=None, material_name=None, category=None, subcategory=None, applications={},
             name="Grey granular furnace residue", description="granular furnace residue from steel plant")
    q = demand(material_id=None, material_name=None, category=None, subcategory=None, intended_application_key=None,
               name="Granular furnace residue wanted", description="granular residue from steel furnace", constraints=())
    r = replace(r, embedding=embed(listing_text(r.name, r.description, None)))
    q = replace(q, embedding=embed(listing_text(q.name, q.description, None)))
    ev = run(r, q)
    assert ev.match_type == "SEMANTIC"
    assert ev.requires_manual_review
    assert ev.overall_score <= PARAMS.semantic_only_score_cap
    assert ev.confidence_level != "HIGH"


def test_excluded_material_is_a_hard_constraint():
    ev = run(slag(), demand(excluded_material_ids=("m-steel-slag",)))
    assert not ev.eligible
    assert c.HardFailure.MATERIAL_EXCLUDED in [f.code for f in ev.failures]


def test_explicit_distance_limit_is_a_hard_constraint():
    ev = run(slag(), demand(max_distance_km=50))
    assert c.HardFailure.BEYOND_MAX_DISTANCE in [f.code for f in ev.failures]


def test_incomparable_units_are_ineligible():
    ev = run(slag(), demand(unit="MWh"))
    assert [f.code for f in ev.failures] == [c.HardFailure.UNIT_FAMILY_MISMATCH]


# --- Demo scenario (ABC Steel -> XYZ Construction) ------------------------------------------

def test_demo_scenario_explanation_matches_brief():
    ev = run(slag(), demand())
    assert ev.eligible
    assert round(ev.location.distance_km) == 82
    assert ev.quantity.supply_utilization == pytest.approx(0.75)
    exp = build_explanation(ev, slag(), demand())
    comps = exp["components"]
    assert comps["material"]["headline"] == "High"
    assert comps["quantity"]["headline"].startswith("75% of supply")
    assert comps["location"]["headline"] == "82 km"
    assert comps["timing"]["headline"] == "Compatible"
    assert comps["processing"]["headline"] == "Moderate"
    assert comps["economic"]["headline"] == "Potentially viable"
    assert comps["environmental"]["headline"] == "Potential benefit"
    assert "Material properties compatible with every stated constraint" in exp["strengths"]
    assert "Processing required before use" in exp["considerations"]
    assert "Transport cost requires confirmation" in exp["considerations"]
    assert exp["headline"] == "Potential opportunity"
    assert "Available supply: 2,000 t/month" in exp["summary"]
    assert "Approximate distance: 82 km" in exp["summary"]


# --- Component formulas ---------------------------------------------------------------------

def test_unit_and_period_normalization():
    monthly = units.normalize(500, "tonne", "WEEK")
    assert monthly.per_month == pytest.approx(500 * 30.4375 / 7)
    assert units.normalize(2_000_000, "kg", "MONTH").per_month == pytest.approx(2000)
    assert units.normalize(3.6, "GJ", "MONTH").per_month == pytest.approx(1.0)
    assert not units.same_family("tonne", "m3")


def test_weekly_demand_is_compared_on_monthly_basis():
    ev = run(slag(quantity=2000), demand(quantity=400, frequency="WEEK"))
    assert ev.quantity.demand == pytest.approx(400 * 30.4375 / 7)  # ~1,739 t/month
    assert ev.quantity.outcome == c.QuantityOutcome.EXCESS_SUPPLY
    short = run(slag(quantity=2000), demand(quantity=500, frequency="WEEK"))  # ~2,174 t/month
    assert short.quantity.outcome == c.QuantityOutcome.PARTIAL_COVERAGE


def test_one_time_supply_against_recurring_demand_is_noted():
    ev = run(slag(quantity=800, frequency="ONE_TIME"), demand())
    assert any("One-time supply" in e for e in ev.quantity.evidence)


def test_haversine_known_distance():
    mumbai, pune = GeoPoint(19.0760, 72.8777), GeoPoint(18.5204, 73.8567)
    assert haversine_km(mumbai, pune) == pytest.approx(120, abs=3)


def test_location_score_decays_linearly():
    ev = run(slag(), demand())
    assert ev.scores["location"] == pytest.approx(1 - ev.location.distance_km / PARAMS.default_max_distance_km, abs=1e-3)


def test_partial_timing_overlap_score():
    requirement = demand(required_from=TODAY, required_until=TODAY + timedelta(days=99))
    resource = slag(available_until=TODAY + timedelta(days=49))
    ev = run(resource, requirement)
    assert ev.timing.outcome == c.TimingOutcome.PARTIAL_OVERLAP
    assert ev.timing.score == pytest.approx(0.5)


def test_property_outcomes_and_soft_credit():
    params = MatchingParameters()
    r = slag(measured={"free_lime_pct": MeasuredValue("free_lime_pct", "Free lime", "%", 3),
                       "moisture_pct": MeasuredValue("moisture_pct", "Moisture", "%", 12)})
    constraints = (ConstraintSpec("free_lime_pct", "Free lime", "%", None, 4, None, "REQUIRED"),
                   ConstraintSpec("moisture_pct", "Moisture", "%", None, 10, None, "PREFERRED"),
                   ConstraintSpec("cao_pct", "CaO", "%", 35, None, None, "OPTIONAL"),
                   ConstraintSpec("sio2_pct", "SiO2", "%", 45, None, None, "OPTIONAL"))
    result = c.evaluate_properties(constraints, r, params)
    outcomes = {ch.key: ch.outcome for ch in result.checks}
    assert outcomes == {"free_lime_pct": c.PropertyOutcome.PASS, "moisture_pct": c.PropertyOutcome.FAIL,
                        "cao_pct": c.PropertyOutcome.LIKELY, "sio2_pct": c.PropertyOutcome.UNKNOWN}
    moisture = next(ch for ch in result.checks if ch.key == "moisture_pct")
    assert moisture.credit == pytest.approx(0.6)  # 20 % over the bound -> 1 - 0.4
    assert not result.failures  # only REQUIRED failures are hard


def test_sio2_example_from_brief():
    r = slag(measured={"sio2_pct": MeasuredValue("sio2_pct", "SiO2", "%", 52)})
    ok = c.evaluate_constraint(ConstraintSpec("sio2_pct", "SiO2", "%", 45, None, None, "REQUIRED"), r)
    assert ok.outcome == c.PropertyOutcome.PASS
    wet = slag(measured={"moisture_pct": MeasuredValue("moisture_pct", "Moisture", "%", 15)})
    bad = c.evaluate_constraint(ConstraintSpec("moisture_pct", "Moisture", "%", None, 10, None, "REQUIRED"), wet)
    assert bad.outcome == c.PropertyOutcome.FAIL


def test_composite_score_renormalizes_unavailable_components():
    weights = MatchingParameters().weights
    full = {k: 1.0 for k in weights}
    assert composite_score(full, weights) == pytest.approx(1.0)
    partial = dict(full, economic=None, environmental=None)
    assert composite_score(partial, weights) == pytest.approx(1.0)
    mixed = dict(full, material=0.0)
    assert composite_score(mixed, weights) == pytest.approx(0.70)


def test_weights_come_from_configuration():
    material_heavy = MatchingParameters(weights={"material": 1.0, "quantity": 0.0, "location": 0.0, "timing": 0.0,
                                                 "processing": 0.0, "economic": 0.0, "environmental": 0.0},
                                        transport_cost_per_tonne_km=4.0)
    ev = run(slag(), demand(), params=material_heavy)
    assert ev.overall_score == pytest.approx(ev.scores["material"], abs=1e-4)


# --- Economic and environmental -------------------------------------------------------------

def test_economic_line_items_and_provenance():
    ev = run(slag(), demand())
    items = {li.key: li for li in ev.economic.line_items}
    assert items["avoided_purchase"].amount == pytest.approx(1500 * 900)
    assert items["avoided_purchase"].basis.value == "USER_PROVIDED"
    assert items["avoided_disposal"].amount == pytest.approx(1500 * 350)
    assert items["transport"].basis.value == "PLATFORM_ASSUMPTION"
    assert items["transport"].amount == pytest.approx(-1500 * ev.location.distance_km * 4.0)
    assert items["processing"].amount == pytest.approx(-1500 * 120)
    assert ev.economic.net_value == pytest.approx(sum(li.amount for li in ev.economic.line_items), abs=0.01)
    assert ev.economic.direction == Direction.POSITIVE_POTENTIAL
    assert any("demo assumption" in a for a in ev.economic.assumptions)


def test_economic_is_insufficient_without_price_inputs():
    ev = run(slag(disposal_cost_per_unit=None), demand(virgin_material_price_per_unit=None))
    assert ev.economic.status == EconomicStatus.INSUFFICIENT_DATA
    assert ev.economic.score is None and ev.economic.net_value is None
    assert ev.scores["economic"] is None  # excluded from the composite, not invented


def test_price_per_kg_is_converted_to_per_tonne():
    ev = run(slag(disposal_cost_per_unit=None), demand(virgin_material_price_per_unit=0.9, unit="kg",
                                                       quantity=1_500_000))
    purchase = next(li for li in ev.economic.line_items if li.key == "avoided_purchase")
    assert purchase.amount == pytest.approx(1500 * 900)


def test_environmental_scenario_calculation():
    ev = run(slag(), demand())
    env = ev.environmental
    d = ev.location.distance_km
    assert env.waste_diverted == 1500 and env.virgin_material_avoided == 1500
    assert env.transport_kgco2e == pytest.approx(1500 * d * 0.1, abs=0.1)
    assert env.baseline_kgco2e == pytest.approx(1500 * 5.0 + 1500 * 1.2, abs=0.1)
    assert env.net_benefit_kgco2e == pytest.approx(env.baseline_kgco2e - env.symbiosis_kgco2e, abs=0.1)
    assert env.uses_demo_factors
    balance = env.net_benefit_kgco2e / env.baseline_kgco2e
    assert env.score == pytest.approx(0.5 * 1.0 + 0.5 * max(0, min(1, 0.5 + 0.5 * balance)), abs=1e-3)
    assert {f.id for f in env.factors_used} >= {"f1", "f2", "f3"}


def test_environmental_without_factors_reports_quantities_only():
    ev = run(slag(), demand(), factors=EnvironmentalFactors())
    env = ev.environmental
    assert env.waste_diverted == 1500
    assert env.net_benefit_kgco2e is None and env.score is None
    assert "virgin material production factor" in env.missing_inputs


def test_internal_use_claims_no_waste_diversion():
    ev = run(slag(current_disposition="INTERNAL_USE"), demand())
    assert ev.environmental.waste_diverted == 0
