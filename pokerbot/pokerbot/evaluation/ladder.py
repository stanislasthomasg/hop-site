"""Level ladder: a bot version climbs from weak opponents to its own best
versions, one level at a time, and only on statistically solid evidence.

Promotion: lower bound of the 95% CI of its bb/100 (duplicate) > 0 over at
least ``min_hands`` hands at the level. Demotion: upper bound < 0. Otherwise it
stays and needs more hands.
"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass

from ..training.registry import list_versions, models_dir, resolve, set_best
from .duplicate import duplicate_match
from .stats import bb100_ci

LEVELS = {
    1: ("Low stakes : bots simples", ["random", "station", "nit", "maniac"]),
    2: ("Mid stakes : profils solides", ["abc", "abc:tightness=0.7", "abc:tightness=1.4"]),
    3: ("High stakes : anciennes versions du bot", []),
    4: ("Élite : meilleure version actuelle", []),
}
MAX_LEVEL = 4


def level_opponents(level: int, version: str) -> list[str]:
    if level in (1, 2):
        return list(LEVELS[level][1])
    vs = list_versions()
    best = resolve("best")
    if level == 3:  # older versions (the current best is faced at level 4)
        older = [v for v in vs if int(v[5:]) < int(version[5:]) and v != best]
        return [f"bot:{v}" for v in older[-3:]]
    if best != version:
        return [f"bot:{best}"]
    others = [v for v in vs if v != version]
    return [f"bot:{others[-1]}"] if others else []


def _db() -> sqlite3.Connection:
    con = sqlite3.connect(models_dir() / "evaluations.db")
    con.execute("""CREATE TABLE IF NOT EXISTS evals (
        ts TEXT, version TEXT, level INTEGER, opponent TEXT, deals INTEGER, hands INTEGER,
        bb100 REAL, lo REAL, hi REAL, decision TEXT, curve TEXT)""")
    return con


def _curve(samples: list[float], points: int = 300) -> list[float]:
    cum, out, acc = [], [], 0.0
    for x in samples:
        acc += x
        cum.append(acc)
    step = max(1, len(cum) // points)
    out = [round(cum[i], 1) for i in range(0, len(cum), step)]
    if cum and out[-1] != round(cum[-1], 1):
        out.append(round(cum[-1], 1))
    return out


def _state() -> dict:
    f = models_dir() / "ladder.json"
    return json.loads(f.read_text()) if f.exists() else {}


def _save_state(st: dict) -> None:
    (models_dir() / "ladder.json").write_text(json.dumps(st, indent=2))


def current_level(version: str) -> int:
    return _state().get(resolve(version), {}).get("level", 1)


@dataclass
class LevelResult:
    level: int
    bb100: float
    lo: float
    hi: float
    hands: int
    decision: str
    per_opponent: list[tuple[str, float, float, float]]


def evaluate_level(version: str, level: int, hands: int, workers: int = 4, seed: int = 0,
                   verbose: bool = True) -> LevelResult | None:
    opps = level_opponents(level, version)
    if not opps:
        return None
    deals = max(1, -(-hands // (2 * len(opps))))   # round up: never fall short of `hands`
    all_samples, per = [], []
    con = _db()
    for k, opp in enumerate(opps):
        res = duplicate_match([f"bot:{version}", opp], deals, seed=seed + 7919 * level + k, workers=workers)
        m, lo, hi = res.bb100(0)
        per.append((opp, m, lo, hi))
        all_samples.extend(res.samples[0])
        if verbose:
            fb = next(iter(res.fallback_rate.values()), 0.0)
            print(f"    vs {opp:22s} {m:+8.1f} bb/100  [{lo:+.1f}, {hi:+.1f}]  "
                  f"({res.hands:,} mains, décisions hors stratégie CFR {100 * fb:.0f} %)", flush=True)
        con.execute("INSERT INTO evals VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (time.strftime("%Y-%m-%d %H:%M:%S"), version, level, opp, deals, res.hands,
                     m, lo, hi, "", json.dumps(_curve(res.samples[0]))))
    con.commit()
    m, lo, hi = bb100_ci(all_samples, hands_per_sample=2)
    total = 2 * len(all_samples)
    decision = "promote" if lo > 0 else ("demote" if hi < 0 else "stay")
    con.execute("INSERT INTO evals VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (time.strftime("%Y-%m-%d %H:%M:%S"), version, level, "ALL", total // 2, total,
                 m, lo, hi, decision, json.dumps(_curve(all_samples))))
    con.commit()
    con.close()
    return LevelResult(level, m, lo, hi, total, decision, per)


def climb(version: str, hands: int = 50_000, workers: int = 4, verbose: bool = True,
          min_hands: int = 50_000) -> list[LevelResult]:
    """Evaluate ``version`` at its current level and move it up/down as earned.
    Keeps climbing while it keeps getting promoted."""
    version = resolve(version)
    st = _state()
    entry = st.setdefault(version, {"level": 1, "history": []})
    results = []
    while True:
        level = entry["level"]
        if verbose:
            print(f"[{version}] niveau {level} : {LEVELS[level][0]}", flush=True)
        r = evaluate_level(version, level, hands, workers, verbose=verbose)
        if r is None:
            if verbose:
                print("    (pas encore d'adversaire à ce niveau : niveau sauté)")
            if level >= MAX_LEVEL:
                entry["champion"] = True
                break
            entry["level"] = level + 1
            continue
        if r.decision == "promote" and r.hands < min_hands:
            r.decision = "stay"
        results.append(r)
        entry["history"].append({"level": level, "bb100": round(r.bb100, 2), "lo": round(r.lo, 2),
                                 "hi": round(r.hi, 2), "hands": r.hands, "decision": r.decision,
                                 "ts": time.strftime("%Y-%m-%d %H:%M:%S")})
        if verbose:
            word = {"promote": "MONTE", "demote": "DESCEND", "stay": "RESTE"}[r.decision]
            print(f"  => niveau {level} : {r.bb100:+.1f} bb/100 [{r.lo:+.1f}, {r.hi:+.1f}] "
                  f"sur {r.hands:,} mains -> {word}", flush=True)
        if r.decision == "promote":
            if level >= MAX_LEVEL:
                entry["champion"] = True
                if resolve("best") != version:
                    set_best(version)
                    if verbose:
                        print(f"  {version} a battu la meilleure version : c'est la nouvelle meilleure")
                break
            entry["level"] = level + 1
            continue
        if r.decision == "demote" and level > 1:
            entry["level"] = level - 1
            entry.pop("champion", None)
        break
    _save_state(st)
    return results
