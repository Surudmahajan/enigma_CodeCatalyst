"""Process Pathway Engine: direct vs Seller → Processor → Buyer."""

from tests.conftest import future, make_org
from tests.test_matching_api import ABC, XYZ, create_need, create_slag

TALEGAON = {"lat": 18.735, "lon": 73.675, "city": "Talegaon"}   # ~15 km from ABC, ~70 km from XYZ
NAGPUR = {"lat": 21.1458, "lon": 79.0882, "city": "Nagpur"}      # ~600+ km away


def processor(client, name, location, available=2200, capacity=3000, cost=180, max_km=None):
    api = make_org(client, name, "Slag processing", **location)
    body = {"method_key": "slag_ageing_crushing_screening", "facility_id": api.facility_id,
            "capacity_per_month": capacity, "available_capacity_per_month": available,
            "processing_cost_per_tonne": cost}
    if max_km:
        body["max_input_distance_km"] = max_km
    response = api.post("/organizations/me/processor-capabilities", json=body)
    assert response.status_code == 201, response.text
    return api


def processed_need(api, kb, **overrides):
    body = dict(material_id=kb.material("Processed Slag Aggregate"), name="Processed slag aggregate 0-40 mm",
                processing_capabilities=[], required_until=future(365),
                property_constraints=[{"property_key": "free_lime_pct", "max_value": 1, "importance": "REQUIRED"},
                                      {"property_key": "particle_size_mm", "max_value": 40, "importance": "REQUIRED"}])
    body.update(overrides)
    return create_need(api, kb, **body)


def setup(client, kb):
    abc = make_org(client, "ABC Steel", "Steel manufacturing", **ABC)
    xyz = make_org(client, "XYZ Construction", "Construction", **XYZ)
    resource = create_slag(abc, kb)
    return abc, xyz, resource


def report(abc, resource):
    response = abc.get(f"/resources/{resource['id']}/processing-pathways")
    assert response.status_code == 200, response.text
    return response.json()


def test_direct_raw_pathway_is_reported(client, kb):
    abc, xyz, resource = setup(client, kb)
    create_need(xyz, kb)  # raw steel slag requirement
    data = report(abc, resource)
    assert [d["buyer"]["organization"]["display_name"] for d in data["direct"]] == ["XYZ Construction"]
    assert data["direct"][0]["overall_score"] > 0.7
    assert data["processed"] == []  # no processor registered
    assert "Sell as-is" in data["recommendation"]


def test_processed_pathway_is_viable_where_direct_fails(client, kb):
    abc, xyz, resource = setup(client, kb)
    processor(client, "Processor X", TALEGAON)
    processed_need(xyz, kb)
    data = report(abc, resource)
    assert data["direct"] == []  # raw slag cannot meet "free lime <= 1 %"
    pathway = data["processed"][0]
    assert pathway["status"] == "VIABLE"
    assert pathway["processor"]["organization"]["display_name"] == "Processor X"
    assert pathway["buyer"]["organization"]["display_name"] == "XYZ Construction"
    assert pathway["buyer_wants"] == "PROCESSED"
    assert pathway["method"]["steps"] == ["ageing", "crushing", "screening"]
    assert pathway["method"]["output_material"] == "Processed Slag Aggregate"
    assert pathway["output_quantity_t"] == 1500
    assert pathway["input_quantity_t"] == round(1500 / 0.92, 1)
    assert pathway["capacity_status"] == "SUFFICIENT"
    assert pathway["direct_to_same_buyer"]["eligible"] is False
    assert "Free lime" in pathway["direct_to_same_buyer"]["reason"]
    assert pathway["blockers"] == []
    assert any("sufficient available capacity" in s for s in pathway["strengths"])
    assert any("demo assumptions" in s for s in pathway["considerations"])
    provenance = {i["key"]: i["provenance"] for i in pathway["economics"]["line_items"]}
    assert provenance["avoided_purchase"] == "User-provided" and provenance["processing"] == "Processor-declared"
    assert provenance["transport_to_processor"] == "Demo assumption"
    assert "Processing looks worth evaluating" in data["recommendation"]
    assert data["transformations"][0]["processors_found"] == 1


def test_insufficient_processor_capacity_blocks_pathway(client, kb):
    abc, xyz, resource = setup(client, kb)
    processor(client, "Micro Crushers", TALEGAON, available=200, capacity=400)
    processed_need(xyz, kb)
    pathway = report(abc, resource)["processed"][0]
    assert pathway["status"] == "NOT_VIABLE" and pathway["capacity_status"] == "INSUFFICIENT"
    assert "available capacity" in pathway["blockers"][0]


