import uuid

from app.core.database import SessionLocal
from app.core.events import DomainEvent, EventType, subscribe
from app.impact.service import record_for_exchange


def _exchange_changed(event: DomainEvent) -> None:
    if event.payload.get("to") != "COMPLETED":
        return
    with SessionLocal() as db:
        record_for_exchange(db, uuid.UUID(event.payload["exchange_id"]))


def register() -> None:
    subscribe(EventType.EXCHANGE_STATUS_CHANGED, _exchange_changed)
