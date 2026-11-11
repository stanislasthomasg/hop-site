"""Run a sequence of hands between agents."""
from __future__ import annotations

import random
from typing import TYPE_CHECKING, Callable, Iterator, Sequence

from .history import HandStore
from .records import HandRecord
from .state import HandState

if TYPE_CHECKING:  # pragma: no cover
    from ..bots.base import Agent


class Table:
    """Cash-game table: every hand starts with each stack reset to ``starting_stack``
    (100 bb by default, i.e. automatic top-up), and the button moves one seat.

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

    def play_hand(self, hand_seed: int | None = None,
                  hole_cards=None, board=None) -> HandRecord:
        n = len(self.agents)
        self.hand_no += 1
        if hand_seed is None:
            hand_seed = self.rng.getrandbits(63)
        state = HandState(
            [self.starting_stack] * n, button=self.button, sb=self.sb, bb=self.bb,
            ante=self.ante, rng=random.Random(hand_seed), hole_cards=hole_cards, board=board,
            hand_no=self.hand_no, seed=hand_seed,
        )
        for seat, agent in enumerate(self.agents):
            agent.on_hand_start(seat, state.view(seat))
        while not state.is_over:
            seat = state.to_act
            action = self.agents[seat].act(state.view(seat))
            state.apply(action)
        rec = state.to_record(self.names, table=self.name)
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
