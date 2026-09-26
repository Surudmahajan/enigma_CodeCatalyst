"""Matching orchestration: candidate retrieval, evaluation, persistence, lifecycle.

Staged filtering (never all-pairs):

    SQL:    ACTIVE listing, other ACTIVE organization, date windows overlap,
            facility inside a coarse bounding box (or no coordinates)
    Python: unit family  ->  material relatedness (structured or semantic)
            ->  full evaluation (engine.evaluate_pair)

The semantic stage runs in Python over the SQL-filtered set for the MVP;
at scale it moves into PostgreSQL with pgvector (docs/matching-engine.md).
"""

import logging
import uuid
from datetime import timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.ai.embeddings import cosine
from app.assessment.models import EmissionFactor, FactorScope
from app.audit import service as audit
from app.common.listings import ListingStatus
from app.core import events
from app.core.dependencies import OrgContext
from app.core.errors import ForbiddenError, NotFoundError, ValidationFailedError
from app.core.events import DomainEvent, EventType
from app.core.time import as_utc, today_utc, utcnow
from app.materials import units
from app.matching import engine
from app.matching.explanation import build_explanation
from app.matching.geo import bounding_box
from app.matching.lifecycle import EARLY_STATES, MATCH_LIFECYCLE
from app.matching.models import ConfidenceLevel, Feasibility, Match, MatchingConfig, MatchStatus, MatchType
from app.matching.profiles import build_requirement_profile, build_resource_profile
from app.matching.types import (
    EnvironmentalFactors,
    FactorRef,
    MatchingParameters,
    RequirementProfile,
    ResourceProfile,
    to_jsonable,
)
from app.organizations.models import Facility, Location, Organization, OrganizationStatus
from app.organizations.permissions import Permission
from app.requirements.models import Requirement
from app.resources.models import Resource

logger = logging.getLogger("symbio.matching")


# --- Configuration ------------------------------------------------------------------------

def active_parameters(db: Session) -> MatchingParameters:
    config = db.scalars(select(MatchingConfig).where(MatchingConfig.is_active.is_(True))
                        .order_by(MatchingConfig.created_at.desc())).first()
    if config is None:
        return MatchingParameters()
    return MatchingParameters.from_config(config.version, config.weights, config.parameters)


def _factor_ref(f: EmissionFactor | None) -> FactorRef | None:
    if f is None:
        return None
    return FactorRef(str(f.id), f.key, float(f.value), f.unit, f.source, f.version, f.geography, f.is_demo_value)


def resolve_factors(db: Session, resource: ResourceProfile, requirement: RequirementProfile,
                    requirement_application_id: uuid.UUID | None) -> EnvironmentalFactors:
    today = today_utc()
    base = select(EmissionFactor).where(
        EmissionFactor.is_active.is_(True), EmissionFactor.valid_from <= today,
        or_(EmissionFactor.valid_until.is_(None), EmissionFactor.valid_until >= today),
    ).order_by(EmissionFactor.valid_from.desc(), EmissionFactor.created_at.desc())

    def first(*conditions) -> EmissionFactor | None:
        return db.scalars(base.where(*conditions)).first()

    transport = first(EmissionFactor.scope == FactorScope.TRANSPORT)
    virgin = None
    if requirement.material_id:
        virgin = first(EmissionFactor.scope == FactorScope.VIRGIN_PRODUCTION,
                       EmissionFactor.material_id == uuid.UUID(requirement.material_id))
    if virgin is None and requirement_application_id:
        virgin = first(EmissionFactor.scope == FactorScope.VIRGIN_PRODUCTION,
                       EmissionFactor.application_type_id == requirement_application_id)
    material_uuid = uuid.UUID(resource.material_id) if resource.material_id else None
    disposal = first(EmissionFactor.scope == FactorScope.DISPOSAL,
                     EmissionFactor.disposition == resource.current_disposition,
                     EmissionFactor.material_id == material_uuid) if material_uuid else None
    disposal = disposal or first(EmissionFactor.scope == FactorScope.DISPOSAL,
                                 EmissionFactor.disposition == resource.current_disposition,
                                 EmissionFactor.material_id.is_(None))
    processing = first(EmissionFactor.scope == FactorScope.PROCESSING, EmissionFactor.material_id == material_uuid) \
        if material_uuid else None
    processing = processing or first(EmissionFactor.scope == FactorScope.PROCESSING, EmissionFactor.material_id.is_(None))
    return EnvironmentalFactors(_factor_ref(transport), _factor_ref(virgin), _factor_ref(disposal),
                                _factor_ref(processing))


