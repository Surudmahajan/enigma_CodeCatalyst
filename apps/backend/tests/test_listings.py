from datetime import date, timedelta

from tests.conftest import Api, future, make_org, register_user


def _resource(api, kb, **overrides):
    body = {
        "facility_id": api.facility_id, "material_id": kb.material("Steel Slag"), "name": "BOF steel slag",
        "quantity_available": 2000, "unit": "tonne", "frequency": "MONTH",
        "availability_start": date.today().isoformat(), "availability_end": future(365),
        "properties": [{"property_key": "cao_pct", "value_numeric": 45},
                       {"property_key": "free_lime_pct", "value_numeric": 3}],
    }
    body.update(overrides)
    return api.post("/resources", json=body)


def test_create_resource_as_draft_then_publish(client, kb):
    api = make_org(client)
    created = _resource(api, kb)
    assert created.status_code == 201, created.text
    data = created.json()
    assert data["status"] == "DRAFT"
    assert {p["property_key"] for p in data["properties"]} == {"cao_pct", "free_lime_pct"}
    assert all(p["source"] == "USER_INPUT" and p["confirmed"] for p in data["properties"])
    published = api.post(f"/resources/{data['id']}/publish")
    assert published.json()["status"] == "ACTIVE"
    assert set(published.json()["allowed_transitions"]) == {"PAUSED", "EXPIRED", "FULFILLED", "ARCHIVED"}


def test_invalid_lifecycle_transition_is_explicit(client, kb):
    api = make_org(client)
    rid = _resource(api, kb).json()["id"]
    response = api.post(f"/resources/{rid}/pause")  # DRAFT -> PAUSED is not allowed
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_STATE_TRANSITION"


def test_archived_resource_is_soft_deleted_and_read_only(client, kb):
    api = make_org(client)
    rid = _resource(api, kb, publish=True).json()["id"]
    assert api.delete(f"/resources/{rid}").json()["status"] == "ARCHIVED"
    assert api.get("/resources").json() == []  # hidden from default list
    assert api.get(f"/resources/{rid}").status_code == 200  # still retrievable for audit
    assert api.patch(f"/resources/{rid}", json={"name": "Renamed slag"}).status_code == 409


def test_property_validation(client, kb):
    api = make_org(client)
    unknown = _resource(api, kb, properties=[{"property_key": "unobtainium_pct", "value_numeric": 1}])
    assert unknown.status_code == 422 and unknown.json()["error"]["code"] == "UNKNOWN_PROPERTY"
    out_of_range = _resource(api, kb, properties=[{"property_key": "sio2_pct", "value_numeric": 140}])
    assert out_of_range.status_code == 422 and out_of_range.json()["error"]["code"] == "PROPERTY_OUT_OF_RANGE"


def test_dates_are_validated(client, kb):
    api = make_org(client)
    backwards = _resource(api, kb, availability_start=future(10), availability_end=future(5))
    assert backwards.status_code == 422
    past = (date.today() - timedelta(days=30)).isoformat()
    ended = _resource(api, kb, availability_start=past, availability_end=(date.today() - timedelta(days=1)).isoformat(),
                      publish=True)
    assert ended.status_code == 422 and ended.json()["error"]["code"] == "WINDOW_IN_PAST"


def test_other_organizations_cannot_see_or_edit_resources(client, kb):
    abc = make_org(client, "ABC Steel")
    xyz = make_org(client, "XYZ Construction")
    rid = _resource(abc, kb).json()["id"]
    assert xyz.get(f"/resources/{rid}").status_code == 404
    assert xyz.patch(f"/resources/{rid}", json={"name": "hijack"}).status_code == 404
    assert xyz.get("/resources").json() == []


def test_viewer_cannot_create_listings(client, kb):
    owner = make_org(client)
    viewer_auth = register_user(client, "viewer@example.com")
    owner.post(f"/organizations/{owner.org_id}/members", json={"email": "viewer@example.com", "role": "VIEWER"})
    viewer = Api(client, viewer_auth["access_token"])
    viewer.facility_id = owner.facility_id
    response = _resource(viewer, kb)
    assert response.status_code == 403 and response.json()["error"]["code"] == "INSUFFICIENT_ROLE"


def test_create_requirement_with_constraints_and_application(client, kb):
    api = make_org(client, "XYZ Construction")
    response = api.post("/requirements", json={
        "facility_id": api.facility_id, "intended_application_id": kb.application("road_subbase"),
        "name": "Sub-base aggregate", "quantity_required": 1500, "unit": "tonne", "frequency": "MONTH",
        "required_from": date.today().isoformat(), "required_until": future(300), "max_transport_distance_km": 150,
        "processing_capabilities": ["screening"], "virgin_material_price_per_unit": 900,
        "property_constraints": [
            {"property_key": "free_lime_pct", "max_value": 4, "importance": "REQUIRED"},
            {"property_key": "moisture_pct", "max_value": 10, "importance": "PREFERRED"},
        ],
        "publish": True,
    })
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["status"] == "ACTIVE"
    assert data["intended_application"]["key"] == "road_subbase"
    assert {c["importance"] for c in data["property_constraints"]} == {"REQUIRED", "PREFERRED"}


def test_organization_can_be_both_provider_and_demander(client, kb):
    api = make_org(client, "ABC Steel", mode="BOTH")
    assert _resource(api, kb, publish=True).status_code == 201
    requirement = api.post("/requirements", json={
        "facility_id": api.facility_id, "material_id": kb.material("Limestone"), "name": "Flux limestone",
        "quantity_required": 800, "unit": "tonne", "frequency": "MONTH",
        "required_from": date.today().isoformat(), "publish": True})
    assert requirement.status_code == 201
    assert len(api.get("/resources").json()) == 1
    assert len(api.get("/requirements").json()) == 1
