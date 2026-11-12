"""Plain data records describing a finished hand (serialisable to JSON)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import IntEnum


class Street(IntEnum):
    PREFLOP = 0
    FLOP = 1
    TURN = 2
    RIVER = 3
    SHOWDOWN = 4


STREET_NAMES = ("preflop", "flop", "turn", "river", "showdown")


@dataclass(slots=True)
class ActionRecord:
    street: int
    seat: int
    kind: str      # post_ante, post_sb, post_bb, fold, check, call, bet, raise
    amount: int    # bet/raise: total street bet after acting; otherwise chips added
    added: int     # chips moved from stack to pot by this action
    all_in: bool = False


@dataclass(slots=True)
class HandRecord:
    hand_no: int
    n_players: int
    button: int
    sb: int
    bb: int
    ante: int
    names: list[str]
    positions: list[str]
    starting_stacks: list[int]
    hole_cards: list[list[int]]
    board: list[int]                       # cards actually dealt (incl. all-in run-outs)
    actions: list[ActionRecord]
    uncalled: list[tuple[int, int, int]]   # (street, seat, amount returned)
    pots: list[dict]                       # {amount, eligible, winners, shares}
    showdown: list[int]                    # seats whose cards were shown
    hand_values: dict[int, str]            # seat -> category at showdown
    payoffs: list[int]                     # net chips won/lost per seat
    final_street: int
    seed: int | None = None
    rake: int = 0
    played_at: str = ""
    table: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def total_pot(self) -> int:
        return sum(p["amount"] for p in self.pots)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["hand_values"] = {str(k): v for k, v in self.hand_values.items()}
        for p in d["pots"]:
            p["shares"] = {str(k): v for k, v in p["shares"].items()}
        return d

    @staticmethod
    def from_dict(d: dict) -> "HandRecord":
        d = dict(d)
        d["actions"] = [ActionRecord(**a) for a in d["actions"]]
        d["uncalled"] = [tuple(u) for u in d["uncalled"]]
        d["hand_values"] = {int(k): v for k, v in d["hand_values"].items()}
        d["pots"] = [
            {**p, "eligible": list(p["eligible"]), "winners": list(p["winners"]),
             "shares": {int(k): v for k, v in p["shares"].items()}}
            for p in d["pots"]
        ]
        return HandRecord(**d)
