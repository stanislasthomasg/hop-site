"""Versioned models: models/bot_v1, bot_v2, ... with a pointer to the best one.

Each version directory holds:
  blueprint.pkl.gz   average strategy used for play   {key: (actions, probs)}
  tables.pkl.gz      regret / strategy sums to resume training
  abstraction.json   card abstraction (bucket thresholds)
  meta.json          parent version, iterations, timings, evaluation results
"""
from __future__ import annotations

import gzip
import json
import os
import pickle
import re
import time
from pathlib import Path

from .abstraction import CardAbstraction
from .mccfr import Tables, average_strategy

PROJECT_ROOT = Path(__file__).resolve().parents[2]


PRETRAINED = Path(__file__).resolve().parents[1] / "pretrained"


def models_dir() -> Path:
    d = Path(os.environ.get("POKERBOT_MODELS", PROJECT_ROOT / "models"))
    d.mkdir(parents=True, exist_ok=True)
    install_pretrained(d)
    return d


def install_pretrained(d: Path) -> None:
    """First run: copy the pre-trained versions shipped with the code, so the bot is
    playable without training. They cannot be resumed (no regret tables)."""
    if not PRETRAINED.exists() or any(p.name.startswith("bot_v") for p in d.iterdir()):
        return
    import shutil
    for v in PRETRAINED.iterdir():
        if v.is_dir() and not (d / v.name).exists():
            shutil.copytree(v, d / v.name)
    if not (d / "best.txt").exists():
        names = sorted((p.name for p in PRETRAINED.iterdir() if p.is_dir()), key=lambda n: int(n[5:]))
        if names:
            (d / "best.txt").write_text(names[-1])


def list_versions() -> list[str]:
    vs = [p.name for p in models_dir().iterdir() if re.fullmatch(r"bot_v\d+", p.name)]
    return sorted(vs, key=lambda v: int(v[5:]))


def resolve(version: str) -> str:
    """'best', 'latest', 'v3', '3' or 'bot_v3' -> 'bot_v3'."""
    version = version.strip()
    if version in ("best", ""):
        f = models_dir() / "best.txt"
        if f.exists():
            return f.read_text().strip()
        version = "latest"
    if version == "latest":
        vs = list_versions()
        if not vs:
            raise FileNotFoundError("no trained model yet: run `python -m pokerbot train`")
        return vs[-1]
    m = re.fullmatch(r"(?:bot_)?v?(\d+)", version)
    if not m:
        raise ValueError(f"bad version: {version!r}")
    name = f"bot_v{m.group(1)}"
    if not (models_dir() / name).exists():
        raise FileNotFoundError(name)
    return name


def set_best(version: str) -> str:
    name = resolve(version)
    (models_dir() / "best.txt").write_text(name)
    return name


def next_version() -> str:
    vs = list_versions()
    return f"bot_v{int(vs[-1][5:]) + 1 if vs else 1}"


def _dump(obj, path: Path) -> None:
    with gzip.open(path, "wb", compresslevel=3) as f:
        pickle.dump(obj, f, protocol=pickle.HIGHEST_PROTOCOL)


def _load(path: Path):
    with gzip.open(path, "rb") as f:
        return pickle.load(f)


def save_version(tables: Tables, abstraction: CardAbstraction, meta: dict,
                 name: str | None = None) -> str:
    name = name or next_version()
    d = models_dir() / name
    d.mkdir(parents=True, exist_ok=True)
    _dump(average_strategy(tables), d / "blueprint.pkl.gz")
    _dump({"regret": tables.regret, "strat": tables.strat, "actions": tables.actions,
           "iterations": tables.iterations, "batches": tables.batches}, d / "tables.pkl.gz")
    (d / "abstraction.json").write_text(json.dumps(abstraction.to_dict()))
    meta = {"version": name, "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            "iterations": tables.iterations, "infosets": len(tables.strat), **meta}
    (d / "meta.json").write_text(json.dumps(meta, indent=2))
    if not (models_dir() / "best.txt").exists():
        set_best(name)
    return name


def load_tables(version: str) -> tuple[Tables, CardAbstraction]:
    d = models_dir() / resolve(version)
    raw = _load(d / "tables.pkl.gz")
    t = Tables()
    t.regret, t.strat, t.actions = raw["regret"], raw["strat"], raw["actions"]
    t.iterations, t.batches = raw["iterations"], raw["batches"]
    return t, CardAbstraction.from_dict(json.loads((d / "abstraction.json").read_text()))


def load_blueprint(version: str):
    d = models_dir() / resolve(version)
    return (_load(d / "blueprint.pkl.gz"),
            CardAbstraction.from_dict(json.loads((d / "abstraction.json").read_text())))


def load_sixmax(version: str):
    """6-max preflop blueprint attached to ``version`` (None if it has none)."""
    f = models_dir() / resolve(version) / "sixmax.pkl.gz"
    return _load(f) if f.exists() else None


def save_sixmax(version: str, tables) -> Path:
    d = models_dir() / resolve(version)
    _dump(average_strategy(tables), d / "sixmax.pkl.gz")
    _dump({"regret": tables.regret, "strat": tables.strat, "actions": tables.actions,
           "iterations": tables.iterations, "batches": tables.batches}, d / "sixmax_tables.pkl.gz")
    update_meta(version, sixmax_iterations=tables.iterations, sixmax_infosets=len(tables.strat))
    return d


def load_sixmax_tables(version: str):
    f = models_dir() / resolve(version) / "sixmax_tables.pkl.gz"
    t = Tables()
    if f.exists():
        raw = _load(f)
        t.regret, t.strat, t.actions = raw["regret"], raw["strat"], raw["actions"]
        t.iterations, t.batches = raw["iterations"], raw["batches"]
    return t


def read_meta(version: str) -> dict:
    return json.loads((models_dir() / resolve(version) / "meta.json").read_text())


def update_meta(version: str, **fields) -> None:
    d = models_dir() / resolve(version)
    meta = json.loads((d / "meta.json").read_text())
    meta.update(fields)
    (d / "meta.json").write_text(json.dumps(meta, indent=2))
