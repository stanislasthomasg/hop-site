"""The learning bot: CFR blueprint + opponent exploitation + explanations.

Heads-up, the real hand is translated into the abstract betting tree (real bet
sizes are mapped to 1/2 pot, pot, 2x pot or all-in with the pseudo-harmonic
mapping), the blueprint gives action probabilities for (bucket, history), the
exploitation layer tilts them against the current opponent, and the chosen
abstract action is converted back to a real amount (same pot fraction).

Off the abstract tree (unusual lines, or 3+ players in the pot) the bot falls
back to equity-based ABC rules, still adjusted by the opponent model.
"""
from __future__ import annotations

import random
from functools import lru_cache

from ..engine.actions import Action
from ..engine.cards import cards_to_str
from ..engine.equity import hand_class, preflop_equity
from ..engine.records import HandRecord
from ..engine.state import PlayerView
from ..training.abstraction import BET_FRACTIONS, CardAbstraction
from .base import Agent
from .exploit import ModelBook, adjust
from .profiles import ABC

ACTION_NAMES = {"f": "se coucher", "k": "checker", "c": "suivre", "h": "relance 1/2 pot",
                "p": "relance pot", "d": "relance 2x pot", "a": "tapis"}


@lru_cache(maxsize=4)
def _cached_blueprint(version: str):
    from ..training.registry import load_blueprint
    return load_blueprint(version)


@lru_cache(maxsize=4)
def _cached_sixmax(version: str):
    from ..training.registry import load_sixmax
    return load_sixmax(version)


SIX_NAMES = {"f": "se coucher", "k": "checker", "c": "suivre", "o": "ouvrir (2,5 bb)",
             "t": "3-bet", "q": "4-bet", "a": "tapis"}


def pseudo_harmonic(x: float, a: float, b: float) -> float:
    """Probability of mapping bet fraction x (a <= x <= b) to the smaller size a."""
    if b <= a:
        return 1.0
    return ((b - x) * (1 + a)) / ((b - a) * (1 + x))


