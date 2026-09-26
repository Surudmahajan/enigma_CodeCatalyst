import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, ValidationError

from app.connections.service import get_for_org as get_connection
from app.core.database import SessionLocal
from app.core.dependencies import DB, Org, resolve_org_context, resolve_user_from_token
from app.core.errors import AppError, NotFoundError
from app.core.rate_limit import rate_limit
from app.messaging import service
from app.messaging.models import Conversation, ConversationStatus, Message, MessageType
from app.messaging.realtime import Client, manager
from app.organizations.schemas import OrganizationPublic
from app.users.models import User

logger = logging.getLogger("symbio.messaging")
router = APIRouter(tags=["messaging"])


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    client_id: str | None = Field(default=None, max_length=64)


class MessageOut(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    message_type: MessageType
    body: str | None
    sender_user_id: uuid.UUID | None
    sender_name: str | None
    sender_organization_id: uuid.UUID | None
    is_mine: bool
    read_by_counterpart: bool
    document: dict[str, Any] | None
    client_id: str | None
    extra: dict[str, Any]
    created_at: datetime


class ConversationOut(BaseModel):
    id: uuid.UUID
    match_id: uuid.UUID
    connection_id: uuid.UUID
    status: ConversationStatus
    counterpart: OrganizationPublic
    my_side: Literal["PROVIDER", "DEMANDER"]
    resource_name: str
    requirement_name: str
    match_status: str
    last_message: MessageOut | None
    unread_count: int
    last_message_at: datetime | None
    created_at: datetime


def message_out(db, m: Message, ctx) -> MessageOut:
    payload = service.message_payload(m)
    mine = m.sender_organization_id == ctx.org_id
    return MessageOut(**payload, is_mine=mine,
                      read_by_counterpart=mine and service.counterpart_has_read(db, m, ctx.org_id))


def conversation_out(db, c: Conversation, ctx) -> ConversationOut:
    match = c.match
    mine_provider = match.provider_org_id == ctx.org_id
    last = db.query(Message).filter(Message.conversation_id == c.id).order_by(Message.created_at.desc()).first()
    return ConversationOut(
        id=c.id, match_id=c.match_id, connection_id=c.connection_id, status=c.status,
        counterpart=OrganizationPublic.model_validate(match.demander_org if mine_provider else match.provider_org),
        my_side="PROVIDER" if mine_provider else "DEMANDER", resource_name=match.resource.name,
        requirement_name=match.requirement.name, match_status=match.status.value,
        last_message=message_out(db, last, ctx) if last else None,
        unread_count=service.unread_count(db, ctx.user.id, c.id), last_message_at=c.last_message_at,
        created_at=c.created_at,
    )


@router.get("/conversations", response_model=list[ConversationOut], summary="Your organization's private channels")
def list_conversations(ctx: Org, db: DB) -> list[ConversationOut]:
    return [conversation_out(db, c, ctx) for c in service.list_for_org(db, ctx)]


@router.get("/conversations/{conversation_id}", response_model=ConversationOut)
def get_conversation(conversation_id: uuid.UUID, ctx: Org, db: DB) -> ConversationOut:
    return conversation_out(db, service.get_for_org(db, ctx, conversation_id), ctx)


@router.get("/connections/{connection_id}/conversation", response_model=ConversationOut, tags=["connections"])
def conversation_for_connection(connection_id: uuid.UUID, ctx: Org, db: DB) -> ConversationOut:
    connection = get_connection(db, ctx, connection_id)
    conversation = service.conversation_for_connection(db, connection.id)
    if conversation is None:
        raise NotFoundError("The conversation opens once the connection is accepted.", code="CONVERSATION_NOT_OPEN")
    return conversation_out(db, conversation, ctx)


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
def list_messages(conversation_id: uuid.UUID, ctx: Org, db: DB, before: datetime | None = None,
                  after: datetime | None = None, limit: int = Query(default=50, ge=1, le=100)) -> list[MessageOut]:
    return [message_out(db, m, ctx) for m in service.list_messages(db, ctx, conversation_id, before, after, limit)]


@router.post("/conversations/{conversation_id}/messages", response_model=MessageOut,
             status_code=status.HTTP_201_CREATED, dependencies=[Depends(rate_limit("messages", 60, 60))])
def send_message(conversation_id: uuid.UUID, body: MessageIn, ctx: Org, db: DB) -> MessageOut:
    return message_out(db, service.send_message(db, ctx, conversation_id, body.text, body.client_id), ctx)


@router.post("/conversations/{conversation_id}/read", status_code=status.HTTP_204_NO_CONTENT)
def mark_conversation_read(conversation_id: uuid.UUID, ctx: Org, db: DB) -> None:
    service.mark_conversation_read(db, ctx, conversation_id)


@router.post("/messages/{message_id}/read", status_code=status.HTTP_204_NO_CONTENT)
def mark_read(message_id: uuid.UUID, ctx: Org, db: DB) -> None:
    service.mark_read(db, ctx, message_id)


# --- WebSocket --------------------------------------------------------------------------------

class _WsIncoming(BaseModel):
    type: Literal["message", "read", "typing", "ping"]
    text: str | None = Field(default=None, max_length=4000)
    client_id: str | None = Field(default=None, max_length=64)
    message_id: uuid.UUID | None = None


def _authorize(token: str, conversation_id: uuid.UUID):
    with SessionLocal() as db:
        user = resolve_user_from_token(db, token)
        conversation = db.get(Conversation, conversation_id)
        if conversation is None:
            return None, None
        org_id = service.user_can_access(db, user, conversation)
        return (user.id, org_id) if org_id else (None, None)


def _handle(user_id: uuid.UUID, org_id: uuid.UUID, conversation_id: uuid.UUID, incoming: _WsIncoming) -> dict | None:
    with SessionLocal() as db:
        user = db.get(User, user_id)
        ctx = resolve_org_context(db, user, org_id)
        if incoming.type == "message":
            message = service.send_message(db, ctx, conversation_id, incoming.text, incoming.client_id)
            return {"type": "ack", "client_id": incoming.client_id, "message_id": str(message.id)}
        if incoming.type == "read" and incoming.message_id:
            service.mark_read(db, ctx, incoming.message_id)
    return None


@router.websocket("/ws/conversations/{conversation_id}")
async def conversation_socket(websocket: WebSocket, conversation_id: uuid.UUID, token: str = Query(...)):
    """Realtime channel. Authenticate with ``?token=<access token>``.

    Client -> server: ``{"type": "message", "text": "...", "client_id": "..."}``,
    ``{"type": "read", "message_id": "..."}``, ``{"type": "typing"}``, ``{"type": "ping"}``.
    Server -> client: ``message``, ``ack``, ``read``, ``typing``, ``pong``, ``error``, ``conversation_closed``.
    Every message is persisted before it is broadcast.
    """
    try:
        user_id, org_id = await run_in_threadpool(_authorize, token, conversation_id)
    except AppError:
        user_id = org_id = None
    if user_id is None:
        await websocket.close(code=4403)
        return
    await websocket.accept()
    client = Client(websocket=websocket, user_id=user_id, loop=asyncio.get_running_loop())
    manager.add(conversation_id, client)
    try:
        while True:
            raw = await websocket.receive_json()
            try:
                incoming = _WsIncoming.model_validate(raw)
            except ValidationError:
                await websocket.send_json({"type": "error", "code": "INVALID_MESSAGE"})
                continue
            if incoming.type == "ping":
                await websocket.send_json({"type": "pong"})
                continue
            if incoming.type == "typing":
                manager.broadcast(conversation_id, {"type": "typing", "user_id": str(user_id)}, exclude=websocket)
                continue
            try:
                reply = await run_in_threadpool(_handle, user_id, org_id, conversation_id, incoming)
            except AppError as exc:
                await websocket.send_json({"type": "error", "code": exc.code, "message": exc.message})
                continue
            if reply:
                await websocket.send_json(reply)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("WebSocket error")
    finally:
        manager.remove(conversation_id, client)
