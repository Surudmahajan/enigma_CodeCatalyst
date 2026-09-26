import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query

from app.core.dependencies import DB, Org
from app.core.rate_limit import rate_limit
from app.matching import service, views
from app.matching.models import MatchStatus
from app.matching.schemas import MatchDetail, MatchSummary, RejectRequest, SearchRequest

router = APIRouter(prefix="/matches", tags=["matching"])


def detail(db, match, ctx) -> MatchDetail:
    return views.to_detail(db, match, ctx)


@router.get("", response_model=list[MatchSummary], summary="Opportunities for your organization")
def list_matches(
    ctx: Org, db: DB,
    side: Literal["provider", "demander"] | None = Query(default=None, description="Filter by your role in the match"),
    status: list[MatchStatus] | None = Query(default=None),
    resource_id: uuid.UUID | None = None,
    requirement_id: uuid.UUID | None = None,
    include_closed: bool = False,
) -> list[MatchSummary]:
    matches = service.list_for_org(db, ctx, side=side, statuses=status, resource_id=resource_id,
                                   requirement_id=requirement_id, include_closed=include_closed)
    return [views.to_summary(m, ctx) for m in matches]


@router.post("/search", response_model=list[MatchSummary], dependencies=[Depends(rate_limit("search", 30, 60))],
             summary="Run matching now for one of your listings")
def search(body: SearchRequest, ctx: Org, db: DB) -> list[MatchSummary]:
    matches = service.search_for_listing(db, ctx, body.resource_id, body.requirement_id)
    return [views.to_summary(m, ctx) for m in matches]


@router.get("/{match_id}", response_model=MatchDetail, summary="Opportunity report with explanation")
def get_match(match_id: uuid.UUID, ctx: Org, db: DB) -> MatchDetail:
    match = service.get_for_org(db, ctx, match_id)
    service.mark_viewed(db, ctx, match)
    return detail(db, match, ctx)


@router.post("/{match_id}/interest", response_model=MatchDetail)
def mark_interested(match_id: uuid.UUID, ctx: Org, db: DB) -> MatchDetail:
    return detail(db, service.mark_interested(db, ctx, match_id), ctx)


@router.post("/{match_id}/reject", response_model=MatchDetail, summary="Dismiss an opportunity")
def reject(match_id: uuid.UUID, body: RejectRequest, ctx: Org, db: DB) -> MatchDetail:
    return detail(db, service.reject(db, ctx, match_id, body.reason), ctx)


@router.post("/{match_id}/refresh", response_model=MatchDetail, summary="Re-evaluate with current data")
def refresh(match_id: uuid.UUID, ctx: Org, db: DB) -> MatchDetail:
    return detail(db, service.refresh(db, ctx, match_id), ctx)
