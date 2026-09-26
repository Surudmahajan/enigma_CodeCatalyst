"""Password hashing (Argon2id) and JWT access/refresh tokens."""

import hashlib
import secrets
import uuid
from datetime import timedelta
from typing import Any, Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import get_settings
from app.core.errors import UnauthorizedError
from app.core.time import utcnow

_hasher = PasswordHasher()

TokenType = Literal["access", "refresh"]


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def generate_opaque_token() -> str:
    """Random URL-safe token for password reset / email verification links."""
    return secrets.token_urlsafe(32)


def create_token(user_id: uuid.UUID, token_type: TokenType) -> tuple[str, str, Any]:
    """Return (encoded_jwt, jti, expires_at)."""
    settings = get_settings()
    now = utcnow()
    if token_type == "access":
        expires = now + timedelta(minutes=settings.access_token_ttl_minutes)
        secret = settings.jwt_secret
    else:
        expires = now + timedelta(days=settings.refresh_token_ttl_days)
        secret = settings.jwt_refresh_secret
    jti = uuid.uuid4().hex
    payload = {"sub": str(user_id), "type": token_type, "jti": jti, "iat": now, "exp": expires}
    return jwt.encode(payload, secret, algorithm=settings.jwt_algorithm), jti, expires


def decode_token(token: str, token_type: TokenType) -> dict[str, Any]:
    settings = get_settings()
    secret = settings.jwt_secret if token_type == "access" else settings.jwt_refresh_secret
    try:
        payload = jwt.decode(token, secret, algorithms=[settings.jwt_algorithm], options={"require": ["exp", "sub"]})
    except jwt.ExpiredSignatureError as exc:
        raise UnauthorizedError("Your session has expired. Please sign in again.", code="TOKEN_EXPIRED") from exc
    except jwt.PyJWTError as exc:
        raise UnauthorizedError("Invalid authentication token.", code="INVALID_TOKEN") from exc
    if payload.get("type") != token_type:
        raise UnauthorizedError("Invalid authentication token.", code="INVALID_TOKEN")
    return payload
