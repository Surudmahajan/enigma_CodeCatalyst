"""Dashboards and analytics computed from stored data only."""

from collections import defaultdict
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.assessment.economic import VERSION as ECONOMIC_VERSION
from app.assessment.environmental import VERSION as ENVIRONMENTAL_VERSION
from app.common.listings import ListingStatus
from app.connections.models import Connection, ConnectionStatus
from app.core.dependencies import OrgContext
from app.exchanges.models import OPEN_EXCHANGE_STATUSES, Exchange, ExchangeStatus
from app.impact.models import ImpactRecord, ImpactSource, MetricType
from app.matching.lifecycle import CLOSED_STATES, CONNECTED_STATES
from app.matching.models import Match, MatchStatus
from app.messaging.service import list_for_org as conversations_for_org
from app.messaging.service import unread_count
from app.notifications.service import unread_count as unread_notifications
from app.organizations.models import OperatingMode, Organization, OrganizationStatus, VerificationStatus
from app.requirements.models import Requirement
from app.resources.models import Resource

OPEN_MATCH = [s for s in MatchStatus if s not in CLOSED_STATES]


def _count(db: Session, query) -> int:
    return db.scalar(select(func.count()).select_from(query.subquery())) or 0


def _potential(matches: list[Match], viewer_org_id) -> dict[str, Any]:
    """Sum of per-month potential from open matches, with data-availability counts.

    Economic value is summed only for connected matches: before connecting,
    combined values could reveal the counterpart's private cost inputs.
    """
    totals = defaultdict(float)
    counts = defaultdict(int)
    demo = False
    for m in matches:
        env = (m.assessment_snapshot or {}).get("environmental") or {}
        econ = (m.assessment_snapshot or {}).get("economic") or {}
        if env.get("waste_diverted") is not None:
            totals["waste_divertable_t_per_month"] += env["waste_diverted"]
            counts["waste"] += 1
        if env.get("virgin_material_avoided") is not None:
            totals["virgin_substitutable_t_per_month"] += env["virgin_material_avoided"]
        if env.get("net_benefit_kgco2e") is not None:
            totals["net_co2e_kg_per_month"] += env["net_benefit_kgco2e"]
            counts["co2e"] += 1
            demo = demo or bool(env.get("uses_demo_factors"))
        if m.status in CONNECTED_STATES and econ.get("net_value") is not None:
            totals["economic_value_per_month_connected"] += econ["net_value"]
            counts["economic"] += 1
    return {
        **{k: round(v, 1) for k, v in totals.items()},
        "opportunities": len(matches),
        "with_co2e_estimate": counts["co2e"],
        "with_connected_economics": counts["economic"],
        "uses_demo_factors": demo,
        "label": "Potential (not realized) — based on current opportunity assessments",
    }


def _realized(db: Session, org_filter) -> dict[str, Any]:
    rows = db.execute(select(ImpactRecord.metric_type, ImpactRecord.unit, ImpactRecord.source_type,
                             ImpactRecord.uses_demo_factors, func.sum(ImpactRecord.value))
                      .where(org_filter).group_by(ImpactRecord.metric_type, ImpactRecord.unit,
                                                  ImpactRecord.source_type, ImpactRecord.uses_demo_factors)).all()
    metrics: dict[str, dict[str, Any]] = {}
    for metric, unit, source, demo, total in rows:
        entry = metrics.setdefault(metric.value, {"unit": unit, "total": 0.0, "by_source": {}, "uses_demo_factors": False})
        entry["total"] = round(entry["total"] + float(total or 0), 3)
        entry["by_source"][source.value] = round(entry["by_source"].get(source.value, 0) + float(total or 0), 3)
        entry["uses_demo_factors"] = entry["uses_demo_factors"] or bool(demo)
    return metrics


def impact_dashboard(db: Session, ctx: OrgContext) -> dict[str, Any]:
    org = ctx.org_id
    open_matches = list(db.scalars(select(Match).where(or_(Match.provider_org_id == org, Match.demander_org_id == org),
                                                       Match.status.in_(OPEN_MATCH))))
    as_provider = [m for m in open_matches if m.provider_org_id == org]
    as_demander = [m for m in open_matches if m.demander_org_id == org]
    completed = _count(db, select(Exchange.id).where(or_(Exchange.provider_org_id == org, Exchange.demander_org_id == org),
                                                     Exchange.status == ExchangeStatus.COMPLETED))
    return {
        "potential": {"as_provider": _potential(as_provider, org), "as_demander": _potential(as_demander, org)},
        "realized": {
            "completed_exchanges": completed,
            "as_provider": _realized(db, ImpactRecord.provider_org_id == org),
            "as_demander": _realized(db, ImpactRecord.demander_org_id == org),
        },
        "methodology": {
            "economic": f"symbio.economic@{ECONOMIC_VERSION}",
            "environmental": f"symbio.environmental@{ENVIRONMENTAL_VERSION}",
            "sources": [s.value for s in ImpactSource],
            "note": ("Potential figures come from current opportunity assessments. Realized figures come from "
                     "completed exchanges and state whether they are estimates, party-reported or verified."),
        },
    }