def test_processed_output_not_meeting_buyer_requirement(client, kb):
    abc, xyz, resource = setup(client, kb)
    processor(client, "Processor X", TALEGAON)
    processed_need(xyz, kb, property_constraints=[
        {"property_key": "free_lime_pct", "max_value": 0.5, "importance": "REQUIRED"}])
    pathway = report(abc, resource)["processed"][0]
    assert pathway["status"] == "NOT_VIABLE"
    assert any(b.startswith("Processed output vs buyer") for b in pathway["blockers"])
    assert pathway["output_checks"][0]["outcome"] == "FAIL"


def test_excessive_distance_weakens_pathway_economics(client, kb):
    abc, xyz, resource = setup(client, kb)
    processor(client, "Processor X", TALEGAON)
    processor(client, "Nagpur Slag Works", NAGPUR, available=4000, capacity=6000, cost=160)
    processed_need(xyz, kb)
    by_processor = {p["processor"]["organization"]["display_name"]: p for p in report(abc, resource)["processed"]}
    near, far = by_processor["Processor X"], by_processor["Nagpur Slag Works"]
    assert far["distance_to_processor_km"] > 500
    assert far["economics"]["direction"] == "NEGATIVE_POTENTIAL"
    assert far["status"] in ("WEAK", "NOT_VIABLE") and far["overall_score"] < near["overall_score"]
    assert far["scores"]["logistics"] < near["scores"]["logistics"]


def test_processor_input_distance_limit_is_a_blocker(client, kb):
    abc, xyz, resource = setup(client, kb)
    processor(client, "Nagpur Slag Works", NAGPUR, available=4000, capacity=6000, max_km=200)
    processed_need(xyz, kb)
    pathway = report(abc, resource)["processed"][0]
    assert pathway["status"] == "NOT_VIABLE"
    assert any("accepts feedstock from up to" in b for b in pathway["blockers"])


def test_no_processor_means_no_processed_pathway(client, kb):
    abc, xyz, resource = setup(client, kb)
    processed_need(xyz, kb)
    data = report(abc, resource)
    assert data["processed"] == [] and data["direct"] == []
    assert data["transformations"][0]["processors_found"] == 0
    assert data["transformations"][0]["input_status"] == "COMPATIBLE"
    assert "no processor/buyer combination" in data["recommendation"]


def test_pathways_are_private_to_the_resource_owner(client, kb):
    abc, xyz, resource = setup(client, kb)
    assert xyz.get(f"/resources/{resource['id']}/processing-pathways").status_code == 404


def test_capability_validation(client, kb):
    api = make_org(client, "Processor X", "Slag processing", **TALEGAON)
    bad = api.post("/organizations/me/processor-capabilities", json={
        "method_key": "slag_ageing_crushing_screening", "facility_id": api.facility_id,
        "capacity_per_month": 100, "available_capacity_per_month": 500})
    assert bad.status_code == 422
    assert api.get("/processing-methods").json()[0]["key"] == "slag_ageing_crushing_screening"


def test_demo_seed_contains_processing_scenario(client, kb, db):
    from app.core.dependencies import resolve_org_context
    from app.pathways.service import build_report
    from app.resources.models import Resource
    from app.seed.demo import seed_demo
    from app.users.models import User
    from sqlalchemy import select

    seed_demo(db)
    user = db.scalars(select(User).where(User.email == "abc@demo.example.com")).one()
    resource = db.scalars(select(Resource).where(Resource.name == "BOF steel slag (weathered)")).one()
    rep = build_report(db, resolve_org_context(db, user, None), resource.id)
    outcomes = {(p.processor.organization.display_name, p.buyer.listing_name, p.status) for p in rep.processed}
    assert ("Processor X", "Processed slag aggregate 0-40 mm (expressway package)", "VIABLE") in outcomes
    assert any(p == "Micro Crushers Pimpri" and s == "NOT_VIABLE" for p, _, s in outcomes)
    assert any(p == "Nagpur Slag Works" and s in ("WEAK", "NOT_VIABLE") for p, _, s in outcomes)
    assert rep.direct and rep.direct[0].buyer.organization.display_name == "XYZ Construction"


# --- Regression tests for the audit fixes -------------------------------------------------------

def _setup_slag(client, kb, **slag):
    abc = make_org(client, "ABC Steel", "Steel manufacturing", **ABC)
    xyz = make_org(client, "XYZ Construction", "Construction", **XYZ)
    return abc, xyz, create_slag(abc, kb, **slag)


def _hero(client, kb, **need):
    abc, xyz, resource = setup(client, kb)
    processor(client, "Processor X", TALEGAON, cost=180)
    processed_need(xyz, kb, **need)
    return abc, xyz, resource


# P1-2: counterparty pricing is not exposed through pathway discovery

