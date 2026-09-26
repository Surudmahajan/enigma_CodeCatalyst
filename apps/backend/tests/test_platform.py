"""Impact tracking, dashboards, admin console API, worker sweeps and the demo seed."""

from datetime import date, timedelta

from sqlalchemy import select

from app.core.security import hash_password
from app.users.models import User
from tests.conftest import PASSWORD, Api
from tests.test_connections_messaging import EXCHANGE, connected, matched


def make_admin(client, db) -> Api:
    db.add(User(email="ops@example.com", password_hash=hash_password(PASSWORD), first_name="Ops", last_name="Admin",
                is_platform_admin=True, is_verified=True))
    db.commit()
    token = client.post("/api/v1/auth/login", json={"email": "ops@example.com", "password": PASSWORD}).json()
    return Api(client, token["access_token"])


# --- Impact -----------------------------------------------------------------------------------

def test_completing_an_exchange_records_explainable_impact(client, kb):
    abc, xyz, match_id, _ = connected(client, kb)
    exchange = abc.post(f"/matches/{match_id}/exchange", json=EXCHANGE).json()
    xyz.post(f"/exchanges/{exchange['id']}/start")
    abc.post(f"/exchanges/{exchange['id']}/complete", json={"delivered_quantity": 4500})
    records = {r["metric_type"]: r for r in abc.get("/impact/records", params={"exchange_id": exchange["id"]}).json()}
    assert float(records["WASTE_DIVERTED"]["value"]) == 4500
    assert float(records["VIRGIN_MATERIAL_AVOIDED"]["value"]) == 4500
    assert records["WASTE_DIVERTED"]["source_type"] == "USER_INPUT"
    assert records["TRANSPORT_EMISSIONS"]["uses_demo_factors"] is True
    assert records["ECONOMIC_VALUE"]["unit"] == "INR"
    assert records["NET_CO2E"]["inputs"]["factor_ids"]
    assert any("reported by the parties" in a for a in records["WASTE_DIVERTED"]["assumptions"])
    # Both parties see the same records.
    assert len(xyz.get("/impact/records").json()) == len(records)


def test_impact_without_delivered_quantity_is_labelled_an_estimate(client, kb):
    abc, xyz, match_id, _ = connected(client, kb)
    body = dict(EXCHANGE, start_date=(date.today() - timedelta(days=61)).isoformat(), end_date=date.today().isoformat())
    exchange = abc.post(f"/matches/{match_id}/exchange", json=body).json()
    xyz.post(f"/exchanges/{exchange['id']}/start")
    abc.post(f"/exchanges/{exchange['id']}/complete", json={})
    record = next(r for r in abc.get("/impact/records").json() if r["metric_type"] == "WASTE_DIVERTED")
    assert record["source_type"] == "SYSTEM_ESTIMATE"


def test_impact_dashboard_separates_potential_and_realized(client, kb):
    abc, _xyz, _m = matched(client, kb)
    dashboard = abc.get("/impact/dashboard").json()
    potential = dashboard["potential"]["as_provider"]
    assert potential["opportunities"] == 1
    assert potential["waste_divertable_t_per_month"] == 1500
    assert potential["uses_demo_factors"] is True
    assert "economic_value_per_month_connected" not in potential  # hidden until connected
    assert dashboard["realized"]["completed_exchanges"] == 0
    assert "Potential" in potential["label"]


def test_dashboard_counters_for_provider_and_demander(client, kb):
    abc, xyz, match_id = matched(client, kb)
    xyz.post(f"/matches/{match_id}/connection-request", json={})
    provider = abc.get("/dashboard").json()["provider"]
    assert provider == {**provider, "active_resources": 1, "potential_matches": 1, "connection_requests": 1,
                        "active_exchanges": 0}
    demander = xyz.get("/dashboard").json()["demander"]
    assert demander["active_requirements"] == 1 and demander["potential_providers"] == 1
    assert demander["connection_requests"] == 0  # xyz sent it


# --- Admin ------------------------------------------------------------------------------------

def test_admin_api_is_forbidden_to_ordinary_users(client, kb):
    abc, _xyz, _m = matched(client, kb)
    for path in ("/admin/organizations", "/admin/analytics", "/admin/matching-configs", "/admin/audit-logs"):
        response = abc.get(path)
        assert response.status_code == 403 and response.json()["error"]["code"] == "ADMIN_REQUIRED"


