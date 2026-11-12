"""Command-line entry point: ``python -m pokerbot <command>`` (see README)."""
from __future__ import annotations

import argparse
import time
from pathlib import Path


def cmd_simulate(a):
    from .bots import make_agent
    from .engine import HandStore, Table, format_hand
    from .evaluation.stats import compute_stats, format_stats_table
    specs = a.agents.split(",") if a.agents else ["random"] * a.players
    agents = [make_agent(s, name=f"{s}-{i + 1}", seed=a.seed + i) for i, s in enumerate(specs)]
    store = None
    if a.db:
        Path(a.db).parent.mkdir(parents=True, exist_ok=True)
        store = HandStore(a.db, session=a.session)
    table = Table(agents, seed=a.seed, store=store, name=a.session)
    log = open(a.log, "w", encoding="utf-8") if a.log else None
    t0 = time.perf_counter()
    recs = []
    for i, rec in enumerate(table.play(a.hands)):
        recs.append(rec)
        if log:
            log.write(format_hand(rec) + "\n\n")
        if i < a.show:
            print(format_hand(rec, in_bb=a.bb), end="\n\n")
    dt = time.perf_counter() - t0
    if log:
        log.close()
    print(f"{a.hands} mains, {len(agents)} joueurs en {dt:.1f}s ({a.hands / dt:,.0f} mains/s)\n")
    print(format_stats_table(compute_stats(recs)))
    if store:
        print(f"\nsauvegardé dans {a.db} ({store.count()} mains)")
        store.close()


def cmd_show(a):
    from .engine import HandStore, format_hand
    with HandStore(a.db) as store:
        print(format_hand(store.get(a.hand_id), in_bb=a.bb))


def cmd_stats(a):
    from .engine import HandStore
    from .evaluation.stats import compute_stats, format_stats_table
    with HandStore(a.db) as store:
        print(format_stats_table(compute_stats(store.iter_hands(a.session))))


def cmd_train(a):
    from .training.run import train_version
    train_version(a.iterations, workers=a.workers, parent=a.parent, minutes=a.minutes,
                  rm_plus=a.rm_plus, seed=a.seed)


def cmd_train_6max(a):
    from .training.registry import load_sixmax_tables, resolve, save_sixmax
    from .training.sixmax import train_sixmax
    v = resolve(a.version)
    tables = load_sixmax_tables(a.source or v)
    train_sixmax(tables, a.iterations, workers=a.workers, minutes=a.minutes)
    print(f"stratégie 6-max enregistrée dans {save_sixmax(v, tables)}")


def cmd_versions(a):
    from .training.registry import list_versions, read_meta, resolve
    try:
        best = resolve("best")
    except FileNotFoundError:
        print("aucune version entraînée")
        return
    from .evaluation.ladder import current_level
    for v in list_versions():
        m = read_meta(v)
        print(f"{'*' if v == best else ' '} {v:8s} {m['iterations']:>11,} it.  {m['infosets']:>9,} infosets  "
              f"parent={m.get('parent')}  niveau={current_level(v)}  {m['created']}")
    print("* = meilleure version (utilisée par bot:best)")


def cmd_set_best(a):
    from .training.registry import set_best
    print(f"meilleure version : {set_best(a.version)}")


def cmd_match(a):
    from .evaluation.duplicate import duplicate_match
    t0 = time.time()
    res = duplicate_match(a.agents.split(","), a.deals, seed=a.seed, workers=a.workers, cash=a.cash)
    print(res.summary())
    if res.fallback_rate:
        print("  décisions hors stratégie CFR : " +
              ", ".join(f"{k} {100 * v:.0f}%" for k, v in res.fallback_rate.items()))
    print(f"  ({time.time() - t0:.0f}s)")


def cmd_ladder(a):
    from .evaluation.ladder import climb
    climb(a.bot, hands=a.hands, workers=a.workers, min_hands=a.min_hands, cash=not a.no_cash)


