"""Connection lifecycle: the only way two organizations can start communicating.

Flow (spec §27): request (authorized member of either party, on a live match)
-> PENDING -> the *other* organization accepts -> conversation opened for both
organizations -> messages. Rejection, withdrawal, revocation and expiry are
explicit transitions.
"""

import uuid
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.audit import service as audit
from app.common.listings import ListingStatus
from app.connections.models import CONNECTION_LIFECYCLE, OPEN_CONNECTION_STATUSES, Connection, ConnectionStatus
from app.core import events
from app.core.dependencies import OrgContext
from app.core.errors import ConflictError, ForbiddenError, NotFoundError
from app.core.events import DomainEvent, EventType
from app.core.time import as_utc, utcnow
from app.matching import service as matching
from app.matching.models import Match, MatchStatus
from app.messaging import service as messaging
from app.organizations.permissions import Permission

PENDING_TTL = timedelta(days=14)
REQUESTABLE = {MatchStatus.DISCOVERED, MatchStatus.VIEWED, MatchStatus.INTERESTED}


def _transition(db: Session, connection: Connection, target: ConnectionStatus, ctx: OrgContext | None,
                note: str | None = None) -> None:
    previous = connection.status
    CONNECTION_LIFECYCLE.assert_transition(previous, target)
    connection.status = target
    now = utcnow()
    if target == ConnectionStatus.ACCEPTED:
        connection.accepted_at = now
    elif target == ConnectionStatus.REJECTED:
        connection.rejected_at = now
    elif target in (ConnectionStatus.REVOKED, ConnectionStatus.EXPIRED):
        connection.revoked_at = now
    if ctx is not None and target != ConnectionStatus.EXPIRED:
        connection.responded_by_user_id = ctx.user.id
    if note:
        connection.response_note = note[:500]
    audit.record(db, action=f"CONNECTION_{target}", entity_type="connection", entity_id=connection.id,
                 actor_user_id=ctx.user.id if ctx else None, organization_id=ctx.org_id if ctx else None,
                 details={"from": previous, "to": target, "match_id": str(connection.match_id)})


def open_connection_for_match(db: Session, match_id: uuid.UUID) -> Connection | None:
    return db.scalars(select(Connection).where(Connection.match_id == match_id,
                                               Connection.status.in_(OPEN_CONNECTION_STATUSES))
                      .order_by(Connection.created_at.desc())).first()


def request_connection(db: Session, ctx: OrgContext, match_id: uuid.UUID, message: str | None) -> Connection:
    ctx.require(Permission.MANAGE_CONNECTIONS)
    match = matching.get_for_org(db, ctx, match_id)
    if match.status not in REQUESTABLE:
        raise ConflictError(f"A connection cannot be requested while the opportunity is {match.status}.",
                            code="MATCH_NOT_REQUESTABLE")
    if open_connection_for_match(db, match.id):
        raise ConflictError("A connection for this opportunity already exists.", code="CONNECTION_EXISTS")
    if match.resource.status != ListingStatus.ACTIVE or match.requirement.status != ListingStatus.ACTIVE:
        raise ConflictError("This opportunity is no longer active.", code="OPPORTUNITY_INACTIVE")
    counterpart = match.demander_org if ctx.org_id == match.provider_org_id else match.provider_org
    if not counterpart.is_active:
        raise ConflictError("The other organization is not available.", code="ORGANIZATION_UNAVAILABLE")
    connection = Connection(match_id=match.id, initiated_by_user_id=ctx.user.id, initiated_by_org_id=ctx.org_id,
                            provider_org_id=match.provider_org_id, demander_org_id=match.demander_org_id,
                            message=(message or None), expires_at=utcnow() + PENDING_TTL)
    db.add(connection)
    db.flush()
    matching.transition(db, match, MatchStatus.CONNECTION_REQUESTED, ctx)
    audit.record(db, action="CONNECTION_REQUESTED", entity_type="connection", entity_id=connection.id,
                 actor_user_id=ctx.user.id, organization_id=ctx.org_id, details={"match_id": str(match.id)})
    db.commit()
    events.publish(DomainEvent(EventType.CONNECTION_REQUESTED, {"connection_id": str(connection.id)}))
    return connection


