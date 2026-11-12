"""Card and bet abstraction shared by training (MCCFR) and play (LearnerBot).

Cards
  * preflop: the 169 strategically distinct classes (exact),
  * flop/turn/river: equity vs a random hand, cut into equal-population buckets
    (thresholds measured on random deals, stored with each model version).
  Equity is estimated by Monte Carlo with an RNG seeded by the cards themselves,
  so the same cards always fall in the same bucket.

Bets: fractions of the pot (after calling): 1/2 pot, pot, 2x pot, plus all-in.
"""
from __future__ import annotations

import bisect
import random
from dataclasses import dataclass, field

from ..engine.equity import class_index, equity_vs_random

BET_FRACTIONS = {"h": 0.5, "p": 1.0, "d": 2.0}   # 'a' = all-in
RAISE_CHARS = "hpda"


def _cards_seed(hole, board) -> int:
    x = 0
    for c in sorted(hole):
        x = x * 53 + c + 1
    for c in sorted(board):
        x = x * 53 + c + 1
    return x


@dataclass
class CardAbstraction:
    buckets: tuple[int, int, int] = (12, 10, 8)        # flop, turn, river
    samples: int = 96                                  # Monte Carlo rollouts per equity
    thresholds: list[list[float]] = field(default_factory=list)
    cheap_raises: int = 2      # raises per street before only pot / all-in remain
    max_raises: int = 4        # bets + raises per street

    def equity(self, hole, board) -> float:
        return equity_vs_random(hole, board, 1, self.samples, random.Random(_cards_seed(hole, board)))

    def bucket(self, hole, board) -> int:
        if not board:
            return class_index(hole)
        street = {3: 0, 4: 1, 5: 2}[len(board)]
        return bisect.bisect_right(self.thresholds[street], self.equity(hole, board))

    def fit(self, n_deals: int = 3000, seed: int = 0) -> "CardAbstraction":
        """Measure equal-population equity thresholds on random deals."""
        rng = random.Random(seed)
        self.thresholds = []
        for street, n_board in enumerate((3, 4, 5)):
            values = []
            for _ in range(n_deals):
                cards = rng.sample(range(52), 2 + n_board)
                values.append(self.equity(cards[:2], cards[2:]))
            values.sort()
            k = self.buckets[street]
            self.thresholds.append([values[int(len(values) * i / k)] for i in range(1, k)])
        return self

    def to_dict(self) -> dict:
        return {"buckets": list(self.buckets), "samples": self.samples, "thresholds": self.thresholds,
                "cheap_raises": self.cheap_raises, "max_raises": self.max_raises}

    @staticmethod
    def from_dict(d: dict) -> "CardAbstraction":
        return CardAbstraction(tuple(d["buckets"]), d["samples"], d["thresholds"],
                               d.get("cheap_raises", 2), d.get("max_raises", 4))

    def new_state(self):
        from .abstract_game import STACK, AState
        return AState(STACK, self.cheap_raises, self.max_raises)