# --- Evaluation and persistence -----------------------------------------------------------

def _snapshot(resource: ResourceProfile, requirement: RequirementProfile, params: MatchingParameters,
              factors: EnvironmentalFactors, ev: engine.MatchEvaluation) -> dict:
    strip = {"embedding"}
    return {
        "evaluated_at": utcnow().isoformat(),
        "matching_version": params.version,
        "methodology_version": engine.METHODOLOGY_VERSION,
        "resource": {k: v for k, v in to_jsonable(resource).items() if k not in strip},
        "requirement": {k: v for k, v in to_jsonable(requirement).items() if k not in strip},
        "parameters": to_jsonable(params),
        "factors": to_jsonable(factors),
        "scores": ev.scores,
        "economic": to_jsonable(ev.economic),
        "environmental": to_jsonable(ev.environmental),
        "timing": to_jsonable(ev.timing),
        "quantity": to_jsonable(ev.quantity),
        "semantic_similarity": ev.material.semantic_similarity if ev.material else None,
    }


def _apply_evaluation(match: Match, ev: engine.MatchEvaluation, explanation: dict, snapshot: dict,
                      params: MatchingParameters) -> None:
    assert ev.quantity and ev.material and ev.processing and ev.timing
    match.matching_version = params.version
    match.methodology_version = engine.METHODOLOGY_VERSION
    match.material_score = ev.scores["material"]
    match.quantity_score = ev.scores["quantity"]
    match.location_score = ev.scores["location"]
    match.timing_score = ev.scores["timing"]
    match.processing_score = ev.scores["processing"]
    match.economic_score = ev.scores["economic"]
    match.environmental_score = ev.scores["environmental"]
    match.overall_score = ev.overall_score
    match.confidence = ev.confidence
    match.confidence_level = ConfidenceLevel(ev.confidence_level)
    match.feasibility = Feasibility(ev.feasibility)
    match.requires_manual_review = ev.requires_manual_review
    match.match_type = MatchType(ev.match_type)
    match.is_hidden_match = ev.is_hidden_match
    match.distance_km = round(ev.location.distance_km, 1) if ev.location and ev.location.distance_km else None
    match.demand_coverage = ev.quantity.demand_coverage
    match.supply_utilization = ev.quantity.supply_utilization
    match.explanation = explanation
    match.assessment_snapshot = snapshot
    match.last_evaluated_at = utcnow()
    match.stale_reason = None


def evaluate_and_store(db: Session, resource: Resource, requirement: Requirement, params: MatchingParameters,
                       rp: ResourceProfile | None = None) -> tuple[Match | None, bool]:
    """Evaluate one pair and upsert its Match. Returns (match, newly_discovered)."""
    rp = rp or build_resource_profile(db, resource)
    qp = build_requirement_profile(requirement)
    factors = resolve_factors(db, rp, qp, requirement.intended_application_id)
    ev = engine.evaluate_pair(rp, qp, params, factors, today_utc())
    existing = db.scalars(select(Match).where(Match.resource_id == resource.id,
                                              Match.requirement_id == requirement.id)).first()
    if not ev.eligible:
        if existing and existing.status in EARLY_STATES:
            reason = ev.failures[0].message if ev.failures else "No longer compatible."
            MATCH_LIFECYCLE.assert_transition(existing.status, MatchStatus.EXPIRED)
            existing.status, existing.stale_reason = MatchStatus.EXPIRED, reason[:255]
            audit.record(db, action="MATCH_EXPIRED", entity_type="match", entity_id=existing.id,
                         details={"reason": reason})
        elif existing:
            existing.stale_reason = (ev.failures[0].message if ev.failures else "Inputs changed.")[:255]
        return existing, False

    explanation = build_explanation(ev, rp, qp)
    snapshot = _snapshot(rp, qp, params, factors, ev)
    expires = utcnow() + timedelta(days=params.match_ttl_days)
    if existing is None:
        match = Match(resource_id=resource.id, requirement_id=requirement.id,
                      provider_org_id=resource.organization_id, demander_org_id=requirement.organization_id,
                      status=MatchStatus.DISCOVERED, expires_at=expires)
        _apply_evaluation(match, ev, explanation, snapshot, params)
        db.add(match)
        db.flush()
        audit.record(db, action="MATCH_GENERATED", entity_type="match", entity_id=match.id,
                     details={"overall_score": match.overall_score, "match_type": match.match_type,
                              "matching_version": params.version})
        return match, True
    newly = False
    if existing.status == MatchStatus.EXPIRED:
        MATCH_LIFECYCLE.assert_transition(existing.status, MatchStatus.DISCOVERED)
        existing.status, newly = MatchStatus.DISCOVERED, True
    _apply_evaluation(existing, ev, explanation, snapshot, params)
    if existing.status in EARLY_STATES:
        existing.expires_at = expires
    return existing, newly


