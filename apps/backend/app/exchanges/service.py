"""Exchange lifecycle. The Match discovers the opportunity; the Exchange is the agreed relationship."""

import uuid
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.audit import service as audit
from app.connections.models import ConnectionStatus
from app.connections.service import open_connection_for_match
from app.core import events
from app.core.dependencies import OrgContext
from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.core.events import DomainEvent, EventType
from app.core.time import utcnow
from app.exchanges.models import EXCHANGE_LIFECYCLE, OPEN_EXCHANGE_STATUSES, Exchange, ExchangeStatus
from app.exchanges.schemas import ExchangeCreate, ExchangeUpdate
from app.materials import units
from app.matching import service as matching
from app.matching.models import MatchStatus
from app.messaging import service as messaging
from app.messaging.models import MessageType
from app.organizations.permissions import Permission

# How the match follows the exchange.
_MATCH_FOR_EXCHANGE = {
    ExchangeStatus.IN_PROGRESS: MatchStatus.ACTIVE_EXCHANGE,
    ExchangeStatus.COMPLETED: MatchStatus.COMPLETED,
}


def open_or_latest_exchange_id(db: Session, match_id: uuid.UUID) -> uuid.UUID | None:
    exchange = db.scalars(select(Exchange).where(Exchange.match_id == match_id)
                          .order_by(Exchange.status.in_(OPEN_EXCHANGE_STATUSES).desc(),
                                    Exchange.created_at.desc())).first()
    return exchange.id if exchange else None


def get_for_org(db: Session, ctx: OrgContext, exchange_id: uuid.UUID) -> Exchange:
    exchange = db.get(Exchange, exchange_id)
    if exchange is None or ctx.org_id not in (exchange.provider_org_id, exchange.demander_org_id):
        raise NotFoundError("The requested exchange does not exist.", code="EXCHANGE_NOT_FOUND")
    return exchange


def list_for_org(db: Session, ctx: OrgContext, status: ExchangeStatus | None = None) -> list[Exchange]:
    query = select(Exchange).where(or_(Exchange.provider_org_id == ctx.org_id, Exchange.demander_org_id == ctx.org_id))
    if status:
        query = query.where(Exchange.status == status)
    return list(db.scalars(query.order_by(Exchange.updated_at.desc())))


def _post_update(db: Session, exchange: Exchange, text: str) -> None:
    connection = open_connection_for_match(db, exchange.match_id)
    conversation = messaging.conversation_for_connection(db, connection.id) if connection else None
    if conversation is not None:
        messaging.add_system_message(db, conversation, text, {"exchange_id": str(exchange.id),
                                                              "exchange_status": exchange.status.value},
                                     message_type=MessageType.STRUCTURED_UPDATE)


def create(db: Session, ctx: OrgContext, match_id: uuid.UUID, data: ExchangeCreate) -> Exchange:
    ctx.require(Permission.MANAGE_EXCHANGES)
    match = matching.get_for_org(db, ctx, match_id)
    connection = open_connection_for_match(db, match.id)
    if connection is None or connection.status != ConnectionStatus.ACCEPTED:
        raise ConflictError("An exchange can only be created after the connection is accepted.",
                            code="CONNECTION_REQUIRED")
    if match.status not in (MatchStatus.CONNECTED, MatchStatus.NEGOTIATING):
        raise ConflictError(f"An exchange cannot be created while the opportunity is {match.status}.",
                            code="MATCH_NOT_READY")
    if db.scalars(select(Exchange).where(Exchange.match_id == match.id,
                                         Exchange.status.in_(OPEN_EXCHANGE_STATUSES))).first():
        raise ConflictError("This opportunity already has an open exchange.", code="EXCHANGE_EXISTS")
    if not units.same_family(data.unit, match.resource.unit):
        raise ValidationFailedError("The agreed unit is not comparable with the resource unit.", code="UNIT_MISMATCH")
    if data.upstream_exchange_id:
        upstream = get_for_org(db, ctx, data.upstream_exchange_id)
        if upstream.demander_org_id != match.provider_org_id:
            raise ValidationFailedError("An upstream exchange must deliver to this exchange's provider.",
                                        code="INVALID_UPSTREAM")
    exchange = Exchange(
        match_id=match.id, provider_org_id=match.provider_org_id, demander_org_id=match.demander_org_id,
        resource_id=match.resource_id, requirement_id=match.requirement_id, created_by_user_id=ctx.user.id,
        **data.model_dump(),
    )
    db.add(exchange)
    if match.status == MatchStatus.CONNECTED:
        matching.transition(db, match, MatchStatus.NEGOTIATING, ctx)
    db.flush()
    audit.record(db, action="EXCHANGE_CREATED", entity_type="exchange", entity_id=exchange.id,
                 actor_user_id=ctx.user.id, organization_id=ctx.org_id,
                 details={"match_id": str(match.id), "agreed_quantity": data.agreed_quantity, "unit": data.unit})
    _post_update(db, exchange, f"{ctx.organization.display_name} proposed an exchange: "
                               f"{data.agreed_quantity:,} {data.unit} per {data.agreed_frequency.value.lower()} "
                               f"from {data.start_date}.")
    db.commit()
    events.publish(DomainEvent(EventType.EXCHANGE_CREATED, {"exchange_id": str(exchange.id)}))
    return exchange


