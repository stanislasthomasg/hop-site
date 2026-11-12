"""Simple 'low stakes' opponent profiles.

Each profile is a small rule set on top of two numbers: the preflop hand class
(ranked by equity vs random hands) and the postflop equity vs random hands
(Monte Carlo). They are deliberately exploitable, each in its own way.
"""
from __future__ import annotations

import random

from ..engine.actions import Action
from ..engine.equity import equity_vs_random, hand_class, top_range
from ..engine.state import PlayerView
from .base import Agent
from .util import (is_preflop, last_aggressor, opponents_in_hand, pot_odds,
                   preflop_raises, sized_raise, street_raises)


class RuleBot(Agent):
    """Base class: provides cached equity and preflop range tests."""

    samples = 150

    def __init__(self, name: str | None = None, seed: int | None = None) -> None:
        super().__init__(name)
        self.rng = random.Random(seed)
        self._eq_key = None
        self._eq = 0.0

    def equity(self, view: PlayerView) -> float:
        key = (view.hole, view.board, opponents_in_hand(view))
        if key != self._eq_key:
            self._eq_key = key
            self._eq = equity_vs_random(view.hole, view.board, max(1, min(key[2], 5)),
                                        self.samples, self.rng)
        return self._eq

    @staticmethod
    def in_range(view: PlayerView, fraction: float) -> bool:
        return hand_class(view.hole) in top_range(fraction)

    def open_size(self, view: PlayerView, bb_mult: float = 2.5) -> Action:
        return view.legal.clamp_raise(int(bb_mult * view.bb))

    def reraise_size(self, view: PlayerView, mult: float = 3.0) -> Action:
        return view.legal.clamp_raise(int(view.current_bet * mult))

    def call_or_fold(self, view: PlayerView, ok: bool) -> Action:
        if view.legal.can_check:
            return Action.check()
        return Action.call() if ok else Action.fold()


class CallingStation(RuleBot):
    """Plays most hands, almost never raises, calls down light."""

    def act(self, view: PlayerView) -> Action:
        legal = view.legal
        if is_preflop(view):
            if self.in_range(view, 0.03) and legal.can_raise and preflop_raises(view) < 2:
                return self.reraise_size(view) if preflop_raises(view) else self.open_size(view)
            return self.call_or_fold(view, self.in_range(view, 0.55) or (view.to_call <= view.bb and self.in_range(view, 0.8)))
        eq = self.equity(view)
        if eq > 0.85 and legal.can_raise and self.rng.random() < 0.5:
            return sized_raise(view, 0.5)
        return self.call_or_fold(view, eq > 0.28 or view.to_call <= view.pot * 0.25)


class Nit(RuleBot):
    """Very tight: few hands, gives up easily, only bets strong hands."""

    def act(self, view: PlayerView) -> Action:
        legal = view.legal
        raises = preflop_raises(view)
        if is_preflop(view):
            if raises == 0:
                if self.in_range(view, 0.09) and legal.can_raise:
                    return self.open_size(view, 3)
                return legal.check_or_fold()
            if self.in_range(view, 0.025) and legal.can_raise:
                return self.reraise_size(view)
            return self.call_or_fold(view, self.in_range(view, 0.07 if raises == 1 else 0.03))
        eq = self.equity(view)
        if eq > 0.8 and legal.can_raise:
            return sized_raise(view, 0.6)
        if view.legal.can_check:
            return Action.check()
        return Action.call() if eq > max(0.62, pot_odds(view) + 0.2) else Action.fold()


class Maniac(RuleBot):
    """Hyper-aggressive: raises a wide range, bets and bluffs constantly, big sizes."""

    def act(self, view: PlayerView) -> Action:
        legal = view.legal
        r = self.rng.random()
        if is_preflop(view):
            if self.in_range(view, 0.6) and legal.can_raise and r < 0.8:
                return self.reraise_size(view, 3.5) if preflop_raises(view) else self.open_size(view, 3.5)
            return self.call_or_fold(view, self.in_range(view, 0.75))
        eq = self.equity(view)
        if legal.can_raise and street_raises(view) < 3 and (r < 0.55 or eq > 0.7):
            return sized_raise(view, self.rng.choice((0.75, 1.0, 1.5)))
        return self.call_or_fold(view, eq > 0.35 or r < 0.3)


# 6-max opening ranges by position (fraction of hands); HU button opens wide.
ABC_OPEN = {"UTG": 0.15, "HJ": 0.19, "CO": 0.27, "BTN": 0.45, "SB": 0.38, "BB": 0.0}
ABC_OPEN_HU = 0.75


class ABC(RuleBot):
    """Solid 'ABC' poker: positional opening ranges, 3-bets value, c-bets, value bets,
    calls with pot odds, rarely bluffs."""

    def __init__(self, name: str | None = None, seed: int | None = None,
                 tightness: float = 1.0) -> None:
        super().__init__(name, seed)
        self.tightness = tightness

    def act(self, view: PlayerView) -> Action:
        return self._preflop(view) if is_preflop(view) else self._postflop(view)

    def _preflop(self, view: PlayerView) -> Action:
        legal = view.legal
        raises = preflop_raises(view)
        t = self.tightness
        if raises == 0:
            if view.n_players == 2:
                frac = ABC_OPEN_HU if view.position == "BTN" else 0.0
            else:
                frac = ABC_OPEN.get(view.position, 0.15)
            if view.position == "BB" or (view.n_players == 2 and view.position == "BB"):
                # unopened pot reaching the BB: raise strong hands, otherwise check
                if self.in_range(view, 0.15 * t) and legal.can_raise:
                    return view.legal.clamp_raise(4 * view.bb)
                return legal.check_or_call()
            if frac and self.in_range(view, frac * t) and legal.can_raise:
                return self.open_size(view, 2.5 if view.n_players > 2 else 2.2)
            return legal.check_or_fold()
        if raises == 1:
            if self.in_range(view, 0.05 * t) and legal.can_raise:
                return self.reraise_size(view, 3.2)
            wide = 0.30 if view.n_players == 2 else 0.14
            return self.call_or_fold(view, self.in_range(view, wide * t))
        if raises == 2:
            if self.in_range(view, 0.02) and legal.can_raise:
                return legal.all_in() if view.current_bet * 2.5 > view.stacks[view.seat] * 0.4 \
                    else self.reraise_size(view, 2.3)
            return self.call_or_fold(view, self.in_range(view, 0.04))
        return self.call_or_fold(view, self.in_range(view, 0.02))

    def _postflop(self, view: PlayerView) -> Action:
        legal = view.legal
        eq = self.equity(view)
        aggressor = last_aggressor(view, 0) == view.seat
        if legal.can_check:
            if eq > 0.72 and legal.can_raise:
                return sized_raise(view, 0.66)
            if eq > 0.55 and legal.can_raise and self.rng.random() < 0.5:
                return sized_raise(view, 0.5)
            if (aggressor and view.street == 1 and opponents_in_hand(view) == 1
                    and legal.can_raise and self.rng.random() < 0.6):
                return sized_raise(view, 0.5)          # continuation bet
            return Action.check()
        if eq > 0.82 and legal.can_raise and street_raises(view) < 3:
            return sized_raise(view, 0.8)
        return Action.call() if eq > pot_odds(view) + 0.08 else Action.fold()

