"""Domain events -> in-app notifications (+ best-effort push).

Notification text names organizations and listings but never includes
message bodies or commercial values.
"""

import uuid

from app.connections import service as connections
from app.connections.models import Connection
from app.core.database import SessionLocal
from app.core.events import DomainEvent, EventType, subscribe
from app.exchanges.models import Exchange
from app.matching.models import Match
from app.messaging.models import Conversation, Message
from app.messaging.realtime import manager
from app.notifications.models import NotificationType
from app.notifications.service import notify_org


def _new_match(event: DomainEvent) -> None:
    with SessionLocal() as db:
        match = db.get(Match, uuid.UUID(event.payload["match_id"]))
        if match is None:
            return
        score = f"{match.overall_score:.0%}"
        notify_org(db, match.provider_org_id, type=NotificationType.NEW_MATCH,
                   title="New potential opportunity",
                   body=f"{match.demander_org.display_name} may be able to use your {match.resource.name} ({score}).",
                   data={"match_id": match.id}, dedupe_key=f"match:{match.id}:provider")
        notify_org(db, match.demander_org_id, type=NotificationType.NEW_MATCH,
                   title="New potential provider",
                   body=f"{match.provider_org.display_name} may be able to supply {match.requirement.name} ({score}).",
                   data={"match_id": match.id}, dedupe_key=f"match:{match.id}:demander")


def _connection_requested(event: DomainEvent) -> None:
    with SessionLocal() as db:
        connection = db.get(Connection, uuid.UUID(event.payload["connection_id"]))
        if connection is None:
            return
        requester = (connection.match.provider_org if connection.initiated_by_org_id == connection.provider_org_id
                     else connection.match.demander_org)
        notify_org(db, connection.recipient_org_id, type=NotificationType.CONNECTION_REQUEST,
                   title="Connection request", body=f"{requester.display_name} wants to discuss an opportunity with you.",
                   data={"connection_id": connection.id, "match_id": connection.match_id})


def _connection_answered(event: DomainEvent) -> None:
    with SessionLocal() as db:
        connection = db.get(Connection, uuid.UUID(event.payload["connection_id"]))
        if connection is None:
            return
        responder = (connection.match.demander_org if connection.initiated_by_org_id == connection.provider_org_id
                     else connection.match.provider_org)
        accepted = event.type == EventType.CONNECTION_ACCEPTED
        conversation = db.query(Conversation).filter(Conversation.connection_id == connection.id).first()
        notify_org(db, connection.initiated_by_org_id,
                   type=NotificationType.CONNECTION_ACCEPTED if accepted else NotificationType.CONNECTION_REJECTED,
                   title="Connection accepted" if accepted else "Connection declined",
                   body=(f"{responder.display_name} accepted. Your private channel is open." if accepted
                         else f"{responder.display_name} declined the connection request."),
                   data={"connection_id": connection.id, "match_id": connection.match_id,
                         **({"conversation_id": conversation.id} if conversation else {})})


def _message_sent(event: DomainEvent) -> None:
    with SessionLocal() as db:
        message = db.get(Message, uuid.UUID(event.payload["message_id"]))
        if message is None or message.sender_organization_id is None:
            return
        conversation = db.get(Conversation, message.conversation_id)
        sender_org = (conversation.match.provider_org if message.sender_organization_id == conversation.match.provider_org_id
                      else conversation.match.demander_org)
        online = manager.online_user_ids(conversation.id)
        for participant in conversation.participants:
            if participant.organization_id == message.sender_organization_id:
                continue
            # In-app history always; push only to members not currently viewing the channel.
            notify_org(db, participant.organization_id, type=NotificationType.NEW_MESSAGE,
                       title="New message", body=f"New message from {sender_org.display_name}.",
                       data={"conversation_id": conversation.id, "match_id": conversation.match_id},
                       push_exclude=online)


def _exchange_changed(event: DomainEvent) -> None:
    with SessionLocal() as db:
        exchange = db.get(Exchange, uuid.UUID(event.payload["exchange_id"]))
        if exchange is None:
            return
        status = exchange.status.value.replace("_", " ").lower()
        for org_id in (exchange.provider_org_id, exchange.demander_org_id):
            notify_org(db, org_id, type=NotificationType.EXCHANGE_STATUS_CHANGED,
                       title="Exchange update", body=f"The exchange for {exchange.match.resource.name} is now {status}.",
                       data={"exchange_id": exchange.id, "match_id": exchange.match_id})


def _match_expired(event: DomainEvent) -> None:
    with SessionLocal() as db:
        connections.expire_for_match(db, uuid.UUID(event.payload["match_id"]))


def register() -> None:
    subscribe(EventType.MATCH_DISCOVERED, _new_match)
    subscribe(EventType.CONNECTION_REQUESTED, _connection_requested)
    subscribe(EventType.CONNECTION_ACCEPTED, _connection_answered)
    subscribe(EventType.CONNECTION_REJECTED, _connection_answered)
    subscribe(EventType.MESSAGE_SENT, _message_sent)
    subscribe(EventType.EXCHANGE_CREATED, _exchange_changed)
    subscribe(EventType.EXCHANGE_STATUS_CHANGED, _exchange_changed)
    subscribe(EventType.LISTING_EXPIRED, _match_expired)