def test_buyer_and_processor_prices_hidden_before_connection(client, kb):
    import json

    abc, xyz, resource = _hero(client, kb, virgin_material_price_per_unit=937)
    pathway = report(abc, resource)["processed"][0]
    items = {i["key"]: i for i in pathway["economics"]["line_items"]}
    for key in ("avoided_purchase", "processing"):   # buyer's price, processor's declared cost
        assert items[key]["amount"] is None and items[key]["formula"] is None and items[key]["hidden"] is True
    assert items["avoided_disposal"]["amount"] is not None           # the seller's own input
    assert items["transport_to_buyer"]["amount"] is not None         # platform assumption
    assert pathway["economics"]["net_value"] is None and pathway["economics"]["gross_benefit"] is None
    assert pathway["economics"]["direction"] == "POSITIVE_POTENTIAL"  # the assessment still uses the inputs
    dump = json.dumps(pathway)
    assert "937" not in dump and "1,405,500" not in dump and "1405500" not in dump


def test_demo_assumption_costs_stay_visible(client, kb, db):
    from sqlalchemy import select

    from app.pathways.models import ProcessorCapability

    abc, _xyz, resource = _hero(client, kb)
    for cap in db.scalars(select(ProcessorCapability)):
        cap.cost_is_demo = True
    db.commit()
    items = {i["key"]: i for i in report(abc, resource)["processed"][0]["economics"]["line_items"]}
    assert items["processing"]["provenance"] == "Demo assumption" and items["processing"]["amount"] is not None


def test_buyer_inputs_visible_once_connected(client, kb):
    abc, xyz, resource = setup(client, kb)
    processor(client, "Processor X", TALEGAON)
    create_need(xyz, kb)  # raw requirement: a direct opportunity exists for this pair
    match_id = abc.get("/matches").json()[0]["id"]
    before = {i["key"]: i for i in report(abc, resource)["processed"][0]["economics"]["line_items"]}
    assert before["avoided_purchase"]["amount"] is None
    connection = abc.post(f"/matches/{match_id}/connection-request", json={}).json()
    xyz.post(f"/connections/{connection['id']}/accept")
    after = {i["key"]: i for i in report(abc, resource)["processed"][0]["economics"]["line_items"]}
    assert after["avoided_purchase"]["amount"] == 1500 * 900


# P1-1: inactive listings do not generate pathways

def test_paused_resource_generates_no_pathways(client, kb):
    abc, _xyz, resource = _hero(client, kb)
    abc.post(f"/resources/{resource['id']}/pause")
    data = report(abc, resource)
    assert data["pathways_active"] is False and data["resource_status"] == "PAUSED"
    assert data["processed"] == [] and data["direct"] == []
    assert "paused" in data["recommendation"]


def test_expired_resource_generates_no_pathways(client, kb, db):
    import uuid

    from app.resources.models import Resource

    abc, _xyz, resource = _hero(client, kb)
    row = db.get(Resource, uuid.UUID(resource["id"]))
    row.status = "EXPIRED"
    db.commit()
    data = report(abc, resource)
    assert data["pathways_active"] is False and data["processed"] == [] and "expired" in data["recommendation"]


def test_active_resource_with_ended_window_generates_no_pathways(client, kb, db):
    import uuid
    from datetime import date, timedelta

    from app.resources.models import Resource

    abc, _xyz, resource = _hero(client, kb)
    row = db.get(Resource, uuid.UUID(resource["id"]))
    row.availability_start, row.availability_end = date.today() - timedelta(days=30), date.today() - timedelta(days=1)
    db.commit()
    data = report(abc, resource)
    assert data["pathways_active"] is False and data["processed"] == []
    assert "availability ended" in data["recommendation"]


def test_paused_requirement_and_inactive_processor_facility_are_excluded(client, kb):
    abc, xyz, resource = setup(client, kb)
    proc = processor(client, "Processor X", TALEGAON)
    need = processed_need(xyz, kb)
    assert len(report(abc, resource)["processed"]) == 1
    xyz.post(f"/requirements/{need['id']}/pause")
    assert report(abc, resource)["processed"] == []
    xyz.post(f"/requirements/{need['id']}/activate")
    proc.patch(f"/facilities/{proc.facility_id}", json={"status": "INACTIVE"})
    data = report(abc, resource)
    assert data["processed"] == [] and data["transformations"][0]["processors_found"] == 0


# P1-4: the connection target is explicit and never borrowed from another listing

def test_processed_pathway_does_not_borrow_raw_opportunity(client, kb):
    abc, xyz, resource = setup(client, kb)
    processor(client, "Processor X", TALEGAON)
    create_need(xyz, kb)                   # raw requirement: a direct opportunity with XYZ exists
    need = processed_need(xyz, kb)         # processed requirement: raw slag cannot meet it directly
    by_listing = {p["buyer"]["listing_id"]: p for p in report(abc, resource)["processed"]}
    target = by_listing[need["id"]]["connection_target"]
    assert by_listing[need["id"]]["buyer_match_id"] is None
    assert target["available"] is False and target["kind"] == "NONE" and target["match_id"] is None
    assert "Processor" in target["relationship"] and need["name"] in target["reason"]


