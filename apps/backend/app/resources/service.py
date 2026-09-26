import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import service as audit
from app.common import listing_service as common
from app.common.listing_schemas import PropertyValueIn, PropertyValueOut
from app.common.listings import ListingStatus, ValueSource
from app.core import events
from app.core.dependencies import OrgContext
from app.core.errors import ConflictError
from app.core.events import DomainEvent, EventType
from app.materials import service as materials
from app.organizations import service as orgs
from app.organizations.permissions import Permission
from app.resources.models import Resource, ResourcePropertyValue
from app.resources.schemas import ResourceCreate, ResourceUpdate

# Changing any of these can change match results, so they trigger recalculation.
MATCH_RELEVANT_FIELDS = {
    "facility_id", "material_id", "name", "description", "quantity_available", "unit", "frequency",
    "availability_start", "availability_end", "physical_state", "processing_required", "processing_types",
    "current_disposition", "disposal_cost_per_unit", "asking_price_per_unit", "processing_cost_per_unit", "properties",
}


def get_owned(db: Session, ctx: OrgContext, resource_id: uuid.UUID) -> Resource:
    resource = db.get(Resource, resource_id)
    if resource is None or resource.organization_id != ctx.org_id:
        # Identical response for "missing" and "someone else's": no cross-org probing.
        raise common.not_found("resource")
    return resource


def list_owned(db: Session, ctx: OrgContext, status: ListingStatus | None = None) -> list[Resource]:
    query = select(Resource).where(Resource.organization_id == ctx.org_id)
    if status:
        query = query.where(Resource.status == status)
    else:
        query = query.where(Resource.status != ListingStatus.ARCHIVED)
    return list(db.scalars(query.order_by(Resource.updated_at.desc())))


def _replace_user_properties(db: Session, resource: Resource, items: list[PropertyValueIn]) -> None:
    definitions = materials.properties_by_key(db, {i.property_key for i in items})
    if len({i.property_key for i in items}) != len(items):
        raise ConflictError("Each property may appear only once.", code="DUPLICATE_PROPERTY")
    # User-entered values replace previous user values; unconfirmed AI suggestions for
    # properties the user has now entered are dropped in favour of the user's value.
    entered = {definitions[i.property_key].id for i in items}
    resource.property_values = [
        pv for pv in resource.property_values
        if pv.source != ValueSource.USER_INPUT and pv.property_id not in entered
    ]
    db.flush()
    for item in items:
        definition = definitions[item.property_key]
        common.check_value_against_definition(definition, item.value_numeric, item.value_text)
        resource.property_values.append(ResourcePropertyValue(
            property_id=definition.id, value_numeric=item.value_numeric, value_text=item.value_text,
            source=ValueSource.USER_INPUT, confirmed=True,
        ))


def create(db: Session, ctx: OrgContext, data: ResourceCreate) -> Resource:
    ctx.require(Permission.MANAGE_LISTINGS)
    orgs.require_active_facility(db, ctx, data.facility_id)
    materials.require_active_material(db, data.material_id)
    common.validate_window(data.availability_start, data.availability_end, publishing=data.publish,
                           label="availability")
    fields = data.model_dump(exclude={"properties", "publish"})
    resource = Resource(**fields, organization_id=ctx.org_id, created_by_user_id=ctx.user.id,
                        status=ListingStatus.ACTIVE if data.publish else ListingStatus.DRAFT)
    db.add(resource)
    db.flush()
    _replace_user_properties(db, resource, data.properties)
    audit.record(db, action="RESOURCE_CREATED", entity_type="resource", entity_id=resource.id,
                 actor_user_id=ctx.user.id, organization_id=ctx.org_id, details={"status": resource.status})
    db.commit()
    db.refresh(resource)
    if resource.status == ListingStatus.ACTIVE:
        events.publish(DomainEvent(EventType.RESOURCE_CREATED, {"resource_id": str(resource.id)}))
    return resource


