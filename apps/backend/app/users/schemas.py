import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.organizations.models import MemberRole, OperatingMode, VerificationStatus


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    phone: str | None
    first_name: str
    last_name: str
    is_verified: bool
    is_platform_admin: bool
    created_at: datetime


class MembershipSummary(BaseModel):
    organization_id: uuid.UUID
    organization_name: str
    operating_mode: OperatingMode
    verification_status: VerificationStatus
    role: MemberRole
    permissions: list[str]


class MeOut(UserOut):
    memberships: list[MembershipSummary]


class UserUpdate(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=32)