def _active_org_ids_clause(org_column):
    return org_column.in_(select(Organization.id).where(Organization.status == OrganizationStatus.ACTIVE))


def _within_box(facility_column, center, radius_km):
    """Facility in a coarse bounding box, or with unknown coordinates (never silently dropped)."""
    min_lat, max_lat, min_lon, max_lon = bounding_box(center, radius_km)
    in_box = select(Facility.id).join(Location, Facility.location_id == Location.id).where(or_(
        Location.latitude.is_(None), Location.longitude.is_(None),
        and_(Location.latitude.between(min_lat, max_lat), Location.longitude.between(min_lon, max_lon)),
    ))
    return facility_column.in_(in_box)


def _quick_related(rp: ResourceProfile, qp: RequirementProfile, params: MatchingParameters) -> bool:
    """Cheap pre-screen before the full evaluation (unit family + any material link)."""
    if not units.same_family(rp.unit, qp.unit):
        return False
    if rp.material_id and rp.material_id == qp.material_id:
        return True
    if qp.intended_application_key and qp.intended_application_key in rp.applications:
        return True
    if rp.category and (rp.category == qp.category or rp.category in qp.acceptable_categories):
        return True
    similarity = cosine(rp.embedding, qp.embedding)
    return similarity is not None and similarity >= params.semantic_candidate_threshold


def run_for_resource(db: Session, resource_id: uuid.UUID) -> list[Match]:
    resource = db.get(Resource, resource_id)
    if resource is None:
        return []
    if resource.status != ListingStatus.ACTIVE or not resource.organization.is_active:
        expire_for_listing(db, resource_id=resource_id, reason="The resource is no longer active.")
        return []
    params = active_parameters(db)
    rp = build_resource_profile(db, resource)
    today = today_utc()
    query = select(Requirement).where(
        Requirement.status == ListingStatus.ACTIVE,
        Requirement.organization_id != resource.organization_id,
        _active_org_ids_clause(Requirement.organization_id),
        or_(Requirement.required_until.is_(None), Requirement.required_until >= today),
    )
    if resource.availability_end is not None:
        query = query.where(Requirement.required_from <= resource.availability_end)
    if rp.location is not None:
        query = query.where(_within_box(Requirement.facility_id, rp.location, params.candidate_radius_km))
    matches, discovered = [], []
    candidates = list(db.scalars(query))
    for requirement in candidates:
        qp = build_requirement_profile(requirement)
        if not _quick_related(rp, qp, params):
            continue
        match, newly = evaluate_and_store(db, resource, requirement, params, rp=rp)
        if match is not None and match.status not in (MatchStatus.EXPIRED,):
            matches.append(match)
        if newly and match is not None:
            discovered.append(match.id)
    _expire_unrelated(db, resource_id=resource.id, keep={m.id for m in matches})
    db.commit()
    logger.info("Matching run for resource: %d candidates, %d matches", len(candidates), len(matches),
                extra={"event": "matching_run"})
    for match_id in discovered:
        events.publish(DomainEvent(EventType.MATCH_DISCOVERED, {"match_id": str(match_id)}))
    return matches


