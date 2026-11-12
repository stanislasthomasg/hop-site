"""Client for the ACPC dealer protocol (Annual Computer Poker Competition), the
standard way bots are connected to poker-bot competitions and research servers.
Simulation/competition only: these servers exist for bots to play each other.

Protocol (heads-up no-limit, game definition "holdem.nolimit.2p.reverse_blinds"):
  client -> "VERSION:2.0.0\\r\\n"
  server -> "MATCHSTATE:<position>:<hand>:<betting>:<cards>\\r\\n"
  client -> "<the same MATCHSTATE string>:<action>\\r\\n" when it is its turn,
            action = f | c | r<N>  (N = total chips committed in the hand after raising)
Positions: 0 = big blind, 1 = small blind/button. Stacks 20000, blinds 50/100.
Betting rounds are separated by '/', cards look like "Ks4c|/9h8d2c/Tc/3s".
"""
from __future__ import annotations

import random
import socket
from dataclasses import dataclass

from ..bots.base import Agent
from ..engine.actions import Action, ActionType
from ..engine.cards import parse_cards
from ..engine.state import HandState

SB, BB, STACK = 50, 100, 20_000


@dataclass
class MatchState:
    raw: str
    position: int
    hand: int
    betting: list[list[str]]
    holes: list[list[int]]       # [] for unknown cards
    board: list[int]


def parse_matchstate(line: str) -> MatchState:
    raw = line.strip()
    _, pos, hand, betting, cards = raw.split(":", 4)
    rounds = []
    for rnd in betting.split("/"):
        acts, i = [], 0
        while i < len(rnd):
            if rnd[i] == "r":
                j = i + 1
                while j < len(rnd) and rnd[j].isdigit():
                    j += 1
                acts.append(rnd[i:j])
                i = j
            else:
                acts.append(rnd[i])
                i += 1
        rounds.append(acts)
    parts = cards.split("/")
    holes = [parse_cards(h) if h else [] for h in parts[0].split("|")]
    board = [c for p in parts[1:] for c in parse_cards(p)]
    return MatchState(raw, int(pos), int(hand), rounds, holes, board)


def build_state(ms: MatchState, rng: random.Random) -> HandState:
    """Engine state for the hand so far; unknown cards are filled with unused ones."""
    known = [c for h in ms.holes for c in h] + ms.board
    rest = [c for c in range(52) if c not in known]
    rng.shuffle(rest)
    holes = []
    for h in (ms.holes + [[], []])[:2]:
        if len(h) == 2:
            holes.append(h)
        else:
            holes.append([rest.pop(), rest.pop()])
    board = ms.board + rest[: 5 - len(ms.board)]
    st = HandState([STACK, STACK], button=1, sb=SB, bb=BB, hole_cards=holes, board=board)
    for rnd in ms.betting:
        for tok in rnd:
            if st.is_over:
                break
            la = st.legal_actions()
            if tok == "f":
                st.apply(Action.fold())
            elif tok == "c":
                st.apply(la.check_or_call())
            else:  # r<N>: N = total committed in the hand
                p = st.players[st.to_act]
                street_start = p.total_bet - p.street_bet
                st.apply(Action.raise_to(int(tok[1:]) - street_start))
    return st


def to_acpc(action: Action, st: HandState) -> str:
    if action.type is ActionType.FOLD:
        return "f"
    if action.type in (ActionType.CHECK, ActionType.CALL):
        return "c"
    p = st.players[st.to_act]
    return f"r{p.total_bet - p.street_bet + action.amount}"


def respond(line: str, bot: Agent, rng: random.Random) -> str | None:
    """Reply to one server line, or None when it is not our turn / the hand is over."""
    if not line.startswith("MATCHSTATE:"):
        return None
    ms = parse_matchstate(line)
    st = build_state(ms, rng)
    if st.is_over or st.to_act != ms.position:
        return None
    action = bot.act(st.view(ms.position))
    return f"{ms.raw}:{to_acpc(action, st)}"


def play_acpc(host: str, port: int, spec: str = "bot:best", verbose: bool = True) -> int:
    """Connect to an ACPC dealer and play until it closes the connection."""
    from ..bots.registry import make_agent
    bot = make_agent(spec, name="pokerbot", seed=0)
    bot.table_names = ["opponent", "pokerbot"]
    rng = random.Random(0)
    hands = 0
    with socket.create_connection((host, port)) as sock:
        sock.sendall(b"VERSION:2.0.0\r\n")
        f = sock.makefile("r", encoding="ascii", newline="\r\n")
        for line in f:
            reply = respond(line, bot, rng)
            if reply:
                sock.sendall((reply + "\r\n").encode("ascii"))
            if line.startswith("MATCHSTATE:"):
                hands = max(hands, parse_matchstate(line).hand + 1)
                if verbose and hands % 1000 == 0:
                    print(f"  {hands} mains jouées", flush=True)
    return hands
