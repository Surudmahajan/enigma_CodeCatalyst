import uuid

from fastapi import APIRouter, status

from app.core.dependencies import DB, CurrentUser, Org, resolve_org_context
from app.core.errors import ForbiddenError
from app.organizations import service
from app.organizations.models import Organization, OrganizationMember
from app.organizations.permissions import permissions_for
from app.organizations.schemas import (
    FacilityIn,
    FacilityOut,
    FacilityUpdate,
    MemberInvite,
    MemberOut,
    MemberUpdate,
    OrganizationContextOut,
    OrganizationCreate,
    OrganizationOut,
    OrganizationPublic,
    OrganizationUpdate,
)

router = APIRouter(prefix="/organizations", tags=["organizations"])
facilities_router = APIRouter(prefix="/facilities", tags=["organizations"])


def _context_out(org: Organization, membership: OrganizationMember) -> OrganizationContextOut:
    base = OrganizationOut.model_validate(org).model_dump()
    return OrganizationContextOut(**base, my_role=membership.role, my_permissions=permissions_for(membership.role))


def _member_out(m: OrganizationMember) -> MemberOut:
    return MemberOut(id=m.id, user_id=m.user_id, email=m.user.email, name=m.user.full_name, role=m.role,
                     status=m.status, created_at=m.created_at)


@router.post("", response_model=OrganizationContextOut, status_code=status.HTTP_201_CREATED,
             summary="Create an organization; the caller becomes its OWNER")
def create_organization(body: OrganizationCreate, user: CurrentUser, db: DB) -> OrganizationContextOut:
    org = service.create_organization(db, user, body)
    ctx = resolve_org_context(db, user, org.id)
    return _context_out(org, ctx.membership)


@router.get("/me", response_model=OrganizationContextOut, summary="The organization you are acting as")
def get_my_organization(ctx: Org) -> OrganizationContextOut:
    return _context_out(ctx.organization, ctx.membership)


@router.patch("/me", response_model=OrganizationContextOut)
def update_my_organization(body: OrganizationUpdate, ctx: Org, db: DB) -> OrganizationContextOut:
    org = service.update_organization(db, ctx, body)
    return _context_out(org, ctx.membership)


@router.get("/me/facilities", response_model=list[FacilityOut])
def list_facilities(ctx: Org, db: DB) -> list[FacilityOut]:
    return [FacilityOut.model_validate(f) for f in service.list_facilities(db, ctx)]


@router.post("/me/facilities", response_model=FacilityOut, status_code=status.HTTP_201_CREATED)
def add_facility(body: FacilityIn, ctx: Org, db: DB) -> FacilityOut:
    return FacilityOut.model_validate(service.add_facility(db, ctx, body))


@facilities_router.patch("/{facility_id}", response_model=FacilityOut)
def update_facility(facility_id: uuid.UUID, body: FacilityUpdate, ctx: Org, db: DB) -> FacilityOut:
    return FacilityOut.model_validate(service.update_facility(db, ctx, facility_id, body))


def _ctx_for(db, user, org_id: uuid.UUID):
    return resolve_org_context(db, user, org_id)


@router.get("/{org_id}/members", response_model=list[MemberOut])
def list_members(org_id: uuid.UUID, user: CurrentUser, db: DB) -> list[MemberOut]:
    ctx = _ctx_for(db, user, org_id)
    return [_member_out(m) for m in service.list_members(db, ctx)]


@router.post("/{org_id}/members", response_model=MemberOut, status_code=status.HTTP_201_CREATED,
             summary="Add an existing SYMBIO user to the organization")
def add_member(org_id: uuid.UUID, body: MemberInvite, user: CurrentUser, db: DB) -> MemberOut:
    ctx = _ctx_for(db, user, org_id)
    return _member_out(service.add_member(db, ctx, body))


@router.patch("/{org_id}/members/{member_id}", response_model=MemberOut)
def update_member(org_id: uuid.UUID, member_id: uuid.UUID, body: MemberUpdate, user: CurrentUser, db: DB) -> MemberOut:
    ctx = _ctx_for(db, user, org_id)
    return _member_out(service.update_member(db, ctx, member_id, body))


@router.get("/{org_id}", response_model=OrganizationPublic, summary="Public profile of any organization")
def get_public_profile(org_id: uuid.UUID, _user: CurrentUser, db: DB) -> OrganizationPublic:
    org = service.get_organization(db, org_id)
    if not org.is_active:
        raise ForbiddenError("This organization is not available.", code="ORGANIZATION_UNAVAILABLE")
    return OrganizationPublic.model_validate(org)
