"""Registration, login, token rotation, logout, password reset, email verification."""

from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.audit import service as audit
from app.auth.models import RefreshToken, UserToken, UserTokenPurpose
from app.auth.schemas import RegisterRequest, TokenPair
from app.core import jobs
from app.core.config import get_settings
from app.core.errors import ConflictError, UnauthorizedError, ValidationFailedError
from app.core.security import (
    create_token,
    decode_token,
    generate_opaque_token,
    hash_password,
    password_needs_rehash,
    sha256_hex,
    verify_password,
)
from app.core.time import as_utc, utcnow
from app.notifications.email import send_email
from app.users.models import User

# Verifying against a real hash when the email is unknown keeps login timing uniform.
_DUMMY_HASH = hash_password("timing-equalizer-not-a-real-password-1")


def normalize_email(email: str) -> str:
    return email.strip().lower()


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalars(select(User).where(User.email == normalize_email(email))).first()


def issue_tokens(db: Session, user: User) -> TokenPair:
    settings = get_settings()
    access, _, _ = create_token(user.id, "access")
    refresh, jti, expires = create_token(user.id, "refresh")
    db.add(RefreshToken(user_id=user.id, jti_hash=sha256_hex(jti), expires_at=expires))
    return TokenPair(access_token=access, refresh_token=refresh, expires_in=settings.access_token_ttl_minutes * 60)


def register(db: Session, data: RegisterRequest) -> tuple[User, TokenPair]:
    email = normalize_email(data.email)
    if get_user_by_email(db, email):
        raise ConflictError("An account with this email already exists.", code="EMAIL_ALREADY_REGISTERED")
    user = User(
        email=email,
        password_hash=hash_password(data.password),
        first_name=data.first_name.strip(),
        last_name=data.last_name.strip(),
        phone=data.phone,
    )
    db.add(user)
    db.flush()
    tokens = issue_tokens(db, user)
    verification_token = _create_user_token(db, user, UserTokenPurpose.EMAIL_VERIFICATION,
                                            timedelta(hours=get_settings().email_verification_ttl_hours))
    audit.record(db, action="USER_REGISTERED", entity_type="user", entity_id=user.id, actor_user_id=user.id)
    db.commit()
    jobs.enqueue(send_email, user.email, "Verify your SYMBIO account",
                 f"Welcome to SYMBIO.\n\nYour verification code:\n{verification_token}\n")
    return user, tokens


def login(db: Session, email: str, password: str) -> tuple[User, TokenPair]:
    user = get_user_by_email(db, email)
    if user is None:
        verify_password(password, _DUMMY_HASH)
        raise UnauthorizedError("Incorrect email or password.", code="INVALID_CREDENTIALS")
    if not verify_password(password, user.password_hash):
        raise UnauthorizedError("Incorrect email or password.", code="INVALID_CREDENTIALS")
    if not user.is_active:
        raise UnauthorizedError("This account is not active.", code="ACCOUNT_INACTIVE")
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    user.last_login_at = utcnow()
    tokens = issue_tokens(db, user)
    db.commit()
    return user, tokens


def _active_refresh_record(db: Session, refresh_token: str) -> tuple[RefreshToken, dict]:
    payload = decode_token(refresh_token, "refresh")
    record = db.scalars(select(RefreshToken).where(RefreshToken.jti_hash == sha256_hex(payload.get("jti", "")))).first()
    if record is None:
        raise UnauthorizedError("Invalid refresh token.", code="INVALID_TOKEN")
    if record.revoked_at is not None:
        # Reuse of a rotated token suggests theft: revoke the whole token family for this user.
        db.execute(update(RefreshToken).where(RefreshToken.user_id == record.user_id, RefreshToken.revoked_at.is_(None))
                   .values(revoked_at=utcnow()))
        db.commit()
        raise UnauthorizedError("This session is no longer valid. Please sign in again.", code="TOKEN_REUSED")
    if as_utc(record.expires_at) <= utcnow():
        raise UnauthorizedError("Your session has expired. Please sign in again.", code="TOKEN_EXPIRED")
    return record, payload


def refresh(db: Session, refresh_token: str) -> TokenPair:
    record, _ = _active_refresh_record(db, refresh_token)
    user = db.get(User, record.user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError("This account is not active.", code="ACCOUNT_INACTIVE")
    record.revoked_at = utcnow()  # rotation: each refresh token is single-use
    tokens = issue_tokens(db, user)
    db.commit()
    return tokens


def logout(db: Session, refresh_token: str) -> None:
    try:
        record, _ = _active_refresh_record(db, refresh_token)
    except UnauthorizedError:
        return  # logging out with an already-invalid token is a no-op
    record.revoked_at = utcnow()
    db.commit()


def _create_user_token(db: Session, user: User, purpose: UserTokenPurpose, ttl: timedelta) -> str:
    raw = generate_opaque_token()
    db.add(UserToken(user_id=user.id, purpose=purpose, token_hash=sha256_hex(raw), expires_at=utcnow() + ttl))
    return raw


def _consume_user_token(db: Session, raw: str, purpose: UserTokenPurpose) -> User:
    token = db.scalars(select(UserToken).where(UserToken.token_hash == sha256_hex(raw),
                                               UserToken.purpose == purpose)).first()
    if token is None or token.used_at is not None or as_utc(token.expires_at) <= utcnow():
        raise ValidationFailedError("This link is invalid or has expired.", code="INVALID_OR_EXPIRED_TOKEN")
    token.used_at = utcnow()
    user = db.get(User, token.user_id)
    assert user is not None
    return user


def request_password_reset(db: Session, email: str) -> None:
    """Always succeeds from the caller's view so accounts cannot be enumerated."""
    user = get_user_by_email(db, email)
    if user is None or not user.is_active:
        return
    raw = _create_user_token(db, user, UserTokenPurpose.PASSWORD_RESET,
                             timedelta(minutes=get_settings().password_reset_ttl_minutes))
    db.commit()
    jobs.enqueue(send_email, user.email, "Reset your SYMBIO password",
                 f"Use this code to reset your password (valid for a short time):\n{raw}\n\n"
                 "If you did not request this, you can ignore this email.")


def confirm_password_reset(db: Session, raw_token: str, new_password: str) -> None:
    user = _consume_user_token(db, raw_token, UserTokenPurpose.PASSWORD_RESET)
    user.password_hash = hash_password(new_password)
    # Changing the password signs out every existing session.
    db.execute(update(RefreshToken).where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
               .values(revoked_at=utcnow()))
    audit.record(db, action="PASSWORD_RESET", entity_type="user", entity_id=user.id, actor_user_id=user.id)
    db.commit()


def verify_email(db: Session, raw_token: str) -> User:
    user = _consume_user_token(db, raw_token, UserTokenPurpose.EMAIL_VERIFICATION)
    user.is_verified = True
    db.commit()
    return user


def resend_verification(db: Session, user: User) -> None:
    if user.is_verified:
        return
    raw = _create_user_token(db, user, UserTokenPurpose.EMAIL_VERIFICATION,
                             timedelta(hours=get_settings().email_verification_ttl_hours))
    db.commit()
    jobs.enqueue(send_email, user.email, "Verify your SYMBIO account", f"Your verification code:\n{raw}\n")
