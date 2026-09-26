import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import service as audit
from app.core.dependencies import OrgContext
from app.core.errors import ConflictError, ForbiddenError, NotFoundError
from app.organizations.models import (
    Facility,
    FacilityStatus,
    Location,
    MemberRole,
    MemberStatus,
    Organization,
    OrganizationMember,
)
from app.organizations.permissions import ROLE_RANK, Permission
from app.organizations.schemas import (
    FacilityIn,
    FacilityUpdate,
    LocationIn,
    MemberInvite,
    MemberUpdate,
    OrganizationCreate,
    OrganizationUpdate,
)
from app.users.models import User


def _location(data: LocationIn) -> Location:
    return Location(**data.model_dump())


def _apply_location(location: Location, data: LocationIn) -> None:
    for field, value in data.model_dump().items():
        setattr(location, field, value)


def create_organization(db: Session, user: User, data: OrganizationCreate) -> Organization:
    hq = _location(data.headquarters)
    org = Organization(
        legal_name=data.legal_name.strip(),
        display_name=data.display_name.strip(),
        industry_sector=data.industry_sector.strip(),
        description=data.description,
        website=str(data.website) if data.website else None,
        business_email=data.business_email,
        business_phone=data.business_phone,
        operating_mode=data.operating_mode,
        location=hq,
    )
    db.add(org)
    db.flush()
    facility_data = data.first_facility or FacilityIn(name="Main facility", location=data.headquarters)
    db.add(Facility(organization_id=org.id, name=facility_data.name, location=_location(facility_data.location)))
    db.add(OrganizationMember(organization_id=org.id, user_id=user.id, role=MemberRole.OWNER))
    audit.record(db, action="ORGANIZATION_CREATED", entity_type="organization", entity_id=org.id,
                 actor_user_id=user.id, organization_id=org.id)
    db.commit()
    db.refresh(org)
    return org


def update_organization(db: Session, ctx: OrgContext, data: OrganizationUpdate) -> Organization:
    ctx.require(Permission.MANAGE_ORGANIZATION)
    org = ctx.organization
    changes = data.model_dump(exclude_unset=True)
    headquarters = changes.pop("headquarters", None)
    for field, value in changes.items():
        setattr(org, field, str(value) if field == "website" and value else value)
    if headquarters is not None:
        if org.location is None:
            org.location = _location(data.headquarters)
        else:
            _apply_location(org.location, data.headquarters)
    audit.record(db, action="ORGANIZATION_UPDATED", entity_type="organization", entity_id=org.id,
                 actor_user_id=ctx.user.id, organization_id=org.id, details={"fields": sorted(data.model_fields_set)})
    db.commit()
    db.refresh(org)
    return org


def get_organization(db: Session, org_id: uuid.UUID) -> Organization:
    org = db.get(Organization, org_id)
    if org is None:
        raise NotFoundError("Organization not found.", code="ORGANIZATION_NOT_FOUND")
    return org


# --- Facilities -------------------------------------------------------------------------

def get_owned_facility(db: Session, ctx: OrgContext, facility_id: uuid.UUID) -> Facility:
    facility = db.get(Facility, facility_id)
    if facility is None or facility.organization_id != ctx.org_id:
        raise NotFoundError("Facility not found.", code="FACILITY_NOT_FOUND")
    return facility


def add_facility(db: Session, ctx: OrgContext, data: FacilityIn) -> Facility:
    ctx.require(Permission.MANAGE_ORGANIZATION)
    facility = Facility(organization_id=ctx.org_id, name=data.name, location=_location(data.location))
    db.add(facility)
    db.commit()
    db.refresh(facility)
    return facility


def update_facility(db: Session, ctx: OrgContext, facility_id: uuid.UUID, data: FacilityUpdate) -> Facility:
    ctx.require(Permission.MANAGE_ORGANIZATION)
    facility = get_owned_facility(db, ctx, facility_id)
    if data.name is not None:
        facility.name = data.name
    if data.status is not None:
        facility.status = data.status
    if data.location is not None:
        _apply_location(facility.location, data.location)
    db.commit()
    db.refresh(facility)
    return facility


