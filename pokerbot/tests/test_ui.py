import json

import pytest

from pokerbot.engine import Action
from pokerbot.evaluation.slumbot import _parse, _state_from, _to_incr
from pokerbot.ui import session as session_mod
from pokerbot.ui.session import GameSession


@pytest.fixture()
def sess(tmp_path, monkeypatch):
    monkeypatch.setattr(session_mod, "DATA_DIR", tmp_path)
    s = GameSession(["abc"], seed=1, db=tmp_path / "h.db")
    yield s
    s.close()


def test_snapshot_hides_opponent_cards(sess):
    sess.new_hand()
    snap = sess.snapshot()
    assert snap["seats"][0]["cards"] is not None
    if snap["phase"] == "playing":
        assert snap["seats"][1]["cards"] is None
    json.dumps(snap)                                   # serialisable for the web page


def test_session_plays_and_records(sess):
    for _ in range(10):
        sess.new_hand()
        while sess.snapshot()["phase"] == "playing":
            sess.act(sess.parse_action("c"))
    st = sess.session_stats()
    assert st["hands"] == 10 and len(st["curve"]) == 10
    assert sess.store.count() == 10


def test_parse_terminal_commands(sess):
    sess.new_hand()
    while sess.snapshot()["phase"] == "over":
        sess.new_hand()
    with pytest.raises(ValueError):
        sess.parse_action("r 0.1")
    assert sess.parse_action("a").type in (Action.raise_to(1).type, Action.call().type)


def test_slumbot_action_parsing():
    assert _parse("b200c/kb300") == [(0, "b200"), (0, "c"), (1, "k"), (1, "b300")]
    resp = {"hole_cards": ["Ac", "Kd"], "board": ["2c", "7h", "9s"], "client_pos": 0,
            "action": "b250c/"}
    st = _state_from(resp, __import__("random").Random(0))
    assert st.street == 1 and st.to_act == 0          # we are the BB: first to act postflop
    from pokerbot.engine import parse_cards
    assert st.board == parse_cards("2c 7h 9s")        # the real flop, not placeholders
    assert _to_incr(Action.raise_to(600)) == "b600" and _to_incr(Action.check()) == "k"


def test_dashboard_export(tmp_path, monkeypatch):
    monkeypatch.setenv("POKERBOT_MODELS", str(tmp_path / "models"))
    from pokerbot.ui import dashboard
    monkeypatch.setattr(dashboard, "DATA_DIR", tmp_path)
    out = dashboard.export_html(tmp_path / "d.html")
    html = out.read_text()
    assert "window.DASHBOARD_DATA" in html and "<style>" in html and "/static/" not in html
