"""No-Limit Hold'em hand state machine (2 to 10 players, heads-up and 6-max).

Rules implemented
-----------------
* Blinds (and optional ante). Heads-up: the button posts the small blind, acts
  first preflop and last postflop. 3+ players: SB and BB left of the button,
  UTG opens preflop, first live player left of the button opens postflop.
* A short stack posts what it has and is all-in.
* Min-raise = size of the last *full* raise (at least one big blind).
* An all-in raise smaller than a full raise does not reopen the betting for
  players who already acted, unless the increments add up to a full raise.
* Uncalled chips are returned to the bettor at the end of each betting round.
* When at most one player can still act, the board is run out to showdown.
* Side pots, split pots and odd chips (closest to the left of the button).

All amounts are integer chips. The default unit is 1 bb = 100 chips.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

from .actions import Action, ActionType, LegalActions
from .cards import shuffled_deck
from .evaluator import evaluate, hand_category
from .pots import award_pots, compute_pots
from .records import ActionRecord, HandRecord, Street


class IllegalActionError(ValueError):
    pass


def position_names(n: int) -> list[str]:
    """Position labels by offset from the button (offset 0 = button)."""
    table = {
        2: ["BTN", "BB"],
        3: ["BTN", "SB", "BB"],
        4: ["BTN", "SB", "BB", "CO"],
        5: ["BTN", "SB", "BB", "UTG", "CO"],
        6: ["BTN", "SB", "BB", "UTG", "HJ", "CO"],
    }
    if n in table:
        return table[n]
    middle = [f"UTG+{i}" if i else "UTG" for i in range(n - 5)]
    return ["BTN", "SB", "BB"] + middle + ["HJ", "CO"]


@dataclass(slots=True)
class PlayerState:
    seat: int
    stack: int
    hole: tuple[int, int]
    street_bet: int = 0
    total_bet: int = 0
    folded: bool = False
    all_in: bool = False
    acted: bool = False  # acted voluntarily on the current street


@dataclass(frozen=True, slots=True)
class PlayerView:
    """What one seat is allowed to see when it must act."""
    seat: int
    n_players: int
    button: int
    position: str
    hole: tuple[int, int]
    board: tuple[int, ...]
    street: Street
    pot: int                       # all chips committed so far, including this street
    stacks: tuple[int, ...]
    street_bets: tuple[int, ...]
    total_bets: tuple[int, ...]
    folded: tuple[bool, ...]
    all_in: tuple[bool, ...]
    starting_stacks: tuple[int, ...]
    current_bet: int
    to_call: int
    legal: LegalActions
    history: tuple[ActionRecord, ...]
    sb: int
    bb: int


class HandState:
    """One hand of NLHE. Drive it with ``legal_actions()`` / ``apply()`` until ``is_over``."""

    def __init__(
        self,
        stacks: Sequence[int],
        button: int = 0,
        sb: int = 50,
        bb: int = 100,
        ante: int = 0,
        rng: random.Random | None = None,
        hole_cards: Sequence[Sequence[int]] | None = None,
        board: Sequence[int] | None = None,
        hand_no: int = 0,
        seed: int | None = None,
    ) -> None:
        n = len(stacks)
        if not 2 <= n <= 10:
            raise ValueError("2 to 10 players")
        if any(s <= 0 for s in stacks):
            raise ValueError("every seated player needs chips")
        if not 0 <= button < n:
            raise ValueError("button out of range")

        self.n = n
        self.button = button
        self.sb = sb
        self.bb = bb
        self.ante = ante
        self.hand_no = hand_no
        self.seed = seed
        self.starting_stacks = list(stacks)

        # --- cards ---------------------------------------------------------------
        if hole_cards is None or board is None:
            if rng is None:
                rng = random.Random(seed)
            deck = shuffled_deck(rng)
            used = set()
            if hole_cards is not None:
                used.update(c for h in hole_cards for c in h)
            if board is not None:
                used.update(board)
            deck = [c for c in deck if c not in used]
            if hole_cards is None:
                hole_cards = [deck[2 * i: 2 * i + 2] for i in range(n)]
                deck = deck[2 * n:]
            if board is None:
                board = deck[:5]
        if len(hole_cards) != n or any(len(h) != 2 for h in hole_cards) or len(board) != 5:
            raise ValueError("need 2 hole cards per player and a 5-card board")
        all_cards = [c for h in hole_cards for c in h] + list(board)
        if len(set(all_cards)) != len(all_cards):
            raise ValueError("duplicate cards")
        self._full_board = list(board)
        self.board: list[int] = []

        self.players = [PlayerState(i, s, (hole_cards[i][0], hole_cards[i][1]))
                        for i, s in enumerate(stacks)]
        labels = position_names(n)
        self.positions = [labels[(i - button) % n] for i in range(n)]

        self.street = Street.PREFLOP
        self.history: list[ActionRecord] = []
        self.uncalled: list[tuple[int, int, int]] = []
        self.current_bet = 0
        self.last_raise_size = bb
        self.to_act = -1
        self.is_over = False
        self.payoffs: list[int] | None = None
        self._pot_awards: list[dict] = []
        self._showdown: list[int] = []
        self._hand_values: dict[int, str] = {}

        # --- forced bets ---------------------------------------------------------
        if n == 2:
            self.sb_seat, self.bb_seat = button, (button + 1) % n
        else:
            self.sb_seat, self.bb_seat = (button + 1) % n, (button + 2) % n
        if ante:
            for p in self.players:
                self._post(p, ante, "post_ante", to_street=False)
        self._post(self.players[self.sb_seat], sb, "post_sb")
        self._post(self.players[self.bb_seat], bb, "post_bb")
        self.current_bet = max(p.street_bet for p in self.players)

        first = self.sb_seat if n == 2 else (self.bb_seat + 1) % n
        self._start_round(first)

    # ------------------------------------------------------------------ queries
    @property
    def pot(self) -> int:
        return sum(p.total_bet for p in self.players)

    def _others_can_respond(self, p: PlayerState) -> bool:
        return any(not q.folded and not q.all_in for q in self.players if q is not p)

    def _needs_action(self, p: PlayerState) -> bool:
        if p.folded or p.all_in:
            return False
        if p.street_bet < self.current_bet:
            return True
        return not p.acted and self._others_can_respond(p)

    def legal_actions(self) -> LegalActions:
        if self.is_over:
            raise IllegalActionError("hand is over")
        p = self.players[self.to_act]
        to_call = min(self.current_bet - p.street_bet, p.stack)
        max_to = p.street_bet + p.stack
        reopened = not p.acted or (self.current_bet - p.street_bet) >= self.last_raise_size
        can_raise = max_to > self.current_bet and reopened and self._others_can_respond(p)
        min_to = min(self.current_bet + self.last_raise_size, max_to) if can_raise else 0
        return LegalActions(
            can_fold=to_call > 0,
            can_check=to_call == 0,
            can_call=to_call > 0,
            call_amount=to_call,
            can_raise=can_raise,
            min_raise_to=min_to,
            max_raise_to=max_to if can_raise else 0,
        )

    def view(self, seat: int | None = None) -> PlayerView:
        seat = self.to_act if seat is None else seat
        p = self.players[seat]
        legal = self.legal_actions() if (not self.is_over and seat == self.to_act) else LegalActions(
            False, False, False, 0, False, 0, 0)
        return PlayerView(
            seat=seat,
            n_players=self.n,
            button=self.button,
            position=self.positions[seat],
            hole=p.hole,
            board=tuple(self.board),
            street=self.street,
            pot=self.pot,
            stacks=tuple(q.stack for q in self.players),
            street_bets=tuple(q.street_bet for q in self.players),
            total_bets=tuple(q.total_bet for q in self.players),
            folded=tuple(q.folded for q in self.players),
            all_in=tuple(q.all_in for q in self.players),
            starting_stacks=tuple(self.starting_stacks),
            current_bet=self.current_bet,
            to_call=min(self.current_bet - p.street_bet, p.stack),
            legal=legal,
            history=tuple(self.history),
            sb=self.sb,
            bb=self.bb,
        )

    # ------------------------------------------------------------------ actions
    def apply(self, action: Action) -> None:
        legal = self.legal_actions()
        if not legal.is_legal(action):
            hint = ""
            if action.type is ActionType.RAISE and legal.can_raise:
                hint = f" (relance entre {legal.min_raise_to} et {legal.max_raise_to})"
            raise IllegalActionError(f"action illégale pour le siège {self.to_act} : {action}{hint}")
        p = self.players[self.to_act]
        t = action.type
        if t is ActionType.FOLD:
            p.folded = True
            self._record(p, "fold", 0, 0)
        elif t is ActionType.CHECK:
            self._record(p, "check", 0, 0)
        elif t is ActionType.CALL:
            added = self._put(p, legal.call_amount)
            self._record(p, "call", added, added)
        else:
            target = action.amount
            kind = "bet" if self.current_bet == 0 else "raise"
            raise_size = target - self.current_bet
            added = self._put(p, target - p.street_bet)
            if raise_size >= self.last_raise_size:
                self.last_raise_size = raise_size   # full raise: reopens the action
            self.current_bet = target
            self._record(p, kind, target, added)
        p.acted = True
        self._advance()

    # ------------------------------------------------------------------ internals
    def _put(self, p: PlayerState, amount: int) -> int:
        amount = min(amount, p.stack)
        p.stack -= amount
        p.street_bet += amount
        p.total_bet += amount
        if p.stack == 0:
            p.all_in = True
        return amount

    def _post(self, p: PlayerState, amount: int, kind: str, to_street: bool = True) -> None:
        if to_street:
            added = self._put(p, amount)
        else:  # antes are dead money, they do not count toward the street bet
            added = min(amount, p.stack)
            p.stack -= added
            p.total_bet += added
            p.all_in = p.stack == 0
        self.history.append(ActionRecord(int(self.street), p.seat, kind, added, added, p.all_in))

    def _record(self, p: PlayerState, kind: str, amount: int, added: int) -> None:
        self.history.append(ActionRecord(int(self.street), p.seat, kind, amount, added, p.all_in))

    def _next_needing_action(self, start: int) -> int | None:
        for k in range(self.n):
            seat = (start + k) % self.n
            if self._needs_action(self.players[seat]):
                return seat
        return None

    def _start_round(self, first: int) -> None:
        seat = self._next_needing_action(first)
        if seat is None:
            self._end_round()
        else:
            self.to_act = seat

    def _advance(self) -> None:
        live = [p for p in self.players if not p.folded]
        if len(live) == 1:
            self._return_uncalled()
            self._finish(showdown=False)
            return
        seat = self._next_needing_action(self.to_act + 1)
        if seat is not None:
            self.to_act = seat
        else:
            self._end_round()

    def _return_uncalled(self) -> None:
        top = max(self.players, key=lambda q: q.street_bet)
        second = max((q.street_bet for q in self.players if q is not top), default=0)
        excess = top.street_bet - second
        if excess > 0:
            top.street_bet -= excess
            top.total_bet -= excess
            top.stack += excess
            if top.stack > 0:
                top.all_in = False
            self.uncalled.append((int(self.street), top.seat, excess))

    def _end_round(self) -> None:
        self._return_uncalled()
        can_act = [p for p in self.players if not p.folded and not p.all_in]
        if self.street == Street.RIVER or len(can_act) <= 1:
            self.board = list(self._full_board)
            self._finish(showdown=True)
            return
        self.street = Street(self.street + 1)
        self.board = self._full_board[: {Street.FLOP: 3, Street.TURN: 4, Street.RIVER: 5}[self.street]]
        for p in self.players:
            p.street_bet = 0
            p.acted = False
        self.current_bet = 0
        self.last_raise_size = self.bb
        self._start_round((self.button + 1) % self.n)

    def _finish(self, showdown: bool) -> None:
        live = [p for p in self.players if not p.folded]
        contributions = [p.total_bet for p in self.players]
        folded = [p.folded for p in self.players]
        pots = compute_pots(contributions, folded)
        if showdown:
            strengths = {p.seat: evaluate(list(p.hole) + self.board) for p in live}
            self._showdown = sorted(strengths)
            self._hand_values = {s: hand_category(v) for s, v in strengths.items()}
        else:
            strengths = {live[0].seat: 0}
        payouts, awards = award_pots(pots, strengths, self.button, self.n)
        for p in self.players:
            p.stack += payouts[p.seat]
        self.payoffs = [p.stack - s for p, s in zip(self.players, self.starting_stacks)]
        if sum(self.payoffs) != 0:  # chip conservation (no rake)
            raise AssertionError(f"chips not conserved: {self.payoffs}")
        self._pot_awards = [
            {"amount": a.amount, "eligible": list(pots[a.pot_index].eligible),
             "winners": list(a.winners), "shares": dict(a.shares)}
            for a in awards
        ]
        self.street = Street.SHOWDOWN if showdown else self.street
        self.to_act = -1
        self.is_over = True

    # ------------------------------------------------------------------ output
    def to_record(self, names: Sequence[str] | None = None, table: str = "") -> HandRecord:
        if not self.is_over:
            raise RuntimeError("hand not finished")
        names = list(names) if names else [f"P{i}" for i in range(self.n)]
        return HandRecord(
            hand_no=self.hand_no,
            n_players=self.n,
            button=self.button,
            sb=self.sb,
            bb=self.bb,
            ante=self.ante,
            names=names,
            positions=list(self.positions),
            starting_stacks=list(self.starting_stacks),
            hole_cards=[list(p.hole) for p in self.players],
            board=list(self.board),
            actions=list(self.history),
            uncalled=list(self.uncalled),
            pots=self._pot_awards,
            showdown=list(self._showdown),
            hand_values=dict(self._hand_values),
            payoffs=list(self.payoffs),
            final_street=int(self.street),
            seed=self.seed,
            played_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            table=table,
        )
