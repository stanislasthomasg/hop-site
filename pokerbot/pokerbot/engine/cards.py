"""Card representation.

A card is an int in [0, 52): ``card = rank * 4 + suit`` with ranks 2..A -> 0..12
and suits c, d, h, s -> 0..3. Ints are cheap to copy, hash and store, and map
directly onto precomputed ``eval7.Card`` objects for evaluation.
"""
from __future__ import annotations

import random
from typing import Iterable, Sequence

RANKS = "23456789TJQKA"
SUITS = "cdhs"
DECK_SIZE = 52


def card_rank(card: int) -> int:
    return card >> 2


def card_suit(card: int) -> int:
    return card & 3


def card_to_str(card: int) -> str:
    return RANKS[card >> 2] + SUITS[card & 3]


def str_to_card(s: str) -> int:
    s = s.strip()
    if len(s) != 2 or s[0].upper() not in RANKS or s[1].lower() not in SUITS:
        raise ValueError(f"invalid card: {s!r}")
    return RANKS.index(s[0].upper()) * 4 + SUITS.index(s[1].lower())


def parse_cards(text: str | Iterable[str]) -> list[int]:
    """Parse ``"AsKd"``, ``"As Kd"`` or ``["As", "Kd"]`` into card ints."""
    if isinstance(text, str):
        compact = text.replace(" ", "").replace(",", "")
        if len(compact) % 2:
            raise ValueError(f"invalid card string: {text!r}")
        return [str_to_card(compact[i:i + 2]) for i in range(0, len(compact), 2)]
    return [str_to_card(c) for c in text]


def cards_to_str(cards: Sequence[int]) -> str:
    return " ".join(card_to_str(c) for c in cards)


def new_deck() -> list[int]:
    return list(range(DECK_SIZE))


def shuffled_deck(rng: random.Random) -> list[int]:
    deck = new_deck()
    rng.shuffle(deck)
    return deck
