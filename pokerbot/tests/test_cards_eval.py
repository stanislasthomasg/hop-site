from pokerbot.engine import card_to_str, evaluate, hand_category, parse_cards, str_to_card


def ev(s):
    return evaluate(parse_cards(s))


def test_card_roundtrip():
    for c in range(52):
        assert str_to_card(card_to_str(c)) == c
    assert parse_cards("As Kd") == parse_cards("AsKd") == parse_cards(["As", "Kd"])


def test_category_order():
    hands = [
        "As Ks Qs Js Ts 2c 3d",  # straight flush
        "9c 9d 9h 9s 2d 3c 4h",  # quads
        "8c 8d 8h 2s 2d 5c 6h",  # full house
        "Ah 9h 6h 4h 2h Kc Qd",  # flush
        "9c Td Jh Qs Kd 2c 3h",  # straight
        "7c 7d 7h Ks 2d 5c 9h",  # trips
        "7c 7d 5h 5s Kd 2c 3h",  # two pair
        "Ac Ad 5h 9s Kd 2c 3h",  # pair
        "Ac Qd 5h 9s 8d 2c 3h",  # high card
    ]
    values = [ev(h) for h in hands]
    assert values == sorted(values, reverse=True)
    assert hand_category(values[0]) == "Straight Flush"
    assert hand_category(values[-1]) == "High Card"


def test_wheel_is_lowest_straight():
    assert hand_category(ev("Ac 2d 3h 4s 5d Kc 9h")) == "Straight"
    assert ev("Ac 2d 3h 4s 5d Kc 9h") < ev("2c 3d 4h 5s 6d Kc 9h")


def test_kicker_and_board_plays():
    board = "Ah Kd 8c 5s 2h"
    assert ev("As Qc " + board) > ev("Ac Jc " + board)       # queen kicker beats jack
    royal = "As Ks Qs Js Ts"
    assert ev("2c 3d " + royal) == ev("4h 7c " + royal)       # board plays: tie
    # Fifth kicker does not count beyond the best five cards
    assert ev("Ac Kc Qd Jh 9s 3c 2d") == ev("Ac Kc Qd Jh 9s 4c 2d")
