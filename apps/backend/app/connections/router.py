import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.connections import service
from app.connections.models import Connection, ConnectionStatus
from app.core.dependencies import DB, Org
from app.messaging import service as messaging
from app.organizations.schemas import OrganizationPublic

router = APIRouter(tags=["connections"])


class ConnectionRequest(BaseModel):
    match_id: uuid.UUID
    message: str | None = Field(default=None, max_length=500)


class MatchConnectionRequest(BaseModel):
    message: str | None = Field(default=None, max_length=500)


class ConnectionResponse(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class ConnectionOut(BaseModel):
    id: uuid.UUID
    match_id: uuid.UUID
    status: ConnectionStatus
    direction: Literal["incoming", "outgoing"]
    counterpart: OrganizationPublic
    my_side: Literal["PROVIDER", "DEMANDER"]
    resource_name: str
    requirement_name: str
    overall_score: float
    message: str | None
    response_note: str | None
    conversation_id: uuid.UUID | None
    can_respond: bool
    created_at: datetime
    accepted_at: datetime | None
    expires_at: datetime | None


def to_out(db, connection: Connection, ctx) -> ConnectionOut:
    match = connection.match
    mine_provider = connection.provider_org_id == ctx.org_id
    counterpart = match.demander_org if mine_provider else match.provider_org
    conversation = messaging.conversation_for_connection(db, connection.id)
    outgoing = connection.initiated_by_org_id == ctx.org_id
    return ConnectionOut(
        id=connection.id, match_id=connection.match_id, status=connection.status,
        direction="outgoing" if outgoing else "incoming", counterpart=OrganizationPublic.model_validate(counterpart),
        my_side="PROVIDER" if mine_provider else "DEMANDER", resource_name=match.resource.name,
        requirement_name=match.requirement.name, overall_score=match.overall_score, message=connection.message,
        response_note=connection.response_note, conversation_id=conversation.id if conversation else None,
        can_respond=connection.status == ConnectionStatus.PENDING and not outgoing,
        created_at=connection.created_at, accepted_at=connection.accepted_at, expires_at=connection.expires_at,
    )


@router.post("/connections", response_model=ConnectionOut, status_code=status.HTTP_201_CREATED,
             summary="Request a connection for a specific match")
def create_connection(body: ConnectionRequest, ctx: Org, db: DB) -> ConnectionOut:
    return to_out(db, service.request_connection(db, ctx, body.match_id, body.message), ctx)


@router.post("/matches/{match_id}/connection-request", response_model=ConnectionOut,
             status_code=status.HTTP_201_CREATED, tags=["matching"])
def request_for_match(match_id: uuid.UUID, body: MatchConnectionRequest, ctx: Org, db: DB) -> ConnectionOut:
    return to_out(db, service.request_connection(db, ctx, match_id, body.message), ctx)


@router.get("/connections", response_model=list[ConnectionOut])
def list_connections(ctx: Org, db: DB, direction: Literal["incoming", "outgoing"] | None = None,
                     status: ConnectionStatus | None = None) -> list[ConnectionOut]:
    return [to_out(db, c, ctx) for c in service.list_for_org(db, ctx, direction, status)]


@router.get("/connections/{connection_id}", response_model=ConnectionOut)
def get_connection(connection_id: uuid.UUID, ctx: Org, db: DB) -> ConnectionOut:
    return to_out(db, service.get_for_org(db, ctx, connection_id), ctx)


@router.post("/connections/{connection_id}/accept", response_model=ConnectionOut)
def accept(connection_id: uuid.UUID, ctx: Org, db: DB) -> ConnectionOut:
    return to_out(db, service.accept(db, ctx, connection_id), ctx)


@router.post("/connections/{connection_id}/reject", response_model=ConnectionOut)
def reject(connection_id: uuid.UUID, body: ConnectionResponse, ctx: Org, db: DB) -> ConnectionOut:
    return to_out(db, service.reject(db, ctx, connection_id, body.note), ctx)


@router.post("/connections/{connection_id}/withdraw", response_model=ConnectionOut)
def withdraw(connection_id: uuid.UUID, ctx: Org, db: DB) -> ConnectionOut:
    return to_out(db, service.withdraw(db, ctx, connection_id), ctx)


@router.post("/connections/{connection_id}/revoke", response_model=ConnectionOut)
def revoke(connection_id: uuid.UUID, body: ConnectionResponse, ctx: Org, db: DB) -> ConnectionOut:
    return to_out(db, service.revoke(db, ctx, connection_id, body.note), ctx)
