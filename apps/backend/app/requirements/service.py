import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import service as audit
from app.common import listing_service as common
from app.common.listing_schemas import PropertyConstraintIn, PropertyConstraintOut
from app.common.listings import ListingStatus
from app.core import events
from app.core.dependencies import OrgContext
from app.core.errors import ConflictError, ValidationFailedError
from app.core.events import DomainEvent, EventType
from app.materials import service as materials
from app.materials.models import PropertyDataType
from app.organizations import service as orgs
from app.organizations.permissions import Permission
from app.requirements.models import Requirement, RequirementPropertyConstraint
from app.requirements.schemas import RequirementCreate, RequirementUpdate

MATCH_RELEVANT_FIELDS = {
    "facility_id", "material_id", "intended_application_id", "name", "description", "quantity_required", "unit",
    "frequency", "required_from", "required_until", "max_transport_distance_km", "processing_capabilities",
    "acceptable_categories", "excluded_material_ids", "virgin_material_price_per_unit", "max_price_per_unit",
    "property_constraints",
}


def get_owned(db: Session, ctx: OrgContext, requirement_id: uuid.UUID) -> Requirement:
    requirement = db.get(Requirement, requirement_id)
    if requirement is None or requirement.organization_id != ctx.org_id:
        raise common.not_found("requirement")
    return requirement


def list_owned(db: Session, ctx: OrgContext, status: ListingStatus | None = None) -> list[Requirement]:
    query = select(Requirement).where(Requirement.organization_id == ctx.org_id)
    if status:
        query = query.where(Requirement.status == status)
    else:
        query = query.where(Requirement.status != ListingStatus.ARCHIVED)
    return list(db.scalars(query.order_by(Requirement.updated_at.desc())))


def _replace_constraints(db: Session, requirement: Requirement, items: list[PropertyConstraintIn]) -> None:
    keys = [i.property_key for i in items]
    if len(set(keys)) != len(keys):
        raise ConflictError("Each property may appear only once.", code="DUPLICATE_PROPERTY")
    definitions = materials.properties_by_key(db, set(keys))
    requirement.property_constraints = []
    db.flush()
    for item in items:
        definition = definitions[item.property_key]
        if definition.data_type == PropertyDataType.NUMERIC and item.min_value is None and item.max_value is None:
            raise ValidationFailedError(f"{definition.name} constraints need a minimum or maximum.",
                                        code="INVALID_CONSTRAINT", details={"property_key": definition.key})
        requirement.property_constraints.append(RequirementPropertyConstraint(
            property_id=definition.id, min_value=item.min_value, max_value=item.max_value,
            text_value=item.text_value, importance=item.importance,
        ))


def _json_ids(ids: list[uuid.UUID] | None) -> list[str]:
    return [str(i) for i in ids or []]


def create(db: Session, ctx: OrgContext, data: RequirementCreate) -> Requirement:
    ctx.require(Permission.MANAGE_LISTINGS)
    orgs.require_active_facility(db, ctx, data.facility_id)
    materials.require_active_material(db, data.material_id)
    materials.require_application_type(db, data.intended_application_id)
    common.validate_window(data.required_from, data.required_until, publishing=data.publish, label="requirement")
    fields = data.model_dump(exclude={"property_constraints", "publish", "excluded_material_ids"})
    requirement = Requirement(**fields, excluded_material_ids=_json_ids(data.excluded_material_ids),
                              organization_id=ctx.org_id, created_by_user_id=ctx.user.id,
                              status=ListingStatus.ACTIVE if data.publish else ListingStatus.DRAFT)
    db.add(requirement)
    db.flush()
    _replace_constraints(db, requirement, data.property_constraints)
    audit.record(db, action="REQUIREMENT_CREATED", entity_type="requirement", entity_id=requirement.id,
                 actor_user_id=ctx.user.id, organization_id=ctx.org_id, details={"status": requirement.status})
    db.commit()
    db.refresh(requirement)
    if requirement.status == ListingStatus.ACTIVE:
        events.publish(DomainEvent(EventType.REQUIREMENT_CREATED, {"requirement_id": str(requirement.id)}))
    return requirement


def update(db: Session, ctx: OrgContext, requirement_id: uuid.UUID, data: RequirementUpdate) -> Requirement:
    ctx.require(Permission.MANAGE_LISTINGS)
    requirement = get_owned(db, ctx, requirement_id)
    if requirement.status == ListingStatus.ARCHIVED:
        raise ConflictError("Archived requirements cannot be edited.", code="LISTING_ARCHIVED")
    changes = data.model_dump(exclude_unset=True, exclude={"property_constraints"})
    if "facility_id" in changes:
        orgs.require_active_facility(db, ctx, changes["facility_id"])
    if "material_id" in changes:
        materials.require_active_material(db, changes["material_id"])
    if "intended_application_id" in changes:
        materials.require_application_type(db, changes["intended_application_id"])
    if "excluded_material_ids" in changes:
        changes["excluded_material_ids"] = _json_ids(data.excluded_material_ids)
    for field, value in changes.items():
        setattr(requirement, field, value)
    common.validate_window(requirement.required_from, requirement.required_until,
                           publishing=requirement.status == ListingStatus.ACTIVE, label="requirement")
    if data.property_constraints is not None:
        _replace_constraints(db, requirement, data.property_constraints)
    changed = sorted(data.model_fields_set)
    audit.record(db, action="REQUIREMENT_UPDATED", entity_type="requirement", entity_id=requirement.id,
                 actor_user_id=ctx.user.id, organization_id=ctx.org_id, details={"fields": changed})
    db.commit()
    db.refresh(requirement)
    if requirement.status == ListingStatus.ACTIVE and MATCH_RELEVANT_FIELDS & set(changed):
        events.publish(DomainEvent(EventType.REQUIREMENT_UPDATED, {"requirement_id": str(requirement.id)}))
    return requirement


def change_status(db: Session, ctx: OrgContext, requirement_id: uuid.UUID, target: ListingStatus) -> Requirement:
    ctx.require(Permission.MANAGE_LISTINGS)
    requirement = get_owned(db, ctx, requirement_id)
    if target == ListingStatus.ACTIVE:
        common.validate_window(requirement.required_from, requirement.required_until, publishing=True,
                               label="requirement")
    previous = common.transition(requirement, target)
    audit.record(db, action="REQUIREMENT_STATUS_CHANGED", entity_type="requirement", entity_id=requirement.id,
                 actor_user_id=ctx.user.id, organization_id=ctx.org_id, details={"from": previous, "to": target})
    db.commit()
    db.refresh(requirement)
    if target == ListingStatus.ACTIVE:
        events.publish(DomainEvent(EventType.REQUIREMENT_UPDATED, {"requirement_id": str(requirement.id)}))
    else:
        events.publish(DomainEvent(EventType.LISTING_DEACTIVATED, {"requirement_id": str(requirement.id)}))
    return requirement


def constraint_out(c: RequirementPropertyConstraint) -> PropertyConstraintOut:
    return PropertyConstraintOut(
        id=c.id, property_key=c.property.key, property_name=c.property.name, unit=c.property.unit,
        min_value=c.min_value, max_value=c.max_value, text_value=c.text_value, importance=c.importance,
    )
