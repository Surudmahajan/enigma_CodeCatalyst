"""UTC time helpers. The backend stores and compares timestamps in UTC only."""

from datetime import UTC, date, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)


def today_utc() -> date:
    return utcnow().date()


def as_utc(value: datetime | None) -> datetime | None:
    """SQLite drops tzinfo; treat naive values read back from the DB as UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
