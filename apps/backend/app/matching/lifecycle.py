from app.core.state_machine import StateMachine
from app.matching.models import MatchStatus

_S = MatchStatus

MATCH_LIFECYCLE = StateMachine[MatchStatus](
    "match",
    {
        _S.DISCOVERED: [_S.VIEWED, _S.INTERESTED, _S.CONNECTION_REQUESTED, _S.REJECTED, _S.EXPIRED, _S.CANCELLED],
        _S.VIEWED: [_S.INTERESTED, _S.CONNECTION_REQUESTED, _S.REJECTED, _S.EXPIRED, _S.CANCELLED],
        _S.INTERESTED: [_S.CONNECTION_REQUESTED, _S.REJECTED, _S.EXPIRED, _S.CANCELLED],
        _S.CONNECTION_REQUESTED: [_S.CONNECTED, _S.REJECTED, _S.EXPIRED, _S.CANCELLED, _S.INTERESTED],
        _S.CONNECTED: [_S.NEGOTIATING, _S.ACTIVE_EXCHANGE, _S.CANCELLED],
        _S.NEGOTIATING: [_S.ACTIVE_EXCHANGE, _S.CANCELLED],
        _S.ACTIVE_EXCHANGE: [_S.COMPLETED, _S.NEGOTIATING, _S.CANCELLED],
        _S.EXPIRED: [_S.DISCOVERED],  # re-surfaced when a re-evaluation finds it viable again
        _S.REJECTED: [],
        _S.COMPLETED: [],
        _S.CANCELLED: [],
    },
)

# Opportunities not yet backed by a connection: these go stale automatically.
EARLY_STATES = frozenset({_S.DISCOVERED, _S.VIEWED, _S.INTERESTED, _S.CONNECTION_REQUESTED})
# States in which the two organizations are connected and may see private details.
CONNECTED_STATES = frozenset({_S.CONNECTED, _S.NEGOTIATING, _S.ACTIVE_EXCHANGE, _S.COMPLETED})
CLOSED_STATES = frozenset({_S.REJECTED, _S.EXPIRED, _S.CANCELLED, _S.COMPLETED})
