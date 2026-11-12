"""High-level training entry point (used by the CLI)."""
from __future__ import annotations

import time

from .abstraction import CardAbstraction
from .mccfr import Tables, TrainConfig, train
from .registry import load_tables, resolve, save_version


def train_version(iterations: int, workers: int = 4, parent: str | None = None,
                  minutes: float | None = None, rm_plus: bool = False, seed: int = 0,
                  buckets: tuple[int, int, int] = (12, 10, 8), verbose: bool = True) -> str:
    """Train a new version, starting from ``parent`` (resume) or from scratch."""
    if parent:
        parent = resolve(parent)
        tables, abstraction = load_tables(parent)
    else:
        abstraction = CardAbstraction(buckets=buckets).fit(3000, seed=seed)
        tables = Tables()
    start_it = tables.iterations
    last = [0.0]

    def progress(t: Tables, done: int, elapsed: float) -> None:
        if verbose and (elapsed - last[0] > 30 or done >= iterations):
            last[0] = elapsed
            print(f"  {t.iterations:>10,} iterations  {done / elapsed:7.0f} it/s  "
                  f"{len(t.strat):>9,} infosets  {elapsed / 60:5.1f} min", flush=True)

    t0 = time.time()
    cfg = TrainConfig(iterations=iterations, workers=workers, rm_plus=rm_plus, seed=seed)
    train(tables, abstraction, cfg, progress=progress,
          time_limit=minutes * 60 if minutes else None)
    name = save_version(tables, abstraction, {
        "parent": parent, "trained_iterations": tables.iterations - start_it,
        "train_seconds": round(time.time() - t0), "rm_plus": rm_plus,
        "buckets": list(abstraction.buckets),
    })
    if verbose:
        print(f"saved {name} ({tables.iterations:,} iterations total)")
    return name
