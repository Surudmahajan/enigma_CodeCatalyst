import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl

from app.organizations.models import (
    FacilityStatus,
    MemberRole,
    MemberStatus,
    OperatingMode,
    OrganizationStatus,
    VerificationStatus,
)


class LocationIn(BaseModel):
    address: str | None = Field(default=None, max_length=500)
    city: str = Field(min_length=1, max_length=120)
    state: str | None = Field(default=None, max_length=120)
    country: str = Field(min_length=2, max_length=80)
    postal_code: str | None = Field(default=None, max_length=20)
    latitude: Decimal | None = Field(default=None, ge=-90, le=90)
    longitude: Decimal | None = Field(default=None, ge=-180, le=180)


class LocationPublic(BaseModel):
    """Approximate location shown before a connection exists."""

    model_config = ConfigDict(from_attributes=True)

    city: str
    state: str | None
    country: str


class LocationPrivate(LocationPublic):
    address: str | None
    postal_code: str | None
    latitude: Decimal | None
    longitude: Decimal | None


class FacilityIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    location: LocationIn


class FacilityUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    location: LocationIn | None = None
    status: FacilityStatus | None = None


class FacilityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    status: FacilityStatus
    location: LocationPrivate


class OrganizationCreate(BaseModel):
    legal_name: str = Field(min_length=2, max_length=255)
    display_name: str = Field(min_length=2, max_length=255)
    industry_sector: str = Field(min_length=2, max_length=120, examples=["Steel manufacturing"])
    description: str | None = Field(default=None, max_length=4000)
    website: HttpUrl | None = None
    business_email: EmailStr | None = None
    business_phone: str | None = Field(default=None, max_length=32)
    operating_mode: OperatingMode = OperatingMode.BOTH
    headquarters: LocationIn
    first_facility: FacilityIn | None = Field(
        default=None, description="Defaults to a facility at the headquarters location"
    )


class OrganizationUpdate(BaseModel):
    legal_name: str | None = Field(default=None, min_length=2, max_length=255)
    display_name: str | None = Field(default=None, min_length=2, max_length=255)
    industry_sector: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=4000)
    website: HttpUrl | None = None
    business_email: EmailStr | None = None
    business_phone: str | None = Field(default=None, max_length=32)
    operating_mode: OperatingMode | None = None
    headquarters: LocationIn | None = None


class OrganizationPublic(BaseModel):
    """What any signed-in organization may see: no contacts, no exact address."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    display_name: str
    industry_sector: str
    description: str | None
    verification_status: VerificationStatus
    location: LocationPublic | None


class OrganizationOut(BaseModel):
    """Full profile, visible to the organization's own members."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    legal_name: str
    display_name: str
    industry_sector: str
    description: str | None
    website: str | None
    business_email: str | None
    business_phone: str | None
    verification_status: VerificationStatus
    status: OrganizationStatus
    operating_mode: OperatingMode
    location: LocationPrivate | None
    facilities: list[FacilityOut]
    created_at: datetime


class OrganizationContextOut(OrganizationOut):
    my_role: MemberRole
    my_permissions: list[str]


class MemberInvite(BaseModel):
    email: EmailStr
    role: MemberRole = MemberRole.MEMBER


class MemberUpdate(BaseModel):
    role: MemberRole | None = None
    status: MemberStatus | None = None


class MemberOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    email: str
    name: str
    role: MemberRole
    status: MemberStatus
    created_at: datetime