def update_terms(db: Session, ctx: OrgContext, exchange_id: uuid.UUID, data: ExchangeUpdate) -> Exchange:
    ctx.require(Permission.MANAGE_EXCHANGES)
    exchange = get_for_org(db, ctx, exchange_id)
    changes = data.model_dump(exclude_unset=True, exclude={"status", "status_reason", "delivered_quantity"})
    if changes:
        if exchange.status not in (ExchangeStatus.PLANNED, ExchangeStatus.PAUSED):
            raise ConflictError("Terms can only change while the exchange is planned or paused.",
                                code="EXCHANGE_TERMS_LOCKED")
        for field, value in changes.items():
            setattr(exchange, field, value)
        if exchange.end_date and exchange.end_date < exchange.start_date:
            raise ValidationFailedError("The end date must be on or after the start date.", code="INVALID_DATES")
        audit.record(db, action="EXCHANGE_TERMS_UPDATED", entity_type="exchange", entity_id=exchange.id,
                     actor_user_id=ctx.user.id, organization_id=ctx.org_id, details={"fields": sorted(changes)})
        _post_update(db, exchange, f"{ctx.organization.display_name} updated the exchange terms.")
        db.commit()
    if data.status is not None and data.status != exchange.status:
        exchange = change_status(db, ctx, exchange_id, data.status, data.status_reason, data.delivered_quantity)
    return exchange


def change_status(db: Session, ctx: OrgContext, exchange_id: uuid.UUID, target: ExchangeStatus,
                  reason: str | None = None, delivered_quantity: Decimal | None = None) -> Exchange:
    ctx.require(Permission.MANAGE_EXCHANGES)
    exchange = get_for_org(db, ctx, exchange_id)
    previous = exchange.status
    EXCHANGE_LIFECYCLE.assert_transition(previous, target)
    now = utcnow()
    exchange.status = target
    exchange.status_reason = reason
    if target == ExchangeStatus.IN_PROGRESS and exchange.started_at is None:
        exchange.started_at = now
    if target == ExchangeStatus.COMPLETED:
        exchange.completed_at = now
        exchange.delivered_quantity = delivered_quantity
    if target in (ExchangeStatus.CANCELLED, ExchangeStatus.FAILED):
        exchange.cancelled_at = now

    match = exchange.match
    match_target = _MATCH_FOR_EXCHANGE.get(target)
    if target in (ExchangeStatus.CANCELLED, ExchangeStatus.FAILED) and match.status == MatchStatus.ACTIVE_EXCHANGE:
        match_target = MatchStatus.NEGOTIATING  # the connection remains; parties may agree new terms
    if match_target and match.status != match_target:
        matching.transition(db, match, match_target, ctx, {"via": f"exchange_{target.lower()}"})

    audit.record(db, action="EXCHANGE_STATUS_CHANGED", entity_type="exchange", entity_id=exchange.id,
                 actor_user_id=ctx.user.id, organization_id=ctx.org_id,
                 details={"from": previous, "to": target, "reason": reason, "delivered_quantity": delivered_quantity})
    label = target.value.replace("_", " ").lower()
    _post_update(db, exchange, f"{ctx.organization.display_name} marked the exchange as {label}"
                               + (f": {reason}" if reason else "."))
    db.commit()
    events.publish(DomainEvent(EventType.EXCHANGE_STATUS_CHANGED,
                               {"exchange_id": str(exchange.id), "from": previous.value, "to": target.value}))
    return exchange
