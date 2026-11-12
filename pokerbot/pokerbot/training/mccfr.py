"""External-sampling Monte Carlo CFR with Linear-CFR discounting, parallelised
over processes.

Each batch, worker processes are forked from the master (copy-on-write view of
the current regret tables), run independent iterations and send back only the
changes they made. The master sums the changes, then applies the Linear CFR
discount ``t / (t + 1)`` to every regret and average-strategy entry, which
weights iteration t proportionally to t. Optionally regrets are floored at zero
(regret-matching+, as in CFR+).
"""
from __future__ import annotations

import multiprocessing as mp
import random
import time
from dataclasses import dataclass

from ..engine.evaluator import _EVAL7_CARDS, FAST_EVAL
from .abstract_game import AState
from .abstraction import CardAbstraction


@dataclass
class TrainConfig:
    iterations: int = 100_000
    batch: int = 2_000            # iterations per worker per batch
    workers: int = 4
    rm_plus: bool = False         # floor regrets at 0 (CFR+-style)
    linear: bool = True           # Linear CFR discounting between batches
    seed: int = 0


class Tables:
    """Regret and average-strategy sums: key -> list[float], plus legal actions."""

    def __init__(self) -> None:
        self.regret: dict[str, list[float]] = {}
        self.strat: dict[str, list[float]] = {}
        self.actions: dict[str, str] = {}
        self.iterations = 0
        self.batches = 0


def regret_matching(reg: list[float]) -> list[float]:
    pos = [r if r > 0 else 0.0 for r in reg]
    s = sum(pos)
    if s > 0:
        return [x / s for x in pos]
    n = len(reg)
    return [1.0 / n] * n


class Trainer:
    def __init__(self, tables: Tables, abstraction: CardAbstraction, rm_plus: bool = False) -> None:
        self.t = tables
        self.abs = abstraction
        self.rm_plus = rm_plus
        self.touched_regret: dict[str, list[float]] = {}   # key -> original values
        self.touched_strat: dict[str, list[float]] = {}

    # ------------------------------------------------------------------ deals
    def deal(self, rng: random.Random):
        cards = rng.sample(range(52), 9)
        holes = (cards[0:2], cards[2:4])
        board = cards[4:9]
        buckets = []
        for h in holes:
            buckets.append([
                self.abs.bucket(h, []),
                self.abs.bucket(h, board[:3]),
                self.abs.bucket(h, board[:4]),
                self.abs.bucket(h, board),
            ])
        E = _EVAL7_CARDS
        b = [E[c] for c in board]
        v0 = FAST_EVAL([E[c] for c in holes[0]] + b)
        v1 = FAST_EVAL([E[c] for c in holes[1]] + b)
        sign = (v0 > v1) - (v0 < v1)
        return buckets, sign

    # ------------------------------------------------------------------ traversal
    def _get(self, key: str, acts: str) -> tuple[list[float], list[float]]:
        t = self.t
        reg = t.regret.get(key)
        if reg is None:
            reg = [0.0] * len(acts)
            t.regret[key] = reg
            t.strat[key] = [0.0] * len(acts)
            t.actions[key] = acts
            self.touched_regret.setdefault(key, None)
            self.touched_strat.setdefault(key, None)
        return reg, t.strat[key]

    def traverse(self, s: AState, i: int, buckets, sign: int, rng: random.Random,
                 prefix: str = "") -> float:
        if s.terminal:
            return s.utility(i, sign)
        p = s.to_act
        acts = s.legal()
        key = f"{prefix}{buckets[p][s.street]}:{s.history}"
        reg, strat_sum = self._get(key, acts)
        sigma = regret_matching(reg)
        if p == i:
            utils = [self.traverse(s.child(a), i, buckets, sign, rng, prefix) for a in acts]
            node = sum(x * u for x, u in zip(sigma, utils))
            if key not in self.touched_regret:
                self.touched_regret[key] = reg[:]
            for k in range(len(acts)):
                r = reg[k] + utils[k] - node
                reg[k] = r if (r > 0 or not self.rm_plus) else 0.0
            return node
        if key not in self.touched_strat:
            self.touched_strat[key] = strat_sum[:]
        for k in range(len(acts)):
            strat_sum[k] += sigma[k]
        x, acc = rng.random(), 0.0
        for k, a in enumerate(acts):
            acc += sigma[k]
            if x < acc:
                break
        return self.traverse(s.child(acts[k]), i, buckets, sign, rng, prefix)

    def run(self, n: int, rng: random.Random) -> None:
        ab = self.abs
        depths = range(len(ab.depths_bb))
        for it in range(n):
            buckets, sign = self.deal(rng)
            d = rng.choices(depths, ab.depth_weights)[0] if len(ab.depths_bb) > 1 else 0
            prefix = ab.key_prefix(d)
            for i in (0, 1):
                self.traverse(ab.new_state(d), i, buckets, sign, rng, prefix)

    def deltas(self):
        """Changes since the trainer was created (for merging into the master)."""
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


