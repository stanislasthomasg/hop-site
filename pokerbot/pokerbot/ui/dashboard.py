"""Dashboard data (versions, ladder evaluations, player stats, win curves) and a
self-contained HTML export."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ..engine.history import HandStore
from ..evaluation.stats import compute_stats
from ..training.registry import list_versions, models_dir, read_meta, resolve
from .session import DATA_DIR

WEB = Path(__file__).with_name("web")


def _versions() -> list[dict]:
    try:
        best = resolve("best")
    except FileNotFoundError:
        best = None
    ladder_file = models_dir() / "ladder.json"
    ladder = json.loads(ladder_file.read_text()) if ladder_file.exists() else {}
    out = []
    for v in list_versions():
        m = read_meta(v)
        lad = ladder.get(v, {})
        out.append({"version": v, "iterations": m.get("iterations"), "infosets": m.get("infosets"),
                    "created": m.get("created"), "parent": m.get("parent"),
                    "train_minutes": round(m.get("train_seconds", 0) / 60, 1),
                    "best": v == best, "level": lad.get("level"), "champion": lad.get("champion", False)})
    return out


def _evals() -> list[dict]:
    f = models_dir() / "evaluations.db"
    if not f.exists():
        return []
    con = sqlite3.connect(f)
    rows = con.execute("SELECT ts, version, level, opponent, hands, bb100, lo, hi, decision, curve "
                       "FROM evals ORDER BY rowid").fetchall()
    con.close()
    return [{"ts": r[0], "version": r[1], "level": r[2], "opponent": r[3], "hands": r[4],
             "bb100": round(r[5], 2), "lo": round(r[6], 2), "hi": round(r[7], 2),
             "decision": r[8], "curve": json.loads(r[9] or "[]")} for r in rows]


def _players(dbs: list[Path], human: str = "you") -> tuple[list[dict], list[float]]:
    records = []
    for db in dbs:
        if db.exists():
            with HandStore(db) as store:
                records.extend(store.iter_hands())
    stats = compute_stats(records)
    curve, acc = [], 0.0
    for r in records:
        if human in r.names:
            acc += r.payoffs[r.names.index(human)] / r.bb
            curve.append(round(acc, 1))
    rows = []
    for st in sorted(stats.values(), key=lambda s: -s.hands):
        d = st.as_dict()
        rows.append({k: (None if isinstance(v, float) and v != v else v) for k, v in d.items()})
    return rows, curve


def build_data(extra_dbs: list[str] | None = None) -> dict:
    dbs = [DATA_DIR / "human.db"] + [Path(p) for p in (extra_dbs or [])]
    players, human_curve = _players(dbs)
    return {"versions": _versions(), "evals": _evals(), "players": players,
            "human_curve": human_curve}


def export_html(out: str | Path, extra_dbs: list[str] | None = None) -> Path:
    """Write a single self-contained HTML file (no server needed)."""
    html = (WEB / "dashboard.html").read_text()
    css = (WEB / "style.css").read_text()
    js = (WEB / "dashboard.js").read_text()
    data = json.dumps(build_data(extra_dbs)).replace("</", "<\\/")
    html = html.replace('<link rel="stylesheet" href="/static/style.css">', f"<style>{css}</style>")
    html = html.replace('<script src="/static/dashboard.js"></script>',
                        f"<script>window.DASHBOARD_DATA = {data};</script><script>{js}</script>")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html)
    return out
