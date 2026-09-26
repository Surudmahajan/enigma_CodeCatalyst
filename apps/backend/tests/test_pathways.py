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
