import uuid

from fastapi import APIRouter, status

from app.core.dependencies import DB, Org
from app.exchanges import service
from app.exchanges.models import EXCHANGE_LIFECYCLE, Exchange, ExchangeStatus
from app.exchanges.schemas import ExchangeComplete, ExchangeCreate, ExchangeOut, ExchangeReason, ExchangeUpdate
from app.organizations.schemas import OrganizationPublic

router = APIRouter(tags=["exchanges"])


def to_out(e: Exchange, ctx) -> ExchangeOut:
    return ExchangeOut(
        id=e.id, match_id=e.match_id, status=e.status, allowed_transitions=sorted(EXCHANGE_LIFECYCLE.allowed_from(e.status)),
        my_side="PROVIDER" if e.provider_org_id == ctx.org_id else "DEMANDER",
        provider=OrganizationPublic.model_validate(e.provider_org), demander=OrganizationPublic.model_validate(e.demander_org),
        resource_id=e.resource_id, requirement_id=e.requirement_id, resource_name=e.match.resource.name,
        requirement_name=e.match.requirement.name, upstream_exchange_id=e.upstream_exchange_id,
        agreed_quantity=e.agreed_quantity, unit=e.unit, agreed_frequency=e.agreed_frequency,
        agreed_price_per_unit=e.agreed_price_per_unit, currency=e.currency, delivery_terms=e.delivery_terms or {},
        start_date=e.start_date, end_date=e.end_date, notes=e.notes, delivered_quantity=e.delivered_quantity,
        status_reason=e.status_reason, started_at=e.started_at, completed_at=e.completed_at, created_at=e.created_at,
        updated_at=e.updated_at,
    )


@router.post("/matches/{match_id}/exchange", response_model=ExchangeOut, status_code=status.HTTP_201_CREATED,
             summary="Record the agreed exchange for a connected match")
def create_exchange(match_id: uuid.UUID, body: ExchangeCreate, ctx: Org, db: DB) -> ExchangeOut:
    return to_out(service.create(db, ctx, match_id, body), ctx)


@router.get("/exchanges", response_model=list[ExchangeOut])
def list_exchanges(ctx: Org, db: DB, status: ExchangeStatus | None = None) -> list[ExchangeOut]:
    return [to_out(e, ctx) for e in service.list_for_org(db, ctx, status)]


@router.get("/exchanges/{exchange_id}", response_model=ExchangeOut)
def get_exchange(exchange_id: uuid.UUID, ctx: Org, db: DB) -> ExchangeOut:
    return to_out(service.get_for_org(db, ctx, exchange_id), ctx)


@router.patch("/exchanges/{exchange_id}", response_model=ExchangeOut)
def update_exchange(exchange_id: uuid.UUID, body: ExchangeUpdate, ctx: Org, db: DB) -> ExchangeOut:
    return to_out(service.update_terms(db, ctx, exchange_id, body), ctx)


@router.post("/exchanges/{exchange_id}/start", response_model=ExchangeOut)
def start(exchange_id: uuid.UUID, ctx: Org, db: DB) -> ExchangeOut:
    return to_out(service.change_status(db, ctx, exchange_id, ExchangeStatus.IN_PROGRESS), ctx)


@router.post("/exchanges/{exchange_id}/pause", response_model=ExchangeOut)
def pause(exchange_id: uuid.UUID, body: ExchangeReason, ctx: Org, db: DB) -> ExchangeOut:
    return to_out(service.change_status(db, ctx, exchange_id, ExchangeStatus.PAUSED, body.reason), ctx)


@router.post("/exchanges/{exchange_id}/complete", response_model=ExchangeOut)
def complete(exchange_id: uuid.UUID, body: ExchangeComplete, ctx: Org, db: DB) -> ExchangeOut:
    return to_out(service.change_status(db, ctx, exchange_id, ExchangeStatus.COMPLETED, body.note,
                                        body.delivered_quantity), ctx)


@router.post("/exchanges/{exchange_id}/cancel", response_model=ExchangeOut)
def cancel(exchange_id: uuid.UUID, body: ExchangeReason, ctx: Org, db: DB) -> ExchangeOut:
    return to_out(service.change_status(db, ctx, exchange_id, ExchangeStatus.CANCELLED, body.reason), ctx)


@router.post("/exchanges/{exchange_id}/fail", response_model=ExchangeOut)
def fail(exchange_id: uuid.UUID, body: ExchangeReason, ctx: Org, db: DB) -> ExchangeOut:
    return to_out(service.change_status(db, ctx, exchange_id, ExchangeStatus.FAILED, body.reason), ctx)
