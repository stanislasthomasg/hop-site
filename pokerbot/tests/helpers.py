from pokerbot.engine import Action, HandState, parse_cards


def make(stacks, holes, board, button=0, sb=50, bb=100, ante=0):
    return HandState(stacks, button=button, sb=sb, bb=bb, ante=ante,
                     hole_cards=[parse_cards(h) for h in holes], board=parse_cards(board))


def play(state, *actions):
    """Apply actions given as 'f', 'x' (check), 'c', 'r300' (raise to), 'a' (all-in)."""
    for a in actions:
        legal = state.legal_actions()
        if a == "f":
            state.apply(Action.fold())
        elif a == "x":
            state.apply(Action.check())
        elif a == "c":
            state.apply(Action.call())
        elif a == "a":
            state.apply(legal.all_in())
        elif a.startswith("r"):
            state.apply(Action.raise_to(int(a[1:])))
        else:
            raise ValueError(a)
    return state
