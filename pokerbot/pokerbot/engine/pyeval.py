"""Pure-Python 5-7 card evaluator, used where the eval7 C extension is not
available (in the browser through Pyodide). Same ordering as eval7: a higher
value is a stronger hand; values are only comparable with each other."""
from __future__ import annotations

from typing import Sequence

CATEGORIES = ("High Card", "Pair", "Two Pair", "Trips", "Straight", "Flush",
              "Full House", "Quads", "Straight Flush")


def _straight_high(mask: int) -> int:
    """Highest card of a straight in a 13-bit rank mask (-1 if none). Wheel = 3 (five-high)."""
    for hi in range(12, 3, -1):
        m = 0b11111 << (hi - 4)
        if mask & m == m:
            return hi
    if mask & 0b1000000001111 == 0b1000000001111:   # A-2-3-4-5
        return 3
    return -1


def _value(cat: int, kickers: Sequence[int]) -> int:
    v = cat
    for k in list(kickers)[:5] + [0] * (5 - min(5, len(kickers))):
        v = (v << 4) | k
    return v


def evaluate(cards: Sequence[int]) -> int:
    counts = [0] * 13
    suits = [[], [], [], []]
    mask = 0
    for c in cards:
        r = c >> 2
        counts[r] += 1
        suits[c & 3].append(r)
        mask |= 1 << r
    for s in suits:
        if len(s) >= 5:
            smask = 0
            for r in s:
                smask |= 1 << r
            hi = _straight_high(smask)
            if hi >= 0:
                return _value(8, [hi])
            return _value(5, sorted(s, reverse=True))
    quads, trips, pairs, singles = [], [], [], []
    for r in range(12, -1, -1):
        n = counts[r]
        if n == 4:
            quads.append(r)
        elif n == 3:
            trips.append(r)
        elif n == 2:
            pairs.append(r)
        elif n == 1:
            singles.append(r)
    if quads:
        q = quads[0]
        rest = [r for r in range(12, -1, -1) if counts[r] and r != q]
        return _value(7, [q, rest[0]])
    if trips and (len(trips) > 1 or pairs):
        t = trips[0]
        p = max(([trips[1]] if len(trips) > 1 else []) + pairs[:1])
        return _value(6, [t, p])
    hi = _straight_high(mask)
    if hi >= 0:
        return _value(4, [hi])
    if trips:
        return _value(3, [trips[0]] + singles[:2])
    if len(pairs) >= 2:
        rest = [r for r in range(12, -1, -1) if counts[r] and r not in pairs[:2]]
        return _value(2, pairs[:2] + rest[:1])
    if pairs:
        return _value(1, [pairs[0]] + singles[:3])
    return _value(0, singles[:5])


def handtype(value: int) -> str:
    return CATEGORIES[value >> 20]
