from pokerbot.bots import RandomBot
from pokerbot.engine import HandStore, Table, format_hand

from helpers import make, play


def test_sqlite_roundtrip(tmp_path):
    db = tmp_path / "hands.db"
    with HandStore(db, session="t") as store:
        table = Table([RandomBot("a", seed=1), RandomBot("b", seed=2), RandomBot("c", seed=3)],
                      seed=7, store=store)
        recs = list(table.play(300))
    with HandStore(db) as store:
        assert store.count() == 300
        assert [r.to_dict() for r in store.iter_hands()] == [r.to_dict() for r in recs]
        res = {name: (k, net) for name, k, net, _ in store.player_results()}
        assert all(k == 300 for k, _ in res.values())
        assert abs(sum(net for _, net in res.values())) < 1e-9
        n_actions = store.conn.execute("SELECT COUNT(*) FROM actions").fetchone()[0]
        assert n_actions == sum(len(r.actions) for r in recs)


def test_text_history_side_pots():
    s = make([10000, 1000, 3000, 6000], ["7h 3d", "As Ah", "Ks Kh", "Qc Qd"],
             "2c 8d 9h Js 4s", button=0)
    play(s, "a", "c", "c", "c")
    text = format_hand(s.to_record(["btn", "sb", "bb", "utg"]))
    for expected in ["utg: raises to 6000 and is all-in", "*** RIVER ***",
                     "sb collected 4000 from main pot", "bb collected 6000 from side pot 1",
                     "utg collected 6000 from side pot 2", "*** SHOWDOWN ***"]:
        assert expected in text, expected


def test_hero_view_hides_mucked_cards():
    s = make([10000, 10000], ["7h 2d", "Ac Kc"], "2c 8d 9h Js 4s")
    play(s, "r300", "f")
    text = format_hand(s.to_record(["hero", "villain"]), hero=0)
    assert "7h 2d" in text and "Ac Kc" not in text
