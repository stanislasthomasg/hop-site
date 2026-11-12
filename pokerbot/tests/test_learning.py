import random

import pytest

from pokerbot.bots.exploit import OpponentModel, adjust
from pokerbot.bots.learner import LearnerBot, pseudo_harmonic
from pokerbot.engine import Action, HandState, Table
from pokerbot.bots import make_agent
from pokerbot.training.abstract_game import AState, replay
from pokerbot.training.abstraction import CardAbstraction
from pokerbot.training.mccfr import Tables, TrainConfig, average_strategy, regret_matching, train
from pokerbot.evaluation.duplicate import duplicate_match


@pytest.fixture(scope="module")
def tiny_model():
    ab = CardAbstraction(buckets=(4, 4, 4), samples=32).fit(300)
    t = Tables()
    train(t, ab, TrainConfig(iterations=1500, batch=250, workers=2))
    return t, ab


def test_abstract_game_rules():
    s = AState()
    assert s.to_act == 0 and s.legal() == "fchpda"
    assert [s.raise_to(c) for c in "hpd"] == [200, 300, 500]
    s = s.child("c")
    assert s.to_act == 1 and "k" in s.legal()          # BB option
    s = s.child("k")
    assert s.street == 1 and s.to_act == 1 and s.history == "ck/"
    s = replay("ck/kk/kk/kk")
    assert s.terminal and s.folder == -1
    assert s.utility(0, +1) == 100 and s.utility(1, +1) == -100
    s = replay("a")
    assert s.legal() == "fc"
    assert replay("af").utility(0, 0) == 100           # BB folds to the shove
    s = replay("ac")
    assert s.terminal and s.contrib == [10000, 10000]


def test_raise_cap():
    s = replay("pppp")                                 # 4 raises preflop
    assert s.legal() == "fc"


def test_regret_matching():
    assert regret_matching([1.0, 3.0, -2.0]) == [0.25, 0.75, 0.0]
    assert regret_matching([-1.0, -1.0]) == [0.5, 0.5]


def test_training_builds_a_valid_strategy(tiny_model):
    t, ab = tiny_model
    bp = average_strategy(t)
    assert len(bp) > 1000
    for key, (acts, probs) in list(bp.items())[:2000]:
        assert len(acts) == len(probs) and abs(sum(probs) - 1) < 1e-3
        hist = key.split(":", 1)[1]
        assert replay(hist).legal() == acts            # actions stored match the tree


def test_aa_never_folds_preflop(tiny_model):
    t, ab = tiny_model
    bp = average_strategy(t)
    acts, probs = bp["0:"]                             # class 0 = AA, SB first to act
    assert probs[acts.index("f")] < 0.15


def test_pseudo_harmonic_mapping():
    assert pseudo_harmonic(0.5, 0.5, 1.0) == pytest.approx(1.0)
    assert pseudo_harmonic(1.0, 0.5, 1.0) == pytest.approx(0.0)
    assert 0.4 < pseudo_harmonic(0.75, 0.5, 1.0) < 0.6


def test_translation_of_real_hand(tiny_model):
    t, ab = tiny_model
    bot = LearnerBot(average_strategy(t), ab, seed=0)
    s = HandState([10000, 10000], button=0, rng=random.Random(1))
    s.apply(Action.raise_to(300))                      # exactly 'p' (pot) preflop
    s.apply(Action.call())
    s.apply(Action.check())                            # BB checks the flop
    a = bot.translate(s.view())
    assert a is not None and a.history == "pc/k" and a.to_act == 0
    s.apply(Action.raise_to(int(0.5 * s.pot)))         # half-pot bet
    a = bot.translate(s.view())
    assert a.history == "pc/kh"


def test_learner_plays_legal_hands_vs_profiles(tiny_model):
    t, ab = tiny_model
    bot = LearnerBot(average_strategy(t), ab, name="learner", seed=1)
    for opp in ("station", "maniac", "abc"):
        table = Table([bot, make_agent(opp, seed=2)], seed=5)
        list(table.play(150))
    assert bot.stats["blueprint"] > 0
    assert "Stratégie CFR" in bot.last_explanation or "Pas de stratégie CFR" in bot.last_explanation


def test_opponent_model_and_adjustment():
    m = OpponentModel("villain")
    m.f["fold_vs_bet"].hits, m.f["fold_vs_bet"].opps = 450, 500   # folds 90% to bets
    probs, why = adjust("khpa", [0.7, 0.1, 0.1, 0.1], m, strength=0.2, facing_bet=False, preflop=False)
    assert sum(probs[1:]) > 0.3 and why                # bluffs more
    empty = OpponentModel("new")
    probs2, why2 = adjust("khpa", [0.7, 0.1, 0.1, 0.1], empty, 0.2, False, False)
    assert probs2 == pytest.approx([0.7, 0.1, 0.1, 0.1]) and not why2   # no data -> blueprint


def test_duplicate_is_zero_sum_and_symmetric():
    res = duplicate_match(["abc", "abc"], deals=60, seed=3, workers=2)
    assert len(res.samples[0]) == 60
    for a, b in zip(res.samples[0], res.samples[1]):
        assert a == pytest.approx(-b)
