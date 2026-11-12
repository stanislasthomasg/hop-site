"""A human seat at a table of bots, advanced one decision at a time.

Shared by the terminal and the web interface. Every hand is saved in SQLite
(``data/human.db`` by default) so the dashboard can track the human's results.
"""
from __future__ import annotations

import random
from pathlib import Path

from ..bots.registry import make_agent
from ..engine.actions import Action, ActionType
from ..engine.cards import card_to_str, cards_to_str
from ..engine.history import HandStore, format_hand
from ..engine.state import HandState
from ..training.registry import PROJECT_ROOT

DATA_DIR = PROJECT_ROOT / "data"
STREET_NAMES_FR = ("préflop", "flop", "turn", "river", "abattage")


class GameSession:
    def __init__(self, opponents: list[str], human_name: str = "you", seed: int | None = None,
                 db: str | Path | None = None, stack: int = 10_000, sb: int = 50, bb: int = 100,
                 book_path: str | Path | None = None) -> None:
        self.rng = random.Random(seed)
        self.human_name = human_name
        self.n = len(opponents) + 1
        self.human_seat = 0
        self.bots = []
        for i, spec in enumerate(opponents):
            kwargs = {}
            agent = make_agent(spec, name=spec if spec not in [o for o in opponents[:i]] else f"{spec}#{i}",
                               seed=self.rng.getrandbits(32))
            if hasattr(agent, "book") and book_path:
                from ..bots.exploit import ModelBook
                agent.book = ModelBook(book_path)
            self.bots.append(agent)
        self.names = [human_name] + [b.name for b in self.bots]
        self.stack, self.sb, self.bb = stack, sb, bb
        DATA_DIR.mkdir(exist_ok=True)
        self.store = HandStore(db or DATA_DIR / "human.db", session=f"human-vs-{'+'.join(opponents)}",
                               batch_size=1)
        self.button = self.rng.randrange(self.n)
        self.hand_no = 0
        self.state: HandState | None = None
        self.log: list[str] = []
        self.explanations: list[dict] = []
        self.results: list[float] = []          # human net bb per hand
        self.last_record = None

    # ------------------------------------------------------------------ flow
    def agent(self, seat: int):
        return None if seat == self.human_seat else self.bots[seat - 1]

    def new_hand(self) -> None:
        if self.state is not None and not self.state.is_over:
            raise RuntimeError("hand in progress")
        self.hand_no += 1
        self.button = (self.button + 1) % self.n
        self.state = HandState([self.stack] * self.n, button=self.button, sb=self.sb, bb=self.bb,
                               rng=random.Random(self.rng.getrandbits(63)), hand_no=self.hand_no)
        self.log, self.explanations, self.last_record = [], [], None
        for seat in range(self.n):
            a = self.agent(seat)
            if a is not None:
                a.table_names = self.names
                a.on_hand_start(seat, self.state.view(seat))
        for rec in self.state.history:
            self.log.append(self._describe(rec))
        self._advance_bots()

    def act(self, action: Action) -> None:
        st = self.state
        if st is None or st.is_over or st.to_act != self.human_seat:
            raise RuntimeError("not your turn")
        st.apply(action)
        self.log.append(self._describe(st.history[-1]))
        self._advance_bots()

    def _advance_bots(self) -> None:
        st = self.state
        street = st.street
        while not st.is_over and st.to_act != self.human_seat:
            seat = st.to_act
            bot = self.agent(seat)
            action = bot.act(st.view(seat))
            st.apply(action)
            self.log.append(self._describe(st.history[-1]))
            expl = getattr(bot, "last_explanation", "")
            self.explanations.append({"seat": seat, "name": self.names[seat],
                                      "action": self.log[-1], "why": expl or "(bot à règles fixes : pas d'explication détaillée)"})
            if st.street != street:
                street = st.street
        if st.is_over:
            self._finish()

    def _finish(self) -> None:
        rec = self.state.to_record(self.names, table="human")
        self.last_record = rec
        for seat in range(self.n):
            a = self.agent(seat)
            if a is not None:
                a.on_hand_end(seat, rec)
                if hasattr(a, "book"):
                    a.book.save()
        self.store.add(rec)
        self.store.commit()
        self.results.append(rec.payoffs[self.human_seat] / self.bb)

    def _describe(self, a) -> str:
        nm = self.names[a.seat]
        c = lambda x: f"{x / self.bb:g} bb"  # noqa: E731
        kinds = {"post_sb": f"poste la petite blinde {c(a.added)}",
                 "post_bb": f"poste la grosse blinde {c(a.added)}",
                 "post_ante": f"poste l'ante {c(a.added)}", "fold": "se couche", "check": "checke",
                 "call": f"suit {c(a.added)}", "bet": f"mise {c(a.amount)}",
                 "raise": f"relance à {c(a.amount)}"}
        return f"[{STREET_NAMES_FR[a.street]}] {nm} {kinds[a.kind]}" + (" (tapis)" if a.all_in else "")

    # ------------------------------------------------------------------ views
    def snapshot(self) -> dict:
        """JSON-friendly state for the interfaces (no hidden information leaked)."""
        st = self.state
        out = {"hand_no": self.hand_no, "names": self.names, "bb": self.bb, "log": self.log,
               "explanations": self.explanations, "session": self.session_stats()}
        if st is None:
            out["phase"] = "idle"
            return out
        over = st.is_over
        showdown = set(self.last_record.showdown) if over and self.last_record else set()
        seats = []
        for p in st.players:
            visible = p.seat == self.human_seat or (over and p.seat in showdown)
            seats.append({
                "seat": p.seat, "name": self.names[p.seat], "position": st.positions[p.seat],
                "stack": p.stack, "bet": p.street_bet, "folded": p.folded, "all_in": p.all_in,
                "cards": [card_to_str(c) for c in p.hole] if visible else None,
                "is_human": p.seat == self.human_seat, "to_act": (not over and st.to_act == p.seat),
                "net": (st.payoffs[p.seat] if over else None),
            })
        out.update({"phase": "over" if over else "playing", "seats": seats,
                    "board": [card_to_str(c) for c in st.board], "pot": st.pot,
                    "street": STREET_NAMES_FR[st.street], "button": st.button})
        if not over and st.to_act == self.human_seat:
            la = st.legal_actions()
            out["legal"] = {"fold": la.can_fold, "check": la.can_check, "call": la.can_call,
                            "call_amount": la.call_amount, "raise": la.can_raise,
                            "min_raise_to": la.min_raise_to, "max_raise_to": la.max_raise_to,
                            "pot": st.pot, "current_bet": st.current_bet}
        if over and self.last_record:
            out["history_text"] = format_hand(self.last_record, in_bb=True)
            out["result_bb"] = self.last_record.payoffs[self.human_seat] / self.bb
        return out

    def session_stats(self) -> dict:
        n = len(self.results)
        net = sum(self.results)
        return {"hands": n, "net_bb": round(net, 1), "bb100": round(100 * net / n, 1) if n else 0.0,
                "curve": [round(sum(self.results[:i + 1]), 1) for i in range(n)]}

    def parse_action(self, text: str) -> Action:
        """Parse terminal shortcuts: f, k/x, c, a, h (1/2 pot), p (pot), r <bb>."""
        st = self.state
        la = st.legal_actions()
        t = text.strip().lower().split()
        if not t:
            raise ValueError("commande vide")
        cmd = t[0]
        if cmd in ("f", "fold"):
            return la.check_or_fold() if la.can_check else Action.fold()
        if cmd in ("k", "x", "check"):
            if not la.can_check:
                raise ValueError("impossible de checker : il y a une mise à suivre")
            return Action.check()
        if cmd in ("c", "call"):
            return la.check_or_call()
        if cmd in ("a", "allin", "all-in"):
            return la.all_in()
        if not la.can_raise:
            raise ValueError("relance impossible ici")
        if cmd in ("h", "p", "d"):
            frac = {"h": 0.5, "p": 1.0, "d": 2.0}[cmd]
            target = st.current_bet + frac * (st.pot + la.call_amount)
            return la.clamp_raise(int(target))
        if cmd in ("r", "b", "raise", "bet") and len(t) > 1:
            amount = int(round(float(t[1]) * self.bb))
            if not la.min_raise_to <= amount <= la.max_raise_to:
                raise ValueError(f"relance entre {la.min_raise_to / self.bb:g} et "
                                 f"{la.max_raise_to / self.bb:g} bb")
            return Action.raise_to(amount)
        raise ValueError(f"commande inconnue : {text!r} (tapez aide)")

    def close(self) -> None:
        self.store.close()