def cmd_learn(a):
    from .evaluation.ladder import climb
    from .training.registry import list_versions
    from .training.run import train_version
    for r in range(a.rounds):
        parent = "best" if list_versions() else None
        print(f"=== Cycle {r + 1}/{a.rounds} : entraînement depuis {parent or 'zéro'} ===")
        v = train_version(a.iterations, workers=a.workers, parent=parent, minutes=a.minutes)
        print(f"=== Cycle {r + 1}/{a.rounds} : échelle de niveaux pour {v} ===")
        climb(v, hands=a.hands, workers=a.workers, min_hands=a.min_hands, cash=not a.no_cash)


def cmd_play(a):
    from .ui.terminal import play_terminal
    play_terminal(a.opponents.split(","), seed=a.seed, name=a.name)


def cmd_web(a):
    from .ui.web_server import serve
    serve(a.port, a.opponents.split(","), host=a.host, open_browser=a.open)


def cmd_dashboard(a):
    from .ui.dashboard import export_html
    out = export_html(a.out, a.db)
    print(f"tableau de bord écrit dans {out}")


def cmd_build_site(a):
    from .ui.site_builder import build_site
    out = build_site(a.out, a.version, a.pyodide_dir, title=a.title, inline=a.inline,
                     base64_binaries=a.base64)
    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file()) / 1e6
    print(f"site statique écrit dans {out} ({size:.1f} Mo). À publier tel quel sur n'importe quel hébergeur.")


def cmd_acpc(a):
    from .evaluation.acpc import play_acpc
    n = play_acpc(a.host, a.port, a.bot)
    print(f"connexion fermée par le serveur après {n} mains")


