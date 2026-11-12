"""Duplicate matches: every deal is replayed with the seats rotated, so each
agent plays every seat's cards from every position. Luck of the cards cancels
out and the win rate converges much faster than in normal play.

Heads-up, a "pair" is 2 hands (same cards, agents swapped). The sample used
for statistics is the agent's net bb over the whole pair.
"""
from __future__ import annotations

import multiprocessing as mp
import random
from dataclasses import dataclass, field

from ..bots.registry import make_agent
from ..engine.state import HandState
from .stats import bb100_ci

SB, BB, STACK = 50, 100, 10_000


@dataclass
class MatchResult:
    specs: list[str]
    deals: int
    hands: int
    samples: list[list[float]]           # per agent: net bb per deal (all rotations)
    fallback_rate: dict[str, float] = field(default_factory=dict)

    def bb100(self, i: int = 0) -> tuple[float, float, float]:
        """bb/100 for agent i with 95% CI (each sample covers n hands)."""
        n = len(self.specs)
        return bb100_ci(self.samples[i], hands_per_sample=n)

    def summary(self) -> str:
        lines = [f"{self.hands:,} hands ({self.deals:,} deals x {len(self.specs)} rotations)"]
        for i, s in enumerate(self.specs):
            m, lo, hi = self.bb100(i)
            lines.append(f"  {s:24s} {m:+8.1f} bb/100   95% CI [{lo:+.1f}, {hi:+.1f}]")
        return "\n".join(lines)


def _names(specs: list[str]) -> list[str]:
    names, seen = [], {}
    for s in specs:
        seen[s] = seen.get(s, 0) + 1
        names.append(s if seen[s] == 1 else f"{s}#{seen[s]}")
    return names


def _play(agents, names, holes, board, button) -> list[int]:
    st = HandState([STACK] * len(agents), button=button, sb=SB, bb=BB,
                   hole_cards=holes, board=board)
    for seat, a in enumerate(agents):
        a.table_names = names
        a.on_hand_start(seat, st.view(seat))
    while not st.is_over:
        st.apply(agents[st.to_act].act(st.view(st.to_act)))
    rec = st.to_record(names)
    for seat, a in enumerate(agents):
        a.on_hand_end(seat, rec)
    return st.payoffs


def _run_chunk(args):
    specs, seeds, agent_seed = args
    n = len(specs)
    names = _names(specs)
    agents = [make_agent(s, name=nm, seed=agent_seed + i) for i, (s, nm) in enumerate(zip(specs, names))]
    out = [[] for _ in range(n)]
    for seed in seeds:
        rng = random.Random(seed)
        deck = rng.sample(range(52), 2 * n + 5)
        holes = [deck[2 * i: 2 * i + 2] for i in range(n)]
        board = deck[2 * n:]
        button = seed % n
        totals = [0] * n
        for r in range(n):
            # agent i sits in seat (i + r) % n
            seating = [None] * n
            for i in range(n):
                seating[(i + r) % n] = i
            pay = _play([agents[i] for i in seating], [names[i] for i in seating],
                        holes, board, button)
            for seat, i in enumerate(seating):
                totals[i] += pay[seat]
        for i in range(n):
            out[i].append(totals[i] / BB)
    fb = {}
    for a, nm in zip(agents, names):
        st = getattr(a, "stats", None)
        if st and (st["blueprint"] + st["fallback"]):
            fb[nm] = st["fallback"] / (st["blueprint"] + st["fallback"])
    return out, fb


def duplicate_match(specs: list[str], deals: int, seed: int = 0, workers: int = 4) -> MatchResult:
    """Play ``deals`` duplicate deals between agents built from ``specs``."""
    rng = random.Random(seed)
    seeds = [rng.getrandbits(60) for _ in range(deals)]
    workers = max(1, min(workers, deals))
    chunks = [(specs, seeds[i::workers], seed * 1000 + i) for i in range(workers)]
    if workers == 1:
        results = [_run_chunk(chunks[0])]
    else:
        with mp.get_context("fork").Pool(workers) as pool:
            results = pool.map(_run_chunk, chunks)
    samples = [[] for _ in specs]
    fbs: dict[str, list[float]] = {}
    for out, fb in results:
        for i in range(len(specs)):
            samples[i].extend(out[i])
        for k, v in fb.items():
            fbs.setdefault(k, []).append(v)
    return MatchResult(list(specs), deals, deals * len(specs), samples,
                       {k: sum(v) / len(v) for k, v in fbs.items()})
