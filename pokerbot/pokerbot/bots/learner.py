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


def pseudo_harmonic(x: float, a: float, b: float) -> float:
    """Probability of mapping bet fraction x (a <= x <= b) to the smaller size a."""
    if b <= a:
        return 1.0
    return ((b - x) * (1 + a)) / ((b - a) * (1 + x))


class LearnerBot(Agent):
    def __init__(self, blueprint: dict, abstraction: CardAbstraction, name: str | None = None,
                 seed: int | None = None, exploit: bool = True, book: ModelBook | None = None,
                 version: str = "", exploit_scale: float = 1.0, min_weight: float = 20.0) -> None:
        super().__init__(name or (version or "learner"))
        self.bp = blueprint
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
                   book=ModelBook(book_path), version=v)

    # ------------------------------------------------------------------ translation
    def translate(self, view: PlayerView) -> AState | None:
        """Replay the real betting in the abstract game. None if it cannot be mapped."""
        if view.n_players != 2:
            return None
        button = view.button
        ap = lambda seat: 0 if seat == button else 1  # noqa: E731
        start_eff = min(view.starting_stacks[i] for i in range(2)) / view.bb
        self._depth = self.abs.depth_index(start_eff)
        s = self.abs.new_state(self._depth)
        start = list(view.starting_stacks)
        contrib = [0, 0]
        bets = [0, 0]
        street = 0
        for a in view.history:
            if a.kind.startswith("post"):
                if a.kind != "post_ante":
                    bets[a.seat] += a.added
                contrib[a.seat] += a.added
                continue
            if a.street != street:
                street = a.street
                bets = [0, 0]
            if s.terminal or s.street != a.street or s.to_act != ap(a.seat):
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
        if s.terminal or s.street != view.street or s.to_act != ap(view.seat):
            return None
        return s

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
