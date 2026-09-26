"""Match-scoped private messaging.

Authorization never trusts a conversation id on its own: access requires the
acting organization to be a participant of that conversation, and the user
to be an active member of that organization (resolved in OrgContext).
"""

import uuid
from datetime import datetime

from sqlalchemy import and_, event, func, select
from sqlalchemy.orm import Session

from app.core import events
from app.core.dependencies import OrgContext
from app.core.errors import ConflictError, NotFoundError
from app.core.events import DomainEvent, EventType
from app.core.time import utcnow
from app.matching.lifecycle import MATCH_LIFECYCLE
from app.matching.models import Match, MatchStatus
from app.messaging.models import (
    Conversation,
    ConversationParticipant,
    ConversationStatus,
    Message,
    MessageType,
    ReadReceipt,
)
from app.messaging.realtime import manager
from app.organizations.models import MemberStatus, OrganizationMember
from app.organizations.permissions import Permission
from app.users.models import User

MAX_PAGE = 100


def open_conversation(db: Session, match: Match, connection) -> Conversation:
    existing = conversation_for_connection(db, connection.id)
    if existing is not None:
        existing.status = ConversationStatus.ACTIVE
        return existing
    conversation = Conversation(match_id=match.id, connection_id=connection.id)
    conversation.participants = [
        ConversationParticipant(organization_id=match.provider_org_id),
        ConversationParticipant(organization_id=match.demander_org_id),
    ]
    db.add(conversation)
    db.flush()
    return conversation


def conversation_for_connection(db: Session, connection_id: uuid.UUID) -> Conversation | None:
    return db.scalars(select(Conversation).where(Conversation.connection_id == connection_id)).first()


def close_conversation(db: Session, conversation: Conversation) -> None:
    conversation.status = ConversationStatus.CLOSED
    manager.close_conversation(conversation.id)


def add_system_message(db: Session, conversation: Conversation, text: str, extra: dict | None = None,
                       message_type: MessageType = MessageType.SYSTEM) -> Message:
    message = Message(conversation_id=conversation.id, message_type=message_type, body=text, extra=extra or {})
    db.add(message)
    conversation.last_message_at = utcnow()
    db.flush()
    _broadcast_after_commit(db, conversation.id, message)
    return message


def participant_org_ids(conversation: Conversation) -> set[uuid.UUID]:
    return {p.organization_id for p in conversation.participants if p.left_at is None}


def get_for_org(db: Session, ctx: OrgContext, conversation_id: uuid.UUID) -> Conversation:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None or ctx.org_id not in participant_org_ids(conversation):
        raise NotFoundError("The requested conversation does not exist.", code="CONVERSATION_NOT_FOUND")
    return conversation


def user_can_access(db: Session, user: User, conversation: Conversation) -> uuid.UUID | None:
    """For WebSocket auth: returns the user's participating organization id, if any."""
    orgs = participant_org_ids(conversation)
    member = db.scalars(select(OrganizationMember).where(
        OrganizationMember.user_id == user.id, OrganizationMember.status == MemberStatus.ACTIVE,
        OrganizationMember.organization_id.in_(orgs))).first()
    if member is None or not member.organization.is_active:
        return None
    return member.organization_id


def list_for_org(db: Session, ctx: OrgContext) -> list[Conversation]:
    query = (select(Conversation).join(ConversationParticipant)
             .where(ConversationParticipant.organization_id == ctx.org_id)
             .order_by(func.coalesce(Conversation.last_message_at, Conversation.created_at).desc()))
    return list(db.scalars(query).unique())


def list_messages(db: Session, ctx: OrgContext, conversation_id: uuid.UUID, before: datetime | None = None,
                  after: datetime | None = None, limit: int = 50) -> list[Message]:
    get_for_org(db, ctx, conversation_id)
    query = select(Message).where(Message.conversation_id == conversation_id, Message.deleted_at.is_(None))
    if after is not None:  # sync forward after reconnecting
        rows = db.scalars(query.where(Message.created_at > after).order_by(Message.created_at).limit(MAX_PAGE))
        return list(rows)
    if before is not None:
        query = query.where(Message.created_at < before)
    rows = list(db.scalars(query.order_by(Message.created_at.desc()).limit(min(limit, MAX_PAGE))))
    return list(reversed(rows))


