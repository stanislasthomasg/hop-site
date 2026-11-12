"""High-level training entry point (used by the CLI)."""
from __future__ import annotations

import time

from .abstraction import CardAbstraction
from .mccfr import Tables, TrainConfig, train
from .registry import load_tables, resolve, save_version


def train_version(iterations: int, workers: int = 4, parent: str | None = None,
                  minutes: float | None = None, rm_plus: bool = False, seed: int = 0,
                  buckets: tuple[int, int, int] = (10, 8, 6), cheap_raises: int = 1,
                  max_raises: int = 3, depths_bb: tuple = (50, 100, 200),
                  depth_weights: tuple = (0.25, 0.5, 0.25), rake_pct: float = 0.05,
                  rake_cap_bb: float = 1.0, verbose: bool = True) -> str:
    """Train a new version, starting from ``parent`` (resume) or from scratch."""
    if parent:
        parent = resolve(parent)
        tables, abstraction = load_tables(parent)
    else:
        abstraction = CardAbstraction(buckets=buckets, cheap_raises=cheap_raises,
                                      max_raises=max_raises, depths_bb=tuple(depths_bb),
                                      depth_weights=tuple(depth_weights), rake_pct=rake_pct,
                                      rake_cap_bb=rake_cap_bb).fit(3000, seed=seed)
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
        "tree": {"cheap_raises": abstraction.cheap_raises, "max_raises": abstraction.max_raises},
        "depths_bb": list(abstraction.depths_bb), "rake": [abstraction.rake_pct, abstraction.rake_cap_bb],
    })
    if verbose:
        print(f"saved {name} ({tables.iterations:,} iterations total)")
    return name
