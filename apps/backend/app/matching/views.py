"""Presenting matches to one side while protecting commercially sensitive data.

Before a connection is accepted the viewer sees what is needed to evaluate
the opportunity (material, quantity, window, approximate location, evidence),
but not the counterpart's descriptions, prices, costs, exact address or
contacts. Economic line items provided by the counterpart are hidden, and so
are the net/gross totals from which they could be back-calculated.
"""

import copy
from typing import Any

from sqlalchemy.orm import Session

from app.core.dependencies import OrgContext
from app.materials.schemas import ApplicationTypeOut, MaterialSummary
from app.matching.lifecycle import CONNECTED_STATES, EARLY_STATES
from app.matching.models import Match, MatchStatus
from app.matching.schemas import ComponentScores, CounterpartContact, ListingView, MatchDetail, MatchSummary
from app.matching.service import side_of
from app.organizations.permissions import Permission
from app.organizations.schemas import LocationPrivate, LocationPublic, OrganizationPublic


def _money(value) -> str | None:
    return str(value) if value is not None else None


def resource_view(match: Match, full: bool) -> ListingView:
    r = match.resource
    return ListingView(
        id=r.id, kind="RESOURCE", name=r.name, material=MaterialSummary.model_validate(r.material) if r.material else None,
        quantity=r.quantity_available, unit=r.unit, frequency=r.frequency, window_start=r.availability_start,
        window_end=r.availability_end, processing_required=r.processing_required,
        processing_types=r.processing_types or [], location=LocationPublic.model_validate(r.facility.location),
        status=r.status.value, description=r.description if full else None,
        commercial_terms={
            "currency": r.currency, "asking_price_per_unit": _money(r.asking_price_per_unit),
            "disposal_cost_per_unit": _money(r.disposal_cost_per_unit),
            "processing_cost_per_unit": _money(r.processing_cost_per_unit),
            "processing_description": r.processing_description, "storage_notes": r.storage_notes,
        } if full else None,
    )


def requirement_view(match: Match, full: bool) -> ListingView:
    q = match.requirement
    return ListingView(
        id=q.id, kind="REQUIREMENT", name=q.name,
        material=MaterialSummary.model_validate(q.material) if q.material else None,
        intended_application=ApplicationTypeOut.model_validate(q.intended_application)
        if q.intended_application else None,
        quantity=q.quantity_required, unit=q.unit, frequency=q.frequency, window_start=q.required_from,
        window_end=q.required_until, location=LocationPublic.model_validate(q.facility.location),
        status=q.status.value, description=q.description if full else None,
        commercial_terms={
            "currency": q.currency, "virgin_material_price_per_unit": _money(q.virgin_material_price_per_unit),
            "max_price_per_unit": _money(q.max_price_per_unit), "economic_constraints": q.economic_constraints,
        } if full else None,
    )


def redact_economic(economic: dict[str, Any] | None, viewer: str, connected: bool) -> dict[str, Any] | None:
    if economic is None or connected:
        return economic
    viewer_role = viewer.lower()
    redacted = copy.deepcopy(economic)
    hidden = False
    for item in redacted.get("line_items", []):
        if item.get("provided_by") not in (viewer_role, "platform"):
            item["amount"], item["formula"], item["hidden"] = None, None, True
            hidden = True
    if hidden:
        redacted["net_value"] = redacted["gross_benefit"] = None
        redacted.setdefault("notes", []).append(
            "Some inputs were provided by the other organization and are visible after connecting.")
    return redacted


