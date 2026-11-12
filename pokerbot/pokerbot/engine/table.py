"""Run a sequence of hands between agents."""
from __future__ import annotations

import random
from typing import TYPE_CHECKING, Callable, Iterator, Sequence

from .cash import CashRules
from .history import HandStore
from .records import HandRecord
from .state import HandState

if TYPE_CHECKING:  # pragma: no cover
    from ..bots.base import Agent


class Table:
    """Table: by default every hand starts with each stack reset to ``starting_stack``
    (100 bb, i.e. automatic top-up), and the button moves one seat.

    With ``cash=CashRules(...)`` it plays like a real cash game: stacks carry over
    from hand to hand, players rebuy when broke (or top up per the rules), and the
    rake is taken from each pot that sees a flop.

    ``seed`` makes the whole session reproducible; each hand also stores its own
    deck seed so it can be replayed (used later for duplicate matches).
    """

    def __init__(
        self,
        agents: Sequence["Agent"],
        sb: int = 50,
        bb: int = 100,
        starting_stack: int = 10_000,
        ante: int = 0,
        seed: int | None = None,
        store: HandStore | None = None,
        name: str = "",
        button: int = 0,
        cash: CashRules | None = None,
        buyins_bb: list[float] | None = None,
    ) -> None:
        if not 2 <= len(agents) <= 10:
            raise ValueError("2 to 10 agents")
        self.agents = list(agents)
        self.sb, self.bb, self.ante = sb, bb, ante
        self.starting_stack = starting_stack
        self.rng = random.Random(seed)
        self.store = store
        self.name = name
        self.button = button
        self.hand_no = 0
        self.names = [a.name for a in self.agents]
        self.cash = cash
        if cash is not None:
            sb, bb = cash.sb, cash.bb
            self.sb, self.bb = sb, bb
        n = len(self.agents)
        self.stacks = [int((buyins_bb[i] if buyins_bb else (cash.max_buyin_bb if cash else starting_stack / bb)) * bb)
                       for i in range(n)]
        self.buyins = [1] * n          # number of buy-ins per seat (cash mode)

    def play_hand(self, hand_seed: int | None = None,
                  hole_cards=None, board=None) -> HandRecord:
        n = len(self.agents)
        self.hand_no += 1
        if hand_seed is None:
            hand_seed = self.rng.getrandbits(63)
        if self.cash is not None:
            for i, s in enumerate(self.stacks):
                new = self.cash.next_stack(s)
                if s <= 0:
                    self.buyins[i] += 1
                self.stacks[i] = new
            stacks, extra = list(self.stacks), self.cash.state_kwargs(n)
        else:
            stacks, extra = [self.starting_stack] * n, {}
        state = HandState(
            stacks, button=self.button, sb=self.sb, bb=self.bb,
            ante=self.ante, rng=random.Random(hand_seed), hole_cards=hole_cards, board=board,
            hand_no=self.hand_no, seed=hand_seed, rake_pct=extra.get("rake_pct", 0.0),
            rake_cap=extra.get("rake_cap", 0),
        )
        for seat, agent in enumerate(self.agents):
            agent.table_names = self.names
            agent.on_hand_start(seat, state.view(seat))
        while not state.is_over:
            seat = state.to_act
            action = self.agents[seat].act(state.view(seat))
            state.apply(action)
        rec = state.to_record(self.names, table=self.name)
        if self.cash is not None:
            self.stacks = [p.stack for p in state.players]
        for seat, agent in enumerate(self.agents):
            agent.on_hand_end(seat, rec)
        if self.store is not None:
            self.store.add(rec)
        self.button = (self.button + 1) % n
        return rec

    def play(self, n_hands: int, callback: Callable[[HandRecord], None] | None = None
             ) -> Iterator[HandRecord]:
        for _ in range(n_hands):
            rec = self.play_hand()
            if callback:
                callback(rec)
            yield rec
        if self.store is not None:
            self.store.commit()

    def run(self, n_hands: int) -> list[int]:
        """Play ``n_hands`` and return total net chips per agent."""
        totals = [0] * len(self.agents)
        for rec in self.play(n_hands):
            for i, p in enumerate(rec.payoffs):
                totals[i] += p
        return totals
