import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, Timestamps, UUIDPrimaryKey, str_enum
from app.core.time import utcnow


class VerificationStatus(StrEnum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"


class OrganizationStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class OperatingMode(StrEnum):
    """Which workspace(s) the organization uses. Controls UI/workflow only —
    it never restricts what data an organization may own (locked principle 2)."""

    PROVIDER = "PROVIDER"
    DEMANDER = "DEMANDER"
    BOTH = "BOTH"


class MemberRole(StrEnum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    MANAGER = "MANAGER"
    MEMBER = "MEMBER"
    VIEWER = "VIEWER"


class MemberStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INVITED = "INVITED"
    REVOKED = "REVOKED"


class FacilityStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class Location(UUIDPrimaryKey, Base):
    """A physical address. Exact coordinates are private until a connection
    exists; public views expose city/state/country only."""

    __tablename__ = "locations"
    __table_args__ = (
        CheckConstraint("latitude IS NULL OR (latitude >= -90 AND latitude <= 90)", name="latitude_range"),
        CheckConstraint("longitude IS NULL OR (longitude >= -180 AND longitude <= 180)", name="longitude_range"),
    )

    address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str] = mapped_column(String(120))
    state: Mapped[str | None] = mapped_column(String(120))
    country: Mapped[str] = mapped_column(String(80))
    postal_code: Mapped[str | None] = mapped_column(String(20))
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))


class Organization(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "organizations"

    legal_name: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(255), index=True)
    industry_sector: Mapped[str] = mapped_column(String(120), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    website: Mapped[str | None] = mapped_column(String(255))
    business_email: Mapped[str | None] = mapped_column(String(320))
    business_phone: Mapped[str | None] = mapped_column(String(32))
    verification_status: Mapped[VerificationStatus] = mapped_column(
        str_enum(VerificationStatus), default=VerificationStatus.PENDING, index=True
    )
    status: Mapped[OrganizationStatus] = mapped_column(str_enum(OrganizationStatus), default=OrganizationStatus.ACTIVE)
    operating_mode: Mapped[OperatingMode] = mapped_column(str_enum(OperatingMode), default=OperatingMode.BOTH)
    location_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("locations.id"))

    location: Mapped[Location | None] = relationship(lazy="joined")
    members = relationship("OrganizationMember", back_populates="organization", lazy="selectin")
    facilities = relationship("Facility", back_populates="organization", lazy="selectin")

    @property
    def is_active(self) -> bool:
        return self.status == OrganizationStatus.ACTIVE


class OrganizationMember(UUIDPrimaryKey, Base):
    __tablename__ = "organization_members"
    __table_args__ = (UniqueConstraint("organization_id", "user_id", name="uq_org_member"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[MemberRole] = mapped_column(str_enum(MemberRole), default=MemberRole.MEMBER)
    status: Mapped[MemberStatus] = mapped_column(str_enum(MemberStatus), default=MemberStatus.ACTIVE)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    organization: Mapped[Organization] = relationship(back_populates="members", lazy="joined")
    user = relationship("User", back_populates="memberships", lazy="joined")


class Facility(UUIDPrimaryKey, Timestamps, Base):
    """A site operated by an organization. Resources and requirements attach
    to a facility, so one company can list from several locations."""

    __tablename__ = "facilities"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    location_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("locations.id"))
    status: Mapped[FacilityStatus] = mapped_column(str_enum(FacilityStatus), default=FacilityStatus.ACTIVE)

    organization: Mapped[Organization] = relationship(back_populates="facilities")
    location: Mapped[Location] = relationship(lazy="joined")
