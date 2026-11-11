"""Main pot / side pot construction and distribution."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence


@dataclass(slots=True)
class Pot:
    amount: int
    eligible: tuple[int, ...]  # seats that can win this pot


@dataclass(slots=True)
class PotAward:
    pot_index: int
    amount: int
    winners: tuple[int, ...]
    shares: dict[int, int] = field(default_factory=dict)


def compute_pots(contributions: Sequence[int], folded: Sequence[bool]) -> list[Pot]:
    """Split total contributions into a main pot and side pots.

    Each distinct contribution level of a live (non-folded) player closes a layer.
    Folded players' chips are dead money: they fill the layers they reached but
    the player is never eligible. Adjacent layers with the same eligible set are
    merged, so a hand without all-ins always produces exactly one pot.
    """
    levels = sorted({c for c, f in zip(contributions, folded) if c > 0 and not f})
    pots: list[Pot] = []
    prev = 0
    for level in levels:
        amount = sum(min(c, level) - min(c, prev) for c in contributions)
        eligible = tuple(i for i, c in enumerate(contributions) if c >= level and not folded[i])
        if pots and pots[-1].eligible == eligible:
            pots[-1].amount += amount
        else:
            pots.append(Pot(amount, eligible))
        prev = level
    # Dead chips above the highest live contribution (cannot normally happen,
    # since uncalled bets are returned) go into the last pot.
    leftover = sum(max(0, c - prev) for c in contributions)
    if leftover:
        if not pots:
            raise ValueError("chips in the pot but no live player")
        pots[-1].amount += leftover
    return pots


def award_pots(
    pots: Sequence[Pot],
    strengths: Mapping[int, int],
    button: int,
    n_seats: int,
) -> tuple[list[int], list[PotAward]]:
    """Give each pot to its best eligible hand(s).

    ``strengths`` maps seat -> hand value (higher wins). Split pots are shared
    equally; odd chips go one by one to the winners closest to the left of the
    button.
    """
    payouts = [0] * n_seats
    awards: list[PotAward] = []
    for idx, pot in enumerate(pots):
        best = max(strengths[s] for s in pot.eligible)
        winners = sorted(
            (s for s in pot.eligible if strengths[s] == best),
            key=lambda s: (s - button - 1) % n_seats,
        )
        share, remainder = divmod(pot.amount, len(winners))
        shares = {}
        for i, s in enumerate(winners):
            won = share + (1 if i < remainder else 0)
            payouts[s] += won
            shares[s] = won
        awards.append(PotAward(idx, pot.amount, tuple(winners), shares))
    return payouts, awards
