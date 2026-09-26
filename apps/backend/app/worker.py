"""Periodic background worker: listing expiry, expiry reminders, stale matches and connections.

    python -m app.worker            # loop forever (interval from WORKER_INTERVAL_SECONDS, default 300)
    python -m app.worker --once     # single sweep (cron-friendly)
"""

import argparse
import logging
import os
import time
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models  # noqa: F401
from app.common.listings import LISTING_LIFECYCLE, ListingStatus
from app.connections import service as connections
from app.core import events, jobs
from app.core.database import SessionLocal
from app.core.events import DomainEvent, EventType
from app.core.logging import configure_logging
from app.core.time import today_utc
from app.matching import handlers as matching_handlers
from app.matching import service as matching
from app.notifications import handlers as notification_handlers
from app.notifications.models import NotificationType
from app.notifications.service import notify_org
from app.requirements.models import Requirement
from app.resources.models import Resource

logger = logging.getLogger("symbio.worker")
REMINDER_DAYS = 7


def expire_listings(db: Session) -> int:
    today = today_utc()
    expired = 0
    targets = [(Resource, Resource.availability_end, "resource_id", NotificationType.LISTING_EXPIRED),
               (Requirement, Requirement.required_until, "requirement_id", NotificationType.LISTING_EXPIRED)]
    for model, end_column, key, note_type in targets:
        for listing in db.scalars(select(model).where(model.status.in_([ListingStatus.ACTIVE, ListingStatus.PAUSED]),
                                                      end_column.is_not(None), end_column < today)):
            LISTING_LIFECYCLE.assert_transition(listing.status, ListingStatus.EXPIRED)
            listing.status = ListingStatus.EXPIRED
            db.commit()
            events.publish(DomainEvent(EventType.LISTING_DEACTIVATED, {key: str(listing.id)}))
            notify_org(db, listing.organization_id, type=note_type, title="Listing expired",
                       body=f"“{listing.name}” has expired and no longer appears in matching. Renew it to continue.",
                       data={key: listing.id}, dedupe_key=f"expired:{listing.id}")
            expired += 1
    return expired


def send_expiry_reminders(db: Session) -> int:
    today = today_utc()
    horizon = today + timedelta(days=REMINDER_DAYS)
    sent = 0
    for model, end_column, key, note_type in (
        (Resource, Resource.availability_end, "resource_id", NotificationType.RESOURCE_EXPIRING),
        (Requirement, Requirement.required_until, "requirement_id", NotificationType.REQUIREMENT_EXPIRING),
    ):
        for listing in db.scalars(select(model).where(model.status == ListingStatus.ACTIVE,
                                                      end_column.between(today, horizon))):
            end = getattr(listing, end_column.key)
            sent += notify_org(db, listing.organization_id, type=note_type, title="Listing expiring soon",
                               body=f"“{listing.name}” expires on {end.isoformat()}.", data={key: listing.id},
                               dedupe_key=f"expiring:{listing.id}:{end.isoformat()}")
    return sent


def sweep() -> dict[str, int]:
    with SessionLocal() as db:
        result = {
            "listings_expired": expire_listings(db),
            "reminders_sent": send_expiry_reminders(db),
            "matches_expired": matching.expire_overdue_matches(db),
            "connections_expired": connections.expire_overdue(db),
        }
    logger.info("Worker sweep complete: %s", result, extra={"event": "worker_sweep"})
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="SYMBIO background worker")
    parser.add_argument("--once", action="store_true", help="run a single sweep and exit")
    args = parser.parse_args()
    configure_logging()
    matching_handlers.register()
    notification_handlers.register()
    interval = int(os.environ.get("WORKER_INTERVAL_SECONDS", "300"))
    while True:
        try:
            sweep()
        except Exception:
            logger.exception("Worker sweep failed")
        if args.once:
            jobs.shutdown()
            return
        time.sleep(interval)


if __name__ == "__main__":
    main()
