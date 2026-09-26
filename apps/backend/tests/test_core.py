from enum import StrEnum

import pytest
from fastapi.testclient import TestClient

from app.core.errors import InvalidStateTransitionError
from app.core.security import create_token, decode_token, hash_password, verify_password
from app.core.state_machine import StateMachine
from app.main import app


def test_health_endpoint_returns_request_id():
    client = TestClient(app)
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers.get("x-request-id")


def test_unknown_route_uses_error_envelope():
    client = TestClient(app)
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_password_hashing_roundtrip():
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong", hashed)


def test_access_token_cannot_be_used_as_refresh_token():
    import uuid

    from app.core.errors import UnauthorizedError

    token, _jti, _exp = create_token(uuid.uuid4(), "access")
    assert decode_token(token, "access")["type"] == "access"
    with pytest.raises(UnauthorizedError):
        decode_token(token, "refresh")


class _Light(StrEnum):
    RED = "RED"
    GREEN = "GREEN"
    YELLOW = "YELLOW"


def test_state_machine_rejects_undeclared_transition():
    machine = StateMachine("light", {_Light.RED: [_Light.GREEN], _Light.GREEN: [_Light.YELLOW]})
    machine.assert_transition(_Light.RED, _Light.GREEN)
    with pytest.raises(InvalidStateTransitionError) as exc:
        machine.assert_transition(_Light.RED, _Light.YELLOW)
    assert exc.value.details["allowed"] == ["GREEN"]
