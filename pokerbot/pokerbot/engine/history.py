"""Hand history: readable text and SQLite storage.

Schema (one row per hand, per seat and per action) is query-friendly so the
opponent-modeling and dashboard steps can compute VPIP/PFR/AF in SQL.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable, Iterator

from .cards import cards_to_str
from .records import STREET_NAMES, HandRecord

# ---------------------------------------------------------------------------- text


def _chips(x: int, bb: int, in_bb: bool) -> str:
    if not in_bb:
        return str(x)
    v = x / bb
    return f"{v:g}bb"


def format_hand(rec: HandRecord, in_bb: bool = False, hero: int | None = None) -> str:
    """PokerStars-like hand history. ``hero`` hides other players' unshown cards."""
    c = lambda x: _chips(x, rec.bb, in_bb)  # noqa: E731
    name = rec.names
    out = [
        f"Hand #{rec.hand_no}  NLHE {c(rec.sb)}/{c(rec.bb)}"
        + (f" ante {c(rec.ante)}" if rec.ante else "")
        + (f"  table '{rec.table}'" if rec.table else "")
        + (f"  {rec.played_at}" if rec.played_at else ""),
        f"{rec.n_players}-handed, seat {rec.button + 1} is the button",
    ]
    for s in range(rec.n_players):
        out.append(f"Seat {s + 1}: {name[s]} [{rec.positions[s]}] ({c(rec.starting_stacks[s])} in chips)")

    def flush_uncalled(st: int) -> None:
        for u_st, seat, amt in rec.uncalled:
            if u_st == st:
                out.append(f"Uncalled bet ({c(amt)}) returned to {name[seat]}")

    street = -1
    for a in rec.actions:
        if a.kind.startswith("post"):
            label = {"post_ante": "posts the ante", "post_sb": "posts small blind",
                     "post_bb": "posts big blind"}[a.kind]
            out.append(f"{name[a.seat]}: {label} {c(a.added)}" + (" and is all-in" if a.all_in else ""))
            continue
        if a.street != street:
            if street >= 0:
                flush_uncalled(street)
            street = a.street
            out.extend(_street_header(rec, street, hero))
        allin = " and is all-in" if a.all_in else ""
        if a.kind in ("fold", "check"):
            out.append(f"{name[a.seat]}: {a.kind}s")
        elif a.kind == "call":
            out.append(f"{name[a.seat]}: calls {c(a.added)}{allin}")
        elif a.kind == "bet":
            out.append(f"{name[a.seat]}: bets {c(a.amount)}{allin}")
        else:
            out.append(f"{name[a.seat]}: raises to {c(a.amount)}{allin}")
    if street < 0:  # nobody acted voluntarily (e.g. all-in on the blinds)
        out.extend(_street_header(rec, 0, hero))
        street = 0
    flush_uncalled(street)
    # Streets dealt without any betting (all-in run-outs)
    last_street = 3 if rec.showdown else street
    for st in range(street + 1, last_street + 1):
        out.extend(_street_header(rec, st, hero))
    if rec.showdown:
        out.append("*** SHOWDOWN ***")
        for s in rec.showdown:
            out.append(f"{name[s]}: shows [{cards_to_str(rec.hole_cards[s])}] ({rec.hand_values[s]})")
    for i, p in enumerate(rec.pots):
        label = "the pot" if len(rec.pots) == 1 else ("main pot" if i == 0 else f"side pot {i}")
        for s, won in p["shares"].items():
            out.append(f"{name[s]} collected {c(won)} from {label}")
    out.append("*** SUMMARY ***")
    out.append(f"Total pot {c(rec.total_pot + rec.rake)}"
               + (f" | Rake {c(rec.rake)}" if rec.rake else "")
               + (f" | Board [{cards_to_str(rec.board)}]" if rec.board else ""))
    for s in range(rec.n_players):
        net = rec.payoffs[s]
        sign = "+" if net > 0 else ""
        cards = ""
        if hero is None or s == hero or s in rec.showdown:
            cards = f" [{cards_to_str(rec.hole_cards[s])}]"
        out.append(f"Seat {s + 1}: {name[s]} ({rec.positions[s]}){cards} net {sign}{c(net)}")
    return "\n".join(out)


def _street_header(rec: HandRecord, street: int, hero: int | None) -> list[str]:
    if street == 0:
        lines = ["*** HOLE CARDS ***"]
        for s in range(rec.n_players):
            if hero is None or s == hero:
                lines.append(f"Dealt to {rec.names[s]} [{cards_to_str(rec.hole_cards[s])}]")
        return lines
    name = STREET_NAMES[street].upper()
    shown = rec.board[: {1: 3, 2: 4, 3: 5}[street]]
    if street == 1:
        return [f"*** {name} *** [{cards_to_str(shown)}]"]
    return [f"*** {name} *** [{cards_to_str(shown[:-1])}] [{cards_to_str(shown[-1:])}]"]


