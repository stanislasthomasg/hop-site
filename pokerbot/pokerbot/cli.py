"""Command-line entry point: ``python -m pokerbot <command>``."""
from __future__ import annotations

import argparse
import time
from pathlib import Path

from .bots import RandomBot
from .engine import HandStore, Table, format_hand


def cmd_simulate(args: argparse.Namespace) -> None:
    agents = [RandomBot(f"random{i + 1}", seed=args.seed + i) for i in range(args.players)]
    store = None
    if args.db:
        Path(args.db).parent.mkdir(parents=True, exist_ok=True)
        store = HandStore(args.db, session=args.session)
    table = Table(agents, seed=args.seed, store=store, name=args.session)
    log = open(args.log, "w", encoding="utf-8") if args.log else None
    t0 = time.perf_counter()
    totals = [0] * args.players
    for i, rec in enumerate(table.play(args.hands)):
        for s, p in enumerate(rec.payoffs):
            totals[s] += p
        if log:
            log.write(format_hand(rec) + "\n\n")
        if i < args.show:
            print(format_hand(rec, in_bb=args.bb), end="\n\n")
    dt = time.perf_counter() - t0
    if log:
        log.close()
    print(f"{args.hands} hands, {args.players} players in {dt:.2f}s "
          f"({args.hands / dt:,.0f} hands/s{', with SQLite' if store else ''})")
    for a, t in zip(agents, totals):
        print(f"  {a.name:10s} {t / table.bb:+10.1f} bb   {100 * t / table.bb / args.hands:+9.1f} bb/100")
    if store:
        print(f"saved to {args.db} ({store.count()} hands in DB)")
        store.close()


def cmd_show(args: argparse.Namespace) -> None:
    with HandStore(args.db) as store:
        print(format_hand(store.get(args.hand_id), in_bb=args.bb))


def cmd_results(args: argparse.Namespace) -> None:
    with HandStore(args.db) as store:
        print(f"{'player':12s} {'hands':>8s} {'net bb':>10s} {'bb/100':>9s}")
        for name, k, net, bb100 in store.player_results(args.session):
            print(f"{name:12s} {k:8d} {net:+10.1f} {bb100:+9.1f}")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="pokerbot")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("simulate", help="play random bots against each other")
    s.add_argument("--players", type=int, default=6)
    s.add_argument("--hands", type=int, default=1000)
    s.add_argument("--seed", type=int, default=0)
    s.add_argument("--db", default="", help="SQLite file to save hands to")
    s.add_argument("--log", default="", help="text file with readable hand histories")
    s.add_argument("--session", default="sim")
    s.add_argument("--show", type=int, default=0, help="print the first N hands")
    s.add_argument("--bb", action="store_true", help="display amounts in big blinds")
    s.set_defaults(func=cmd_simulate)

    s = sub.add_parser("show", help="print one hand from the database")
    s.add_argument("hand_id", type=int)
    s.add_argument("--db", default="data/hands.db")
    s.add_argument("--bb", action="store_true")
    s.set_defaults(func=cmd_show)

    s = sub.add_parser("results", help="net results per player in the database")
    s.add_argument("--db", default="data/hands.db")
    s.add_argument("--session", default=None)
    s.set_defaults(func=cmd_results)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
