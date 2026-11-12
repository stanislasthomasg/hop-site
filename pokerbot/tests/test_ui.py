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


def test_app_api_roundtrip(tmp_path, monkeypatch):
    from pokerbot.ui.web_server import App
    monkeypatch.setattr(session_mod, "DATA_DIR", tmp_path)
    app = App(["abc"], seed=3, db=False)
    assert app.handle("/api/state", None) == (200, {"phase": "idle"})
    code, snap = app.handle("/api/new_session", {"opponents": ["abc"]})
    assert code == 200 and snap["phase"] in ("playing", "over")
    code, err = app.handle("/api/act", {"type": "raise", "amount": 1})
    assert code == 400 and "error" in err
    out = json.loads(app.handle_json("/api/new_hand", "{}"))
    assert out["status"] in (200, 400)


def test_history_never_shows_mucked_bot_cards(sess):
    from pokerbot.engine.cards import cards_to_str
    for _ in range(40):
        sess.new_hand()
        while sess.snapshot()["phase"] == "playing":
            sess.act(sess.parse_action("f"))           # human folds: no showdown
        rec = sess.last_record
        if not rec.showdown:
            bot_cards = cards_to_str(rec.hole_cards[1])
            assert bot_cards not in sess.snapshot()["history_text"]


def test_acpc_protocol():
    import random
    from pokerbot.bots import make_agent
    from pokerbot.evaluation.acpc import build_state, parse_matchstate, respond, to_acpc
    ms = parse_matchstate("MATCHSTATE:0:12:r300c/r600:Ks4c|/9h8d2c\r\n")
    assert ms.position == 0 and ms.hand == 12 and ms.betting == [["r300", "c"], ["r600"]]
    assert len(ms.holes[0]) == 2 and ms.holes[1] == [] and len(ms.board) == 3
    st = build_state(ms, random.Random(0))
    # Preflop: SB raises to 300, BB calls. Flop: the BB acts first and bets 300 (600 in total).
    assert st.street == 1 and st.to_act == 1 and st.current_bet == 300
    assert to_acpc(Action.raise_to(900), st) == "r1200"   # 300 preflop + 900 street total
    bot = make_agent("abc", seed=1)
    bot.table_names = ["opp", "me"]
    assert respond("MATCHSTATE:1:0::7s7d|\r\n", bot, random.Random(0)).startswith("MATCHSTATE:1:0::7s7d|:")
    assert respond("MATCHSTATE:0:0::|9c9d\r\n", bot, random.Random(0)) is None   # not our turn


def test_acpc_client_against_fake_dealer():
    import socket
    import threading
    from pokerbot.evaluation.acpc import play_acpc
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    got = []

    def dealer():
        conn, _ = srv.accept()
        f = conn.makefile("r", newline="\r\n")
        got.append(f.readline().strip())                      # VERSION
        conn.sendall(b"MATCHSTATE:1:0::AsAd|\r\n")             # we are the button, first to act
        got.append(f.readline().strip())
        conn.sendall(b"MATCHSTATE:1:0:f:AsAd|\r\n")            # hand over: no reply expected
        conn.close()
        srv.close()

    th = threading.Thread(target=dealer)
    th.start()
    assert play_acpc("127.0.0.1", port, "abc", verbose=False) == 1
    th.join()
    assert got[0] == "VERSION:2.0.0" and got[1].startswith("MATCHSTATE:1:0::AsAd|:r")   # AA raises


def test_pretrained_model_installs_on_first_run(tmp_path, monkeypatch):
    monkeypatch.setenv("POKERBOT_MODELS", str(tmp_path / "models"))
    from pokerbot.training.registry import list_versions, resolve
    assert resolve("best") == "bot_v2" and "bot_v2" in list_versions()
    from pokerbot.bots import make_agent
    bot = make_agent("bot:best", seed=0)
    assert bot.six is not None and len(bot.bp) > 1000
