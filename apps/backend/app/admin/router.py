"""Admin console API. Every route requires a platform administrator (never an ordinary user)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select

from app.admin import service
from app.analytics.service import platform_analytics
from app.assessment.models import EmissionFactor, FactorScope
from app.audit.models import AuditLog
from app.core import jobs
from app.core.dependencies import DB, PlatformAdmin
from app.impact.service import verify_exchange_impact
from app.materials.schemas import (
    ApplicationTypeIn,
    ApplicationTypeOut,
    MaterialApplicationIn,
    MaterialApplicationOut,
    MaterialIn,
    MaterialOut,
    MaterialUpdate,
    PropertyDefinitionIn,
    PropertyDefinitionOut,
)
from app.matching.models import MatchingConfig, MatchStatus
from app.organizations.models import Organization, OrganizationStatus, VerificationStatus
from app.organizations.schemas import LocationPublic
from app.requirements.models import Requirement
from app.resources.models import Resource

router = APIRouter(prefix="/admin", tags=["admin"])


class AdminOrganizationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    legal_name: str
    display_name: str
    industry_sector: str
    business_email: str | None
    website: str | None
    verification_status: VerificationStatus
    status: OrganizationStatus
    operating_mode: str
    location: LocationPublic | None
    created_at: datetime
    member_count: int = 0
    active_resources: int = 0
    active_requirements: int = 0


class VerificationIn(BaseModel):
    status: Literal["VERIFIED", "REJECTED", "PENDING"]
    note: str | None = Field(default=None, max_length=500)


class NoteIn(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class ListingAdminOut(BaseModel):
    id: uuid.UUID
    kind: str
    organization: str
    name: str
    material: str | None
    quantity: Decimal
    unit: str
    frequency: str
    status: str
    window_start: date
    window_end: date | None
    updated_at: datetime


class MatchAdminOut(BaseModel):
    id: uuid.UUID
    provider: str
    demander: str
    resource: str
    requirement: str
    status: MatchStatus
    overall_score: float
    confidence_level: str
    match_type: str
    is_hidden_match: bool
    requires_manual_review: bool
    matching_version: str
    distance_km: float | None
    updated_at: datetime


class EmissionFactorIn(BaseModel):
    key: str = Field(min_length=3, max_length=80)
    scope: FactorScope
    material_id: uuid.UUID | None = None
    application_type_id: uuid.UUID | None = None
    disposition: str | None = None
    value: Decimal = Field(ge=0)
    unit: str = Field(max_length=32, examples=["kgCO2e/t-km"])
    source: str = Field(min_length=3, description="Citation for the factor")
    geography: str = Field(min_length=2, max_length=80)
    methodology: str = Field(min_length=3)
    version: str = Field(min_length=1, max_length=32)
    valid_from: date
    valid_until: date | None = None
    is_demo_value: bool = False


class EmissionFactorOut(EmissionFactorIn):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    is_active: bool
    created_at: datetime


class MatchingConfigIn(BaseModel):
    version: str = Field(pattern=r"^[0-9A-Za-z.\-]{1,32}$")
    description: str | None = None
    weights: dict[str, float]
    parameters: dict[str, Any] = Field(default_factory=dict)


class MatchingConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version: str
    description: str | None
    weights: dict[str, float]
    parameters: dict[str, Any]
    is_active: bool
    created_at: datetime


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    actor_user_id: uuid.UUID | None
    organization_id: uuid.UUID | None
    action: str
    entity_type: str
    entity_id: uuid.UUID | None
    details: dict[str, Any]
    request_id: str | None
    created_at: datetime


# --- Organizations ---------------------------------------------------------------------------

@router.get("/organizations", response_model=list[AdminOrganizationOut])
def list_organizations(_admin: PlatformAdmin, db: DB, verification_status: VerificationStatus | None = None,
                       q: str | None = Query(default=None, max_length=100)) -> list[AdminOrganizationOut]:
    query = select(Organization)
    if verification_status:
        query = query.where(Organization.verification_status == verification_status)
    if q:
        like = f"%{q.lower()}%"
        query = query.where(or_(func.lower(Organization.display_name).like(like),
                                func.lower(Organization.industry_sector).like(like)))
    out = []
    for org in db.scalars(query.order_by(Organization.created_at.desc())):
        item = AdminOrganizationOut.model_validate(org)
        item.member_count = len([m for m in org.members if m.status.value == "ACTIVE"])
        item.active_resources = db.scalar(select(func.count()).select_from(Resource).where(
            Resource.organization_id == org.id, Resource.status == "ACTIVE")) or 0
        item.active_requirements = db.scalar(select(func.count()).select_from(Requirement).where(
            Requirement.organization_id == org.id, Requirement.status == "ACTIVE")) or 0
        out.append(item)
    return out


@router.post("/organizations/{org_id}/verification", response_model=AdminOrganizationOut)
def set_verification(org_id: uuid.UUID, body: VerificationIn, admin: PlatformAdmin, db: DB) -> AdminOrganizationOut:
    return AdminOrganizationOut.model_validate(
        service.set_verification(db, admin, org_id, VerificationStatus(body.status), body.note))


@router.post("/organizations/{org_id}/suspend", response_model=AdminOrganizationOut)
def suspend(org_id: uuid.UUID, body: NoteIn, admin: PlatformAdmin, db: DB) -> AdminOrganizationOut:
    return AdminOrganizationOut.model_validate(service.set_suspended(db, admin, org_id, True, body.note))


@router.post("/organizations/{org_id}/reinstate", response_model=AdminOrganizationOut)
def reinstate(org_id: uuid.UUID, body: NoteIn, admin: PlatformAdmin, db: DB) -> AdminOrganizationOut:
    return AdminOrganizationOut.model_validate(service.set_suspended(db, admin, org_id, False, body.note))


# --- Listings and matches (read-only oversight) --------------------------------------------------

@router.get("/resources", response_model=list[ListingAdminOut])
def list_resources(_admin: PlatformAdmin, db: DB, status: str | None = None) -> list[ListingAdminOut]:
    query = select(Resource)
    if status:
        query = query.where(Resource.status == status)
    return [ListingAdminOut(id=r.id, kind="RESOURCE", organization=r.organization.display_name, name=r.name,
                            material=r.material.canonical_name if r.material else None, quantity=r.quantity_available,
                            unit=r.unit.value, frequency=r.frequency.value, status=r.status.value,
                            window_start=r.availability_start, window_end=r.availability_end, updated_at=r.updated_at)
            for r in db.scalars(query.order_by(Resource.updated_at.desc()).limit(500))]


@router.get("/requirements", response_model=list[ListingAdminOut])
def list_requirements(_admin: PlatformAdmin, db: DB, status: str | None = None) -> list[ListingAdminOut]:
    query = select(Requirement)
    if status:
        query = query.where(Requirement.status == status)
    return [ListingAdminOut(id=q.id, kind="REQUIREMENT", organization=q.organization.display_name, name=q.name,
                            material=q.material.canonical_name if q.material else None, quantity=q.quantity_required,
                            unit=q.unit.value, frequency=q.frequency.value, status=q.status.value,
                            window_start=q.required_from, window_end=q.required_until, updated_at=q.updated_at)
            for q in db.scalars(query.order_by(Requirement.updated_at.desc()).limit(500))]


@router.get("/matches", response_model=list[MatchAdminOut])
def list_matches(_admin: PlatformAdmin, db: DB, status: MatchStatus | None = None) -> list[MatchAdminOut]:
    return [MatchAdminOut(id=m.id, provider=m.provider_org.display_name, demander=m.demander_org.display_name,
                          resource=m.resource.name, requirement=m.requirement.name, status=m.status,
                          overall_score=m.overall_score, confidence_level=m.confidence_level.value,
                          match_type=m.match_type.value, is_hidden_match=m.is_hidden_match,
                          requires_manual_review=m.requires_manual_review, matching_version=m.matching_version,
                          distance_km=float(m.distance_km) if m.distance_km is not None else None,
                          updated_at=m.updated_at)
            for m in service.matches_for_admin(db, status)]


@router.post("/rematch", status_code=status.HTTP_202_ACCEPTED, summary="Re-evaluate all active listings")
def rematch(_admin: PlatformAdmin) -> dict[str, str]:
    jobs.enqueue(service.rematch_all)
    return {"status": "queued"}


# --- Knowledge base ----------------------------------------------------------------------------

@router.post("/materials", response_model=MaterialOut, status_code=status.HTTP_201_CREATED)
def create_material(body: MaterialIn, admin: PlatformAdmin, db: DB) -> MaterialOut:
    return MaterialOut.model_validate(service.create_material(db, admin, body))


@router.patch("/materials/{material_id}", response_model=MaterialOut)
def update_material(material_id: uuid.UUID, body: MaterialUpdate, admin: PlatformAdmin, db: DB) -> MaterialOut:
    return MaterialOut.model_validate(service.update_material(db, admin, material_id, body))


@router.post("/properties", response_model=PropertyDefinitionOut, status_code=status.HTTP_201_CREATED)
def create_property(body: PropertyDefinitionIn, admin: PlatformAdmin, db: DB) -> PropertyDefinitionOut:
    return PropertyDefinitionOut.model_validate(service.create_property(db, admin, body))


@router.post("/applications", response_model=ApplicationTypeOut, status_code=status.HTTP_201_CREATED)
def create_application(body: ApplicationTypeIn, admin: PlatformAdmin, db: DB) -> ApplicationTypeOut:
    return ApplicationTypeOut.model_validate(service.create_application_type(db, admin, body))


@router.post("/material-applications", response_model=MaterialApplicationOut)
def save_material_application(body: MaterialApplicationIn, admin: PlatformAdmin, db: DB) -> MaterialApplicationOut:
    return MaterialApplicationOut.model_validate(service.upsert_material_application(db, admin, body))


@router.delete("/material-applications/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_material_application(link_id: uuid.UUID, admin: PlatformAdmin, db: DB) -> None:
    service.delete_material_application(db, admin, link_id)


# --- Environmental factors ---------------------------------------------------------------------

@router.get("/emission-factors", response_model=list[EmissionFactorOut])
def list_factors(_admin: PlatformAdmin, db: DB, include_retired: bool = False) -> list[EmissionFactorOut]:
    query = select(EmissionFactor)
    if not include_retired:
        query = query.where(EmissionFactor.is_active.is_(True))
    return [EmissionFactorOut.model_validate(f) for f in db.scalars(query.order_by(EmissionFactor.key,
                                                                                   EmissionFactor.valid_from.desc()))]


@router.post("/emission-factors", response_model=EmissionFactorOut, status_code=status.HTTP_201_CREATED,
             summary="Add a new factor version (factors are never edited in place)")
def create_factor(body: EmissionFactorIn, admin: PlatformAdmin, db: DB) -> EmissionFactorOut:
    return EmissionFactorOut.model_validate(service.create_emission_factor(db, admin, body.model_dump()))


@router.post("/emission-factors/{factor_id}/retire", response_model=EmissionFactorOut)
def retire_factor(factor_id: uuid.UUID, admin: PlatformAdmin, db: DB) -> EmissionFactorOut:
    return EmissionFactorOut.model_validate(service.retire_emission_factor(db, admin, factor_id))


# --- Scoring configuration ---------------------------------------------------------------------

@router.get("/matching-configs", response_model=list[MatchingConfigOut])
def list_configs(_admin: PlatformAdmin, db: DB) -> list[MatchingConfigOut]:
    return [MatchingConfigOut.model_validate(c) for c in
            db.scalars(select(MatchingConfig).order_by(MatchingConfig.created_at.desc()))]


@router.post("/matching-configs", response_model=MatchingConfigOut, status_code=status.HTTP_201_CREATED)
def create_config(body: MatchingConfigIn, admin: PlatformAdmin, db: DB) -> MatchingConfigOut:
    return MatchingConfigOut.model_validate(
        service.create_matching_config(db, admin, body.version, body.weights, body.parameters, body.description))


@router.post("/matching-configs/{config_id}/activate", response_model=MatchingConfigOut,
             summary="Activate a configuration and re-evaluate all active listings")
def activate_config(config_id: uuid.UUID, admin: PlatformAdmin, db: DB) -> MatchingConfigOut:
    return MatchingConfigOut.model_validate(service.activate_matching_config(db, admin, config_id))


# --- Analytics, audit, impact verification --------------------------------------------------------

@router.get("/analytics", summary="Platform analytics from stored data")
def analytics(_admin: PlatformAdmin, db: DB) -> dict[str, Any]:
    return platform_analytics(db)


@router.get("/audit-logs", response_model=list[AuditLogOut])
def audit_logs(_admin: PlatformAdmin, db: DB, entity_type: str | None = None, action: str | None = None,
               limit: int = Query(default=100, ge=1, le=500)) -> list[AuditLogOut]:
    query = select(AuditLog)
    if entity_type:
        query = query.where(AuditLog.entity_type == entity_type)
    if action:
        query = query.where(AuditLog.action == action)
    return [AuditLogOut.model_validate(a) for a in db.scalars(query.order_by(AuditLog.created_at.desc()).limit(limit))]


@router.post("/impact/{exchange_id}/verify", summary="Mark an exchange's impact records as verified outcomes")
def verify_impact(exchange_id: uuid.UUID, admin: PlatformAdmin, db: DB) -> dict[str, int]:
    return {"verified_records": verify_exchange_impact(db, exchange_id, admin.id)}
