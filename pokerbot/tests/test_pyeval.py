import random

import eval7

from pokerbot.engine import pyeval
from pokerbot.engine.cards import card_to_str

E7 = [eval7.Card(card_to_str(c)) for c in range(52)]
NAMES = {"Trips": "Trips", "Quads": "Quads"}


def test_pure_python_evaluator_matches_eval7():
    rng = random.Random(0)
    for _ in range(20000):
        cards = rng.sample(range(52), 14)
        a, b = cards[:7], cards[7:]
        ea, eb = eval7.evaluate([E7[c] for c in a]), eval7.evaluate([E7[c] for c in b])
        pa, pb = pyeval.evaluate(a), pyeval.evaluate(b)
        assert (ea > eb) - (ea < eb) == (pa > pb) - (pa < pb), ([card_to_str(c) for c in a], [card_to_str(c) for c in b])
        assert eval7.handtype(ea) == pyeval.handtype(pa)


def test_same_board_ties_and_kickers():
    rng = random.Random(1)
    for _ in range(20000):
        cards = rng.sample(range(52), 9)
        board = cards[4:]
        a, b = cards[:2] + board, cards[2:4] + board
        ea, eb = eval7.evaluate([E7[c] for c in a]), eval7.evaluate([E7[c] for c in b])
        pa, pb = pyeval.evaluate(a), pyeval.evaluate(b)
        assert (ea > eb) - (ea < eb) == (pa > pb) - (pa < pb)