def send_message(db: Session, ctx: OrgContext, conversation_id: uuid.UUID, text: str | None,
                 client_id: str | None = None, document_id: uuid.UUID | None = None) -> Message:
    ctx.require(Permission.SEND_MESSAGES)
    conversation = get_for_org(db, ctx, conversation_id)
    if conversation.status != ConversationStatus.ACTIVE:
        raise ConflictError("This conversation is closed.", code="CONVERSATION_CLOSED")
    if client_id:  # idempotent retry from a flaky mobile connection
        duplicate = db.scalars(select(Message).where(Message.conversation_id == conversation_id,
                                                     Message.sender_user_id == ctx.user.id,
                                                     Message.client_id == client_id)).first()
        if duplicate:
            return duplicate
    message = Message(conversation_id=conversation_id, sender_user_id=ctx.user.id, sender_organization_id=ctx.org_id,
                      message_type=MessageType.DOCUMENT if document_id else MessageType.TEXT,
                      body=(text or "").strip() or None, document_id=document_id, client_id=client_id)
    db.add(message)
    conversation.last_message_at = utcnow()
    match = conversation.match
    if match.status == MatchStatus.CONNECTED and MATCH_LIFECYCLE.can_transition(match.status, MatchStatus.NEGOTIATING):
        match.status = MatchStatus.NEGOTIATING  # first exchange of messages starts negotiation
    db.flush()
    db.add(ReadReceipt(message_id=message.id, user_id=ctx.user.id))
    db.commit()
    db.refresh(message)
    manager.broadcast(conversation_id, {"type": "message", "message": message_payload(message)})
    events.publish(DomainEvent(EventType.MESSAGE_SENT, {"message_id": str(message.id)}))
    return message


def mark_read(db: Session, ctx: OrgContext, message_id: uuid.UUID) -> None:
    message = db.get(Message, message_id)
    if message is None:
        raise NotFoundError("Message not found.", code="MESSAGE_NOT_FOUND")
    get_for_org(db, ctx, message.conversation_id)
    _record_reads(db, ctx.user.id, [message])
    manager.broadcast(message.conversation_id, {"type": "read", "message_id": str(message.id),
                                                "user_id": str(ctx.user.id)})


def mark_conversation_read(db: Session, ctx: OrgContext, conversation_id: uuid.UUID) -> None:
    get_for_org(db, ctx, conversation_id)
    unread = db.scalars(_unread_query(ctx.user.id, conversation_id)).all()
    _record_reads(db, ctx.user.id, unread)


def _record_reads(db: Session, user_id: uuid.UUID, messages: list[Message]) -> None:
    if not messages:
        return
    ids = [m.id for m in messages]
    already = set(db.scalars(select(ReadReceipt.message_id).where(ReadReceipt.user_id == user_id,
                                                                  ReadReceipt.message_id.in_(ids))))
    for message_id in ids:
        if message_id not in already:
            db.add(ReadReceipt(message_id=message_id, user_id=user_id))
    db.commit()


def _unread_query(user_id: uuid.UUID, conversation_id: uuid.UUID):
    receipt = and_(ReadReceipt.message_id == Message.id, ReadReceipt.user_id == user_id)
    return (select(Message).outerjoin(ReadReceipt, receipt)
            .where(Message.conversation_id == conversation_id, ReadReceipt.id.is_(None), Message.deleted_at.is_(None)))


def unread_count(db: Session, user_id: uuid.UUID, conversation_id: uuid.UUID) -> int:
    return db.scalar(select(func.count()).select_from(_unread_query(user_id, conversation_id).subquery())) or 0


def counterpart_has_read(db: Session, message: Message, my_org_id: uuid.UUID) -> bool:
    """True when any member of the other organization has read the message."""
    other_members = select(OrganizationMember.user_id).where(OrganizationMember.organization_id != my_org_id)
    return bool(db.scalar(select(func.count()).select_from(ReadReceipt).where(
        ReadReceipt.message_id == message.id, ReadReceipt.user_id.in_(other_members),
        ReadReceipt.user_id != message.sender_user_id)))


def message_payload(message: Message) -> dict:
    return {
        "id": str(message.id),
        "conversation_id": str(message.conversation_id),
        "message_type": message.message_type.value,
        "body": message.body,
        "sender_user_id": str(message.sender_user_id) if message.sender_user_id else None,
        "sender_name": message.sender.full_name if message.sender else None,
        "sender_organization_id": str(message.sender_organization_id) if message.sender_organization_id else None,
        "document": {"id": str(message.document.id), "file_name": message.document.file_name,
                     "file_type": message.document.file_type, "file_size": message.document.file_size}
        if message.document else None,
        "client_id": message.client_id,
        "extra": message.extra or {},
        "created_at": message.created_at.isoformat(),
    }


def _broadcast_after_commit(db: Session, conversation_id: uuid.UUID, message: Message) -> None:
    @event.listens_for(db, "after_commit", once=True)
    def _send(_session) -> None:
        try:
            manager.broadcast(conversation_id, {"type": "message", "message": message_payload(message)})
        except Exception:  # realtime is best-effort; the message is already persisted
            pass