class LearnerBot(Agent):
    def __init__(self, blueprint: dict, abstraction: CardAbstraction, name: str | None = None,
                 seed: int | None = None, exploit: bool = True, book: ModelBook | None = None,
                 version: str = "", exploit_scale: float = 1.0, min_weight: float = 20.0,
                 sixmax: dict | None = None) -> None:
        super().__init__(name or (version or "learner"))
        self.bp = blueprint
        self.six = sixmax
        self.abs = abstraction
        self.rng = random.Random(seed)
        self.exploit = exploit
        self.exploit_scale = exploit_scale
        self.book = book or ModelBook()
        self.version = version
        self.fallback = ABC(seed=seed)
        self.table_names: list[str] = []
        self._depth = 0
        self.last_explanation = ""
        self.stats = {"blueprint": 0, "fallback": 0}
        self.min_weight = min_weight
        self._hands = 0

    @classmethod
    def from_version(cls, version: str = "best", name: str | None = None, seed: int | None = None,
                     exploit: bool = True, book_path: str | None = None) -> "LearnerBot":
        from ..training.registry import resolve
        v = resolve(version)
        bp, ab = _cached_blueprint(v)
        return cls(bp, ab, name=name or v, seed=seed, exploit=exploit,
                   book=ModelBook(book_path), version=v, sixmax=_cached_sixmax(v))

    # ------------------------------------------------------------------ translation
    def translate(self, view: PlayerView) -> AState | None:
        """Replay the real betting in the heads-up abstract game. None if it cannot be mapped.

        Heads-up tables map directly. At a 6-max table, a pot that reaches the flop
        with exactly two players is mapped onto the heads-up tree: the player in
        position becomes the button, and the preflop action is summarised by the
        equivalent heads-up line (limped, raised by the player in or out of position,
        3-bet by either), then the postflop betting is translated as usual."""
        n = view.n_players
        live = [i for i in range(n) if not view.folded[i]]
        if n == 2:
            ip, op = view.button, 1 - view.button
            hist0 = None
        elif len(live) == 2 and view.street >= 1:
            order = sorted(live, key=lambda i: (i - view.button - 1) % n)
            op, ip = order                    # first to act postflop is out of position
            hist0 = self._synthetic_preflop(view, ip, op)
            if hist0 is None:
                return None
        else:
            return None
        ap = {ip: 0, op: 1}
        start = list(view.starting_stacks)
        start_eff = min(start[ip], start[op]) / view.bb
        self._depth = self.abs.depth_index(start_eff)
        s = self.abs.new_state(self._depth)
        if hist0 is not None:
            for ch in hist0:
                if ch != "/":
                    if ch not in s.legal():
                        return None
                    s._apply(ch)
        contrib = [0] * n
        bets = [0] * n
        street = 0
        for a in view.history:
            if a.kind.startswith("post"):
                if a.kind != "post_ante":
                    bets[a.seat] += a.added
                contrib[a.seat] += a.added
                continue
            if a.street != street:
                street = a.street
                bets = [0] * n
            if hist0 is not None and a.street == 0:
                contrib[a.seat] += a.added      # preflop already summarised
                bets[a.seat] += a.added
                continue
            if s.terminal or s.street != a.street or s.to_act != ap.get(a.seat, -1):
                return None
            legal = s.legal()
            if a.kind == "fold":
                ch = "f"
            elif a.kind == "check":
                ch = "k" if "k" in legal else None
            elif a.kind == "call":
                ch = "c" if "c" in legal else ("k" if "k" in legal else None)
            else:
                cur = max(bets)
                pot, to_call = sum(contrib), cur - bets[a.seat]
                left = start[a.seat] - contrib[a.seat]
                ch = self._map_raise(legal, (a.amount - cur) / max(1, pot + to_call),
                                     a.all_in or a.added >= 0.85 * left)
            if ch is None:
                return None
            contrib[a.seat] += a.added
            bets[a.seat] += a.added
            s._apply(ch)
        if s.terminal or s.street != view.street or s.to_act != ap.get(view.seat, -1):
            return None
        return s

    @staticmethod
    def _synthetic_preflop(view: PlayerView, ip: int, op: int) -> str | None:
        """Heads-up preflop line equivalent to a multi-way preflop that ended heads-up."""
        raisers = [a.seat for a in view.history if a.street == 0 and a.kind in ("bet", "raise")]
        if not raisers:
            return "ck/"
        last = raisers[-1]
        if last not in (ip, op):
            return None
        if len(raisers) == 1:
            return "pc/" if last == ip else "cpc/"
        if len(raisers) == 2:
            return "cppc/" if last == ip else "hpc/"
        return None                            # 4-bet pots are (nearly) all-in: rules suffice

    # ------------------------------------------------------------------ 6-max preflop
    SIX_SEAT = {"UTG": 0, "HJ": 1, "CO": 2, "BTN": 3, "SB": 4, "BB": 5}

    def translate_sixmax(self, view: PlayerView):
        """Map a real 6-max preflop to the 6-max abstract game (or None)."""
        if self.six is None or view.n_players != 6 or view.street != 0:
            return None
        from ..engine.state import position_names
        from ..training.sixmax import PState
        labels = position_names(6)
        seat_of = {i: self.SIX_SEAT[labels[(i - view.button) % 6]] for i in range(6)}
        s = PState()
        for a in view.history:
            if a.kind.startswith("post"):
                continue
            if s.terminal or s.to_act != seat_of[a.seat]:
                return None
            legal = s.legal()
            if a.kind == "fold":
                ch = "f"
            elif a.kind == "check":
                ch = "k"
            elif a.kind == "call":
                ch = "c"
            else:
                big = a.all_in or a.amount >= 0.45 * view.starting_stacks[a.seat]
                ch = "a" if big else {0: "o", 1: "t", 2: "q"}.get(s.nraises, "a")
            if ch not in legal:
                return None
            s._apply(ch)
        if s.terminal or s.to_act != seat_of[view.seat]:
            return None
        return s, seat_of[view.seat]

    def _map_raise(self, legal: str, frac: float, all_in: bool) -> str | None:
        sizes = [(BET_FRACTIONS[ch], ch) for ch in legal if ch in BET_FRACTIONS]
        if all_in or not sizes:
            if "a" in legal:
                return "a"
            return "c" if "c" in legal else None
        sizes.sort()
        if frac <= sizes[0][0]:
            return sizes[0][1]
        if frac >= sizes[-1][0]:
            # between the biggest size and all-in: treat >3x pot as all-in
            return "a" if frac > 3 * sizes[-1][0] and "a" in legal else sizes[-1][1]
        for (fa, ca), (fb, cb) in zip(sizes, sizes[1:]):
            if fa <= frac <= fb:
                return ca if self.rng.random() < pseudo_harmonic(frac, fa, fb) else cb
        return sizes[-1][1]

    # ------------------------------------------------------------------ acting
    def _opponent_model(self, view: PlayerView):
        if not self.exploit or not self.table_names:
            return None
        opp = [s for s in range(view.n_players) if s != view.seat and not view.folded[s]]
        return self.book.get(self.table_names[opp[0]]) if len(opp) == 1 else None

    def _strength(self, view: PlayerView) -> float:
        if not view.board:
            return preflop_equity(view.hole, 1)
        return self.abs.equity(view.hole, view.board)

    def act(self, view: PlayerView) -> Action:
        if view.n_players == 6 and view.street == 0 and self.six is not None:
            return self._act_sixmax(view)
        s = self.translate(view)
        entry, why = None, "coup hors de l'arbre abstrait (ligne inhabituelle ou multiway)"
        if s is not None:
            bucket = self.abs.bucket(view.hole, view.board)
            key = f"{self.abs.key_prefix(self._depth)}{bucket}:{s.history}"
            entry = self.bp.get(key)
            why = "situation jamais rencontrée à l'entraînement"
            if entry is not None and entry[0] != s.legal():
                entry = None
            elif entry is not None and len(entry) > 2 and entry[2] < self.min_weight:
                why = f"situation trop peu entraînée (poids {entry[2]:.0f} < {self.min_weight:.0f})"
                entry = None
        if entry is None:
            return self._fallback_act(view, why)
        self.stats["blueprint"] += 1
        acts, probs = entry[0], entry[1]
        strength = self._strength(view)
        model = self._opponent_model(view)
        new_probs, reasons = adjust(acts, list(probs), model, strength,
                                    facing_bet=view.to_call > 0, preflop=not view.board,
                                    scale=self.exploit_scale, street=int(view.street))
        k = self._sample(new_probs)
        ch = acts[k]
        action = self._to_real(view, ch)
        self.last_explanation = self._explain(view, bucket, s.history, acts, probs, new_probs,
                                              reasons, strength, ch, action, model)
        return action

    def _act_sixmax(self, view: PlayerView) -> Action:
        r = self.translate_sixmax(view)
        if r is None:
            return self._fallback_act(view, "ligne préflop 6-max hors de l'arbre (limp, taille inhabituelle)")
        s6, seat6 = r
        from ..engine.equity import class_index
        key = f"{seat6}|{class_index(view.hole)}|{s6.history}"
        entry = self.six.get(key)
        if entry is None or entry[0] != s6.legal() or entry[2] < self.min_weight:
            return self._fallback_act(view, "situation préflop 6-max trop peu entraînée")
        self.stats["blueprint"] += 1
        acts, probs = entry[0], entry[1]
        ch = acts[self._sample(probs)]
        legal = view.legal
        if ch == "f":
            action = legal.check_or_fold()
        elif ch in "kc":
            action = legal.check_or_call()
        elif ch == "a":
            action = legal.all_in()
        elif ch == "o":
            mult = 3.0 if view.position in ("SB", "BB") else 2.5
            action = legal.clamp_raise(int(mult * view.bb))
        else:
            action = legal.clamp_raise(int(view.current_bet * (3.25 if ch == "t" else 2.3)))
        self.last_explanation = "\n".join([
            f"[{self.version}] préflop 6-max, {view.position} : main [{cards_to_str(view.hole)}] "
            f"-> classe {hand_class(view.hole)}",
            f"Ligne abstraite 6-max : '{s6.history or '-'}'",
            "Stratégie MCCFR 6-max : " + ", ".join(
                f"{SIX_NAMES[a]} {100 * p_:.0f} %" for a, p_ in zip(acts, probs) if p_ >= 0.005),
            f"Tirage : {SIX_NAMES[ch]} -> {action}"])
        return action

    def _sample(self, probs) -> int:
        x, acc = self.rng.random(), 0.0
        for k, p in enumerate(probs):
            acc += p
            if x < acc:
                return k
        return len(probs) - 1

    def _to_real(self, view: PlayerView, ch: str) -> Action:
        legal = view.legal
        if ch == "f":
            return legal.check_or_fold()
        if ch in "kc":
            return legal.check_or_call()
        if ch == "a":
            return legal.all_in()
        target = view.current_bet + BET_FRACTIONS[ch] * (view.pot + view.to_call)
        return legal.clamp_raise(int(target))

    def _fallback_act(self, view: PlayerView, why: str) -> Action:
        self.stats["fallback"] += 1
        action = self.fallback.act(view)
        eq = self._strength(view) if view.n_players == 2 or view.board else None
        self.last_explanation = (
            f"Main {hand_class(view.hole)} [{cards_to_str(view.hole)}]"
            + (f", équité contre une main au hasard ~{100 * eq:.0f} %" if eq is not None else "")
            + f"\nPas de stratégie CFR ici ({why}) : règles ABC (ranges + équité contre la cote du pot)."
            + f"\nAction : {action}")
        return action

    def _explain(self, view, bucket, history, acts, probs, new_probs, reasons, strength,
                 ch, action, model) -> str:
        street = ["préflop", "flop", "turn", "river"][view.street]
        if view.board:
            nb = self.abs.buckets[view.street - 1]
            hand = f"groupe {bucket + 1}/{nb} (équité ~{100 * strength:.0f} %)"
        else:
            hand = f"classe {hand_class(view.hole)} (équité contre une main au hasard ~{100 * strength:.0f} %)"
        lines = [f"[{self.version}] {street} : main [{cards_to_str(view.hole)}] -> {hand}",
                 f"Ligne abstraite : '{history or '-'}'",
                 "Stratégie CFR (proche GTO) : " + ", ".join(
                     f"{ACTION_NAMES[a]} {100 * p:.0f} %" for a, p in zip(acts, probs) if p >= 0.005)]
        if reasons:
            lines.append(f"Ajustement contre {model.name} ({model.hands} mains observées, profil : "
                         f"{model.profile_label()}) : " + " ; ".join(reasons))
            lines.append("Après ajustement : " + ", ".join(
                f"{ACTION_NAMES[a]} {100 * p:.0f} %" for a, p in zip(acts, new_probs) if p >= 0.005))
        elif model is not None:
            lines.append(f"Pas d'ajustement contre {model.name} ({model.hands} mains) : trop peu de données "
                         "ou jeu proche de la référence, le bot reste sur sa stratégie CFR.")
        lines.append(f"Tirage : {ACTION_NAMES[ch]} -> {action}")
        return "\n".join(lines)

    # ------------------------------------------------------------------ learning
    def on_hand_end(self, seat: int, record: HandRecord) -> None:
        self.book.observe(record, seat)
        self._hands += 1
        if self.book.path and self._hands % 200 == 0:
            self.book.save()
