"""Explicit lifecycle state machines.

Every status change in the domain goes through ``StateMachine.assert_transition``
so allowed transitions live in one place per entity instead of being implied
by scattered ``if`` statements.
"""

from collections.abc import Iterable, Mapping
from enum import StrEnum

from app.core.errors import InvalidStateTransitionError


class StateMachine[S: StrEnum]:
    def __init__(self, name: str, transitions: Mapping[S, Iterable[S]]):
        self.name = name
        self._transitions: dict[S, frozenset[S]] = {k: frozenset(v) for k, v in transitions.items()}

    def can_transition(self, current: S, target: S) -> bool:
        return target in self._transitions.get(current, frozenset())

    def allowed_from(self, current: S) -> frozenset[S]:
        return self._transitions.get(current, frozenset())

    def assert_transition(self, current: S, target: S) -> None:
        if not self.can_transition(current, target):
            raise InvalidStateTransitionError(
                f"A {self.name} cannot move from {current} to {target}.",
                details={"entity": self.name, "from": str(current), "to": str(target),
                         "allowed": sorted(str(s) for s in self.allowed_from(current))},
            )
