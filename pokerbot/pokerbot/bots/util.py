"""Helpers shared by rule-based bots: bet sizing and reading the action history."""
from __future__ import annotations

from ..engine.actions import Action
from ..engine.records import Street
from ..engine.state import PlayerView


def opponents_in_hand(view: PlayerView) -> int:
    return sum(1 for s, f in enumerate(view.folded) if not f and s != view.seat)


def pot_after_call(view: PlayerView) -> int:
    return view.pot + view.to_call


def pot_raise_to(view: PlayerView, frac: float) -> int:
    """Raise-to amount for a bet/raise of ``frac`` x the pot (after calling)."""
    return int(view.current_bet + frac * pot_after_call(view))


def sized_raise(view: PlayerView, frac: float) -> Action:
    return view.legal.clamp_raise(pot_raise_to(view, frac))


def preflop_raises(view: PlayerView) -> int:
    """Number of voluntary bets/raises so far preflop."""
    return sum(1 for a in view.history if a.street == 0 and a.kind in ("bet", "raise"))


def street_raises(view: PlayerView) -> int:
    return sum(1 for a in view.history if a.street == view.street and a.kind in ("bet", "raise"))


def last_aggressor(view: PlayerView, street: int) -> int | None:
    seat = None
    for a in view.history:
        if a.street == street and a.kind in ("bet", "raise"):
            seat = a.seat
    return seat


def pot_odds(view: PlayerView) -> float:
    if view.to_call <= 0:
        return 0.0
    return view.to_call / (view.pot + view.to_call)


def is_preflop(view: PlayerView) -> bool:
    return view.street == Street.PREFLOP
