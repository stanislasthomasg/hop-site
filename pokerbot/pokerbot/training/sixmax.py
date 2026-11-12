"""6-max preflop strategy by multi-player MCCFR.

Abstract game: six players at 100 bb, preflop only, standard sizes
  first raise  'o' : open to 2.5 bb (3 bb from the small blind)
  re-raise     't' : 3-bet to 3.25x the current bet
  re-re-raise  'q' : 4-bet to 2.3x the current bet
  all-in       'a'
Limping is only allowed for the small blind (complete), as in most solved
cash-game preflop strategies. When two or more players see the flop, the hand
is scored as if checked down on a randomly dealt board (equity realisation is
approximated by raw equity, a known simplification), and the rake is taken.

Seats are indexed in preflop acting order: 0 UTG, 1 HJ, 2 CO, 3 BTN, 4 SB, 5 BB.
Infoset key: "<seat>|<hand class>|<history>".
"""
from __future__ import annotations

import multiprocessing as mp
import random
import time

from ..engine.equity import class_index
from ..engine.evaluator import _EVAL7_CARDS, FAST_EVAL
from .mccfr import Tables, discount, merge, regret_matching

POSITIONS = ["UTG", "HJ", "CO", "BTN", "SB", "BB"]
N = 6
SB, BB, STACK = 50, 100, 10_000
RAKE_PCT, RAKE_CAP = 0.05, 300


class PState:
    __slots__ = ("bets", "folded", "acted", "to_act", "nraises", "history", "terminal", "cur")

    def __init__(self) -> None:
        self.bets = [0, 0, 0, 0, SB, BB]
        self.folded = [False] * N
        self.acted = [False] * N
        self.to_act = 0
        self.nraises = 0
        self.history = ""
        self.terminal = False
        self.cur = BB

    def copy(self) -> "PState":
        s = PState.__new__(PState)
        s.bets = self.bets[:]
        s.folded = self.folded[:]
        s.acted = self.acted[:]
        s.to_act = self.to_act
        s.nraises = self.nraises
        s.history = self.history
        s.terminal = self.terminal
        s.cur = self.cur
        return s

    def legal(self) -> str:
        p = self.to_act
        if self.nraises == 0:
            if p == 4:
                return "fco"            # SB: fold, complete, raise
            if p == 5:
                return "ko"             # BB after a SB limp: check or raise
            return "fo"
        acts = "fc"
        if self.bets[p] + 0 < STACK and self.cur < STACK:
            acts += {1: "ta", 2: "qa", 3: "a"}.get(self.nraises, "")
        return acts

    def raise_to(self, ch: str) -> int:
        if ch == "o":
            return 300 if self.to_act == 4 or self.to_act == 5 else 250
        if ch == "t":
            return min(STACK, int(self.cur * 3.25))
        if ch == "q":
            return min(STACK, int(self.cur * 2.3))
        return STACK

    def child(self, ch: str) -> "PState":
        s = self.copy()
        s._apply(ch)
        return s

    def _apply(self, ch: str) -> None:
        p = self.to_act
        self.history += ch
        if ch == "f":
            self.folded[p] = True
        elif ch == "c":
            self.bets[p] = self.cur
        elif ch != "k":
            target = self.raise_to(ch)
            self.bets[p] = target
            self.cur = target
            self.nraises = 4 if ch == "a" else self.nraises + 1   # after a shove: call or fold
        self.acted[p] = True
        live = [i for i in range(N) if not self.folded[i]]
        if len(live) == 1:
            self.terminal = True
            return
        for k in range(1, N + 1):
            q = (p + k) % N
            if self.folded[q] or (self.bets[q] >= STACK and self.bets[q] == self.cur):
                continue
            if not self.acted[q] or self.bets[q] < self.cur:
                self.to_act = q
                return
        self.terminal = True            # betting closed: flop (or all-in showdown)

    def utility(self, player: int, values: list[int]) -> float:
        live = [i for i in range(N) if not self.folded[i]]
        pot = sum(self.bets)
        if len(live) == 1:
            return float(pot - self.bets[player]) if live[0] == player else float(-self.bets[player])
        rake = min(RAKE_CAP, RAKE_PCT * pot)
        best = max(values[i] for i in live)
        winners = [i for i in live if values[i] == best]
        if player in winners:
            return (pot - rake) / len(winners) - self.bets[player]
        return float(-self.bets[player])