def get_for_org(db: Session, ctx: OrgContext, connection_id: uuid.UUID) -> Connection:
    connection = db.get(Connection, connection_id)
    if connection is None or ctx.org_id not in (connection.provider_org_id, connection.demander_org_id):
        raise NotFoundError("The requested connection does not exist.", code="CONNECTION_NOT_FOUND")
    return connection


def list_for_org(db: Session, ctx: OrgContext, direction: str | None = None,
                 status: ConnectionStatus | None = None) -> list[Connection]:
    query = select(Connection).where(or_(Connection.provider_org_id == ctx.org_id,
                                         Connection.demander_org_id == ctx.org_id))
    if direction == "outgoing":
        query = query.where(Connection.initiated_by_org_id == ctx.org_id)
    elif direction == "incoming":
        query = query.where(Connection.initiated_by_org_id != ctx.org_id)
    if status:
        query = query.where(Connection.status == status)
    return list(db.scalars(query.order_by(Connection.created_at.desc())))


def _require_recipient(ctx: OrgContext, connection: Connection) -> None:
    if connection.initiated_by_org_id == ctx.org_id:
        raise ForbiddenError("Only the other organization can respond to this request.", code="NOT_RECIPIENT")


def _expire_if_overdue(db: Session, connection: Connection) -> None:
    if (connection.status == ConnectionStatus.PENDING and connection.expires_at
            and as_utc(connection.expires_at) <= utcnow()):
        expire(db, connection)
        raise ConflictError("This connection request has expired.", code="CONNECTION_EXPIRED")


def accept(db: Session, ctx: OrgContext, connection_id: uuid.UUID) -> Connection:
    ctx.require(Permission.MANAGE_CONNECTIONS)
    connection = get_for_org(db, ctx, connection_id)
    _require_recipient(ctx, connection)
    _expire_if_overdue(db, connection)
    match = connection.match
    if match.resource.status != ListingStatus.ACTIVE or match.requirement.status != ListingStatus.ACTIVE:
        raise ConflictError("This opportunity is no longer active.", code="OPPORTUNITY_INACTIVE")
    # One transaction: connection, match state and conversation change together.
    _transition(db, connection, ConnectionStatus.ACCEPTED, ctx)
    matching.transition(db, match, MatchStatus.CONNECTED, ctx)
    conversation = messaging.open_conversation(db, match, connection)
    messaging.add_system_message(
        db, conversation,
        f"{ctx.organization.display_name} accepted the connection. You can now share specifications, documents "
        "and negotiate terms for this opportunity.",
    )
    db.commit()
    events.publish(DomainEvent(EventType.CONNECTION_ACCEPTED, {"connection_id": str(connection.id)}))
    return connection


def reject(db: Session, ctx: OrgContext, connection_id: uuid.UUID, note: str | None) -> Connection:
    ctx.require(Permission.MANAGE_CONNECTIONS)
    connection = get_for_org(db, ctx, connection_id)
    _require_recipient(ctx, connection)
    _transition(db, connection, ConnectionStatus.REJECTED, ctx, note)
    matching.transition(db, connection.match, MatchStatus.REJECTED, ctx, {"via": "connection_rejected"})
    connection.match.rejected_by_org_id = ctx.org_id
    db.commit()
    events.publish(DomainEvent(EventType.CONNECTION_REJECTED, {"connection_id": str(connection.id)}))
    return connection