def list_facilities(db: Session, ctx: OrgContext) -> list[Facility]:
    return list(db.scalars(select(Facility).where(Facility.organization_id == ctx.org_id).order_by(Facility.created_at)))


def require_active_facility(db: Session, ctx: OrgContext, facility_id: uuid.UUID) -> Facility:
    facility = get_owned_facility(db, ctx, facility_id)
    if facility.status != FacilityStatus.ACTIVE:
        raise ConflictError("This facility is inactive.", code="FACILITY_INACTIVE")
    return facility


# --- Members ----------------------------------------------------------------------------

def list_members(db: Session, ctx: OrgContext) -> list[OrganizationMember]:
    return list(db.scalars(select(OrganizationMember).where(OrganizationMember.organization_id == ctx.org_id)
                           .order_by(OrganizationMember.created_at)))


def _assert_can_manage_role(ctx: OrgContext, target_role: MemberRole) -> None:
    # Nobody may grant or manage a role above their own; only owners manage owners.
    if ROLE_RANK[target_role] > ROLE_RANK[ctx.membership.role] or (
        target_role == MemberRole.OWNER and ctx.membership.role != MemberRole.OWNER
    ):
        raise ForbiddenError("You cannot manage a role higher than your own.", code="ROLE_ESCALATION")


def add_member(db: Session, ctx: OrgContext, data: MemberInvite) -> OrganizationMember:
    ctx.require(Permission.MANAGE_ORGANIZATION)
    _assert_can_manage_role(ctx, data.role)
    user = db.scalars(select(User).where(User.email == data.email.strip().lower())).first()
    if user is None:
        raise NotFoundError("No SYMBIO account uses this email. Ask them to register first.", code="USER_NOT_FOUND")
    existing = db.scalars(select(OrganizationMember).where(OrganizationMember.organization_id == ctx.org_id,
                                                           OrganizationMember.user_id == user.id)).first()
    if existing and existing.status == MemberStatus.ACTIVE:
        raise ConflictError("This user is already a member.", code="ALREADY_MEMBER")
    if existing:
        existing.status, existing.role = MemberStatus.ACTIVE, data.role
        member = existing
    else:
        member = OrganizationMember(organization_id=ctx.org_id, user_id=user.id, role=data.role)
        db.add(member)
    db.flush()
    audit.record(db, action="MEMBER_ADDED", entity_type="organization_member", entity_id=member.id,
                 actor_user_id=ctx.user.id, organization_id=ctx.org_id, details={"role": data.role})
    db.commit()
    db.refresh(member)
    return member


def _active_owner_count(db: Session, org_id: uuid.UUID) -> int:
    return db.scalar(select(func.count()).select_from(OrganizationMember).where(
        OrganizationMember.organization_id == org_id, OrganizationMember.role == MemberRole.OWNER,
        OrganizationMember.status == MemberStatus.ACTIVE)) or 0


def update_member(db: Session, ctx: OrgContext, member_id: uuid.UUID, data: MemberUpdate) -> OrganizationMember:
    ctx.require(Permission.MANAGE_ORGANIZATION)
    member = db.get(OrganizationMember, member_id)
    if member is None or member.organization_id != ctx.org_id:
        raise NotFoundError("Member not found.", code="MEMBER_NOT_FOUND")
    _assert_can_manage_role(ctx, member.role)
    if data.role is not None:
        _assert_can_manage_role(ctx, data.role)
    losing_owner = member.role == MemberRole.OWNER and (
        (data.role is not None and data.role != MemberRole.OWNER)
        or (data.status is not None and data.status != MemberStatus.ACTIVE)
    )
    if losing_owner and _active_owner_count(db, ctx.org_id) <= 1:
        raise ConflictError("An organization must keep at least one owner.", code="LAST_OWNER")
    if data.role is not None:
        member.role = data.role
    if data.status is not None:
        member.status = data.status
    audit.record(db, action="MEMBER_UPDATED", entity_type="organization_member", entity_id=member.id,
                 actor_user_id=ctx.user.id, organization_id=ctx.org_id,
                 details=data.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(member)
    return member
