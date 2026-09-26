from fastapi import APIRouter, Depends, status

from app.auth import service
from app.auth.schemas import (
    AuthResponse,
    LoginRequest,
    MessageResponse,
    PasswordResetConfirm,
    PasswordResetRequest,
    RefreshRequest,
    RegisterRequest,
    TokenPair,
    VerifyEmailRequest,
)
from app.core.dependencies import DB, CurrentUser
from app.core.rate_limit import rate_limit
from app.users.schemas import UserOut

router = APIRouter(prefix="/auth", tags=["auth"])

_auth_limit = Depends(rate_limit("auth", limit=10, window_seconds=60))


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED,
             dependencies=[_auth_limit], summary="Create a user account")
def register(body: RegisterRequest, db: DB) -> AuthResponse:
    user, tokens = service.register(db, body)
    return AuthResponse(**tokens.model_dump(), user=UserOut.model_validate(user))


@router.post("/login", response_model=AuthResponse, dependencies=[_auth_limit], summary="Sign in with email and password")
def login(body: LoginRequest, db: DB) -> AuthResponse:
    user, tokens = service.login(db, body.email, body.password)
    return AuthResponse(**tokens.model_dump(), user=UserOut.model_validate(user))


@router.post("/refresh", response_model=TokenPair, dependencies=[_auth_limit],
             summary="Exchange a refresh token for a new token pair (rotation)")
def refresh(body: RefreshRequest, db: DB) -> TokenPair:
    return service.refresh(db, body.refresh_token)


@router.post("/logout", response_model=MessageResponse, summary="Revoke a refresh token")
def logout(body: RefreshRequest, db: DB) -> MessageResponse:
    service.logout(db, body.refresh_token)
    return MessageResponse(message="Signed out.")


@router.post("/password-reset/request", response_model=MessageResponse, status_code=status.HTTP_202_ACCEPTED,
             dependencies=[_auth_limit])
def request_password_reset(body: PasswordResetRequest, db: DB) -> MessageResponse:
    service.request_password_reset(db, body.email)
    return MessageResponse(message="If an account exists for this email, a reset code has been sent.")


@router.post("/password-reset/confirm", response_model=MessageResponse, dependencies=[_auth_limit])
def confirm_password_reset(body: PasswordResetConfirm, db: DB) -> MessageResponse:
    service.confirm_password_reset(db, body.token, body.new_password)
    return MessageResponse(message="Password updated. Please sign in again.")


@router.post("/verify-email", response_model=MessageResponse, dependencies=[_auth_limit])
def verify_email(body: VerifyEmailRequest, db: DB) -> MessageResponse:
    service.verify_email(db, body.token)
    return MessageResponse(message="Email verified.")


@router.post("/verify-email/resend", response_model=MessageResponse, dependencies=[_auth_limit])
def resend_verification(user: CurrentUser, db: DB) -> MessageResponse:
    service.resend_verification(db, user)
    return MessageResponse(message="Verification email sent.")