def run_for_requirement(db: Session, requirement_id: uuid.UUID) -> list[Match]:
    requirement = db.get(Requirement, requirement_id)
    if requirement is None:
        return []
    if requirement.status != ListingStatus.ACTIVE or not requirement.organization.is_active:
        expire_for_listing(db, requirement_id=requirement_id, reason="The requirement is no longer active.")
        return []
    params = active_parameters(db)
    qp = build_requirement_profile(requirement)
    today = today_utc()
    query = select(Resource).where(
        Resource.status == ListingStatus.ACTIVE,
        Resource.organization_id != requirement.organization_id,
        _active_org_ids_clause(Resource.organization_id),
        or_(Resource.availability_end.is_(None), Resource.availability_end >= today),
    )
    if requirement.required_until is not None:
        query = query.where(Resource.availability_start <= requirement.required_until)
    if qp.location is not None:
        query = query.where(_within_box(Resource.facility_id, qp.location, params.candidate_radius_km))
    matches, discovered = [], []
    for resource in db.scalars(query):
        rp = build_resource_profile(db, resource)
        if not _quick_related(rp, qp, params):
            continue
        match, newly = evaluate_and_store(db, resource, requirement, params, rp=rp)
        if match is not None and match.status != MatchStatus.EXPIRED:
            matches.append(match)
        if newly and match is not None:
            discovered.append(match.id)
    _expire_unrelated(db, requirement_id=requirement.id, keep={m.id for m in matches})
    db.commit()
    for match_id in discovered:
        events.publish(DomainEvent(EventType.MATCH_DISCOVERED, {"match_id": str(match_id)}))
    return matches


def _expire_unrelated(db: Session, *, keep: set[uuid.UUID], resource_id: uuid.UUID | None = None,
                      requirement_id: uuid.UUID | None = None) -> None:
    """Early-stage matches of this listing that were not re-confirmed by the run become stale."""
    query = select(Match).where(Match.status.in_(EARLY_STATES))
    query = query.where(Match.resource_id == resource_id) if resource_id else query.where(
        Match.requirement_id == requirement_id)
    for match in db.scalars(query):
        if match.id not in keep:
            match.status, match.stale_reason = MatchStatus.EXPIRED, "No longer a candidate after the latest update."


def expire_for_listing(db: Session, *, reason: str, resource_id: uuid.UUID | None = None,
                       requirement_id: uuid.UUID | None = None) -> int:
    query = select(Match).where(Match.status.in_(EARLY_STATES))
    query = query.where(Match.resource_id == resource_id) if resource_id else query.where(
        Match.requirement_id == requirement_id)
    expired = []
    for match in db.scalars(query):
        match.status, match.stale_reason = MatchStatus.EXPIRED, reason
        expired.append(match.id)
    db.commit()
    for match_id in expired:
        events.publish(DomainEvent(EventType.LISTING_EXPIRED, {"match_id": str(match_id)}))
    return len(expired)


def expire_overdue_matches(db: Session) -> int:
    now = utcnow()
    count = 0
    for match in db.scalars(select(Match).where(Match.status.in_(EARLY_STATES), Match.expires_at.is_not(None))):
        if as_utc(match.expires_at) <= now:
            match.status, match.stale_reason = MatchStatus.EXPIRED, "The opportunity was not acted on in time."
            count += 1
    db.commit()
    return count


# --- Access and user actions -----------------------------------------------------------------

def side_of(match: Match, ctx: OrgContext) -> str:
    if match.provider_org_id == ctx.org_id:
        return "PROVIDER"
    if match.demander_org_id == ctx.org_id:
        return "DEMANDER"
    raise NotFoundError("The requested match does not exist.", code="MATCH_NOT_FOUND")


def get_for_org(db: Session, ctx: OrgContext, match_id: uuid.UUID) -> Match:
    match = db.get(Match, match_id)
    if match is None:
        raise NotFoundError("The requested match does not exist.", code="MATCH_NOT_FOUND")
    side_of(match, ctx)  # raises the same 404 for other organizations' matches
    return match


def list_for_org(db: Session, ctx: OrgContext, *, side: str | None = None, statuses: list[MatchStatus] | None = None,
                 resource_id: uuid.UUID | None = None, requirement_id: uuid.UUID | None = None,
                 include_closed: bool = False) -> list[Match]:
    if side == "provider":
        query = select(Match).where(Match.provider_org_id == ctx.org_id)
    elif side == "demander":
        query = select(Match).where(Match.demander_org_id == ctx.org_id)
    else:
        query = select(Match).where(or_(Match.provider_org_id == ctx.org_id, Match.demander_org_id == ctx.org_id))
    if statuses:
        query = query.where(Match.status.in_(statuses))
    elif not include_closed:
        query = query.where(Match.status.not_in([MatchStatus.EXPIRED, MatchStatus.REJECTED, MatchStatus.CANCELLED]))
    if resource_id:
        query = query.where(Match.resource_id == resource_id)
    if requirement_id:
        query = query.where(Match.requirement_id == requirement_id)
    return list(db.scalars(query.order_by(Match.overall_score.desc(), Match.created_at.desc())))


