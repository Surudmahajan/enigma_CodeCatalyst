"""Platform administration. Changes to rules, factors and weights are versioned
and audited; historical matches keep the versions they were computed with."""

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assessment.models import EmissionFactor
from app.audit import service as audit
from app.common.listings import ListingStatus
from app.core import jobs
from app.core.database import SessionLocal
from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.materials.models import ApplicationType, Material, MaterialApplication, MaterialProperty, PropertyDefinition
from app.materials.schemas import (
    ApplicationTypeIn,
    MaterialApplicationIn,
    MaterialIn,
    MaterialPropertyIn,
    MaterialUpdate,
    PropertyDefinitionIn,
)
from app.matching import service as matching
from app.matching.models import Match, MatchingConfig
from app.organizations.models import Organization, OrganizationStatus, VerificationStatus
from app.requirements.models import Requirement
from app.resources.models import Resource
from app.users.models import User

WEIGHT_KEYS = {"material", "quantity", "location", "timing", "processing", "economic", "environmental"}


# --- Organizations ---------------------------------------------------------------------------

def _org(db: Session, org_id: uuid.UUID) -> Organization:
    org = db.get(Organization, org_id)
    if org is None:
        raise NotFoundError("Organization not found.", code="ORGANIZATION_NOT_FOUND")
    return org


def set_verification(db: Session, admin: User, org_id: uuid.UUID, status: VerificationStatus, note: str | None):
    org = _org(db, org_id)
    previous = org.verification_status
    org.verification_status = status
    audit.record(db, action="ORGANIZATION_VERIFICATION_CHANGED", entity_type="organization", entity_id=org.id,
                 actor_user_id=admin.id, organization_id=org.id,
                 details={"from": previous, "to": status, "note": note})
    db.commit()
    return org


def set_suspended(db: Session, admin: User, org_id: uuid.UUID, suspended: bool, note: str | None):
    org = _org(db, org_id)
    org.status = OrganizationStatus.SUSPENDED if suspended else OrganizationStatus.ACTIVE
    audit.record(db, action="ORGANIZATION_SUSPENDED" if suspended else "ORGANIZATION_REINSTATED",
                 entity_type="organization", entity_id=org.id, actor_user_id=admin.id, organization_id=org.id,
                 details={"note": note})
    db.commit()
    # Suspended organizations drop out of matching; reinstated ones are re-matched.
    for resource_id in db.scalars(select(Resource.id).where(Resource.organization_id == org.id,
                                                            Resource.status == ListingStatus.ACTIVE)):
        jobs.enqueue(_rematch_resource, resource_id)
    for requirement_id in db.scalars(select(Requirement.id).where(Requirement.organization_id == org.id,
                                                                  Requirement.status == ListingStatus.ACTIVE)):
        jobs.enqueue(_rematch_requirement, requirement_id)
    return org


# --- Material knowledge base -----------------------------------------------------------------

def _apply_material_properties(db: Session, material: Material, items: list[MaterialPropertyIn]) -> None:
    keys = {i.property_key for i in items}
    props = {p.key: p for p in db.scalars(select(PropertyDefinition).where(PropertyDefinition.key.in_(keys)))}
    missing = keys - props.keys()
    if missing:
        raise ValidationFailedError("Unknown property keys.", code="UNKNOWN_PROPERTY", details={"keys": sorted(missing)})
    material.properties = [MaterialProperty(property_id=props[i.property_key].id, typical_min=i.typical_min,
                                            typical_max=i.typical_max, note=i.note) for i in items]


def create_material(db: Session, admin: User, data: MaterialIn) -> Material:
    if db.scalars(select(Material).where(Material.canonical_name == data.canonical_name)).first():
        raise ConflictError("A material with this name already exists.", code="MATERIAL_EXISTS")
    material = Material(**data.model_dump(exclude={"properties"}))
    db.add(material)
    db.flush()
    _apply_material_properties(db, material, data.properties)
    audit.record(db, action="MATERIAL_CREATED", entity_type="material", entity_id=material.id, actor_user_id=admin.id)
    db.commit()
    return material


