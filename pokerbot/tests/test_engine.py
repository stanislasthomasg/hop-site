import random

import pytest

from pokerbot.engine import Action, HandState, IllegalActionError, Street, Table
from pokerbot.bots import RandomBot

from helpers import make, play

BOARD_DRY = "2c 8d 9h Js 4s"
ROYAL = "As Ks Qs Js Ts"


# ---------------------------------------------------------------- heads-up order
def test_heads_up_button_posts_sb_and_acts_first_preflop():
    s = make([10000, 10000], ["7h 2d", "Ac Kc"], BOARD_DRY, button=0)
    assert s.sb_seat == 0 and s.bb_seat == 1
    assert s.players[0].street_bet == 50 and s.players[1].street_bet == 100
    assert s.to_act == 0
    la = s.legal_actions()
    assert la.call_amount == 50 and la.min_raise_to == 200 and la.max_raise_to == 10000
    assert not la.can_check


def test_heads_up_bb_option_then_bb_acts_first_postflop():
    s = make([10000, 10000], ["7h 2d", "Ac Kc"], BOARD_DRY, button=0)
    play(s, "c")                         # SB limps
    assert s.to_act == 1                 # BB has the option
    la = s.legal_actions()
    assert la.can_check and la.can_raise and not la.can_fold
    play(s, "x")
    assert s.street == Street.FLOP and len(s.board) == 3
    assert s.to_act == 1                 # BB (out of position) first postflop


# ---------------------------------------------------------------- 6-max order
def test_six_max_positions_and_order():
    s = make([10000] * 6, ["2c 3c", "4c 5c", "6c 7c", "8c 9c", "Tc Jc", "Qc Kc"],
             "2d 8d 9h Js 4s", button=0)
    assert s.positions == ["BTN", "SB", "BB", "UTG", "HJ", "CO"]
    assert s.to_act == 3                 # UTG opens
    play(s, "f", "f", "c", "c", "c")     # UTG, HJ fold; CO, BTN, SB call
    assert s.to_act == 2                 # BB option
    play(s, "x")
    assert s.street == Street.FLOP and s.to_act == 1   # SB first postflop


def test_walk_returns_uncalled_bb():
    s = make([10000] * 6, ["2c 3c", "4c 5c", "6c 7c", "8c 9c", "Tc Jc", "Qc Kc"],
             "2d 8d 9h Js 4s", button=0)
    play(s, "f", "f", "f", "f", "f")
    assert s.is_over and s.payoffs == [0, -50, 50, 0, 0, 0]
    assert s.uncalled == [(0, 2, 50)]


# ---------------------------------------------------------------- raise sizes
def test_min_raise_tracks_last_full_raise():
    s = make([10000] * 3, ["2h 3h", "4h 5h", "6h 7h"], BOARD_DRY, button=0)
    play(s, "r300")                      # BTN opens to 300 (raise of 200)
    assert s.legal_actions().min_raise_to == 500
    play(s, "r900")                      # SB 3-bets to 900 (raise of 600)
    assert s.legal_actions().min_raise_to == 1500
    with pytest.raises(IllegalActionError):
        s.apply(Action.raise_to(1400))
    with pytest.raises(IllegalActionError):
        s.apply(Action.check())


def test_postflop_min_bet_is_one_big_blind():
    s = make([10000, 10000], ["7h 2d", "Ac Kc"], BOARD_DRY)
    play(s, "c", "x")
    la = s.legal_actions()
    assert la.can_check and la.min_raise_to == 100
    play(s, "r100")
    assert s.legal_actions().min_raise_to == 200


def _incomplete_raise_spot(bb_stack):
    # 3-handed, button 0, SB 1, BB 2. Everyone limps/checks to the flop.
    s = make([10000, 10000, bb_stack], ["2h 3h", "4h 5h", "6h 7h"], BOARD_DRY, button=0)
    play(s, "c", "c", "x")
    assert s.street == Street.FLOP and s.to_act == 1
    play(s, "r300")                      # SB bets 300
    play(s, "a")                         # BB shoves
    return s


def test_short_all_in_does_not_reopen_betting():
    s = _incomplete_raise_spot(bb_stack=100 + 450)  # BB all-in to 450 < min raise 600
    assert s.players[2].all_in and s.current_bet == 450
    assert s.to_act == 0
    assert s.legal_actions().can_raise   # BTN has not acted yet: may raise
    play(s, "c")
    assert s.to_act == 1
    la = s.legal_actions()
    assert la.can_call and la.call_amount == 150
    assert not la.can_raise              # SB faced only an incomplete raise


def test_full_all_in_reopens_betting():
    s = _incomplete_raise_spot(bb_stack=100 + 700)  # BB all-in to 700 >= min raise 600
    play(s, "c")
    la = s.legal_actions()
    assert la.can_raise and la.min_raise_to == 700 + 400


