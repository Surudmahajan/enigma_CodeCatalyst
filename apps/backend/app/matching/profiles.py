"""Translate ORM listings into immutable engine profiles."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.embeddings import embed, embedding_model_name, listing_text
from app.materials.models import Material, MaterialApplication, PropertyDefinition
from app.matching.types import (
    ApplicationRule,
    ConstraintSpec,
    GeoPoint,
    MeasuredValue,
    RequirementProfile,
    ResourceProfile,
    TypicalRange,
)
from app.requirements.models import Requirement
from app.resources.models import Resource


def _f(value) -> float | None:
    return float(value) if value is not None else None


def _geo(facility) -> GeoPoint | None:
    loc = facility.location if facility else None
    if loc is None or loc.latitude is None or loc.longitude is None:
        return None
    return GeoPoint(float(loc.latitude), float(loc.longitude))


def resource_text(r: Resource) -> str:
    material = r.material
    return listing_text(r.name, r.description, material.canonical_name if material else None,
                        [material.category] if material else None)


def requirement_text(q: Requirement) -> str:
    extra = []
    if q.material:
        extra.append(q.material.category)
    if q.intended_application:
        extra += [q.intended_application.name, q.intended_application.description or ""]
    return listing_text(q.name, q.description, q.material.canonical_name if q.material else None, extra)


def ensure_embedding(listing: Resource | Requirement) -> tuple[float, ...]:
    """Compute and cache the listing embedding when missing or produced by another model."""
    model = embedding_model_name()
    if listing.embedding and listing.embedding_model == model:
        return tuple(listing.embedding)
    text = resource_text(listing) if isinstance(listing, Resource) else requirement_text(listing)
    vector = embed(text)
    listing.embedding, listing.embedding_model = list(vector), model
    return vector


def _application_rules(db: Session, material: Material | None,
                       properties: dict[str, PropertyDefinition]) -> dict[str, ApplicationRule]:
    if material is None:
        return {}
    rules: dict[str, ApplicationRule] = {}
    for link in db.scalars(select(MaterialApplication).where(MaterialApplication.material_id == material.id)):
        enriched = []
        for rule in link.required_properties or []:
            definition = properties.get(rule.get("property_key", ""))
            enriched.append({**rule, "name": definition.name if definition else rule.get("property_key"),
                             "unit": definition.unit if definition else None})
        rules[link.application_type.key] = ApplicationRule(link.application_type.key, link.application_type.name,
                                                           tuple(enriched))
    return rules


def _property_index(db: Session) -> dict[str, PropertyDefinition]:
    return {p.key: p for p in db.scalars(select(PropertyDefinition))}


def build_resource_profile(db: Session, r: Resource, properties: dict[str, PropertyDefinition] | None = None
                           ) -> ResourceProfile:
    properties = properties or _property_index(db)
    material = r.material
    measured = {
        pv.property.key: MeasuredValue(pv.property.key, pv.property.name, pv.property.unit,
                                       _f(pv.value_numeric), pv.value_text)
        for pv in r.property_values if pv.confirmed  # unconfirmed AI suggestions never reach the engine
    }
    typical = {
        mp.property.key: TypicalRange(mp.property.key, mp.property.name, mp.property.unit,
                                      _f(mp.typical_min), _f(mp.typical_max))
        for mp in (material.properties if material else [])
    }
    return ResourceProfile(
        id=str(r.id), organization_id=str(r.organization_id), organization_name=r.organization.display_name,
        name=r.name, description=r.description, material_id=str(material.id) if material else None,
        material_name=material.canonical_name if material else None,
        category=material.category if material else None, subcategory=material.subcategory if material else None,
        quantity=float(r.quantity_available), unit=r.unit.value, frequency=r.frequency.value,
        available_from=r.availability_start, available_until=r.availability_end, location=_geo(r.facility),
        processing_required=r.processing_required, processing_types=tuple(r.processing_types or ()),
        current_disposition=r.current_disposition.value, currency=r.currency,
        disposal_cost_per_unit=_f(r.disposal_cost_per_unit), asking_price_per_unit=_f(r.asking_price_per_unit),
        processing_cost_per_unit=_f(r.processing_cost_per_unit), measured=measured, typical=typical,
        applications=_application_rules(db, material, properties), embedding=ensure_embedding(r),
    )


def build_requirement_profile(q: Requirement) -> RequirementProfile:
    material, application = q.material, q.intended_application
    constraints = tuple(
        ConstraintSpec(c.property.key, c.property.name, c.property.unit, _f(c.min_value), _f(c.max_value),
                       c.text_value, c.importance.value)
        for c in q.property_constraints
    )
    return RequirementProfile(
        id=str(q.id), organization_id=str(q.organization_id), organization_name=q.organization.display_name,
        name=q.name, description=q.description, material_id=str(material.id) if material else None,
        material_name=material.canonical_name if material else None,
        category=material.category if material else None, subcategory=material.subcategory if material else None,
        intended_application_key=application.key if application else None,
        intended_application_name=application.name if application else None,
        quantity=float(q.quantity_required), unit=q.unit.value, frequency=q.frequency.value,
        required_from=q.required_from, required_until=q.required_until, location=_geo(q.facility),
        currency=q.currency, max_distance_km=_f(q.max_transport_distance_km),
        processing_capabilities=tuple(q.processing_capabilities or ()),
        acceptable_categories=tuple(q.acceptable_categories or ()),
        excluded_material_ids=tuple(q.excluded_material_ids or ()),
        virgin_material_price_per_unit=_f(q.virgin_material_price_per_unit),
        max_price_per_unit=_f(q.max_price_per_unit), constraints=constraints, embedding=ensure_embedding(q),
    )
