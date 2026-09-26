"""Builds the direct-vs-processed pathway report for one of the caller's resources."""

import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.audit import service as audit
from app.common.listings import ListingStatus
from app.core.dependencies import OrgContext
from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.core.time import today_utc
from app.matching import components as c
from app.matching.engine import evaluate_pair
from app.matching.lifecycle import CLOSED_STATES
from app.matching.models import Match
from app.matching.profiles import _application_rules, _property_index, build_requirement_profile, build_resource_profile
from app.matching.service import active_parameters, resolve_factors
from app.matching.types import ConstraintSpec, GeoPoint, MeasuredValue
from app.organizations import service as orgs
from app.organizations.models import Organization, OrganizationStatus
from app.organizations.permissions import Permission
from app.organizations.schemas import OrganizationPublic
from app.pathways import engine
from app.pathways.models import ProcessingMethod, ProcessorCapability
from app.pathways.schemas import (
    CapabilityIn,
    DirectComparison,
    DirectPathway,
    PathwayParty,
    PathwayReport,
    ProcessedPathway,
    Transformation,
)
from app.requirements.models import Requirement
from app.resources import service as resources

DISCLAIMER = ("Pathways are potential routes assessed from the data provided. Processing specifications, costs and "
              "transport figures marked as demo assumptions or estimates are not quotes or market prices. The "
              "organizations decide; contact still goes through the normal connection flow.")


def _method_spec(db: Session, method: ProcessingMethod, props) -> engine.MethodSpec:
    def name(key):
        return (props[key].name, props[key].unit) if key in props else (key, None)

    constraints = tuple(ConstraintSpec(r["property_key"], *name(r["property_key"]), r.get("min"), r.get("max"), None,
                                       r.get("importance", "REQUIRED")) for r in method.input_constraints or [])
    output = {k: MeasuredValue(k, *name(k), float(v)) for k, v in (method.output_properties or {}).items()}
    out = method.output_material
    return engine.MethodSpec(
        id=str(method.id), key=method.key, name=method.name, steps=tuple(method.processing_steps or ()),
        input_constraints=constraints, output_material_id=str(out.id), output_material_name=out.canonical_name,
        output_category=out.category, output_subcategory=out.subcategory, output_properties=output,
        output_applications=_application_rules(db, out, props), expected_yield=method.expected_yield,
        processing_time_days=method.processing_time_days,
        indicative_cost_per_tonne=float(method.indicative_cost_per_tonne) if method.indicative_cost_per_tonne else None,
        source_note=method.source_note,
    )


def _processor_spec(cap: ProcessorCapability) -> engine.ProcessorSpec:
    loc = cap.facility.location
    geo = GeoPoint(float(loc.latitude), float(loc.longitude)) if loc.latitude is not None and loc.longitude is not None else None
    return engine.ProcessorSpec(
        capability_id=str(cap.id), organization_id=str(cap.organization_id),
        organization_name=cap.organization.display_name, city=loc.city, location=geo,
        capacity_per_month=float(cap.capacity_per_month), available_capacity_per_month=float(cap.available_capacity_per_month),
        cost_per_tonne=float(cap.processing_cost_per_tonne) if cap.processing_cost_per_tonne is not None else None,
        cost_is_demo=cap.cost_is_demo, max_input_distance_km=float(cap.max_input_distance_km) if cap.max_input_distance_km else None,
        currency=cap.currency,
    )


def _party(org: Organization, listing_id=None, listing_name=None) -> PathwayParty:
    return PathwayParty(organization=OrganizationPublic.model_validate(org), listing_id=listing_id, listing_name=listing_name)


def _input_status(rp, spec: engine.MethodSpec) -> str:
    checks = [c.evaluate_constraint(s, rp) for s in spec.input_constraints]
    if any(ch.importance == "REQUIRED" and ch.outcome == c.PropertyOutcome.FAIL for ch in checks):
        return "INCOMPATIBLE"
    if any(ch.outcome not in (c.PropertyOutcome.PASS, c.PropertyOutcome.LIKELY) for ch in checks):
        return "NEEDS_DATA"
    return "COMPATIBLE"


