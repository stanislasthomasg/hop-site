"""EXPERIMENTAL client for Slumbot (https://slumbot.com), a public heads-up
research bot whose API is meant to be played by other bots (simulation, no
money). Not tested here: the development machine had no network access to
slumbot.com. Slumbot plays 200 bb stacks with 50/100 blinds; our blueprint
was trained at 100 bb, the bet translation still works by pot fractions.

API (from Slumbot's sample client): POST /api/new_hand {token?} and
POST /api/act {token, incr}. The action string uses k (check), c (call),
f (fold), b<N> (bet/raise to N chips on this street) and '/' between streets.
client_pos 1 = small blind/button, 0 = big blind. A finished hand carries
'winnings' (chips, from our point of view).
"""
from __future__ import annotations

import json
import random
import urllib.request

from ..bots.registry import make_agent
from ..engine.actions import Action, ActionType
from ..engine.cards import parse_cards
from ..engine.state import HandState
from .stats import bb100_ci

HOST = "https://slumbot.com"
SB, BB, STACK = 50, 100, 20_000


def _post(path: str, data: dict) -> dict:
    req = urllib.request.Request(HOST + path, data=json.dumps(data).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        out = json.loads(r.read())
    if "error_msg" in out:
        raise RuntimeError(out["error_msg"])
    return out


def _parse(action: str) -> list[tuple[int, str]]:
    """'b200c/kb300' -> [(0,'b200'), (0,'c'), (1,'k'), (1,'b300')]"""
    out, street, i = [], 0, 0
    while i < len(action):
        ch = action[i]
        if ch == "/":
            street += 1
            i += 1
        elif ch == "b":
            j = i + 1
            while j < len(action) and action[j].isdigit():
                j += 1
            out.append((street, action[i:j]))
            i = j
        else:
            out.append((street, ch))
            i += 1
    return out


def _state_from(resp: dict, rng: random.Random) -> HandState:
    me = parse_cards(resp["hole_cards"])
    board = parse_cards(resp.get("board", []))
    rest = [c for c in range(52) if c not in me and c not in board]
    rng.shuffle(rest)
    full_board = board + rest[: 5 - len(board)]
    villain = rest[5 - len(board): 7 - len(board)]
    button = 0 if resp["client_pos"] == 1 else 1   # we sit in seat 0
    st = HandState([STACK, STACK], button=button, sb=SB, bb=BB,
                   hole_cards=[me, villain], board=full_board)
    for _, tok in _parse(resp.get("action", "")):
        if tok == "k":
            st.apply(Action.check())
        elif tok == "c":
            st.apply(Action.call())
        elif tok == "f":
            st.apply(Action.fold())
        else:
            st.apply(Action.raise_to(int(tok[1:])))
    return st


def _to_incr(a: Action) -> str:
    return {ActionType.FOLD: "f", ActionType.CHECK: "k", ActionType.CALL: "c"}.get(a.type) or f"b{a.amount}"


def play_slumbot(hands: int, spec: str = "bot:best", token: str | None = None, verbose: bool = True):
    bot = make_agent(spec, name="pokerbot", seed=0)
    bot.table_names = ["pokerbot", "slumbot"]
    rng = random.Random(0)
    results = []
    for h in range(hands):
        r = _post("/api/new_hand", {"token": token} if token else {})
        token = r.get("token", token)
        while "winnings" not in r:
            st = _state_from(r, rng)
            if st.is_over or st.to_act != 0:
                raise RuntimeError(f"unexpected state from Slumbot: {r}")
            r = _post("/api/act", {"token": token, "incr": _to_incr(bot.act(st.view(0)))})
            token = r.get("token", token)
        results.append(r["winnings"] / BB)
        if verbose and (h + 1) % 100 == 0:
            m, lo, hi = bb100_ci(results)
            print(f"  {h + 1} hands vs Slumbot: {m:+.1f} bb/100 [{lo:+.1f}, {hi:+.1f}]", flush=True)
    return bb100_ci(results), results