def update(db: Session, ctx: OrgContext, resource_id: uuid.UUID, data: ResourceUpdate) -> Resource:
    ctx.require(Permission.MANAGE_LISTINGS)
    resource = get_owned(db, ctx, resource_id)
    if resource.status == ListingStatus.ARCHIVED:
        raise ConflictError("Archived resources cannot be edited.", code="LISTING_ARCHIVED")
    changes = data.model_dump(exclude_unset=True, exclude={"properties"})
    if "facility_id" in changes:
        orgs.require_active_facility(db, ctx, changes["facility_id"])
    if "material_id" in changes:
        materials.require_active_material(db, changes["material_id"])
    for field, value in changes.items():
        setattr(resource, field, value)
    common.validate_window(resource.availability_start, resource.availability_end,
                           publishing=resource.status == ListingStatus.ACTIVE, label="availability")
    if data.properties is not None:
        _replace_user_properties(db, resource, data.properties)
    changed = sorted(data.model_fields_set)
    audit.record(db, action="RESOURCE_UPDATED", entity_type="resource", entity_id=resource.id,
                 actor_user_id=ctx.user.id, organization_id=ctx.org_id, details={"fields": changed})
    db.commit()
    db.refresh(resource)
    if resource.status == ListingStatus.ACTIVE and MATCH_RELEVANT_FIELDS & set(changed):
        events.publish(DomainEvent(EventType.RESOURCE_UPDATED, {"resource_id": str(resource.id)}))
    return resource


def change_status(db: Session, ctx: OrgContext, resource_id: uuid.UUID, target: ListingStatus) -> Resource:
    ctx.require(Permission.MANAGE_LISTINGS)
    resource = get_owned(db, ctx, resource_id)
    if target == ListingStatus.ACTIVE:
        common.validate_window(resource.availability_start, resource.availability_end, publishing=True,
                               label="availability")
    previous = common.transition(resource, target)
    audit.record(db, action="RESOURCE_STATUS_CHANGED", entity_type="resource", entity_id=resource.id,
                 actor_user_id=ctx.user.id, organization_id=ctx.org_id, details={"from": previous, "to": target})
    db.commit()
    db.refresh(resource)
    if target == ListingStatus.ACTIVE:
        events.publish(DomainEvent(EventType.RESOURCE_UPDATED, {"resource_id": str(resource.id)}))
    else:
        events.publish(DomainEvent(EventType.LISTING_DEACTIVATED, {"resource_id": str(resource.id)}))
    return resource


def confirm_property(db: Session, ctx: OrgContext, resource_id: uuid.UUID, value_id: uuid.UUID,
                     accept: bool) -> Resource:
    """Human confirmation step for AI-extracted values (AI suggestion -> validation -> structured data)."""
    ctx.require(Permission.MANAGE_LISTINGS)
    resource = get_owned(db, ctx, resource_id)
    value = next((pv for pv in resource.property_values if pv.id == value_id), None)
    if value is None:
        raise common.not_found("property_value")
    if accept:
        common.check_value_against_definition(value.property, value.value_numeric, value.value_text)
        value.confirmed = True
    else:
        resource.property_values.remove(value)
    audit.record(db, action="RESOURCE_PROPERTY_CONFIRMED" if accept else "RESOURCE_PROPERTY_REJECTED",
                 entity_type="resource", entity_id=resource.id, actor_user_id=ctx.user.id,
                 organization_id=ctx.org_id, details={"property_key": value.property.key, "source": value.source})
    db.commit()
    db.refresh(resource)
    if accept and resource.status == ListingStatus.ACTIVE:
        events.publish(DomainEvent(EventType.RESOURCE_UPDATED, {"resource_id": str(resource.id)}))
    return resource


def property_out(pv: ResourcePropertyValue) -> PropertyValueOut:
    return PropertyValueOut(
        id=pv.id, property_key=pv.property.key, property_name=pv.property.name, unit=pv.property.unit,
        value_numeric=pv.value_numeric, value_text=pv.value_text, source=pv.source, confirmed=pv.confirmed,
        confidence=pv.confidence,
    )
