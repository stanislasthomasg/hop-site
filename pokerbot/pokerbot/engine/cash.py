"""Cash-game rules: rake structure, buy-ins, top-ups and realistic stack depths."""
from __future__ import annotations

import random
from dataclasses import dataclass, field


@dataclass(frozen=True)
class CashRules:
    sb: int = 50
    bb: int = 100
    rake_pct: float = 0.05
    # rake cap in big blinds by number of players dealt in (typical online NL structure)
    cap_bb: dict = field(default_factory=lambda: {2: 1.0, 3: 2.0, 4: 2.0, 5: 3.0, 6: 3.0})
    min_buyin_bb: float = 40.0
    max_buyin_bb: float = 100.0
    top_up_below_bb: float = 0.0   # 0 = never top up, rebuy only when broke
    rebuy_bb: float = 100.0

    def rake_cap(self, n_players: int) -> int:
        cap = self.cap_bb.get(n_players, max(self.cap_bb.values()))
        return int(cap * self.bb)

    def state_kwargs(self, n_players: int) -> dict:
        return {"sb": self.sb, "bb": self.bb, "rake_pct": self.rake_pct,
                "rake_cap": self.rake_cap(n_players)}

    def next_stack(self, stack: int) -> int:
        """Stack for the next hand: rebuy when broke, optional automatic top-up."""
        if stack <= 0:
            return int(self.rebuy_bb * self.bb)
        if self.top_up_below_bb and stack < self.top_up_below_bb * self.bb:
            return int(self.max_buyin_bb * self.bb)
        return stack


NO_RAKE = CashRules(rake_pct=0.0)


def sample_stack_bb(rng: random.Random) -> float:
    """Effective stack depths seen at real cash tables: mostly ~100 bb, with short
    stacks (fresh min buy-ins, losers) and deep stacks (winners who were not capped)."""
    r = rng.random()
    if r < 0.5:
        return 100.0
    if r < 0.75:
        return rng.uniform(40, 95)
    return rng.uniform(105, 250)
