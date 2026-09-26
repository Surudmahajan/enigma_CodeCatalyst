from tests.conftest import Api, make_org, register_user


def test_create_organization_makes_caller_owner_with_default_facility(client):
    api = make_org(client, "ABC Steel")
    org = api.get("/organizations/me").json()
    assert org["my_role"] == "OWNER"
    assert "MANAGE_ORGANIZATION" in org["my_permissions"]
    assert org["verification_status"] == "PENDING"
    assert len(org["facilities"]) == 1
    me = api.get("/users/me").json()
    assert me["memberships"][0]["organization_name"] == "ABC Steel"


def test_user_without_organization_is_told_to_create_one(client):
    auth = register_user(client)
    response = Api(client, auth["access_token"]).get("/resources")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "NO_ORGANIZATION"


def test_public_profile_hides_contacts_and_exact_address(client):
    abc = make_org(client, "ABC Steel")
    xyz = make_org(client, "XYZ Construction")
    profile = xyz.get(f"/organizations/{abc.org_id}").json()
    assert profile["display_name"] == "ABC Steel"
    assert profile["location"] == {"city": "Pune", "state": "Maharashtra", "country": "India"}
    for private in ("business_email", "business_phone", "legal_name", "address", "latitude"):
        assert private not in profile and private not in profile["location"]


def test_cannot_act_as_an_organization_you_do_not_belong_to(client):
    abc = make_org(client, "ABC Steel")
    xyz = make_org(client, "XYZ Construction")
    spoof = Api(client, xyz.token, org_id=abc.org_id)
    response = spoof.get("/organizations/me")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "NOT_A_MEMBER"


def test_member_management_and_role_rules(client):
    owner = make_org(client, "ABC Steel")
    colleague = register_user(client, "viewer@abc.example")
    added = owner.post(f"/organizations/{owner.org_id}/members", json={"email": "viewer@abc.example", "role": "VIEWER"})
    assert added.status_code == 201
    viewer = Api(client, colleague["access_token"])
    # Viewers can read but not change the organization.
    assert viewer.get("/organizations/me").status_code == 200
    assert viewer.patch("/organizations/me", json={"description": "x"}).status_code == 403
    # The last owner cannot demote themself.
    members = owner.get(f"/organizations/{owner.org_id}/members").json()
    owner_member = next(m for m in members if m["role"] == "OWNER")
    demote = owner.patch(f"/organizations/{owner.org_id}/members/{owner_member['id']}", json={"role": "ADMIN"})
    assert demote.status_code == 409
    assert demote.json()["error"]["code"] == "LAST_OWNER"


def test_admin_cannot_grant_owner(client):
    owner = make_org(client)
    admin_auth = register_user(client, "admin@abc.example")
    owner.post(f"/organizations/{owner.org_id}/members", json={"email": "admin@abc.example", "role": "ADMIN"})
    register_user(client, "someone@abc.example")
    admin = Api(client, admin_auth["access_token"])
    response = admin.post(f"/organizations/{owner.org_id}/members",
                          json={"email": "someone@abc.example", "role": "OWNER"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ROLE_ESCALATION"


def test_add_facility_and_update(client):
    api = make_org(client)
    created = api.post("/organizations/me/facilities", json={
        "name": "Slag yard", "location": {"city": "Chakan", "country": "India", "latitude": 18.76, "longitude": 73.86}})
    assert created.status_code == 201
    updated = api.patch(f"/facilities/{created.json()['id']}", json={"status": "INACTIVE"})
    assert updated.json()["status"] == "INACTIVE"