def withdraw(db: Session, ctx: OrgContext, connection_id: uuid.UUID) -> Connection:
    ctx.require(Permission.MANAGE_CONNECTIONS)
    connection = get_for_org(db, ctx, connection_id)
    if connection.initiated_by_org_id != ctx.org_id or connection.status != ConnectionStatus.PENDING:
        raise ConflictError("Only a pending request you sent can be withdrawn.", code="CANNOT_WITHDRAW")
    _transition(db, connection, ConnectionStatus.REVOKED, ctx, "Withdrawn by requester")
    matching.transition(db, connection.match, MatchStatus.INTERESTED, ctx, {"via": "connection_withdrawn"})
    db.commit()
    return connection


def revoke(db: Session, ctx: OrgContext, connection_id: uuid.UUID, note: str | None) -> Connection:
    """End an accepted connection. The conversation becomes read-only; history is kept for audit."""
    ctx.require(Permission.MANAGE_CONNECTIONS)
    connection = get_for_org(db, ctx, connection_id)
    if connection.status != ConnectionStatus.ACCEPTED:
        raise ConflictError("Only an accepted connection can be revoked.", code="CANNOT_REVOKE")
    match = connection.match
    if match.status == MatchStatus.ACTIVE_EXCHANGE:
        raise ConflictError("Complete or cancel the active exchange before ending the connection.",
                            code="EXCHANGE_IN_PROGRESS")
    _transition(db, connection, ConnectionStatus.REVOKED, ctx, note)
    if match.status in (MatchStatus.CONNECTED, MatchStatus.NEGOTIATING):
        matching.transition(db, match, MatchStatus.CANCELLED, ctx, {"via": "connection_revoked"})
    conversation = messaging.conversation_for_connection(db, connection.id)
    if conversation is not None:
        messaging.add_system_message(db, conversation,
                                     f"{ctx.organization.display_name} ended this connection. The conversation "
                                     "is now read-only.")
        messaging.close_conversation(db, conversation)
    db.commit()
    return connection


def expire(db: Session, connection: Connection) -> None:
    _transition(db, connection, ConnectionStatus.EXPIRED, None)
    if connection.match.status == MatchStatus.CONNECTION_REQUESTED:
        matching.transition(db, connection.match, MatchStatus.EXPIRED, None, {"via": "connection_expired"})
        connection.match.stale_reason = "The connection request was not answered in time."
    db.commit()


def expire_overdue(db: Session) -> int:
    now = utcnow()
    overdue = [c for c in db.scalars(select(Connection).where(Connection.status == ConnectionStatus.PENDING))
               if c.expires_at and as_utc(c.expires_at) <= now]
    for connection in overdue:
        expire(db, connection)
    return len(overdue)


def expire_for_match(db: Session, match_id: uuid.UUID) -> None:
    """A pending request on an opportunity that went stale expires with it."""
    connection = open_connection_for_match(db, match_id)
    if connection is not None and connection.status == ConnectionStatus.PENDING:
        _transition(db, connection, ConnectionStatus.EXPIRED, None, "The opportunity is no longer active.")
        db.commit()


def connection_context_for(db: Session, match: Match, ctx: OrgContext) -> tuple[dict | None, uuid.UUID | None]:
    """Connection/exchange state embedded in the match detail view."""
    from app.exchanges.service import open_or_latest_exchange_id

    connection = open_connection_for_match(db, match.id) or db.scalars(
        select(Connection).where(Connection.match_id == match.id).order_by(Connection.created_at.desc())).first()
    exchange_id = open_or_latest_exchange_id(db, match.id)
    if connection is None:
        return None, exchange_id
    conversation = messaging.conversation_for_connection(db, connection.id)
    return {
        "id": str(connection.id),
        "status": connection.status.value,
        "initiated_by_me": connection.initiated_by_org_id == ctx.org_id,
        "can_respond": connection.status == ConnectionStatus.PENDING and connection.initiated_by_org_id != ctx.org_id,
        "message": connection.message,
        "conversation_id": str(conversation.id) if conversation else None,
        "created_at": connection.created_at.isoformat(),
        "accepted_at": connection.accepted_at.isoformat() if connection.accepted_at else None,
    }, exchange_id
