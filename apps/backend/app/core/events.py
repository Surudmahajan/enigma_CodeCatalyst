"""Minimal in-process domain event bus.

Services publish events (``RESOURCE_CREATED``, ``CONNECTION_ACCEPTED`` ...)
after their transaction commits. Handlers (matching recalculation,
notifications, audit, analytics) subscribe without the publishing service
knowing about them, which keeps side effects out of the primary request path.
Handlers run through the job queue.
"""

import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.core import jobs

logger = logging.getLogger("symbio.events")


class EventType(StrEnum):
    RESOURCE_CREATED = "RESOURCE_CREATED"
    RESOURCE_UPDATED = "RESOURCE_UPDATED"
    REQUIREMENT_CREATED = "REQUIREMENT_CREATED"
    REQUIREMENT_UPDATED = "REQUIREMENT_UPDATED"
    LISTING_DEACTIVATED = "LISTING_DEACTIVATED"
    MATCH_DISCOVERED = "MATCH_DISCOVERED"
    MATCH_RECALCULATED = "MATCH_RECALCULATED"
    CONNECTION_REQUESTED = "CONNECTION_REQUESTED"
    CONNECTION_ACCEPTED = "CONNECTION_ACCEPTED"
    CONNECTION_REJECTED = "CONNECTION_REJECTED"
    MESSAGE_SENT = "MESSAGE_SENT"
    EXCHANGE_CREATED = "EXCHANGE_CREATED"
    EXCHANGE_STATUS_CHANGED = "EXCHANGE_STATUS_CHANGED"
    LISTING_EXPIRED = "LISTING_EXPIRED"


@dataclass(frozen=True)
class DomainEvent:
    type: EventType
    payload: dict[str, Any] = field(default_factory=dict)


Handler = Callable[[DomainEvent], None]
_handlers: dict[EventType, list[Handler]] = defaultdict(list)


def subscribe(event_type: EventType, handler: Handler) -> None:
    if handler not in _handlers[event_type]:
        _handlers[event_type].append(handler)


def publish(event: DomainEvent) -> None:
    """Dispatch to subscribers via the job queue. Call only after commit."""
    for handler in _handlers.get(event.type, []):
        jobs.enqueue(handler, event)
