"""Integration tests: listings -> events -> matching engine -> Match records -> API views."""

from datetime import date

from tests.conftest import future, make_org

# ~82 km apart (Pune -> north).
ABC = {"lat": 18.52, "lon": 73.85, "city": "Pune"}
XYZ = {"lat": 19.2575, "lon": 73.85, "city": "Nashik Road"}


def provider_and_demander(client):
    abc = make_org(client, "ABC Steel", "Steel manufacturing", **ABC)
    xyz = make_org(client, "XYZ Construction", "Construction", **XYZ)
    return abc, xyz


def create_slag(api, kb, **overrides):
    body = {
        "facility_id": api.facility_id, "material_id": kb.material("Steel Slag"), "name": "BOF steel slag",
        "description": "Weathered LD converter slag", "quantity_available": 2000, "unit": "tonne",
        "frequency": "MONTH", "availability_start": date.today().isoformat(), "availability_end": future(365),
        "processing_required": True, "processing_types": ["crushing"], "current_disposition": "DISPOSAL",
        "disposal_cost_per_unit": 350, "processing_cost_per_unit": 120,
        "properties": [{"property_key": "free_lime_pct", "value_numeric": 2.5},
                       {"property_key": "moisture_pct", "value_numeric": 6}],
        "publish": True,
    }
    body.update(overrides)
    response = api.post("/resources", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def create_need(api, kb, **overrides):
    body = {
        "facility_id": api.facility_id, "material_id": kb.material("Steel Slag"),
        "intended_application_id": kb.application("road_subbase"), "name": "Slag aggregate for sub-base",
        "quantity_required": 1500, "unit": "tonne", "frequency": "MONTH",
        "required_from": date.today().isoformat(), "required_until": future(300),
        "processing_capabilities": ["crushing", "screening"], "virgin_material_price_per_unit": 900,
        "property_constraints": [{"property_key": "free_lime_pct", "max_value": 4, "importance": "REQUIRED"},
                                 {"property_key": "moisture_pct", "max_value": 10, "importance": "PREFERRED"}],
        "publish": True,
    }
    body.update(overrides)
    response = api.post("/requirements", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_publishing_listings_discovers_match_for_both_sides(client, kb):
    abc, xyz = provider_and_demander(client)
    resource = create_slag(abc, kb)
    requirement = create_need(xyz, kb)

    provider_view = abc.get("/matches").json()
    demander_view = xyz.get("/matches").json()
    assert len(provider_view) == len(demander_view) == 1
    assert provider_view[0]["id"] == demander_view[0]["id"]
    assert provider_view[0]["my_side"] == "PROVIDER" and demander_view[0]["my_side"] == "DEMANDER"
    assert provider_view[0]["counterpart"]["display_name"] == "XYZ Construction"
    assert provider_view[0]["my_listing_id"] == resource["id"]
    assert demander_view[0]["my_listing_id"] == requirement["id"]
    assert provider_view[0]["is_new"] is True
    assert round(provider_view[0]["distance_km"]) == 82
    assert provider_view[0]["supply_utilization"] == 0.75


def test_opportunity_report_is_explained_and_versioned(client, kb):
    abc, xyz = provider_and_demander(client)
    create_slag(abc, kb)
    create_need(xyz, kb)
    match_id = abc.get("/matches").json()[0]["id"]
    detail = abc.get(f"/matches/{match_id}").json()
    assert detail["status"] == "VIEWED"  # opening the report marks it viewed
    assert detail["explanation"]["headline"] == "Potential opportunity"
    assert detail["explanation"]["components"]["timing"]["headline"] == "Compatible"
    assert detail["explanation"]["disclaimer"]
    assert detail["matching_version"] == "1.0"
    assert detail["methodology_version"].startswith("economic-")
    assert detail["environmental"]["uses_demo_factors"] is True
    assert "REQUEST_CONNECTION" in detail["allowed_actions"]
    assert detail["confidence_level"] in {"HIGH", "MEDIUM", "LOW"}


def test_counterpart_private_data_is_hidden_before_connection(client, kb):
    abc, xyz = provider_and_demander(client)
    create_slag(abc, kb)
    create_need(xyz, kb)
    match_id = xyz.get("/matches").json()[0]["id"]
    detail = xyz.get(f"/matches/{match_id}").json()
    # The demander sees the provider's resource only in limited form.
    assert detail["resource"]["description"] is None
    assert detail["resource"]["commercial_terms"] is None
    assert "latitude" not in detail["resource"]["location"]
    assert detail["counterpart_contact"] is None
    # The provider's disposal cost is hidden, and so are totals that would reveal it.
    economic = detail["economic"]
    disposal = next(li for li in economic["line_items"] if li["key"] == "avoided_disposal")
    assert disposal["amount"] is None and disposal["hidden"] is True
    assert economic["net_value"] is None
    # The demander still sees its own inputs.
    purchase = next(li for li in economic["line_items"] if li["key"] == "avoided_purchase")
    assert purchase["amount"] == 1500 * 900
    # Its own listing is shown in full.
    assert detail["requirement"]["commercial_terms"]["virgin_material_price_per_unit"] == "900.00"


def test_hidden_match_between_different_material_names(client, kb):
    abc, xyz = provider_and_demander(client)
    create_slag(abc, kb)
    create_need(xyz, kb, material_id=kb.material("Natural Aggregate"), name="Crushed stone GSB")
    matches = xyz.get("/matches").json()
    assert len(matches) == 1
    assert matches[0]["match_type"] == "APPLICATION"
    assert matches[0]["is_hidden_match"] is True
    assert matches[0]["top_strengths"][0].startswith("Hidden match")


def test_property_mismatch_produces_no_match(client, kb):
    abc, xyz = provider_and_demander(client)
    create_slag(abc, kb, properties=[{"property_key": "free_lime_pct", "value_numeric": 8}])
    create_need(xyz, kb)
    assert xyz.get("/matches").json() == []


def test_non_overlapping_windows_produce_no_match(client, kb):
    abc, xyz = provider_and_demander(client)
    create_slag(abc, kb, availability_end=future(30))
    create_need(xyz, kb, required_from=future(60), required_until=future(120))
    assert abc.get("/matches").json() == []


def test_match_goes_stale_when_listing_paused_and_resurfaces_on_reactivation(client, kb):
    abc, xyz = provider_and_demander(client)
    resource = create_slag(abc, kb)
    create_need(xyz, kb)
    match_id = abc.get("/matches").json()[0]["id"]
    abc.post(f"/resources/{resource['id']}/pause")
    assert abc.get("/matches").json() == []
    closed = abc.get("/matches", params={"include_closed": True}).json()
    assert closed[0]["status"] == "EXPIRED"
    assert closed[0]["stale_reason"] == "The resource is no longer active."
    abc.post(f"/resources/{resource['id']}/activate")
    again = abc.get("/matches").json()
    assert again[0]["id"] == match_id and again[0]["status"] == "DISCOVERED"


def test_editing_a_listing_recalculates_the_match(client, kb):
    abc, xyz = provider_and_demander(client)
    resource = create_slag(abc, kb)
    create_need(xyz, kb)
    before = abc.get("/matches").json()[0]
    abc.patch(f"/resources/{resource['id']}", json={"quantity_available": 900})
    after = abc.get("/matches").json()[0]
    assert after["id"] == before["id"]
    assert after["demand_coverage"] == 0.6
    # Making a REQUIRED property fail expires it.
    abc.patch(f"/resources/{resource['id']}", json={"properties": [{"property_key": "free_lime_pct",
                                                                    "value_numeric": 9}]})
    assert abc.get("/matches").json() == []


def test_third_party_cannot_see_the_match(client, kb):
    abc, xyz = provider_and_demander(client)
    outsider = make_org(client, "Nosy Corp")
    create_slag(abc, kb)
    create_need(xyz, kb)
    match_id = abc.get("/matches").json()[0]["id"]
    assert outsider.get(f"/matches/{match_id}").status_code == 404
    assert outsider.get("/matches").json() == []


def test_interest_and_reject_lifecycle(client, kb):
    abc, xyz = provider_and_demander(client)
    create_slag(abc, kb)
    create_need(xyz, kb)
    match_id = abc.get("/matches").json()[0]["id"]
    interested = xyz.post(f"/matches/{match_id}/interest").json()
    assert interested["status"] == "INTERESTED"
    rejected = abc.post(f"/matches/{match_id}/reject", json={"reason": "Not now"}).json()
    assert rejected["status"] == "REJECTED"
    # Rejected is terminal: a refresh does not resurrect it.
    refreshed = abc.post(f"/matches/{match_id}/refresh")
    assert refreshed.json()["status"] == "REJECTED"


def test_search_endpoint_runs_matching_for_own_listing_only(client, kb):
    abc, xyz = provider_and_demander(client)
    resource = create_slag(abc, kb)
    create_need(xyz, kb)
    results = abc.post("/matches/search", json={"resource_id": resource["id"]}).json()
    assert len(results) == 1
    assert xyz.post("/matches/search", json={"resource_id": resource["id"]}).status_code == 404


def test_same_organization_never_matches_itself(client, kb):
    both = make_org(client, "ABC Steel", **ABC)
    create_slag(both, kb)
    create_need(both, kb)
    assert both.get("/matches").json() == []


def test_snapshot_records_inputs(client, kb, db):
    from sqlalchemy import select

    from app.matching.models import Match

    abc, xyz = provider_and_demander(client)
    create_slag(abc, kb)
    create_need(xyz, kb)
    match = db.scalars(select(Match)).one()
    snap = match.assessment_snapshot
    assert snap["resource"]["quantity"] == 2000
    assert snap["requirement"]["quantity"] == 1500
    assert snap["parameters"]["weights"]["material"] == 0.30
    assert snap["factors"]["transport"]["is_demo_value"] is True
    assert "embedding" not in snap["resource"]
