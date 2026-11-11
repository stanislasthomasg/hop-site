from pokerbot.engine import award_pots, compute_pots


def test_single_pot():
    pots = compute_pots([300, 300, 300], [False, False, False])
    assert [(p.amount, p.eligible) for p in pots] == [(900, (0, 1, 2))]


def test_three_side_pots():
    pots = compute_pots([1000, 3000, 5000, 5000], [False] * 4)
    assert [(p.amount, p.eligible) for p in pots] == [
        (4000, (0, 1, 2, 3)), (6000, (1, 2, 3)), (4000, (2, 3))]


def test_folded_money_is_dead_but_counted():
    pots = compute_pots([500, 300, 1000], [True, False, False])
    assert [(p.amount, p.eligible) for p in pots] == [(900, (1, 2)), (900, (2,))]
    assert sum(p.amount for p in pots) == 1800


def test_short_stack_wins_main_pot_only():
    pots = compute_pots([1000, 3000, 3000], [False] * 3)
    payouts, _ = award_pots(pots, {0: 100, 1: 50, 2: 10}, button=0, n_seats=3)
    assert payouts == [3000, 4000, 0]


def test_split_with_odd_chip_goes_left_of_button():
    pots = compute_pots([100, 101, 100], [False, True, False])
    assert sum(p.amount for p in pots) == 301
    payouts, awards = award_pots(pots, {0: 7, 2: 7}, button=1, n_seats=3)
    # seat 2 is first left of the button (seat 1) -> gets the odd chip
    assert payouts == [150, 0, 151]


def test_three_way_split_main_two_way_split_side():
    pots = compute_pots([1000, 5000, 5000], [False] * 3)
    payouts, _ = award_pots(pots, {0: 9, 1: 9, 2: 9}, button=0, n_seats=3)
    assert payouts == [1000, 5000, 5000]