def transition(db: Session, match: Match, target: MatchStatus, ctx: OrgContext | None = None,
               details: dict | None = None) -> None:
    previous = match.status
    MATCH_LIFECYCLE.assert_transition(previous, target)
    match.status = target
    audit.record(db, action="MATCH_STATUS_CHANGED", entity_type="match", entity_id=match.id,
                 actor_user_id=ctx.user.id if ctx else None, organization_id=ctx.org_id if ctx else None,
                 details={"from": previous, "to": target, **(details or {})})


def mark_viewed(db: Session, ctx: OrgContext, match: Match) -> None:
    side = side_of(match, ctx)
    now = utcnow()
    changed = False
    if side == "PROVIDER" and match.provider_viewed_at is None:
        match.provider_viewed_at, changed = now, True
    if side == "DEMANDER" and match.demander_viewed_at is None:
        match.demander_viewed_at, changed = now, True
    if match.status == MatchStatus.DISCOVERED:
        transition(db, match, MatchStatus.VIEWED, ctx)
        changed = True
    if changed:
        db.commit()


def mark_interested(db: Session, ctx: OrgContext, match_id: uuid.UUID) -> Match:
    ctx.require(Permission.VIEW)
    match = get_for_org(db, ctx, match_id)
    side = side_of(match, ctx)
    if side == "PROVIDER":
        match.provider_interested_at = utcnow()
    else:
        match.demander_interested_at = utcnow()
    if match.status in (MatchStatus.DISCOVERED, MatchStatus.VIEWED):
        transition(db, match, MatchStatus.INTERESTED, ctx)
    db.commit()
    return match


def reject(db: Session, ctx: OrgContext, match_id: uuid.UUID, reason: str | None) -> Match:
    ctx.require(Permission.MANAGE_CONNECTIONS)
    match = get_for_org(db, ctx, match_id)
    if match.status not in EARLY_STATES:
        raise ForbiddenError("Connected opportunities are closed by cancelling the connection or exchange.",
                             code="MATCH_ALREADY_CONNECTED")
    transition(db, match, MatchStatus.REJECTED, ctx, {"reason": (reason or "")[:200]})
    match.rejected_by_org_id = ctx.org_id
    db.commit()
    return match


def refresh(db: Session, ctx: OrgContext, match_id: uuid.UUID) -> Match:
    match = get_for_org(db, ctx, match_id)
    resource, requirement = match.resource, match.requirement
    if resource.status != ListingStatus.ACTIVE or requirement.status != ListingStatus.ACTIVE:
        if match.status in EARLY_STATES:
            match.status, match.stale_reason = MatchStatus.EXPIRED, "A listing in this opportunity is no longer active."
            db.commit()
        return match
    updated, newly = evaluate_and_store(db, resource, requirement, active_parameters(db))
    db.commit()
    if newly and updated is not None:
        events.publish(DomainEvent(EventType.MATCH_DISCOVERED, {"match_id": str(updated.id)}))
    return updated or match


def search_for_listing(db: Session, ctx: OrgContext, resource_id: uuid.UUID | None,
                       requirement_id: uuid.UUID | None) -> list[Match]:
    """Synchronous matching run for one of the caller's own listings."""
    if (resource_id is None) == (requirement_id is None):
        raise ValidationFailedError("Provide exactly one of resource_id or requirement_id.")
    if resource_id:
        listing = db.get(Resource, resource_id)
        if listing is None or listing.organization_id != ctx.org_id:
            raise NotFoundError("The requested resource does not exist.", code="RESOURCE_NOT_FOUND")
        run_for_resource(db, resource_id)
        return list_for_org(db, ctx, resource_id=resource_id)
    listing = db.get(Requirement, requirement_id)
    if listing is None or listing.organization_id != ctx.org_id:
        raise NotFoundError("The requested requirement does not exist.", code="REQUIREMENT_NOT_FOUND")
    run_for_requirement(db, requirement_id)
    return list_for_org(db, ctx, requirement_id=requirement_id)
