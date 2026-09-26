"""Shared lifecycle for listings (Resources and Requirements).

Resources and Requirements are separate entities with different fields
(locked principle 5) but follow the same status lifecycle from the spec.
"""

from enum import StrEnum

from app.core.state_machine import StateMachine


class ListingStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    EXPIRED = "EXPIRED"
    FULFILLED = "FULFILLED"
    ARCHIVED = "ARCHIVED"


class PropertyImportance(StrEnum):
    REQUIRED = "REQUIRED"
    PREFERRED = "PREFERRED"
    OPTIONAL = "OPTIONAL"


class ValueSource(StrEnum):
    """Provenance of a technical value. Only confirmed values feed matching."""

    USER_INPUT = "USER_INPUT"
    AI_EXTRACTED = "AI_EXTRACTED"
    DOCUMENT_VERIFIED = "DOCUMENT_VERIFIED"


_S = ListingStatus
LISTING_LIFECYCLE = StateMachine[ListingStatus](
    "listing",
    {
        _S.DRAFT: [_S.ACTIVE, _S.ARCHIVED],
        _S.ACTIVE: [_S.PAUSED, _S.EXPIRED, _S.FULFILLED, _S.ARCHIVED],
        _S.PAUSED: [_S.ACTIVE, _S.EXPIRED, _S.ARCHIVED],
        _S.EXPIRED: [_S.ACTIVE, _S.ARCHIVED],      # renew with new dates
        _S.FULFILLED: [_S.ACTIVE, _S.ARCHIVED],    # relist
        _S.ARCHIVED: [],
    },
)

# Statuses from which a listing is visible to the matching engine.
MATCHABLE_STATUSES = frozenset({ListingStatus.ACTIVE})
