"""Hand evaluation backed by eval7 (C extension, ~2.5M 7-card evals/s).

``evaluate`` returns an int where a higher value is a stronger hand, so equal
values mean a split.
"""
from __future__ import annotations

from typing import Sequence

from .cards import DECK_SIZE, card_to_str

try:  # fast C evaluator when installed
    import eval7
    HAS_EVAL7 = True
except ImportError:  # browser (Pyodide) or minimal install: pure-Python fallback
    from . import pyeval as eval7  # type: ignore[no-redef]
    HAS_EVAL7 = False

# FAST_EVAL(list of CARD_OBJS[c]) works with either backend (hot loops use it directly)
if HAS_EVAL7:
    _EVAL7_CARDS = [eval7.Card(card_to_str(c)) for c in range(DECK_SIZE)]
else:
    _EVAL7_CARDS = list(range(DECK_SIZE))
CARD_OBJS = _EVAL7_CARDS
FAST_EVAL = eval7.evaluate


def evaluate(cards: Sequence[int]) -> int:
    """Strength of the best 5-card hand among 5 to 7 cards (higher is better)."""
    return FAST_EVAL([_EVAL7_CARDS[c] for c in cards])


def hand_category(value: int) -> str:
    """Category name such as 'Pair', 'Flush', 'Straight Flush'."""
    return eval7.handtype(value)


def describe(cards: Sequence[int]) -> str:
    return hand_category(evaluate(cards))