class SixMaxTrainer:
    def __init__(self, tables: Tables) -> None:
        self.t = tables
        self.touched_regret: dict = {}
        self.touched_strat: dict = {}

    def _get(self, key, acts):
        reg = self.t.regret.get(key)
        if reg is None:
            reg = [0.0] * len(acts)
            self.t.regret[key] = reg
            self.t.strat[key] = [0.0] * len(acts)
            self.t.actions[key] = acts
            self.touched_regret.setdefault(key, None)
            self.touched_strat.setdefault(key, None)
        return reg, self.t.strat[key]

    def traverse(self, s: PState, i: int, classes, values, rng) -> float:
        if s.terminal:
            return s.utility(i, values)
        p = s.to_act
        acts = s.legal()
        key = f"{p}|{classes[p]}|{s.history}"
        reg, strat = self._get(key, acts)
        sigma = regret_matching(reg)
        if p == i:
            utils = [self.traverse(s.child(a), i, classes, values, rng) for a in acts]
            node = sum(x * u for x, u in zip(sigma, utils))
            if key not in self.touched_regret:
                self.touched_regret[key] = reg[:]
            for k in range(len(acts)):
                reg[k] += utils[k] - node
            return node
        if key not in self.touched_strat:
            self.touched_strat[key] = strat[:]
        for k in range(len(acts)):
            strat[k] += sigma[k]
        x, acc = rng.random(), 0.0
        for k in range(len(acts)):
            acc += sigma[k]
            if x < acc:
                break
        return self.traverse(s.child(acts[k]), i, classes, values, rng)

    def run(self, n: int, rng: random.Random) -> None:
        E = _EVAL7_CARDS
        for _ in range(n):
            cards = rng.sample(range(52), 2 * N + 5)
            board = [E[c] for c in cards[2 * N:]]
            holes = [cards[2 * j: 2 * j + 2] for j in range(N)]
            classes = [class_index(h) for h in holes]
            values = [FAST_EVAL([E[h[0]], E[h[1]]] + board) for h in holes]
            for i in range(N):
                self.traverse(PState(), i, classes, values, rng)

    def deltas(self):
        t = self.t
        dr, ds, acts = {}, {}, {}
        for k, orig in self.touched_regret.items():
            cur = t.regret[k]
            dr[k] = cur if orig is None else [c - o for c, o in zip(cur, orig)]
            acts[k] = t.actions[k]
        for k, orig in self.touched_strat.items():
            cur = t.strat[k]
            ds[k] = cur if orig is None else [c - o for c, o in zip(cur, orig)]
            acts[k] = t.actions[k]
        return dr, ds, acts


_SHARED: dict = {}


def _worker(args):
    n, seed = args
    tr = SixMaxTrainer(_SHARED["tables"])
    tr.run(n, random.Random(seed))
    return tr.deltas()


def train_sixmax(tables: Tables, iterations: int, workers: int = 4, batch: int = 4000,
                 minutes: float | None = None, seed: int = 0, verbose: bool = True) -> Tables:
    ctx = mp.get_context("fork")
    rng = random.Random(seed + tables.iterations)
    done, t0, last = 0, time.time(), 0.0
    while done < iterations:
        per = min(batch, max(1, (iterations - done) // workers))
        _SHARED["tables"] = tables
        jobs = [(per, rng.getrandbits(62)) for _ in range(workers)]
        if workers == 1:
            results = [_worker(jobs[0])]
        else:
            with ctx.Pool(workers) as pool:
                results = pool.map(_worker, jobs)
        merge(tables, results, False)
        tables.batches += 1
        discount(tables)
        done += per * workers
        tables.iterations += per * workers
        el = time.time() - t0
        if verbose and (el - last > 30 or done >= iterations):
            last = el
            print(f"  6-max: {tables.iterations:>10,} it.  {done / el:6.0f} it/s  "
                  f"{len(tables.strat):>8,} infosets  {el / 60:5.1f} min", flush=True)
        if minutes and el > minutes * 60:
            break
    return tables


def replay(history: str) -> PState:
    s = PState()
    for ch in history:
        s._apply(ch)
    return s
