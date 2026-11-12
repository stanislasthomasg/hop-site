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
    small = replay("h", cheap_raises=1, max_raises=3)  # smaller tree used from v2 on
    assert small.legal() == "fcpa"
    assert replay("hpa", cheap_raises=1, max_raises=3).legal() == "fc"


def test_regret_matching():
    assert regret_matching([1.0, 3.0, -2.0]) == [0.25, 0.75, 0.0]
    assert regret_matching([-1.0, -1.0]) == [0.5, 0.5]


def test_training_builds_a_valid_strategy(tiny_model):
    t, ab = tiny_model
    bp = average_strategy(t)
    assert len(bp) > 1000
    for key, (acts, probs, weight) in list(bp.items())[:2000]:
        assert weight > 0
        assert len(acts) == len(probs) and abs(sum(probs) - 1) < 1e-3
        hist = key.split(":", 1)[1]
        assert replay(hist).legal() == acts            # actions stored match the tree


def test_aa_never_folds_preflop(tiny_model):
    t, ab = tiny_model
    bp = average_strategy(t)
    acts, probs, _ = bp["0:"]                          # class 0 = AA, SB first to act
    assert probs[acts.index("f")] < 0.15


def test_pseudo_harmonic_mapping():
    assert pseudo_harmonic(0.5, 0.5, 1.0) == pytest.approx(1.0)
    assert pseudo_harmonic(1.0, 0.5, 1.0) == pytest.approx(0.0)
    assert 0.4 < pseudo_harmonic(0.75, 0.5, 1.0) < 0.6


def test_translation_of_real_hand(tiny_model):
    t, ab = tiny_model
    bot = LearnerBot(average_strategy(t), ab, seed=0, min_weight=0)
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
    bot = LearnerBot(average_strategy(t), ab, name="learner", seed=1, min_weight=0)
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


def test_rake_in_abstract_utility():
    s = AState(10_000, rake_pct=0.05, rake_cap=100)
    s = s.child("p").child("f")                        # preflop fold: no rake
    assert s.utility(0, 0) == 100
    s = AState(10_000, rake_pct=0.05, rake_cap=100)
    for ch in "ck" + "kk" + "kk" + "kk":
        s = s.child(ch)
    assert s.terminal
    assert s.utility(0, +1) == 100 - 10 and s.utility(1, +1) == -100   # 5% of 200
    assert s.utility(0, 0) == -5                        # split pot: rake shared


def test_depth_selection():
    ab = CardAbstraction(depths_bb=(50, 100, 200))
    assert [ab.depth_index(x) for x in (30, 60, 80, 100, 140, 160, 400)] == [0, 0, 1, 1, 1, 2, 2]
    assert ab.new_state(2).stack == 20_000 and ab.key_prefix(1) == "1|"
    assert CardAbstraction().key_prefix(0) == ""        # single-depth versions keep old keys


def test_size_specific_fold_tracking_and_tilt():
    from pokerbot.engine import parse_cards
    m = OpponentModel("villain")
    # villain folds to every half-pot flop bet, never to pot-sized ones
    for i in range(120):
        s = HandState([10000, 10000], button=0, hole_cards=[parse_cards("Ah Kh"), parse_cards("7c 2d")],
                      board=parse_cards("2s 8d 9h Js 4c"))
        s.apply(Action.call()); s.apply(Action.check())              # limp, check
        s.apply(Action.check())                                      # BB (villain) checks the flop
        size = int(0.5 * s.pot) if i % 2 == 0 else s.pot
        s.apply(Action.raise_to(size))                               # hero bets
        s.apply(Action.fold() if i % 2 == 0 else Action.call())
        while not s.is_over:
            s.apply(Action.check())                                  # check it down
        m.update(1, s.to_record())
    assert m.f["fvb1small"].opps == 60 and m.f["fvb1small"].hits == 60
    assert m.f["fvb1big"].opps == 60 and m.f["fvb1big"].hits == 0
    probs, why = adjust("khpa", [0.7, 0.1, 0.1, 0.1], m, strength=0.2, facing_bet=False,
                        preflop=False, street=1)
    assert probs[1] > probs[2]                 # bluff with the small size he folds to
    assert any("petites mises" in w for w in why)
    assert m.profile_label()


def test_duplicate_cash_conditions_pay_rake():
    res = duplicate_match(["abc", "abc"], deals=80, seed=5, workers=2, cash=True)
    total = sum(res.samples[0]) + sum(res.samples[1])
    assert total < 0                                   # the rake leaves the table


def test_sixmax_game_and_bot_mapping():
    from pokerbot.training.sixmax import PState, replay, train_sixmax
    s = replay("offffc")                                # UTG opens, BB calls
    # UTG is in position against the BB after the flop: realises 105% of the pot
    assert s.terminal and s.utility(0, [9, 0, 0, 0, 0, 1]) == pytest.approx((550 - 27.5) * 1.05 - 250)
    assert replay("ffffc").legal() == "ko"              # SB completes: BB option
    t = Tables()
    train_sixmax(t, 400, workers=1, batch=400, verbose=False)
    six = average_strategy(t)
    tiny = CardAbstraction(buckets=(2, 2, 2), samples=8).fit(50)
    bot = LearnerBot({}, tiny, name="bot", seed=1, min_weight=0, sixmax=six)
    others = [make_agent("abc", name=f"abc{i}", seed=i) for i in range(5)]
    table = Table([bot] + others, seed=2)
    list(table.play(200))
    assert bot.stats["blueprint"] > 0                   # 6-max preflop strategy used


def test_synthetic_preflop_for_heads_up_pots_in_6max():
    from pokerbot.engine import parse_cards
    tiny = CardAbstraction(buckets=(2, 2, 2), samples=8).fit(50)
    bot = LearnerBot({}, tiny, seed=0)
    holes = [parse_cards(h) for h in ("2c 3c", "4c 5c", "6c 7c", "8c 9c", "Tc Jc", "Qc Kc")]
    s = HandState([10000] * 6, button=0, hole_cards=holes, board=parse_cards("2d 8d 9h Js 4s"))
    # UTG (3) opens, everyone folds but the BB (2) who calls -> BB out of position
    s.apply(Action.raise_to(250))
    for _ in range(4):
        s.apply(Action.fold())
    s.apply(Action.call())
    assert s.street == 1 and s.to_act == 2
    a = bot.translate(s.view())
    assert a is not None and a.history == "pc/" and a.to_act == 1   # BB = abstract OOP player


def test_river_solver_value_bets_nuts_and_folds_air():
    """River solve on a fixed spot: with the nuts the bot bets, with nothing it does not call."""
    from pokerbot.bots.river_search import RiverSolver
    from pokerbot.engine import parse_cards
    tiny = CardAbstraction(buckets=(2, 2, 2), samples=8).fit(50)
    solver = RiverSolver(tiny, {}, iterations=60, min_rel_weight=0.0, max_hands=200)
    board = parse_cards("Ah Kd 7c 4s 2h")
    root = replay("pc/kk/kk/")                      # checked down to the river, pot 600
    assert root.street == 3 and root.to_act == 1
    acts, probs, _ = solver.solve(root, "k", board, parse_cards("As Ad"), 0, [])
    bet = sum(p for a, p in zip(acts, probs) if a in "hpda")
    assert acts == "khpda" and bet > 0.6               # top set in position: bet
    acts, probs, _ = solver.solve(root, "p", board, parse_cards("6d 3c"), 0, [])
    assert acts[0] == "f" and probs[0] > 0.6           # 6-high facing a pot bet: mostly fold
