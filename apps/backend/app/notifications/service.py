import uuid
from collections.abc import Iterable

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core import jobs
from app.core.errors import NotFoundError
from app.core.time import utcnow
from app.notifications.models import Notification, NotificationType, PushToken
from app.notifications.push import send_push
from app.organizations.models import MemberStatus, OrganizationMember


def active_member_ids(db: Session, organization_id: uuid.UUID) -> list[uuid.UUID]:
    return list(db.scalars(select(OrganizationMember.user_id).where(
        OrganizationMember.organization_id == organization_id, OrganizationMember.status == MemberStatus.ACTIVE)))


def notify_users(db: Session, user_ids: Iterable[uuid.UUID], *, type: NotificationType, title: str, body: str,
                 data: dict | None = None, organization_id: uuid.UUID | None = None, dedupe_key: str | None = None,
                 push: bool = True, push_exclude: set[uuid.UUID] | None = None) -> int:
    """Create in-app notifications (committed by the caller's session) and queue push delivery."""
    user_ids = list(dict.fromkeys(user_ids))
    if not user_ids:
        return 0
    if dedupe_key:
        already = set(db.scalars(select(Notification.user_id).where(Notification.dedupe_key == dedupe_key,
                                                                    Notification.user_id.in_(user_ids))))
        user_ids = [u for u in user_ids if u not in already]
    payload = {k: str(v) for k, v in (data or {}).items()}
    for user_id in user_ids:
        db.add(Notification(user_id=user_id, organization_id=organization_id, type=type, title=title[:200],
                            body=body[:500], data=payload, dedupe_key=dedupe_key))
    db.commit()
    if push:
        targets = [u for u in user_ids if u not in (push_exclude or set())]
        tokens = list(db.scalars(select(PushToken.token).where(PushToken.user_id.in_(targets)))) if targets else []
        if tokens:
            jobs.enqueue(send_push, tokens, title, body, {**payload, "type": type.value})
    return len(user_ids)


def notify_org(db: Session, organization_id: uuid.UUID, *, exclude_user_id: uuid.UUID | None = None,
               **kwargs) -> int:
    members = [u for u in active_member_ids(db, organization_id) if u != exclude_user_id]
    return notify_users(db, members, organization_id=organization_id, **kwargs)


def list_for_user(db: Session, user_id: uuid.UUID, *, unread_only: bool = False, limit: int = 50,
                  before=None) -> list[Notification]:
    query = select(Notification).where(Notification.user_id == user_id)
    if unread_only:
        query = query.where(Notification.read_at.is_(None))
    if before is not None:
        query = query.where(Notification.created_at < before)
    return list(db.scalars(query.order_by(Notification.created_at.desc()).limit(limit)))


def unread_count(db: Session, user_id: uuid.UUID) -> int:
    return db.scalar(select(func.count()).select_from(Notification).where(
        Notification.user_id == user_id, Notification.read_at.is_(None))) or 0


def mark_read(db: Session, user_id: uuid.UUID, notification_id: uuid.UUID) -> Notification:
    notification = db.get(Notification, notification_id)
    if notification is None or notification.user_id != user_id:
        raise NotFoundError("Notification not found.", code="NOTIFICATION_NOT_FOUND")
    notification.read_at = notification.read_at or utcnow()
    db.commit()
    return notification


def mark_all_read(db: Session, user_id: uuid.UUID) -> None:
    db.execute(update(Notification).where(Notification.user_id == user_id, Notification.read_at.is_(None))
               .values(read_at=utcnow()))
    db.commit()


def register_push_token(db: Session, user_id: uuid.UUID, token: str, platform: str) -> None:
    existing = db.scalars(select(PushToken).where(PushToken.token == token)).first()
    if existing:
        existing.user_id, existing.platform, existing.last_seen_at = user_id, platform, utcnow()
    else:
        db.add(PushToken(user_id=user_id, token=token, platform=platform))
    db.commit()


def remove_push_token(db: Session, user_id: uuid.UUID, token: str) -> None:
    existing = db.scalars(select(PushToken).where(PushToken.token == token, PushToken.user_id == user_id)).first()
    if existing:
        db.delete(existing)
        db.commit()