def build_report(db: Session, ctx: OrgContext, resource_id: uuid.UUID) -> PathwayReport:
    resource = resources.get_owned(db, ctx, resource_id)
    rp = build_resource_profile(db, resource)
    params = active_parameters(db)
    today = today_utc()
    props = _property_index(db)
    supply = f"{float(resource.quantity_available):,.0f} {resource.unit.value}/{resource.frequency.value.lower()}"

    # Direct pathways: the existing matching engine's opportunities for this resource.
    matches = list(db.scalars(select(Match).where(Match.resource_id == resource.id, Match.status.not_in(CLOSED_STATES))
                              .order_by(Match.overall_score.desc())))
    direct = [DirectPathway(
        match_id=m.id, buyer=_party(m.demander_org, m.requirement_id, m.requirement.name), status=m.status.value,
        overall_score=m.overall_score, feasibility=m.feasibility.value,
        distance_km=float(m.distance_km) if m.distance_km is not None else None, demand_coverage=m.demand_coverage,
        match_type=m.match_type.value, strengths=(m.explanation or {}).get("strengths", [])[:4],
        considerations=(m.explanation or {}).get("considerations", [])[:4],
    ) for m in matches]
    match_by_buyer_org = {}
    for m in matches:
        match_by_buyer_org.setdefault(m.demander_org_id, m.id)

    methods = [] if resource.material_id is None else list(db.scalars(select(ProcessingMethod).where(
        ProcessingMethod.input_material_id == resource.material_id, ProcessingMethod.is_active.is_(True))))
    specs = {m.id: _method_spec(db, m, props) for m in methods}
    capabilities = list(db.scalars(
        select(ProcessorCapability).join(Organization, ProcessorCapability.organization_id == Organization.id)
        .where(ProcessorCapability.method_id.in_([m.id for m in methods]), ProcessorCapability.is_active.is_(True),
               Organization.status == OrganizationStatus.ACTIVE))) if methods else []
    requirements = list(db.scalars(select(Requirement).join(Organization, Requirement.organization_id == Organization.id).where(
        Requirement.status == ListingStatus.ACTIVE, Requirement.organization_id != resource.organization_id,
        Organization.status == OrganizationStatus.ACTIVE,
        or_(Requirement.required_until.is_(None), Requirement.required_until >= today)))) if capabilities else []

    processed: list[ProcessedPathway] = []
    qp_cache, direct_cache = {}, {}
    for cap in capabilities:
        spec, proc = specs[cap.method_id], _processor_spec(cap)
        for requirement in requirements:
            if requirement.id not in qp_cache:
                qp = build_requirement_profile(requirement)
                factors = resolve_factors(db, rp, qp, requirement.intended_application_id)
                d = evaluate_pair(rp, qp, params, factors, today)
                reason = None if d.eligible else (d.failures[0].message if d.failures else "Not compatible.")
                qp_cache[requirement.id] = (qp, factors)
                direct_cache[requirement.id] = DirectComparison(
                    eligible=d.eligible, overall_score=d.overall_score if d.scores else None, reason=reason)
            qp, factors = qp_cache[requirement.id]
            result = engine.evaluate_processed_pathway(rp, spec, proc, qp, params, factors, today)
            if result is None:
                continue
            buyer_wants = "PROCESSED" if requirement.material is not None and requirement.material.is_processed else "RAW"
            processed.append(ProcessedPathway(
                id=f"{cap.id}:{requirement.id}", status=result.status, overall_score=result.overall_score,
                scores=result.scores,
                method={"key": spec.key, "name": spec.name, "steps": list(spec.steps),
                        "output_material": spec.output_material_name, "expected_yield": spec.expected_yield,
                        "processing_time_days": spec.processing_time_days,
                        "output_specification": {k: v.value for k, v in spec.output_properties.items()},
                        "output_specification_label": "Method specification (demo data)", "source_note": spec.source_note},
                processor=_party(cap.organization),
                processor_capacity={"capacity_t_per_month": proc.capacity_per_month,
                                    "available_t_per_month": proc.available_capacity_per_month,
                                    "city": proc.city, "max_input_distance_km": proc.max_input_distance_km},
                buyer=_party(requirement.organization, requirement.id, requirement.name), buyer_wants=buyer_wants,
                input_quantity_t=result.input_quantity, output_quantity_t=result.output_quantity, basis=result.basis,
                distance_to_processor_km=result.distance_to_processor_km,
                distance_to_buyer_km=result.distance_to_buyer_km, capacity_status=result.capacity_status,
                economics=result.economics, environment=result.environment, input_checks=result.input_checks,
                output_checks=result.output_checks, strengths=result.strengths, considerations=result.considerations,
                blockers=result.blockers, direct_to_same_buyer=direct_cache[requirement.id],
                buyer_match_id=match_by_buyer_org.get(requirement.organization_id),
            ))
    order = {"VIABLE": 0, "WEAK": 1, "NOT_VIABLE": 2}
    processed.sort(key=lambda p: (order[p.status], -p.overall_score))

    transformations = [Transformation(
        method_key=s.key, method_name=s.name, steps=list(s.steps), output_material=s.output_material_name,
        expected_yield=s.expected_yield, processing_time_days=s.processing_time_days, input_status=_input_status(rp, s),
        processors_found=sum(1 for cap in capabilities if cap.method_id == mid),
    ) for mid, s in specs.items()]

    return PathwayReport(
        resource_id=resource.id, resource_name=resource.name,
        material=resource.material.canonical_name if resource.material else None, supply=supply, direct=direct,
        processed=processed[:12], transformations=transformations,
        recommendation=_recommend(direct, processed, transformations), version=engine.VERSION, disclaimer=DISCLAIMER,
    )