def test_connection_target_is_the_same_listing_pair(client, kb):
    abc, xyz, resource = setup(client, kb)
    processor(client, "Processor X", TALEGAON)
    raw = create_need(xyz, kb)
    match = abc.get("/matches", params={"requirement_id": raw["id"]}).json()[0]
    pathway = next(p for p in report(abc, resource)["processed"] if p["buyer"]["listing_id"] == raw["id"])
    target = pathway["connection_target"]
    assert target["available"] is True and target["kind"] == "DIRECT_OPPORTUNITY"
    assert target["match_id"] == match["id"] == pathway["buyer_match_id"]
    assert target["with_organization"] == "XYZ Construction" and target["about_requirement"] == raw["name"]


# P1-3: missing economic inputs are never presented as viability

def test_missing_prices_are_insufficient_data_not_viable(client, kb):
    abc, xyz, resource = _setup_slag(client, kb, disposal_cost_per_unit=None)
    processor(client, "Processor X", TALEGAON)
    processed_need(xyz, kb, virgin_material_price_per_unit=None)
    data = report(abc, resource)
    pathway = data["processed"][0]
    assert pathway["status"] == "INSUFFICIENT_DATA"
    econ = pathway["economics"]
    assert econ["status"] == "INSUFFICIENT_DATA" and econ["net_value"] is None and econ["direction"] is None
    assert pathway["scores"]["economic"] is None
    assert any("Economics not assessed" in c for c in pathway["considerations"])
    assert "worth evaluating" not in data["recommendation"]


def test_missing_processing_cost_is_insufficient_data(client, kb, db):
    from sqlalchemy import select

    from app.pathways.models import ProcessingMethod

    for method in db.scalars(select(ProcessingMethod)):
        method.indicative_cost_per_tonne = None
    db.commit()
    abc, xyz, resource = setup(client, kb)
    processor(client, "Processor X", TALEGAON, cost=None)
    processed_need(xyz, kb)
    pathway = report(abc, resource)["processed"][0]
    assert pathway["status"] == "INSUFFICIENT_DATA"
    assert "processing cost" in pathway["economics"]["missing_inputs"]


def test_blockers_still_win_over_insufficient_data(client, kb):
    abc, xyz, resource = _setup_slag(client, kb, disposal_cost_per_unit=None)
    processor(client, "Micro Crushers", TALEGAON, available=100, capacity=200)
    processed_need(xyz, kb, virgin_material_price_per_unit=None)
    assert report(abc, resource)["processed"][0]["status"] == "NOT_VIABLE"


# P2-5: direct and processed routes are compared on one basis

def test_direct_route_score_uses_the_pathway_basis():
    from app.matching.types import MatchingParameters
    from app.pathways import engine

    params = MatchingParameters()
    perfect = engine.direct_route_score(material=1, quantity=1, distance_km=0, timing=1, economic=1, environmental=1,
                                        negative_economics=False, params=params)
    assert perfect == 1.0
    far = engine.direct_route_score(material=1, quantity=1, distance_km=600, timing=1, economic=1, environmental=1,
                                    negative_economics=False, params=params)
    assert engine.route_logistics_score(600, params) == 0.0 and far < perfect
    capped = engine.direct_route_score(material=1, quantity=1, distance_km=0, timing=1, economic=0.2, environmental=1,
                                       negative_economics=True, params=params)
    assert capped == engine.NEGATIVE_ECONOMICS_CAP


def test_recommendation_compares_route_scores_not_match_scores(client, kb):
    abc, xyz, resource = setup(client, kb)
    processor(client, "Processor X", TALEGAON)
    create_need(xyz, kb)
    processed_need(xyz, kb)
    data = report(abc, resource)
    best_direct = max(data["direct"], key=lambda d: d["route_score"])
    best_processed = next(p for p in data["processed"] if p["status"] == "VIABLE")
    assert best_direct["route_score"] != best_direct["overall_score"]   # the two bases really differ
    assert f"{best_direct['route_score']:.0%}" in data["recommendation"]
    assert f"{best_processed['overall_score']:.0%}" in data["recommendation"]
    assert "same route basis" in data["recommendation"]
    assert data["comparison_basis"].startswith("pathway-1.0 route score")
    same_buyer = next(p for p in data["processed"]
                      if p["buyer"]["listing_name"] == "Slag aggregate for sub-base")["direct_to_same_buyer"]
    assert same_buyer["overall_score"] != same_buyer["match_score"]