# ---------------------------------------------------------------------------- SQLite

SCHEMA = """
CREATE TABLE IF NOT EXISTS hands (
    hand_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    session     TEXT,
    table_name  TEXT,
    hand_no     INTEGER,
    played_at   TEXT,
    n_players   INTEGER,
    button      INTEGER,
    sb          INTEGER,
    bb          INTEGER,
    ante        INTEGER,
    board       TEXT,
    total_pot   INTEGER,
    final_street INTEGER,
    seed        INTEGER,
    record_json TEXT
);
CREATE TABLE IF NOT EXISTS hand_players (
    hand_id     INTEGER,
    seat        INTEGER,
    name        TEXT,
    position    TEXT,
    hole        TEXT,
    start_stack INTEGER,
    payoff      INTEGER,
    showed      INTEGER,
    PRIMARY KEY (hand_id, seat)
);
CREATE TABLE IF NOT EXISTS actions (
    hand_id  INTEGER,
    seq      INTEGER,
    street   INTEGER,
    seat     INTEGER,
    kind     TEXT,
    amount   INTEGER,
    added    INTEGER,
    all_in   INTEGER,
    PRIMARY KEY (hand_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_hp_name ON hand_players(name);
CREATE INDEX IF NOT EXISTS idx_hands_session ON hands(session);
"""


class HandStore:
    """Append-only SQLite store. Writes are buffered and committed in batches."""

    def __init__(self, path: str | Path, session: str = "", batch_size: int = 500) -> None:
        self.path = str(path)
        self.session = session
        self.batch_size = batch_size
        self.conn = sqlite3.connect(self.path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(SCHEMA)
        self._pending = 0

    def add(self, rec: HandRecord) -> int:
        cur = self.conn.execute(
            "INSERT INTO hands (session, table_name, hand_no, played_at, n_players, button, sb, bb,"
            " ante, board, total_pot, final_street, seed, record_json)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (self.session, rec.table, rec.hand_no, rec.played_at, rec.n_players, rec.button,
             rec.sb, rec.bb, rec.ante, cards_to_str(rec.board), rec.total_pot, rec.final_street,
             rec.seed, json.dumps(rec.to_dict(), separators=(",", ":"))),
        )
        hand_id = cur.lastrowid
        self.conn.executemany(
            "INSERT INTO hand_players VALUES (?,?,?,?,?,?,?,?)",
            [(hand_id, s, rec.names[s], rec.positions[s], cards_to_str(rec.hole_cards[s]),
              rec.starting_stacks[s], rec.payoffs[s], int(s in rec.showdown))
             for s in range(rec.n_players)],
        )
        self.conn.executemany(
            "INSERT INTO actions VALUES (?,?,?,?,?,?,?,?)",
            [(hand_id, i, a.street, a.seat, a.kind, a.amount, a.added, int(a.all_in))
             for i, a in enumerate(rec.actions)],
        )
        self._pending += 1
        if self._pending >= self.batch_size:
            self.commit()
        return hand_id

    def add_many(self, records: Iterable[HandRecord]) -> None:
        for r in records:
            self.add(r)
        self.commit()

    def commit(self) -> None:
        self.conn.commit()
        self._pending = 0

    def close(self) -> None:
        self.commit()
        self.conn.close()

    def __enter__(self) -> "HandStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------------ reading
    def get(self, hand_id: int) -> HandRecord:
        row = self.conn.execute("SELECT record_json FROM hands WHERE hand_id=?", (hand_id,)).fetchone()
        if row is None:
            raise KeyError(hand_id)
        return HandRecord.from_dict(json.loads(row[0]))

    def iter_hands(self, session: str | None = None) -> Iterator[HandRecord]:
        q, args = "SELECT record_json FROM hands", ()
        if session is not None:
            q, args = q + " WHERE session=?", (session,)
        for (js,) in self.conn.execute(q + " ORDER BY hand_id", args):
            yield HandRecord.from_dict(json.loads(js))

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM hands").fetchone()[0]

    def player_results(self, session: str | None = None) -> list[tuple[str, int, float, float]]:
        """(name, hands, net bb, bb/100) per player."""
        q = ("SELECT hp.name, COUNT(*), SUM(CAST(hp.payoff AS REAL) / h.bb)"
             " FROM hand_players hp JOIN hands h USING (hand_id)")
        args: tuple = ()
        if session is not None:
            q += " WHERE h.session=?"
            args = (session,)
        q += " GROUP BY hp.name ORDER BY 3 DESC"
        return [(n, k, net, 100 * net / k) for n, k, net in self.conn.execute(q, args)]