def update_material(db: Session, admin: User, material_id: uuid.UUID, data: MaterialUpdate) -> Material:
    material = db.get(Material, material_id)
    if material is None:
        raise NotFoundError("Material not found.", code="MATERIAL_NOT_FOUND")
    for field, value in data.model_dump(exclude_unset=True, exclude={"properties"}).items():
        setattr(material, field, value)
    if data.properties is not None:
        _apply_material_properties(db, material, data.properties)
    audit.record(db, action="MATERIAL_UPDATED", entity_type="material", entity_id=material.id, actor_user_id=admin.id,
                 details={"fields": sorted(data.model_fields_set)})
    db.commit()
    return material


def create_property(db: Session, admin: User, data: PropertyDefinitionIn) -> PropertyDefinition:
    if db.scalars(select(PropertyDefinition).where(PropertyDefinition.key == data.key)).first():
        raise ConflictError("A property with this key already exists.", code="PROPERTY_EXISTS")
    prop = PropertyDefinition(**data.model_dump())
    db.add(prop)
    audit.record(db, action="PROPERTY_CREATED", entity_type="property", entity_id=None, actor_user_id=admin.id,
                 details={"key": data.key})
    db.commit()
    return prop


def create_application_type(db: Session, admin: User, data: ApplicationTypeIn) -> ApplicationType:
    if db.scalars(select(ApplicationType).where(ApplicationType.key == data.key)).first():
        raise ConflictError("An application with this key already exists.", code="APPLICATION_EXISTS")
    app_type = ApplicationType(**data.model_dump())
    db.add(app_type)
    audit.record(db, action="APPLICATION_CREATED", entity_type="application_type", entity_id=None,
                 actor_user_id=admin.id, details={"key": data.key})
    db.commit()
    return app_type


def upsert_material_application(db: Session, admin: User, data: MaterialApplicationIn) -> MaterialApplication:
    app_type = db.scalars(select(ApplicationType).where(ApplicationType.key == data.application_key)).first()
    if app_type is None or db.get(Material, data.material_id) is None:
        raise NotFoundError("Unknown material or application.", code="MAPPING_TARGET_NOT_FOUND")
    link = db.scalars(select(MaterialApplication).where(MaterialApplication.material_id == data.material_id,
                                                        MaterialApplication.application_type_id == app_type.id)).first()
    link = link or MaterialApplication(material_id=data.material_id, application_type_id=app_type.id)
    link.description, link.source_note = data.description, data.source_note
    link.required_properties = [r.model_dump() for r in data.required_properties]
    db.add(link)
    audit.record(db, action="MATERIAL_APPLICATION_SAVED", entity_type="material_application", entity_id=None,
                 actor_user_id=admin.id, details={"material_id": data.material_id, "application": data.application_key})
    db.commit()
    return link


def delete_material_application(db: Session, admin: User, link_id: uuid.UUID) -> None:
    link = db.get(MaterialApplication, link_id)
    if link is None:
        raise NotFoundError("Mapping not found.", code="MAPPING_NOT_FOUND")
    db.delete(link)
    audit.record(db, action="MATERIAL_APPLICATION_DELETED", entity_type="material_application", entity_id=link_id,
                 actor_user_id=admin.id)
    db.commit()


# --- Emission factors (append-only versions) -----------------------------------------------------

def create_emission_factor(db: Session, admin: User, data: dict) -> EmissionFactor:
    if data.get("valid_until") and data["valid_until"] < data["valid_from"]:
        raise ValidationFailedError("valid_until must be on or after valid_from.")
    factor = EmissionFactor(**data)
    db.add(factor)
    db.flush()
    audit.record(db, action="EMISSION_FACTOR_CREATED", entity_type="emission_factor", entity_id=factor.id,
                 actor_user_id=admin.id, details={"key": factor.key, "version": factor.version, "value": factor.value})
    db.commit()
    return factor


