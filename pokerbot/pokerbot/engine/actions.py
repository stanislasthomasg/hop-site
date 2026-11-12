"""Actions an agent can take and the set of legal actions at a decision point.

Bets and raises share one type, ``RAISE``, whose ``amount`` is the player's
total bet on the current street after the action ("raise to"), never the
increment. A bet is simply a raise when nobody has bet yet.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class ActionType(IntEnum):
    FOLD = 0
    CHECK = 1
    CALL = 2
    RAISE = 3


@dataclass(frozen=True, slots=True)
class Action:
    type: ActionType
    amount: int = 0  # only meaningful for RAISE: total street bet after acting

    @staticmethod
    def fold() -> "Action":
        return Action(ActionType.FOLD)

    @staticmethod
    def check() -> "Action":
        return Action(ActionType.CHECK)

    @staticmethod
    def call() -> "Action":
        return Action(ActionType.CALL)

    @staticmethod
    def raise_to(amount: int) -> "Action":
        return Action(ActionType.RAISE, int(amount))

    def __str__(self) -> str:
        if self.type is ActionType.RAISE:
            return f"relance à {self.amount}"
        return {ActionType.FOLD: "se couche", ActionType.CHECK: "check",
                ActionType.CALL: "suit"}[self.type]


@dataclass(frozen=True, slots=True)
class LegalActions:
    can_fold: bool
    can_check: bool
    can_call: bool
    call_amount: int     # chips added by calling (capped at the stack: call all-in for less)
    can_raise: bool
    min_raise_to: int    # smallest legal raise-to (equals max_raise_to for a short all-in)
    max_raise_to: int    # all-in

    def is_legal(self, action: Action) -> bool:
        t = action.type
        if t is ActionType.FOLD:
            return self.can_fold
        if t is ActionType.CHECK:
            return self.can_check
        if t is ActionType.CALL:
            return self.can_call
        if t is ActionType.RAISE:
            return self.can_raise and self.min_raise_to <= action.amount <= self.max_raise_to
        return False

    # Convenience helpers for bots -------------------------------------------------
    def check_or_call(self) -> Action:
        return Action.check() if self.can_check else Action.call()

    def check_or_fold(self) -> Action:
        return Action.check() if self.can_check else Action.fold()

    def all_in(self) -> Action:
        if self.can_raise:
            return Action.raise_to(self.max_raise_to)
        return self.check_or_call()

    def clamp_raise(self, amount: int) -> Action:
        """Raise to ``amount`` clamped into the legal range; check/call if no raise is possible."""
        if not self.can_raise:
            return self.check_or_call()
        return Action.raise_to(max(self.min_raise_to, min(int(amount), self.max_raise_to)))
