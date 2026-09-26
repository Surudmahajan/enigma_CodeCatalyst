import re

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.users.schemas import UserOut

_PASSWORD_RULES = "at least 10 characters, including a letter and a number"


def _check_password(value: str) -> str:
    if len(value) < 10 or not re.search(r"[A-Za-z]", value) or not re.search(r"\d", value):
        raise ValueError(f"Password must be {_PASSWORD_RULES}.")
    return value


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128, examples=["Str0ng-password"])
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=32)

    _password = field_validator("password")(_check_password)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Access token lifetime in seconds")


class AuthResponse(TokenPair):
    user: UserOut


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    new_password: str = Field(min_length=10, max_length=128)

    _password = field_validator("new_password")(_check_password)


class VerifyEmailRequest(BaseModel):
    token: str = Field(min_length=10, max_length=200)


class MessageResponse(BaseModel):
    message: str