def retire_emission_factor(db: Session, admin: User, factor_id: uuid.UUID) -> EmissionFactor:
    factor = db.get(EmissionFactor, factor_id)
    if factor is None:
        raise NotFoundError("Emission factor not found.", code="FACTOR_NOT_FOUND")
    factor.is_active = False
    factor.valid_until = factor.valid_until or date.today()
    audit.record(db, action="EMISSION_FACTOR_RETIRED", entity_type="emission_factor", entity_id=factor.id,
                 actor_user_id=admin.id)
    db.commit()
    return factor


# --- Matching configuration --------------------------------------------------------------------

def create_matching_config(db: Session, admin: User, version: str, weights: dict[str, float], parameters: dict,
                           description: str | None) -> MatchingConfig:
    if set(weights) != WEIGHT_KEYS:
        raise ValidationFailedError("Weights must define exactly: " + ", ".join(sorted(WEIGHT_KEYS)),
                                    code="INVALID_WEIGHTS")
    if any(w < 0 for w in weights.values()) or abs(sum(weights.values()) - 1.0) > 1e-6:
        raise ValidationFailedError("Weights must be non-negative and sum to 1.", code="INVALID_WEIGHTS")
    if db.scalars(select(MatchingConfig).where(MatchingConfig.version == version)).first():
        raise ConflictError("This version already exists; configurations are immutable.", code="CONFIG_EXISTS")
    base = matching.active_parameters(db)
    merged = {k: v for k, v in base.__dict__.items() if k not in ("version", "weights")}
    merged.update(parameters)
    config = MatchingConfig(version=version, weights=weights, parameters=merged, description=description,
                            created_by_user_id=admin.id, is_active=False)
    db.add(config)
    db.flush()
    audit.record(db, action="MATCHING_CONFIG_CREATED", entity_type="matching_config", entity_id=config.id,
                 actor_user_id=admin.id, details={"version": version, "weights": weights})
    db.commit()
    return config


def activate_matching_config(db: Session, admin: User, config_id: uuid.UUID) -> MatchingConfig:
    config = db.get(MatchingConfig, config_id)
    if config is None:
        raise NotFoundError("Configuration not found.", code="CONFIG_NOT_FOUND")
    for other in db.scalars(select(MatchingConfig).where(MatchingConfig.is_active.is_(True))):
        other.is_active = False
    config.is_active = True
    audit.record(db, action="MATCHING_CONFIG_ACTIVATED", entity_type="matching_config", entity_id=config.id,
                 actor_user_id=admin.id, details={"version": config.version})
    db.commit()
    jobs.enqueue(rematch_all)
    return config


# --- Re-matching jobs -------------------------------------------------------------------------

def _rematch_resource(resource_id: uuid.UUID) -> None:
    with SessionLocal() as db:
        matching.run_for_resource(db, resource_id)


def _rematch_requirement(requirement_id: uuid.UUID) -> None:
    with SessionLocal() as db:
        matching.run_for_requirement(db, requirement_id)


def rematch_all() -> int:
    """Re-evaluate every active resource (each run covers both directions of its pairs)."""
    with SessionLocal() as db:
        ids = list(db.scalars(select(Resource.id).where(Resource.status == ListingStatus.ACTIVE)))
        for resource_id in ids:
            matching.run_for_resource(db, resource_id)
        for requirement_id in db.scalars(select(Requirement.id).where(Requirement.status == ListingStatus.ACTIVE)):
            matching.run_for_requirement(db, requirement_id)
        return len(ids)


def matches_for_admin(db: Session, status=None, limit: int = 200) -> list[Match]:
    query = select(Match)
    if status:
        query = query.where(Match.status == status)
    return list(db.scalars(query.order_by(Match.updated_at.desc()).limit(limit)))

