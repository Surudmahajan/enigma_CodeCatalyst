import uuid

from fastapi import APIRouter, status

from app.common.listing_schemas import FacilityRef
from app.common.listing_service import allowed_transitions
from app.common.listings import ListingStatus
from app.core.dependencies import DB, Org
from app.materials.schemas import ApplicationTypeOut, MaterialSummary
from app.requirements import service
from app.requirements.models import Requirement
from app.requirements.schemas import RequirementCreate, RequirementOut, RequirementStatusChange, RequirementUpdate

router = APIRouter(prefix="/requirements", tags=["requirements (demander)"])


def to_out(r: Requirement) -> RequirementOut:
    return RequirementOut(
        id=r.id, organization_id=r.organization_id, facility=FacilityRef.model_validate(r.facility),
        material=MaterialSummary.model_validate(r.material) if r.material else None,
        intended_application=ApplicationTypeOut.model_validate(r.intended_application)
        if r.intended_application else None,
        name=r.name, description=r.description, status=r.status, allowed_transitions=allowed_transitions(r.status),
        currency=r.currency, quantity_required=r.quantity_required, unit=r.unit, frequency=r.frequency,
        required_from=r.required_from, required_until=r.required_until,
        max_transport_distance_km=r.max_transport_distance_km,
        processing_capabilities=r.processing_capabilities or [], acceptable_categories=r.acceptable_categories or [],
        excluded_material_ids=[uuid.UUID(i) for i in r.excluded_material_ids or []],
        virgin_material_price_per_unit=r.virgin_material_price_per_unit, max_price_per_unit=r.max_price_per_unit,
        economic_constraints=r.economic_constraints,
        property_constraints=[service.constraint_out(c) for c in r.property_constraints],
        created_at=r.created_at, updated_at=r.updated_at,
    )


@router.post("", response_model=RequirementOut, status_code=status.HTTP_201_CREATED,
             summary="Create a requirement (what your organization needs)")
def create_requirement(body: RequirementCreate, ctx: Org, db: DB) -> RequirementOut:
    return to_out(service.create(db, ctx, body))


@router.get("", response_model=list[RequirementOut], summary="Your organization's requirements")
def list_requirements(ctx: Org, db: DB, status: ListingStatus | None = None) -> list[RequirementOut]:
    return [to_out(r) for r in service.list_owned(db, ctx, status)]


@router.get("/{requirement_id}", response_model=RequirementOut)
def get_requirement(requirement_id: uuid.UUID, ctx: Org, db: DB) -> RequirementOut:
    return to_out(service.get_owned(db, ctx, requirement_id))


@router.patch("/{requirement_id}", response_model=RequirementOut)
def update_requirement(requirement_id: uuid.UUID, body: RequirementUpdate, ctx: Org, db: DB) -> RequirementOut:
    return to_out(service.update(db, ctx, requirement_id, body))


@router.delete("/{requirement_id}", response_model=RequirementOut, summary="Archive (soft-delete) a requirement")
def archive_requirement(requirement_id: uuid.UUID, ctx: Org, db: DB) -> RequirementOut:
    return to_out(service.change_status(db, ctx, requirement_id, ListingStatus.ARCHIVED))


@router.post("/{requirement_id}/status", response_model=RequirementOut, summary="Explicit lifecycle transition")
def change_status(requirement_id: uuid.UUID, body: RequirementStatusChange, ctx: Org, db: DB) -> RequirementOut:
    return to_out(service.change_status(db, ctx, requirement_id, body.status))


@router.post("/{requirement_id}/publish", response_model=RequirementOut)
def publish(requirement_id: uuid.UUID, ctx: Org, db: DB) -> RequirementOut:
    return to_out(service.change_status(db, ctx, requirement_id, ListingStatus.ACTIVE))


@router.post("/{requirement_id}/activate", response_model=RequirementOut)
def activate(requirement_id: uuid.UUID, ctx: Org, db: DB) -> RequirementOut:
    return to_out(service.change_status(db, ctx, requirement_id, ListingStatus.ACTIVE))


@router.post("/{requirement_id}/pause", response_model=RequirementOut)
def pause(requirement_id: uuid.UUID, ctx: Org, db: DB) -> RequirementOut:
    return to_out(service.change_status(db, ctx, requirement_id, ListingStatus.PAUSED))