# --------------------------------------------------------------------- parallel
_SHARED: dict = {}


def _worker(args):
    n, seed = args
    tables, abstraction, rm_plus = _SHARED["tables"], _SHARED["abs"], _SHARED["rm_plus"]
    tr = Trainer(tables, abstraction, rm_plus)
    tr.run(n, random.Random(seed))
    return tr.deltas()


def merge(tables: Tables, results, rm_plus: bool) -> None:
    for dr, ds, acts in results:
        for k, d in dr.items():
            reg = tables.regret.get(k)
            if reg is None:
                tables.regret[k] = list(d)
                tables.strat.setdefault(k, [0.0] * len(d))
                tables.actions[k] = acts[k]
            else:
                for j, x in enumerate(d):
                    reg[j] += x
            if rm_plus:
                r = tables.regret[k]
                for j, x in enumerate(r):
                    if x < 0:
                        r[j] = 0.0
        for k, d in ds.items():
            st = tables.strat.get(k)
            if st is None:
                tables.strat[k] = list(d)
                tables.regret.setdefault(k, [0.0] * len(d))
                tables.actions[k] = acts[k]
            else:
                for j, x in enumerate(d):
                    st[j] += x


def discount(tables: Tables) -> None:
    b = tables.batches
    f = b / (b + 1.0)
    for reg in tables.regret.values():
        for j in range(len(reg)):
            reg[j] *= f
    for st in tables.strat.values():
        for j in range(len(st)):
            st[j] *= f


def train(tables: Tables, abstraction: CardAbstraction, cfg: TrainConfig,
          progress=None, time_limit: float | None = None) -> Tables:
    """Run ``cfg.iterations`` more iterations (each = one deal traversed for both players)."""
    ctx = mp.get_context("fork")
    rng = random.Random(cfg.seed + tables.iterations)
    done, t0 = 0, time.time()
    while done < cfg.iterations:
        per = min(cfg.batch, max(1, (cfg.iterations - done) // cfg.workers))
        _SHARED.update(tables=tables, abs=abstraction, rm_plus=cfg.rm_plus)
        jobs = [(per, rng.getrandbits(62)) for _ in range(cfg.workers)]
        if cfg.workers == 1:
            results = [_worker(jobs[0])]
        else:
            with ctx.Pool(cfg.workers) as pool:
                results = pool.map(_worker, jobs)
        merge(tables, results, cfg.rm_plus)
        tables.batches += 1
        if cfg.linear:
            discount(tables)
        done += per * cfg.workers
        tables.iterations += per * cfg.workers
        if progress:
            progress(tables, done, time.time() - t0)
        if time_limit and time.time() - t0 > time_limit:
            break
    return tables


def average_strategy(tables: Tables) -> dict[str, tuple[str, tuple[float, ...], float]]:
    """Blueprint: key -> (actions, probabilities, weight) from the average strategy.
    ``weight`` (discounted visit mass) tells how well trained the infoset is."""
    out = {}
    for k, st in tables.strat.items():
        s = sum(st)
        if s <= 0:
            continue
        out[k] = (tables.actions[k], tuple(round(x / s, 4) for x in st), round(s, 2))
    return out
