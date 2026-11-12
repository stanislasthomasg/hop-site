"""Compact heads-up NLHE betting tree used for MCCFR training and for translating
real hands into the abstraction.

Player 0 is the button (small blind), player 1 the big blind. Stacks are equal
(100 bb). Actions are single characters: f(old) k(check) c(all) h(1/2 pot)
p(ot) d(2x pot) a(ll-in). The history string separates streets with '/'.
"""
from __future__ import annotations

from .abstraction import BET_FRACTIONS

SB, BB, STACK = 50, 100, 10_000
MAX_RAISES = 4        # bets + raises per street
CHEAP_RAISES = 2      # after this many raises only pot and all-in remain, then all-in only


class AState:
    __slots__ = ("street", "contrib", "bets", "to_act", "nraises", "last_raise",
                 "acted", "history", "terminal", "folder", "stack")

    def __init__(self, stack: int = STACK) -> None:
        self.stack = stack
        self.street = 0
        self.contrib = [SB, BB]
        self.bets = [SB, BB]
        self.to_act = 0
        self.nraises = 0
        self.last_raise = BB
        self.acted = [False, False]
        self.history = ""
        self.terminal = False
        self.folder = -1

    def copy(self) -> "AState":
        s = AState.__new__(AState)
        s.stack = self.stack
        s.street = self.street
        s.contrib = self.contrib[:]
        s.bets = self.bets[:]
        s.to_act = self.to_act
        s.nraises = self.nraises
        s.last_raise = self.last_raise
        s.acted = self.acted[:]
        s.history = self.history
        s.terminal = self.terminal
        s.folder = self.folder
        return s

    # ---------------------------------------------------------------- queries
    @property
    def pot(self) -> int:
        return self.contrib[0] + self.contrib[1]

    def to_call(self) -> int:
        p = self.to_act
        return self.bets[1 - p] - self.bets[p]

    def raise_to(self, ch: str) -> int:
        """Street bet after raising with size ``ch`` (before legality clamping)."""
        p = self.to_act
        if ch == "a":
            return self.bets[p] + self.stack - self.contrib[p]
        tc = self.to_call()
        target = self.bets[1 - p] + int(BET_FRACTIONS[ch] * (self.pot + tc))
        return max(target, self.bets[1 - p] + self.last_raise)

    def legal(self) -> str:
        p, o = self.to_act, 1 - self.to_act
        tc = self.to_call()
        acts = "fc" if tc > 0 else "k"
        my_left = self.stack - self.contrib[p]
        if my_left > tc and self.contrib[o] < self.stack and self.nraises < MAX_RAISES:
            all_in_to = self.bets[p] + my_left
            if self.nraises < CHEAP_RAISES:
                sizes = "hpd"
            elif self.nraises < CHEAP_RAISES + 1:
                sizes = "p"
            else:
                sizes = ""
            seen = set()
            for ch in sizes:
                t = self.raise_to(ch)
                if t < all_in_to and t not in seen:
                    seen.add(t)
                    acts += ch
            acts += "a"
        return acts

    # ---------------------------------------------------------------- transitions
    def child(self, ch: str) -> "AState":
        s = self.copy()
        s._apply(ch)
        return s

    def _apply(self, ch: str) -> None:
        p, o = self.to_act, 1 - self.to_act
        self.history += ch
        if ch == "f":
            self.terminal = True
            self.folder = p
            return
        if ch == "k":
            self.acted[p] = True
        elif ch == "c":
            amt = min(self.to_call(), self.stack - self.contrib[p])
            self.bets[p] += amt
            self.contrib[p] += amt
            self.acted[p] = True
        else:
            target = self.raise_to(ch)
            target = min(target, self.bets[p] + self.stack - self.contrib[p])
            size = target - self.bets[o]
            if size > self.last_raise:
                self.last_raise = size
            self.contrib[p] += target - self.bets[p]
            self.bets[p] = target
            self.nraises += 1
            self.acted[p] = True
        if self.bets[0] == self.bets[1] and self.acted[o]:
            self._next_street()
        else:
            self.to_act = o

    def _next_street(self) -> None:
        if self.street == 3 or self.contrib[0] >= self.stack or self.contrib[1] >= self.stack:
            self.terminal = True
            return
        self.street += 1
        self.history += "/"
        self.bets = [0, 0]
        self.acted = [False, False]
        self.nraises = 0
        self.last_raise = BB
        self.to_act = 1

    def utility(self, player: int, showdown_sign: int) -> float:
        """Chips won by ``player``. ``showdown_sign``: +1 if player 0 wins, -1 if 1 wins, 0 tie."""
        if self.folder >= 0:
            # the winner collects what the folder put in; the folder loses it
            won = self.contrib[self.folder] if self.folder != player else -self.contrib[player]
            return float(won)
        v = self.contrib[1 - player] * showdown_sign  # contributions are equal at showdown
        return float(v if player == 0 else -v)


def replay(history: str, stack: int = STACK) -> AState:
    s = AState(stack)
    for ch in history:
        if ch != "/":
            s._apply(ch)
    return s
