"""Hand strength helpers: Monte Carlo equity and the 169 preflop hand classes."""
from __future__ import annotations

import json
import random
from functools import lru_cache
from pathlib import Path
from typing import Sequence

from .cards import RANKS, card_rank, card_suit
from .evaluator import _EVAL7_CARDS, FAST_EVAL

_PREFLOP_FILE = Path(__file__).with_name("preflop_equity.json")


def equity_vs_random(hole: Sequence[int], board: Sequence[int], n_opponents: int = 1,
                     samples: int = 200, rng: random.Random | None = None) -> float:
    """Probability of winning (ties count half) against ``n_opponents`` random hands,
    with the rest of the board dealt at random."""
    rng = rng or random.Random()
    dead = set(hole) | set(board)
    deck = [c for c in range(52) if c not in dead]
    need_board = 5 - len(board)
    k = need_board + 2 * n_opponents
    ev = FAST_EVAL
    E = _EVAL7_CARDS
    hero = [E[c] for c in hole]
    base = [E[c] for c in board]
    total = 0.0
    for _ in range(samples):
        draw = rng.sample(deck, k)
        full = base + [E[c] for c in draw[:need_board]]
        mine = ev(hero + full)
        best_opp = 0
        for j in range(n_opponents):
            o = draw[need_board + 2 * j: need_board + 2 * j + 2]
            v = ev([E[o[0]], E[o[1]]] + full)
            if v > best_opp:
                best_opp = v
        if mine > best_opp:
            total += 1.0
        elif mine == best_opp:
            total += 0.5
    return total / samples


# ------------------------------------------------------------------ 169 classes
def hand_class(hole: Sequence[int]) -> str:
    """'AA', 'AKs', 'T9o'..."""
    a, b = hole
    ra, rb = card_rank(a), card_rank(b)
    if ra < rb:
        ra, rb = rb, ra
    if ra == rb:
        return RANKS[ra] * 2
    return RANKS[ra] + RANKS[rb] + ("s" if card_suit(a) == card_suit(b) else "o")


def all_hand_classes() -> list[str]:
    out = []
    for i in range(12, -1, -1):
        for j in range(i, -1, -1):
            if i == j:
                out.append(RANKS[i] * 2)
            else:
                out.append(RANKS[i] + RANKS[j] + "s")
                out.append(RANKS[i] + RANKS[j] + "o")
    return out


def class_combos(cls: str) -> int:
    return 6 if len(cls) == 2 else (4 if cls[2] == "s" else 12)


def class_index(hole: Sequence[int]) -> int:
    return _class_to_index()[hand_class(hole)]


@lru_cache(maxsize=1)
def _class_to_index() -> dict[str, int]:
    return {c: i for i, c in enumerate(all_hand_classes())}


@lru_cache(maxsize=1)
def preflop_equity_table() -> dict[str, list[float]]:
    """{class: [equity vs 1 random hand, vs 2, ..., vs 5]} (precomputed, see build)."""
    if not _PREFLOP_FILE.exists():
        build_preflop_table()
    return json.loads(_PREFLOP_FILE.read_text())


def preflop_equity(hole: Sequence[int], n_opponents: int = 1) -> float:
    return preflop_equity_table()[hand_class(hole)][min(max(n_opponents, 1), 5) - 1]


@lru_cache(maxsize=8)
def preflop_ranking(n_opponents: int = 1) -> list[str]:
    """Hand classes from strongest to weakest."""
    t = preflop_equity_table()
    return sorted(t, key=lambda c: -t[c][min(n_opponents, 5) - 1])


@lru_cache(maxsize=64)
def top_range(fraction: float, n_opponents: int = 1) -> frozenset[str]:
    """Best hand classes covering ``fraction`` of the 1326 combos."""
    out, combos = set(), 0
    for c in preflop_ranking(n_opponents):
        if combos >= fraction * 1326:
            break
        out.add(c)
        combos += class_combos(c)
    return frozenset(out)


def build_preflop_table(samples: int = 6000, seed: int = 1) -> None:
    from .cards import str_to_card
    rng = random.Random(seed)
    table = {}
    for cls in all_hand_classes():
        r1, r2 = cls[0], cls[1]
        if len(cls) == 2:
            hole = [str_to_card(r1 + "c"), str_to_card(r2 + "d")]
        elif cls[2] == "s":
            hole = [str_to_card(r1 + "s"), str_to_card(r2 + "s")]
        else:
            hole = [str_to_card(r1 + "s"), str_to_card(r2 + "h")]
        table[cls] = [round(equity_vs_random(hole, [], k, samples, rng), 4) for k in range(1, 6)]
    _PREFLOP_FILE.write_text(json.dumps(table, indent=0))