def cmd_slumbot(a):
    from .evaluation.slumbot import play_slumbot
    (m, lo, hi), _ = play_slumbot(a.hands, a.bot)
    print(f"vs Slumbot : {m:+.1f} bb/100 [{lo:+.1f}, {hi:+.1f}]")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="pokerbot", description="Bots de NLHE qui apprennent (simulation uniquement)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("simulate", help="faire jouer des bots entre eux")
    s.add_argument("--agents", default="", help="ex. abc,station,nit,maniac,random,bot:best")
    s.add_argument("--players", type=int, default=6, help="nombre de bots aléatoires si --agents est vide")
    s.add_argument("--hands", type=int, default=1000)
    s.add_argument("--seed", type=int, default=0)
    s.add_argument("--db", default="", help="fichier SQLite où sauvegarder les mains")
    s.add_argument("--log", default="", help="fichier texte d'historique lisible")
    s.add_argument("--session", default="sim")
    s.add_argument("--show", type=int, default=0, help="afficher les N premières mains")
    s.add_argument("--bb", action="store_true", help="montants en big blinds")
    s.set_defaults(func=cmd_simulate)

    s = sub.add_parser("show", help="afficher une main de la base")
    s.add_argument("hand_id", type=int)
    s.add_argument("--db", default="data/hands.db")
    s.add_argument("--bb", action="store_true")
    s.set_defaults(func=cmd_show)

    s = sub.add_parser("stats", help="VPIP/PFR/AF... des joueurs d'une base")
    s.add_argument("--db", default="data/human.db")
    s.add_argument("--session", default=None)
    s.set_defaults(func=cmd_stats)

    s = sub.add_parser("train", help="entraîner une nouvelle version (MCCFR)")
    s.add_argument("--iterations", type=int, default=1_000_000)
    s.add_argument("--workers", type=int, default=4)
    s.add_argument("--from", dest="parent", default=None, help="reprendre depuis une version (ex. best, v2)")
    s.add_argument("--minutes", type=float, default=None, help="limite de temps")
    s.add_argument("--rm-plus", action="store_true", help="regret-matching+ (CFR+) au lieu de Linear CFR")
    s.add_argument("--seed", type=int, default=0)
    s.set_defaults(func=cmd_train)

    s = sub.add_parser("train-6max", help="entraîner la stratégie préflop 6-max d'une version")
    s.add_argument("--version", default="best")
    s.add_argument("--source", default=None, help="reprendre la stratégie 6-max d'une autre version")
    s.add_argument("--iterations", type=int, default=5_000_000)
    s.add_argument("--minutes", type=float, default=None)
    s.add_argument("--workers", type=int, default=4)
    s.set_defaults(func=cmd_train_6max)

    s = sub.add_parser("versions", help="lister les versions du bot")
    s.set_defaults(func=cmd_versions)

    s = sub.add_parser("set-best", help="revenir à / choisir une version (rollback)")
    s.add_argument("version")
    s.set_defaults(func=cmd_set_best)

    s = sub.add_parser("match", help="match duplicate entre agents")
    s.add_argument("agents", help="ex. bot:best,abc")
    s.add_argument("--deals", type=int, default=5000)
    s.add_argument("--workers", type=int, default=4)
    s.add_argument("--seed", type=int, default=0)
    s.add_argument("--cash", action="store_true", help="conditions cash : rake + tapis variables")
    s.set_defaults(func=cmd_match)

    s = sub.add_parser("ladder", help="évaluer une version sur l'échelle de niveaux")
    s.add_argument("--bot", default="latest")
    s.add_argument("--hands", type=int, default=50_000, help="mains par niveau")
    s.add_argument("--min-hands", type=int, default=50_000)
    s.add_argument("--workers", type=int, default=4)
    s.add_argument("--no-cash", action="store_true", help="100 bb sans rake (ancien protocole)")
    s.set_defaults(func=cmd_ladder)

    s = sub.add_parser("learn", help="boucle continue : entraîner puis évaluer, N cycles")
    s.add_argument("--rounds", type=int, default=3)
    s.add_argument("--iterations", type=int, default=1_000_000)
    s.add_argument("--minutes", type=float, default=None)
    s.add_argument("--hands", type=int, default=50_000)
    s.add_argument("--min-hands", type=int, default=50_000)
    s.add_argument("--workers", type=int, default=4)
    s.add_argument("--no-cash", action="store_true")
    s.set_defaults(func=cmd_learn)

    s = sub.add_parser("play", help="jouer contre un bot dans le terminal")
    s.add_argument("--opponents", default="bot:best", help="ex. bot:best ou bot:best,abc,nit (6-max)")
    s.add_argument("--name", default="you")
    s.add_argument("--seed", type=int, default=None)
    s.set_defaults(func=cmd_play)

    s = sub.add_parser("web", help="interface web locale (table + tableau de bord)")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--opponents", default="bot:best")
    s.add_argument("--open", action="store_true", help="ouvrir le navigateur automatiquement")
    s.set_defaults(func=cmd_web)

    s = sub.add_parser("dashboard", help="exporter le tableau de bord en un fichier HTML")
    s.add_argument("--out", default="data/dashboard.html")
    s.add_argument("--db", action="append", default=[], help="base(s) de mains supplémentaire(s)")
    s.set_defaults(func=cmd_dashboard)

    s = sub.add_parser("build-site", help="site statique pour jouer contre le bot dans le navigateur")
    s.add_argument("--out", default="site")
    s.add_argument("--version", default="best")
    s.add_argument("--pyodide-dir", default=None,
                   help="dossier Pyodide 0.26.4 à embarquer (sinon chargé depuis le CDN jsdelivr)")
    s.add_argument("--title", default="Poker contre le bot")
    s.add_argument("--inline", action="store_true", help="CSS/JS dans la page, sans balises html/head/body")
    s.add_argument("--base64", action="store_true", help="binaires en base64 (.txt) pour les hébergeurs qui refusent .zip/.gz")
    s.set_defaults(func=cmd_build_site)

    s = sub.add_parser("acpc", help="jouer sur un serveur de compétition de bots (protocole ACPC)")
    s.add_argument("host")
    s.add_argument("port", type=int)
    s.add_argument("--bot", default="bot:best")
    s.set_defaults(func=cmd_acpc)

    s = sub.add_parser("slumbot", help="(expérimental) jouer contre Slumbot via son API")
    s.add_argument("--hands", type=int, default=1000)
    s.add_argument("--bot", default="bot:best")
    s.set_defaults(func=cmd_slumbot)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