def org_dashboard(db: Session, ctx: OrgContext) -> dict[str, Any]:
    org = ctx.org_id

    def listing_count(model) -> int:
        return _count(db, select(model.id).where(model.organization_id == org, model.status == ListingStatus.ACTIVE))

    def match_count(column) -> int:
        return _count(db, select(Match.id).where(column == org, Match.status.in_(OPEN_MATCH)))

    def new_count(column, viewed) -> int:
        return _count(db, select(Match.id).where(column == org, Match.status == MatchStatus.DISCOVERED, viewed.is_(None)))

    def pending_incoming(side_column) -> int:
        return _count(db, select(Connection.id).where(side_column == org, Connection.initiated_by_org_id != org,
                                                      Connection.status == ConnectionStatus.PENDING))

    def active_exchanges(column) -> int:
        return _count(db, select(Exchange.id).where(column == org, Exchange.status.in_(OPEN_EXCHANGE_STATUSES)))

    impact = impact_dashboard(db, ctx)
    realized_provider = impact["realized"]["as_provider"]
    realized_demander = impact["realized"]["as_demander"]

    def realized(metrics, key):
        return metrics.get(key, {}).get("total", 0.0)

    top = list(db.scalars(select(Match).where(or_(Match.provider_org_id == org, Match.demander_org_id == org),
                                              Match.status.in_(OPEN_MATCH))
                          .order_by(Match.overall_score.desc()).limit(5)))
    unread_messages = sum(unread_count(db, ctx.user.id, c.id) for c in conversations_for_org(db, ctx))
    return {
        "organization": {"id": str(org), "name": ctx.organization.display_name,
                         "operating_mode": ctx.organization.operating_mode.value,
                         "verification_status": ctx.organization.verification_status.value},
        "provider": {
            "active_resources": listing_count(Resource),
            "potential_matches": match_count(Match.provider_org_id),
            "new_matches": new_count(Match.provider_org_id, Match.provider_viewed_at),
            "connection_requests": pending_incoming(Connection.provider_org_id),
            "active_exchanges": active_exchanges(Exchange.provider_org_id),
            "impact": {
                "potential_waste_divertable_t_per_month":
                    impact["potential"]["as_provider"].get("waste_divertable_t_per_month", 0.0),
                "realized_waste_diverted_t": realized(realized_provider, MetricType.WASTE_DIVERTED.value),
            },
        },
        "demander": {
            "active_requirements": listing_count(Requirement),
            "potential_providers": match_count(Match.demander_org_id),
            "new_matches": new_count(Match.demander_org_id, Match.demander_viewed_at),
            "connection_requests": pending_incoming(Connection.demander_org_id),
            "active_exchanges": active_exchanges(Exchange.demander_org_id),
            "resource_savings": {
                "potential_virgin_substitutable_t_per_month":
                    impact["potential"]["as_demander"].get("virgin_substitutable_t_per_month", 0.0),
                "realized_virgin_material_avoided_t":
                    realized(realized_demander, MetricType.VIRGIN_MATERIAL_AVOIDED.value),
            },
        },
        "top_opportunity_ids": [str(m.id) for m in top],
        "unread_messages": unread_messages,
        "unread_notifications": unread_notifications(db, ctx.user.id),
    }


def platform_analytics(db: Session) -> dict[str, Any]:
    active_org = select(Organization.id).where(Organization.status == OrganizationStatus.ACTIVE)
    providers = select(Resource.organization_id).where(Resource.status == ListingStatus.ACTIVE).distinct()
    demanders = select(Requirement.organization_id).where(Requirement.status == ListingStatus.ACTIVE).distinct()
    status_counts = dict(db.execute(select(Match.status, func.count()).group_by(Match.status)).all())
    exchange_counts = dict(db.execute(select(Exchange.status, func.count()).group_by(Exchange.status)).all())
    open_matches = list(db.scalars(select(Match).where(Match.status.in_(OPEN_MATCH))))
    potential = _potential(open_matches, None)
    potential.pop("economic_value_per_month_connected", None)
    connected_value = sum(((m.assessment_snapshot or {}).get("economic") or {}).get("net_value") or 0
                          for m in open_matches if m.status in CONNECTED_STATES)
    return {
        "organizations": {
            "total": _count(db, select(Organization.id)),
            "active": _count(db, active_org),
            "verified": _count(db, select(Organization.id).where(
                Organization.verification_status == VerificationStatus.VERIFIED)),
            "pending_verification": _count(db, select(Organization.id).where(
                Organization.verification_status == VerificationStatus.PENDING)),
            "by_mode": {m.value: _count(db, select(Organization.id).where(Organization.operating_mode == m))
                        for m in OperatingMode},
        },
        "active_providers": _count(db, providers),
        "active_demanders": _count(db, demanders),
        "active_resources": _count(db, select(Resource.id).where(Resource.status == ListingStatus.ACTIVE)),
        "active_requirements": _count(db, select(Requirement.id).where(Requirement.status == ListingStatus.ACTIVE)),
        "matches_discovered": sum(status_counts.values()),
        "matches_by_status": {k.value: v for k, v in status_counts.items()},
        "hidden_matches": _count(db, select(Match.id).where(Match.is_hidden_match.is_(True))),
        "connections_created": _count(db, select(Connection.id)),
        "connections_accepted": _count(db, select(Connection.id).where(Connection.status.in_(
            [ConnectionStatus.ACCEPTED, ConnectionStatus.REVOKED])).where(Connection.accepted_at.is_not(None))),
        "active_exchanges": sum(v for k, v in exchange_counts.items() if k in OPEN_EXCHANGE_STATUSES),
        "completed_exchanges": exchange_counts.get(ExchangeStatus.COMPLETED, 0),
        "potential": {**potential, "economic_value_per_month_connected": round(connected_value, 2)},
        "realized": _realized(db, ImpactRecord.id.is_not(None)),
    }
