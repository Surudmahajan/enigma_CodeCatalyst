import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.dependencies import DB, CurrentUser
from app.notifications import service
from app.notifications.models import NotificationType

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: NotificationType
    title: str
    body: str
    data: dict[str, Any]
    organization_id: uuid.UUID | None
    read_at: datetime | None
    created_at: datetime


class UnreadCount(BaseModel):
    unread: int


class PushTokenIn(BaseModel):
    token: str = Field(min_length=10, max_length=255, pattern=r"^[A-Za-z0-9\[\]_:\-\.]+$")
    platform: Literal["android", "ios", "web"]


@router.get("", response_model=list[NotificationOut], summary="In-app notification history")
def list_notifications(user: CurrentUser, db: DB, unread_only: bool = False,
                       limit: int = Query(default=50, ge=1, le=100), before: datetime | None = None
                       ) -> list[NotificationOut]:
    return [NotificationOut.model_validate(n) for n in
            service.list_for_user(db, user.id, unread_only=unread_only, limit=limit, before=before)]


@router.get("/unread-count", response_model=UnreadCount)
def unread_count(user: CurrentUser, db: DB) -> UnreadCount:
    return UnreadCount(unread=service.unread_count(db, user.id))


@router.post("/{notification_id}/read", response_model=NotificationOut)
def mark_read(notification_id: uuid.UUID, user: CurrentUser, db: DB) -> NotificationOut:
    return NotificationOut.model_validate(service.mark_read(db, user.id, notification_id))


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
def mark_all_read(user: CurrentUser, db: DB) -> None:
    service.mark_all_read(db, user.id)


@router.post("/push-tokens", status_code=status.HTTP_204_NO_CONTENT, summary="Register an Expo push token")
def register_push_token(body: PushTokenIn, user: CurrentUser, db: DB) -> None:
    service.register_push_token(db, user.id, body.token, body.platform)


@router.delete("/push-tokens/{token}", status_code=status.HTTP_204_NO_CONTENT)
def remove_push_token(token: str, user: CurrentUser, db: DB) -> None:
    service.remove_push_token(db, user.id, token)