def _recommend(direct: list[DirectPathway], processed: list[ProcessedPathway], transformations) -> str:
    best_direct = max(direct, key=lambda d: d.overall_score, default=None)
    viable = [p for p in processed if p.status == "VIABLE"]
    best_processed = viable[0] if viable else None
    if best_processed and (best_direct is None or best_processed.overall_score > best_direct.overall_score):
        return (f"Processing looks worth evaluating: {best_processed.processor.organization.display_name} → "
                f"{best_processed.buyer.organization.display_name} scores {best_processed.overall_score:.0%}"
                + (f" vs {best_direct.overall_score:.0%} for the best direct sale." if best_direct
                   else ", and no direct buyer was found."))
    if best_direct and best_processed:
        return (f"Direct sale to {best_direct.buyer.organization.display_name} ({best_direct.overall_score:.0%}) remains "
                f"stronger than the best processing pathway ({best_processed.overall_score:.0%}).")
    if best_direct:
        return (f"Sell as-is: direct sale to {best_direct.buyer.organization.display_name} scores "
                f"{best_direct.overall_score:.0%}; no viable processing pathway was found.")
    if not transformations:
        return "No direct buyer and no known processing method for this material yet."
    return "No viable pathway yet: processing methods exist, but no processor/buyer combination is currently feasible."


# --- Processor capabilities (minimal management for the organization itself) -------------------

def list_methods(db: Session) -> list[ProcessingMethod]:
    return list(db.scalars(select(ProcessingMethod).where(ProcessingMethod.is_active.is_(True)).order_by(ProcessingMethod.name)))


def list_capabilities(db: Session, ctx: OrgContext) -> list[ProcessorCapability]:
    return list(db.scalars(select(ProcessorCapability).where(ProcessorCapability.organization_id == ctx.org_id)))


def add_capability(db: Session, ctx: OrgContext, data: CapabilityIn) -> ProcessorCapability:
    ctx.require(Permission.MANAGE_ORGANIZATION)
    method = db.scalars(select(ProcessingMethod).where(ProcessingMethod.key == data.method_key)).first()
    if method is None:
        raise NotFoundError("Unknown processing method.", code="METHOD_NOT_FOUND")
    orgs.require_active_facility(db, ctx, data.facility_id)
    if data.available_capacity_per_month > data.capacity_per_month:
        raise ValidationFailedError("Available capacity cannot exceed total capacity.", code="INVALID_CAPACITY")
    if db.scalars(select(ProcessorCapability).where(ProcessorCapability.organization_id == ctx.org_id,
                                                    ProcessorCapability.method_id == method.id,
                                                    ProcessorCapability.facility_id == data.facility_id)).first():
        raise ConflictError("This facility already offers this method.", code="CAPABILITY_EXISTS")
    cap = ProcessorCapability(organization_id=ctx.org_id, method_id=method.id, facility_id=data.facility_id,
                              capacity_per_month=data.capacity_per_month,
                              available_capacity_per_month=data.available_capacity_per_month,
                              processing_cost_per_tonne=data.processing_cost_per_tonne,
                              max_input_distance_km=data.max_input_distance_km, notes=data.notes)
    db.add(cap)
    db.flush()
    audit.record(db, action="PROCESSOR_CAPABILITY_ADDED", entity_type="processor_capability", entity_id=cap.id,
                 actor_user_id=ctx.user.id, organization_id=ctx.org_id, details={"method": data.method_key})
    db.commit()
    db.refresh(cap)
    return cap
