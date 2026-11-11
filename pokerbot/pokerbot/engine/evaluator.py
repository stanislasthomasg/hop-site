"""Hand evaluation backed by eval7 (C extension, ~2.5M 7-card evals/s).

``evaluate`` returns an int where a higher value is a stronger hand, so equal
values mean a split.
"""
from __future__ import annotations

from typing import Sequence

import eval7

from .cards import DECK_SIZE, card_to_str

_EVAL7_CARDS = [eval7.Card(card_to_str(c)) for c in range(DECK_SIZE)]


def to_eval7(cards: Sequence[int]) -> list:
    return [_EVAL7_CARDS[c] for c in cards]


def evaluate(cards: Sequence[int]) -> int:
    """Strength of the best 5-card hand among 5 to 7 cards (higher is better)."""
    return eval7.evaluate([_EVAL7_CARDS[c] for c in cards])


def hand_category(value: int) -> str:
    """Category name such as 'Pair', 'Flush', 'Straight Flush'."""
    return eval7.handtype(value)


def describe(cards: Sequence[int]) -> str:
    return hand_category(evaluate(cards))
