"""Uniformly random legal play. Used for fuzz testing and as the weakest opponent."""
from __future__ import annotations

import random

from ..engine.actions import Action
from ..engine.state import PlayerView
from .base import Agent


class RandomBot(Agent):
    def __init__(self, name: str | None = None, seed: int | None = None,
                 p_fold: float = 0.25, p_raise: float = 0.25) -> None:
        super().__init__(name)
        self.rng = random.Random(seed)
        self.p_fold, self.p_raise = p_fold, p_raise

    def act(self, view: PlayerView) -> Action:
        legal = view.legal
        r = self.rng.random()
        if r < self.p_fold and legal.can_fold:
            return Action.fold()
        if r < self.p_fold + self.p_raise and legal.can_raise:
            # Mix min-raises, pot-ish raises and shoves to hit every engine path.
            k = self.rng.random()
            if k < 0.3:
                return Action.raise_to(legal.min_raise_to)
            if k < 0.8:
                return Action.raise_to(self.rng.randint(legal.min_raise_to, legal.max_raise_to))
            return Action.raise_to(legal.max_raise_to)
        return legal.check_or_call()