def _allowed_actions(match: Match, ctx: OrgContext, connection: dict | None, exchange_id) -> list[str]:
    actions = []
    if match.status in (MatchStatus.DISCOVERED, MatchStatus.VIEWED):
        actions.append("MARK_INTERESTED")
    if ctx.can(Permission.MANAGE_CONNECTIONS):
        if match.status in (MatchStatus.DISCOVERED, MatchStatus.VIEWED, MatchStatus.INTERESTED):
            actions.append("REQUEST_CONNECTION")
        if connection and connection.get("status") == "PENDING" and connection.get("can_respond"):
            actions += ["ACCEPT_CONNECTION", "REJECT_CONNECTION"]
        if match.status in EARLY_STATES:
            actions.append("REJECT")
    if match.status in CONNECTED_STATES and connection and connection.get("conversation_id"):
        actions.append("OPEN_CHAT")
    if (ctx.can(Permission.MANAGE_EXCHANGES) and match.status in (MatchStatus.CONNECTED, MatchStatus.NEGOTIATING)
            and exchange_id is None):
        actions.append("CREATE_EXCHANGE")
    if match.status not in (MatchStatus.REJECTED, MatchStatus.CANCELLED, MatchStatus.COMPLETED):
        actions.append("REFRESH")
    return actions


def _counterpart(match: Match, side: str):
    return match.demander_org if side == "PROVIDER" else match.provider_org


def to_summary(match: Match, ctx: OrgContext) -> MatchSummary:
    side = side_of(match, ctx)
    explanation = match.explanation or {}
    mine_is_resource = side == "PROVIDER"
    viewed_at = match.provider_viewed_at if mine_is_resource else match.demander_viewed_at
    material = match.resource.material
    return MatchSummary(
        id=match.id, status=match.status, my_side=side,
        counterpart=OrganizationPublic.model_validate(_counterpart(match, side)),
        my_listing_id=match.resource_id if mine_is_resource else match.requirement_id,
        my_listing_name=match.resource.name if mine_is_resource else match.requirement.name,
        counterpart_listing_name=match.requirement.name if mine_is_resource else match.resource.name,
        material_name=material.canonical_name if material else None, overall_score=match.overall_score,
        confidence_level=match.confidence_level, feasibility=match.feasibility, match_type=match.match_type,
        is_hidden_match=match.is_hidden_match, requires_manual_review=match.requires_manual_review,
        distance_km=float(match.distance_km) if match.distance_km is not None else None,
        demand_coverage=match.demand_coverage, supply_utilization=match.supply_utilization,
        headline=explanation.get("headline", "Potential opportunity"),
        top_strengths=explanation.get("strengths", [])[:3], top_considerations=explanation.get("considerations", [])[:3],
        is_new=viewed_at is None and match.status == MatchStatus.DISCOVERED, stale_reason=match.stale_reason,
        updated_at=match.updated_at, expires_at=match.expires_at,
    )


def to_detail(db: Session, match: Match, ctx: OrgContext, connection: dict | None = None,
              exchange_id=None) -> MatchDetail:
    summary = to_summary(match, ctx)
    side = summary.my_side
    connected = match.status in CONNECTED_STATES
    snapshot = match.assessment_snapshot or {}
    counterpart_org = _counterpart(match, side)
    contact = None
    if connected:
        facility = match.requirement.facility if side == "PROVIDER" else match.resource.facility
        contact = CounterpartContact(
            legal_name=counterpart_org.legal_name, business_email=counterpart_org.business_email,
            business_phone=counterpart_org.business_phone, website=counterpart_org.website,
            facility_name=facility.name, facility_location=LocationPrivate.model_validate(facility.location),
        )
    return MatchDetail(
        **summary.model_dump(),
        scores=ComponentScores(material=match.material_score, quantity=match.quantity_score,
                               location=match.location_score, timing=match.timing_score,
                               processing=match.processing_score, economic=match.economic_score,
                               environmental=match.environmental_score),
        confidence=match.confidence, explanation=match.explanation,
        economic=redact_economic(snapshot.get("economic"), side, connected),
        environmental=snapshot.get("environmental"),
        resource=resource_view(match, full=connected or side == "PROVIDER"),
        requirement=requirement_view(match, full=connected or side == "DEMANDER"),
        counterpart_contact=contact, connection=connection, exchange_id=exchange_id,
        allowed_actions=_allowed_actions(match, ctx, connection, exchange_id),
        matching_version=match.matching_version, methodology_version=match.methodology_version,
        last_evaluated_at=match.last_evaluated_at, created_at=match.created_at,
    )