def test_admin_verification_suspension_and_analytics(client, kb, db):
    abc, xyz, _m = matched(client, kb)
    admin = make_admin(client, db)
    orgs = admin.get("/admin/organizations", params={"verification_status": "PENDING"}).json()
    assert {o["display_name"] for o in orgs} == {"ABC Steel", "XYZ Construction"}
    verified = admin.post(f"/admin/organizations/{abc.org_id}/verification", json={"status": "VERIFIED"}).json()
    assert verified["verification_status"] == "VERIFIED"
    analytics = admin.get("/admin/analytics").json()
    assert analytics["active_resources"] == 1 and analytics["matches_discovered"] == 1
    # Suspending an organization removes it from matching and blocks its actions.
    admin.post(f"/admin/organizations/{abc.org_id}/suspend", json={"note": "Compliance review"})
    assert xyz.get("/matches").json() == []
    blocked = abc.post("/resources", json={})
    assert blocked.status_code in (403, 422)
    listing_create = abc.patch("/organizations/me", json={"description": "x"})
    assert listing_create.status_code == 403
    actions = [a["action"] for a in admin.get("/admin/audit-logs").json()]
    assert "ORGANIZATION_SUSPENDED" in actions and "ORGANIZATION_VERIFICATION_CHANGED" in actions


def test_matching_configs_are_validated_versioned_and_reapplied(client, kb, db):
    abc, _xyz, _m = matched(client, kb)
    admin = make_admin(client, db)
    bad = admin.post("/admin/matching-configs", json={"version": "2.0", "weights": {"material": 1.0}})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "INVALID_WEIGHTS"
    weights = {"material": 0.4, "quantity": 0.2, "location": 0.1, "timing": 0.1, "processing": 0.1,
               "economic": 0.05, "environmental": 0.05}
    created = admin.post("/admin/matching-configs", json={"version": "2.0", "weights": weights}).json()
    assert created["is_active"] is False
    assert admin.post("/admin/matching-configs", json={"version": "2.0", "weights": weights}).status_code == 409
    admin.post(f"/admin/matching-configs/{created['id']}/activate")
    match_id = abc.get("/matches").json()[0]["id"]
    assert abc.get(f"/matches/{match_id}").json()["matching_version"] == "2.0"


def test_emission_factors_are_added_as_new_versions(client, kb, db):
    admin = make_admin(client, db)
    created = admin.post("/admin/emission-factors", json={
        "key": "transport.road.truck", "scope": "TRANSPORT", "value": 0.095, "unit": "kgCO2e/t-km",
        "source": "Example national freight factor table 2026", "geography": "IN", "methodology": "Well-to-wheel",
        "version": "2026.1", "valid_from": date.today().isoformat()}).json()
    assert created["is_demo_value"] is False
    retired = admin.post(f"/admin/emission-factors/{created['id']}/retire").json()
    assert retired["is_active"] is False
    keys = [f["key"] for f in admin.get("/admin/emission-factors", params={"include_retired": True}).json()]
    assert keys.count("transport.road.truck") == 2  # demo factor + new version kept side by side


# --- Worker -----------------------------------------------------------------------------------

def test_worker_expires_listings_and_their_matches(client, kb, db):
    from app.resources.models import Resource
    from app.worker import sweep

    abc, _xyz, _m = matched(client, kb)
    resource = db.scalars(select(Resource)).one()
    resource.availability_start = date.today() - timedelta(days=30)
    resource.availability_end = date.today() - timedelta(days=1)
    db.commit()
    result = sweep()
    assert result["listings_expired"] == 1
    assert abc.get(f"/resources/{resource.id}").json()["status"] == "EXPIRED"
    assert abc.get("/matches").json() == []
    assert "LISTING_EXPIRED" in [n["type"] for n in abc.get("/notifications").json()]


# --- Demo seed --------------------------------------------------------------------------------

def test_demo_seed_produces_the_documented_scenarios(client, kb, db):
    from app.matching.models import Match
    from app.seed.demo import DOMAIN, seed_demo

    summary = seed_demo(db)
    assert summary["organizations"] >= 15
    login = client.post("/api/v1/auth/login", json={"email": f"xyz@{DOMAIN}", "password": "Symbio-Demo-2026!"})
    assert login.status_code == 200
    xyz = Api(client, login.json()["access_token"])
    demo = next(m for m in xyz.get("/matches").json() if m["counterpart"]["display_name"] == "ABC Steel"
                and m["match_type"] == "EXACT_MATERIAL")
    assert round(demo["distance_km"]) == 82 and demo["supply_utilization"] == 0.75
    matches = list(db.scalars(select(Match)))
    # Property mismatch: ABC's BOF slag (free lime 2.5 %) never matches Metro Roads' "free lime <= 1 %".
    assert not any(m.resource.name == "BOF steel slag (weathered)" and m.demander_org.display_name == "Metro Roads"
                   for m in matches)
    assert not any(m.demander_org.display_name == "Pune Metro Contractors" for m in matches)
    assert any(m.match_type.value == "SEMANTIC" for m in matches)
    assert any(m.is_hidden_match and m.demander_org.display_name == "Shakti Cement" for m in matches)
    assert any(m.status.value == "COMPLETED" for m in matches)
    # Idempotent: seeding twice does not duplicate organizations.
    assert seed_demo(db)["organizations"] == summary["organizations"]
