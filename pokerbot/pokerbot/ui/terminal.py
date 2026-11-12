"""Jouer contre les bots dans le terminal."""
from __future__ import annotations

from .session import GameSession

HELP = """Commandes :  f se coucher | k checker | c suivre | h relance 1/2 pot | p relance pot
             d relance 2x pot | a tapis | r <bb> relancer à <bb> (ex. r 7.5)
             ? pourquoi les bots ont joué ça | s stats de session | aide | q quitter"""


def _cards(cs):
    return " ".join(cs) if cs else "?? ??"


def render(snap: dict) -> str:
    bb = snap["bb"]
    lines = [f"\n=== Main n°{snap['hand_no']} - {snap['street']} - pot {snap['pot'] / bb:g} bb ===",
             f"Tableau : {_cards(snap['board']) if snap['board'] else '(aucune carte)'}"]
    for s in snap["seats"]:
        flag = "->" if s["to_act"] else "  "
        status = "couché" if s["folded"] else ("TAPIS" if s["all_in"] else "")
        cards = _cards(s["cards"]) if s["cards"] else ("     " if s["folded"] else "## ##")
        net = f"  net {s['net'] / bb:+g} bb" if s["net"] is not None else ""
        lines.append(f"{flag} {s['name']:16s} {s['position']:4s} [{cards}]  tapis {s['stack'] / bb:7g} bb"
                     f"  mise {s['bet'] / bb:g}  {status}{net}")
    return "\n".join(lines)


def _explain(snap: dict) -> None:
    if not snap["explanations"]:
        print("  (les bots n'ont pas encore agi)")
    for e in snap["explanations"]:
        print(f"\n{e['action']}\n{e['why']}")


def play_terminal(opponents: list[str], seed: int | None = None, name: str = "you") -> None:
    sess = GameSession(opponents, human_name=name, seed=seed)
    print(f"Vous ({name}) contre {', '.join(opponents)}. Tapis de 100 bb, blindes 0,5/1 bb.")
    print(HELP)
    shown = 0
    try:
        sess.new_hand()
        while True:
            snap = sess.snapshot()
            for line in snap["log"][shown:]:
                print("  " + line)
            shown = len(snap["log"])
            if snap["phase"] == "over":
                print(render(snap))
                s = snap["session"]
                print(f"Résultat : {snap['result_bb']:+g} bb | session : {s['hands']} mains, "
                      f"{s['net_bb']:+g} bb ({s['bb100']:+g} bb/100)")
                cmd = input("[n] main suivante, [?] explications, [h] historique, [q] quitter > ").strip().lower()
                if cmd == "q":
                    break
                if cmd == "?":
                    _explain(snap)
                    input("(entrée) ")
                if cmd == "h":
                    print(snap["history_text"])
                    input("(entrée) ")
                sess.new_hand()
                shown = 0
                continue
            print(render(snap))
            la = snap["legal"]
            opts = []
            if la["fold"]:
                opts.append("f")
            opts.append("k" if la["check"] else f"c ({la['call_amount'] / snap['bb']:g} bb)")
            if la["raise"]:
                opts.append(f"h/p/d/a ou r <{la['min_raise_to'] / snap['bb']:g}..{la['max_raise_to'] / snap['bb']:g}>")
            cmd = input("Votre action [" + ", ".join(opts) + "] > ").strip()
            if cmd in ("q", "quit", "quitter"):
                break
            if cmd == "?":
                _explain(snap)
                continue
            if cmd == "s":
                s = snap["session"]
                print(f"  {s['hands']} mains, {s['net_bb']:+g} bb, {s['bb100']:+g} bb/100")
                continue
            if cmd in ("help", "aide"):
                print(HELP)
                continue
            try:
                sess.act(sess.parse_action(cmd))
            except ValueError as e:
                print(f"  ! {e}")
    except (EOFError, KeyboardInterrupt):
        print()
    finally:
        st = sess.session_stats()
        print(f"\nSession : {st['hands']} mains, {st['net_bb']:+g} bb ({st['bb100']:+g} bb/100). "
              "Mains sauvegardées dans data/human.db")
        sess.close()
