import pytest

from pokerbot.bots import make_agent
from pokerbot.engine import Table
from pokerbot.engine.equity import equity_vs_random, hand_class, preflop_equity, top_range
from pokerbot.engine import parse_cards
from pokerbot.evaluation.stats import bb100_ci, compute_stats

from helpers import make, play


def test_hand_classes_and_ranges():
    assert hand_class(parse_cards("Ah Kh")) == "AKs"
    assert hand_class(parse_cards("2c 7d")) == "72o"
    assert hand_class(parse_cards("Td Tc")) == "TT"
    assert preflop_equity(parse_cards("As Ad")) > 0.84
    assert "AA" in top_range(0.02) and "72o" not in top_range(0.5)
    combos = sum(6 if len(c) == 2 else 4 if c[2] == "s" else 12 for c in top_range(0.2))
    assert 0.19 * 1326 <= combos <= 0.23 * 1326


def test_equity_monte_carlo():
    import random
    rng = random.Random(0)
    nuts = equity_vs_random(parse_cards("As Ks"), parse_cards("Qs Js Ts"), 1, 300, rng)
    assert nuts == 1.0
    dominated = equity_vs_random(parse_cards("2c 3d"), parse_cards("Ah Kh Qh Jd 9s"), 1, 500, rng)
    assert dominated < 0.2  # ties when the board plays


def test_stats_on_scripted_hand():
    s = make([10000, 10000], ["Ah Kh", "Qc Qd"], "2c 8d 9h Js 4s", button=0)
    play(s, "r300", "r900", "c")       # BTN opens, BB 3-bets, BTN calls
    play(s, "r600", "f")               # BB c-bets the flop, BTN folds
    st = compute_stats([s.to_record(["btn", "bb"])])
    btn, bb = st["btn"], st["bb"]
    assert (btn.vpip.hits, btn.pfr.hits, bb.vpip.hits, bb.pfr.hits) == (1, 1, 1, 1)
    assert (bb.three_bet.hits, bb.three_bet.opps) == (1, 1)
    assert (btn.fold_to_3bet.hits, btn.fold_to_3bet.opps) == (0, 1)
    assert (bb.cbet.hits, bb.cbet.opps) == (1, 1)
    assert (btn.fold_to_cbet.hits, btn.fold_to_cbet.opps) == (1, 1)
    assert bb.post_aggr == 1 and btn.post_calls == 0


def test_bb100_ci():
    m, lo, hi = bb100_ci([1.0, -1.0] * 500)
    assert m == 0 and lo < 0 < hi


@pytest.fixture(scope="module")
def six_max_stats():
    specs = ["random", "station", "nit", "maniac", "abc", "abc"]
    agents = [make_agent(s, name=f"{s}{i}", seed=i) for i, s in enumerate(specs)]
    return compute_stats(Table(agents, seed=3).play(2500))


def test_profiles_match_their_style(six_max_stats):
    st = {k.rstrip("0123456789"): v for k, v in six_max_stats.items()}
    assert st["nit"].vpip.pct < 14
    assert st["station"].vpip.pct > 45 and st["station"].pfr.pct < 6 and st["station"].af < 0.5
    assert st["maniac"].pfr.pct > 35 and st["maniac"].af > 3
    assert 14 < st["abc"].vpip.pct < 26 and st["abc"].pfr.pct > 10
