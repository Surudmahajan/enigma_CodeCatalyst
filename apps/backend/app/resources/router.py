import uuid

from fastapi import APIRouter, status
from pydantic import BaseModel

from app.common.listing_schemas import FacilityRef
from app.common.listing_service import allowed_transitions
from app.common.listings import ListingStatus
from app.core.dependencies import DB, Org
from app.materials.schemas import MaterialSummary
from app.resources import service
from app.resources.models import Resource
from app.resources.schemas import ResourceCreate, ResourceOut, ResourceStatusChange, ResourceUpdate

router = APIRouter(prefix="/resources", tags=["resources (provider)"])


def to_out(r: Resource) -> ResourceOut:
    return ResourceOut(
        id=r.id, organization_id=r.organization_id, facility=FacilityRef.model_validate(r.facility),
        material=MaterialSummary.model_validate(r.material) if r.material else None, name=r.name,
        description=r.description, status=r.status, allowed_transitions=allowed_transitions(r.status),
        currency=r.currency, quantity_available=r.quantity_available, unit=r.unit, frequency=r.frequency,
        availability_start=r.availability_start, availability_end=r.availability_end,
        physical_state=r.physical_state, processing_required=r.processing_required,
        processing_types=r.processing_types or [], processing_description=r.processing_description,
        storage_notes=r.storage_notes, current_use=r.current_use, current_disposition=r.current_disposition,
        disposal_cost_per_unit=r.disposal_cost_per_unit, asking_price_per_unit=r.asking_price_per_unit,
        processing_cost_per_unit=r.processing_cost_per_unit,
        properties=[service.property_out(pv) for pv in r.property_values],
        created_at=r.created_at, updated_at=r.updated_at,
    )


@router.post("", response_model=ResourceOut, status_code=status.HTTP_201_CREATED,
             summary="Create a resource (what your organization can provide)")
def create_resource(body: ResourceCreate, ctx: Org, db: DB) -> ResourceOut:
    return to_out(service.create(db, ctx, body))


@router.get("", response_model=list[ResourceOut], summary="Your organization's resources")
def list_resources(ctx: Org, db: DB, status: ListingStatus | None = None) -> list[ResourceOut]:
    return [to_out(r) for r in service.list_owned(db, ctx, status)]


@router.get("/{resource_id}", response_model=ResourceOut)
def get_resource(resource_id: uuid.UUID, ctx: Org, db: DB) -> ResourceOut:
    return to_out(service.get_owned(db, ctx, resource_id))


@router.patch("/{resource_id}", response_model=ResourceOut)
def update_resource(resource_id: uuid.UUID, body: ResourceUpdate, ctx: Org, db: DB) -> ResourceOut:
    return to_out(service.update(db, ctx, resource_id, body))


@router.delete("/{resource_id}", response_model=ResourceOut, summary="Archive (soft-delete) a resource")
def archive_resource(resource_id: uuid.UUID, ctx: Org, db: DB) -> ResourceOut:
    return to_out(service.change_status(db, ctx, resource_id, ListingStatus.ARCHIVED))


@router.post("/{resource_id}/status", response_model=ResourceOut, summary="Explicit lifecycle transition")
def change_status(resource_id: uuid.UUID, body: ResourceStatusChange, ctx: Org, db: DB) -> ResourceOut:
    return to_out(service.change_status(db, ctx, resource_id, body.status))


@router.post("/{resource_id}/publish", response_model=ResourceOut)
def publish(resource_id: uuid.UUID, ctx: Org, db: DB) -> ResourceOut:
    return to_out(service.change_status(db, ctx, resource_id, ListingStatus.ACTIVE))


@router.post("/{resource_id}/activate", response_model=ResourceOut)
def activate(resource_id: uuid.UUID, ctx: Org, db: DB) -> ResourceOut:
    return to_out(service.change_status(db, ctx, resource_id, ListingStatus.ACTIVE))


@router.post("/{resource_id}/pause", response_model=ResourceOut)
def pause(resource_id: uuid.UUID, ctx: Org, db: DB) -> ResourceOut:
    return to_out(service.change_status(db, ctx, resource_id, ListingStatus.PAUSED))


class PropertyConfirmation(BaseModel):
    accept: bool = True


@router.post("/{resource_id}/properties/{value_id}/confirm", response_model=ResourceOut,
             summary="Confirm or reject an AI-extracted property value")
def confirm_property(resource_id: uuid.UUID, value_id: uuid.UUID, body: PropertyConfirmation,
                     ctx: Org, db: DB) -> ResourceOut:
    return to_out(service.confirm_property(db, ctx, resource_id, value_id, body.accept))