# ---------------------------------------------------------------- all-in & uncalled
def test_shove_fold_returns_uncalled():
    s = make([10000, 10000], ["7h 2d", "Ac Kc"], BOARD_DRY)
    play(s, "a", "f")
    assert s.is_over and s.payoffs == [100, -100]
    assert s.uncalled == [(0, 0, 9900)]
    assert s.board == []                 # no showdown, no board dealt


def test_call_all_in_for_less_returns_excess_and_runs_out_board():
    s = make([10000, 3000], ["Ah Ad", "Kc Kd"], BOARD_DRY)
    play(s, "a", "c")
    assert s.is_over and s.street == Street.SHOWDOWN
    assert len(s.board) == 5
    assert s.uncalled == [(0, 0, 7000)]
    assert s.payoffs == [3000, -3000]


def test_multiple_all_ins_build_three_pots():
    # button 0, SB 1 (1000 chips), BB 2 (3000), UTG 3 (6000), BTN 0 (10000)
    s = make([10000, 1000, 3000, 6000],
             ["7h 3d", "As Ah", "Ks Kh", "Qc Qd"], BOARD_DRY, button=0)
    play(s, "a", "c", "c", "c")          # UTG shoves 6000, BTN calls, SB+BB call all-in
    assert s.is_over and len(s.board) == 5
    rec = s.to_record()
    assert [(p["amount"], p["eligible"]) for p in rec.pots] == [
        (4000, [0, 1, 2, 3]), (6000, [0, 2, 3]), (6000, [0, 3])]
    assert [p["winners"] for p in rec.pots] == [[1], [2], [3]]
    assert s.payoffs == [-6000, 3000, 3000, 0]
    assert s.players[0].stack == 4000


def test_all_in_three_way_split_with_side_pot():
    s = make([1000, 5000, 5000], ["2c 3d", "4c 5d", "6c 7d"], ROYAL, button=0)
    play(s, "a", "a", "c")
    assert s.is_over and s.payoffs == [0, 0, 0]
    rec = s.to_record()
    assert len(rec.pots) == 2 and rec.pots[0]["amount"] == 3000 and rec.pots[1]["amount"] == 8000


def test_split_pot_odd_chip():
    # Blinds 5/10. BTN calls, SB folds (dead 5), BB checks -> pot 25 split BTN/BB.
    s = make([1000] * 3, ["2c 3d", "4c 5d", "6c 7d"], ROYAL, button=0, sb=5, bb=10)
    play(s, "c", "f", "x")
    play(s, "x", "x", "x", "x", "x", "x")
    assert s.is_over
    assert s.payoffs == [2, -5, 3]       # BB is first left of the button among winners


def test_short_bb_posts_all_in_and_cannot_be_raised():
    s = make([10000, 60], ["7h 2d", "Ac Kc"], BOARD_DRY)
    assert s.players[1].all_in and s.current_bet == 60
    la = s.legal_actions()
    assert la.call_amount == 10 and not la.can_raise
    play(s, "c")
    assert s.is_over and len(s.board) == 5 and s.pot == 120


def test_short_sb_all_in_blind_needs_no_action():
    s = make([30, 10000], ["Ac Kc", "7h 3d"], BOARD_DRY)
    assert s.is_over                     # BB covers, nobody can act
    assert s.uncalled == [(0, 1, 70)]
    assert s.payoffs == [30, -30]


def test_antes_are_dead_money():
    s = make([10000] * 3, ["2h 3h", "4h 5h", "6h 7h"], BOARD_DRY, ante=10)
    assert s.pot == 3 * 10 + 50 + 100
    assert s.current_bet == 100
    play(s, "f", "f")
    assert s.payoffs == [-10, -60, 70]


def test_illegal_fold_when_check_available():
    s = make([10000, 10000], ["7h 2d", "Ac Kc"], BOARD_DRY)
    play(s, "c")
    with pytest.raises(IllegalActionError):
        s.apply(Action.fold())


# ---------------------------------------------------------------- fuzzing
@pytest.mark.parametrize("n_players", [2, 3, 6])
def test_random_play_conserves_chips(n_players):
    rng = random.Random(n_players)
    agents = [RandomBot(seed=i) for i in range(n_players)]
    for hand in range(3000):
        stacks = [rng.choice([rng.randint(1, 300), rng.randint(100, 20000)]) for _ in range(n_players)]
        s = HandState(stacks, button=hand % n_players, rng=rng)
        steps = 0
        while not s.is_over:
            s.apply(agents[s.to_act].act(s.view()))
            steps += 1
            assert steps < 500
        assert sum(s.payoffs) == 0
        assert all(p.stack >= 0 for p in s.players)
        assert all(-st <= po for st, po in zip(stacks, s.payoffs))
        rec = s.to_record()
        contributed = sum(st - p.stack for st, p in zip(stacks, s.players)) + sum(s.payoffs)
        assert rec.total_pot == sum(p.total_bet for p in s.players)
        assert contributed == 0


def test_table_is_reproducible_with_seed():
    def run():
        t = Table([RandomBot(seed=1), RandomBot(seed=2)], seed=42)
        return [r.payoffs for r in t.play(200)]
    assert run() == run()
