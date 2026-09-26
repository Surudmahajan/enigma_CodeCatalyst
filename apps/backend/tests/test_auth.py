from sqlalchemy import select

from app.auth.models import UserToken, UserTokenPurpose
from app.core.security import sha256_hex
from tests.conftest import PASSWORD, Api, register_user


def test_register_login_and_me(client):
    auth = register_user(client, "Owner@Example.com")
    assert auth["user"]["email"] == "owner@example.com"  # normalized
    login = client.post("/api/v1/auth/login", json={"email": "owner@example.com", "password": PASSWORD})
    assert login.status_code == 200
    me = Api(client, login.json()["access_token"]).get("/users/me")
    assert me.status_code == 200
    assert me.json()["memberships"] == []


def test_duplicate_registration_rejected(client):
    register_user(client, "dup@example.com")
    response = client.post("/api/v1/auth/register", json={
        "email": "DUP@example.com", "password": PASSWORD, "first_name": "A", "last_name": "B"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EMAIL_ALREADY_REGISTERED"


def test_weak_password_rejected(client):
    response = client.post("/api/v1/auth/register", json={
        "email": "weak@example.com", "password": "onlyletters", "first_name": "A", "last_name": "B"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_wrong_password_and_unknown_email_look_identical(client):
    register_user(client, "known@example.com")
    wrong = client.post("/api/v1/auth/login", json={"email": "known@example.com", "password": "Nope-12345678"})
    unknown = client.post("/api/v1/auth/login", json={"email": "ghost@example.com", "password": "Nope-12345678"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["code"] == unknown.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_protected_route_requires_token(client):
    assert client.get("/api/v1/users/me").status_code == 401
    bad = client.get("/api/v1/users/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert bad.status_code == 401


def test_refresh_rotates_and_detects_reuse(client):
    auth = register_user(client)
    first = client.post("/api/v1/auth/refresh", json={"refresh_token": auth["refresh_token"]})
    assert first.status_code == 200
    # Re-using the rotated token is treated as theft and kills the session family.
    reuse = client.post("/api/v1/auth/refresh", json={"refresh_token": auth["refresh_token"]})
    assert reuse.status_code == 401
    assert reuse.json()["error"]["code"] == "TOKEN_REUSED"
    after = client.post("/api/v1/auth/refresh", json={"refresh_token": first.json()["refresh_token"]})
    assert after.status_code == 401


def test_logout_revokes_refresh_token(client):
    auth = register_user(client)
    assert client.post("/api/v1/auth/logout", json={"refresh_token": auth["refresh_token"]}).status_code == 200
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": auth["refresh_token"]}).status_code == 401


def test_password_reset_flow(client, db, monkeypatch):
    import app.auth.service as auth_service

    captured = {}
    counter = iter(range(1000))

    def fake_token():
        captured["t"] = f"reset-token-abc-{next(counter):06d}"
        return captured["t"]

    monkeypatch.setattr(auth_service, "generate_opaque_token", fake_token)
    register_user(client, "reset@example.com")
    assert client.post("/api/v1/auth/password-reset/request", json={"email": "reset@example.com"}).status_code == 202
    # Unknown email behaves identically (no account enumeration).
    assert client.post("/api/v1/auth/password-reset/request", json={"email": "no@example.com"}).status_code == 202
    token = db.scalars(select(UserToken).where(UserToken.purpose == UserTokenPurpose.PASSWORD_RESET)).one()
    assert token.token_hash == sha256_hex(captured["t"])  # only the hash is stored
    ok = client.post("/api/v1/auth/password-reset/confirm",
                     json={"token": captured["t"], "new_password": "Brand-new-pass-99"})
    assert ok.status_code == 200
    again = client.post("/api/v1/auth/password-reset/confirm",
                        json={"token": captured["t"], "new_password": "Another-pass-99"})
    assert again.status_code == 422  # single use
    assert client.post("/api/v1/auth/login", json={"email": "reset@example.com",
                                                   "password": "Brand-new-pass-99"}).status_code == 200
