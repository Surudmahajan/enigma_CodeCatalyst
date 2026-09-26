"""Behaviour shared by the Resource and Requirement services (no duplicated lifecycle logic)."""

from datetime import date
from decimal import Decimal
from typing import Protocol

from app.common.listings import LISTING_LIFECYCLE, ListingStatus
from app.core.errors import NotFoundError, ValidationFailedError
from app.core.time import today_utc
from app.materials.models import PropertyDataType, PropertyDefinition


class Listing(Protocol):
    status: ListingStatus


def validate_window(start: date, end: date | None, *, publishing: bool, label: str) -> None:
    if end is not None and end < start:
        raise ValidationFailedError(f"The {label} end date must be on or after the start date.", code="INVALID_DATES")
    if publishing and end is not None and end < today_utc():
        raise ValidationFailedError(f"The {label} window has already ended.", code="WINDOW_IN_PAST")


def check_value_against_definition(definition: PropertyDefinition, numeric: Decimal | None, text: str | None) -> None:
    if definition.data_type == PropertyDataType.NUMERIC:
        if numeric is None:
            raise ValidationFailedError(f"{definition.name} needs a numeric value.", code="INVALID_PROPERTY_VALUE",
                                        details={"property_key": definition.key})
        if (definition.valid_min is not None and numeric < definition.valid_min) or (
            definition.valid_max is not None and numeric > definition.valid_max
        ):
            raise ValidationFailedError(
                f"{definition.name} must be between {definition.valid_min} and {definition.valid_max}"
                f"{' ' + definition.unit if definition.unit else ''}.",
                code="PROPERTY_OUT_OF_RANGE", details={"property_key": definition.key},
            )
    elif text is None and numeric is None:
        raise ValidationFailedError(f"{definition.name} needs a value.", code="INVALID_PROPERTY_VALUE")


def transition(listing: Listing, target: ListingStatus) -> ListingStatus:
    """Apply a lifecycle transition; returns the previous status."""
    previous = listing.status
    LISTING_LIFECYCLE.assert_transition(previous, target)
    listing.status = target
    return previous


def allowed_transitions(status: ListingStatus) -> list[ListingStatus]:
    return sorted(LISTING_LIFECYCLE.allowed_from(status))


def not_found(entity: str) -> NotFoundError:
    return NotFoundError(f"The requested {entity} does not exist.", code=f"{entity.upper()}_NOT_FOUND")
