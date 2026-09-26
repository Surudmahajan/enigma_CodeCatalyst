"""Event handlers that keep matches in sync with listing changes (run as background jobs)."""

import uuid

from app.core.database import SessionLocal
from app.core.events import DomainEvent, EventType, subscribe
from app.matching import service


def _on_resource_changed(event: DomainEvent) -> None:
    with SessionLocal() as db:
        service.run_for_resource(db, uuid.UUID(event.payload["resource_id"]))


def _on_requirement_changed(event: DomainEvent) -> None:
    with SessionLocal() as db:
        service.run_for_requirement(db, uuid.UUID(event.payload["requirement_id"]))


def _on_listing_deactivated(event: DomainEvent) -> None:
    with SessionLocal() as db:
        if "resource_id" in event.payload:
            service.expire_for_listing(db, resource_id=uuid.UUID(event.payload["resource_id"]),
                                       reason="The resource is no longer active.")
        else:
            service.expire_for_listing(db, requirement_id=uuid.UUID(event.payload["requirement_id"]),
                                       reason="The requirement is no longer active.")


def register() -> None:
    subscribe(EventType.RESOURCE_CREATED, _on_resource_changed)
    subscribe(EventType.RESOURCE_UPDATED, _on_resource_changed)
    subscribe(EventType.REQUIREMENT_CREATED, _on_requirement_changed)
    subscribe(EventType.REQUIREMENT_UPDATED, _on_requirement_changed)
    subscribe(EventType.LISTING_DEACTIVATED, _on_listing_deactivated)
