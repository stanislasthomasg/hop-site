"""Player statistics (VPIP, PFR, 3-bet, AF, c-bet, fold to c-bet, WTSD) and
win-rate estimates with confidence intervals."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable

from ..engine.records import HandRecord

VOLUNTARY = ("call", "bet", "raise")
AGGRESSIVE = ("bet", "raise")


@dataclass
class Counter:
    hits: int = 0
    opps: int = 0

    def add(self, hit: bool) -> None:
        self.opps += 1
        self.hits += int(hit)

    @property
    def pct(self) -> float:
        return 100.0 * self.hits / self.opps if self.opps else float("nan")


@dataclass
class PlayerStats:
    name: str
    hands: int = 0
    net_bb: float = 0.0
    vpip: Counter = field(default_factory=Counter)
    pfr: Counter = field(default_factory=Counter)
    three_bet: Counter = field(default_factory=Counter)
    fold_to_3bet: Counter = field(default_factory=Counter)
    cbet: Counter = field(default_factory=Counter)
    fold_to_cbet: Counter = field(default_factory=Counter)
    wtsd: Counter = field(default_factory=Counter)
    won_at_sd: Counter = field(default_factory=Counter)
    post_aggr: int = 0
    post_calls: int = 0
    results_bb: list[float] = field(default_factory=list)

    @property
    def af(self) -> float:
        return self.post_aggr / self.post_calls if self.post_calls else float("inf") if self.post_aggr else 0.0

    @property
    def bb100(self) -> float:
        return 100.0 * self.net_bb / self.hands if self.hands else 0.0

    def as_dict(self) -> dict:
        return {
            "name": self.name, "hands": self.hands, "net_bb": round(self.net_bb, 1),
            "bb100": round(self.bb100, 2), "vpip": round(self.vpip.pct, 1),
            "pfr": round(self.pfr.pct, 1), "3bet": round(self.three_bet.pct, 1),
            "fold_to_3bet": round(self.fold_to_3bet.pct, 1), "af": round(self.af, 2),
            "cbet": round(self.cbet.pct, 1), "fold_to_cbet": round(self.fold_to_cbet.pct, 1),
            "wtsd": round(self.wtsd.pct, 1), "w$sd": round(self.won_at_sd.pct, 1),
        }


def update_stats(stats: dict[str, PlayerStats], rec: HandRecord) -> None:
    """Accumulate one hand into ``stats`` (keyed by player name)."""
    n = rec.n_players
    names = rec.names
    for s in range(n):
        st = stats.setdefault(names[s], PlayerStats(names[s]))
        st.hands += 1
        r = rec.payoffs[s] / rec.bb
        st.net_bb += r
        st.results_bb.append(r)

    pre = [a for a in rec.actions if a.street == 0 and not a.kind.startswith("post")]
    vpip, pfr = set(), set()
    raises = 0
    pf_aggressor = None
    seen_3bet_opp: set[int] = set()
    seen_f3_opp: set[int] = set()
    opener = None
    for a in pre:
        st = stats[names[a.seat]]
        if raises == 1 and a.seat not in seen_3bet_opp and a.seat != opener:
            seen_3bet_opp.add(a.seat)
            st.three_bet.add(a.kind == "raise")
        if raises == 2 and a.seat == opener and a.seat not in seen_f3_opp:
            seen_f3_opp.add(a.seat)
            st.fold_to_3bet.add(a.kind == "fold")
        if a.kind in VOLUNTARY:
            vpip.add(a.seat)
        if a.kind in AGGRESSIVE:
            pfr.add(a.seat)
            raises += 1
            pf_aggressor = a.seat
            if raises == 1:
                opener = a.seat
    for s in range(n):
        # A player who folds/checks without ever acting voluntarily still counts as a hand
        stats[names[s]].vpip.add(s in vpip)
        stats[names[s]].pfr.add(s in pfr)

    # Postflop: aggression factor, c-bet, fold to c-bet
    flop = [a for a in rec.actions if a.street == 1]
    for a in rec.actions:
        if a.street >= 1:
            st = stats[names[a.seat]]
            if a.kind in AGGRESSIVE:
                st.post_aggr += 1
            elif a.kind == "call":
                st.post_calls += 1
    if flop and pf_aggressor is not None:
        first_bet = next((i for i, a in enumerate(flop) if a.kind in AGGRESSIVE), None)
        # c-bet opportunity: aggressor acts on the flop before anyone bets
        agg_turn = next((i for i, a in enumerate(flop) if a.seat == pf_aggressor), None)
        if agg_turn is not None and (first_bet is None or first_bet >= agg_turn):
            is_cbet = first_bet == agg_turn
            stats[names[pf_aggressor]].cbet.add(is_cbet)
            if is_cbet:
                responded = set()
                for a in flop[agg_turn + 1:]:
                    if a.seat in responded or a.seat == pf_aggressor:
                        break
                    responded.add(a.seat)
                    stats[names[a.seat]].fold_to_cbet.add(a.kind == "fold")
                    if a.kind == "raise":
                        break

    # Went to showdown (among players who saw the flop)
    if rec.final_street >= 1 or rec.showdown:
        folded_pre = {a.seat for a in pre if a.kind == "fold"}
        for s in range(n):
            if s in folded_pre:
                continue
            st = stats[names[s]]
            went = s in rec.showdown
            st.wtsd.add(went)
            if went:
                st.won_at_sd.add(rec.payoffs[s] > 0)


def compute_stats(records: Iterable[HandRecord]) -> dict[str, PlayerStats]:
    stats: dict[str, PlayerStats] = {}
    for rec in records:
        update_stats(stats, rec)
    return stats


# ------------------------------------------------------------------ win rates
def mean_ci(samples: list[float], z: float = 1.96) -> tuple[float, float, float]:
    """Mean and normal-approximation confidence interval."""
    n = len(samples)
    if n == 0:
        return 0.0, float("-inf"), float("inf")
    m = sum(samples) / n
    if n == 1:
        return m, float("-inf"), float("inf")
    var = sum((x - m) ** 2 for x in samples) / (n - 1)
    half = z * math.sqrt(var / n)
    return m, m - half, m + half


def bb100_ci(results_bb: list[float], hands_per_sample: int = 1) -> tuple[float, float, float]:
    """bb/100 with 95% CI. Each sample is the net bb of ``hands_per_sample`` hands
    (2 for a heads-up duplicate pair)."""
    m, lo, hi = mean_ci(results_bb)
    k = 100.0 / hands_per_sample
    return m * k, lo * k, hi * k


def format_stats_table(stats: dict[str, PlayerStats]) -> str:
    cols = ["hands", "bb100", "vpip", "pfr", "3bet", "af", "cbet", "fold_to_cbet", "wtsd", "w$sd"]
    head = f"{'player':14s}" + "".join(f"{c:>13s}" for c in cols)
    lines = [head]
    for st in sorted(stats.values(), key=lambda s: -s.bb100):
        d = st.as_dict()
        lines.append(f"{st.name:14s}" + "".join(f"{d[c]:>13}" for c in cols))
    return "\n".join(lines)
