"""Real-time search on the river (subgame re-solving).

When the river is reached heads-up, the bot:
  1. rebuilds both players' ranges: every two-card combo is weighted by the
     probability that the blueprint would have taken the observed actions with it
     (combo -> bucket on each street -> blueprint frequency of the action taken);
  2. builds the river betting subtree (same bet sizes as the blueprint);
  3. solves it with vectorised CFR+ over the exact combos (no card abstraction,
     card removal included, rake included);
  4. plays the solved average strategy for its actual hand at the current node.

This is "unsafe" re-solving (no gadget): sound in practice when the blueprint
ranges are reasonable, which is what Libratus/Pluribus-style bots build on.
"""
from __future__ import annotations

from itertools import combinations

import numpy as np

from ..engine.equity import class_index
from ..engine.evaluator import evaluate
from ..training.abstract_game import AState


class _Node:
    __slots__ = ("state", "player", "actions", "children", "regret", "strat")

    def __init__(self, state: AState) -> None:
        self.state = state
        self.player = -1 if state.terminal else state.to_act
        self.actions = "" if state.terminal else state.legal()
        self.children = [] if state.terminal else [_Node(state.child(a)) for a in self.actions]
        self.regret = None
        self.strat = None


class RiverSolver:
    def __init__(self, abstraction, blueprint: dict, key_prefix: str = "",
                 iterations: int = 80, min_rel_weight: float = 1e-2, max_hands: int = 600) -> None:
        self.abs = abstraction
        self.bp = blueprint
        self.prefix = key_prefix
        self.iterations = iterations
        self.min_rel = min_rel_weight
        self.max_hands = max_hands

    # ------------------------------------------------------------------ ranges
    def _bucket_table(self, combos, board):
        """bucket[street][i] for every combo (preflop class, then flop / turn buckets)."""
        out = [[class_index(c) for c in combos]]
        for n in (3, 4):
            b = board[:n]
            out.append([self.abs.bucket(c, b) for c in combos])
        return out

    def ranges(self, combos, board, decisions) -> list[np.ndarray]:
        """decisions: [(player, street, history_before, action_char)] before the river."""
        buckets = self._bucket_table(combos, board)
        w = [np.ones(len(combos)), np.ones(len(combos))]
        for player, street, hist, ch in decisions:
            col = buckets[street]
            probs = np.empty(len(combos))
            cache: dict[int, float] = {}
            for i, b in enumerate(col):
                v = cache.get(b)
                if v is None:
                    e = self.bp.get(f"{self.prefix}{b}:{hist}")
                    v = e[1][e[0].index(ch)] if e is not None and ch in e[0] else 1.0
                    cache[b] = v
                probs[i] = v
            w[player] *= probs
        return w

    # ------------------------------------------------------------------ solve
    def solve(self, root: AState, river_path: str, board, hole, me: int, decisions,
              rake_pct: float = 0.0, rake_cap: float = 0.0):
        dead = set(board)
        combos = [c for c in combinations([x for x in range(52) if x not in dead], 2)]
        w = self.ranges(combos, board, decisions)
        my_combo = tuple(sorted(hole))
        my_i = next(i for i, c in enumerate(combos) if tuple(sorted(c)) == my_combo)
        keep = []
        for p in (0, 1):
            m = w[p].max()
            idx = np.nonzero(w[p] >= m * self.min_rel)[0] if m > 0 else np.arange(len(combos))
            if len(idx) > self.max_hands:   # keep the likeliest combos (random tie-break)
                order = np.random.default_rng(0).permutation(len(idx))
                idx = idx[order][np.argsort(-w[p][idx[order]], kind="stable")[: self.max_hands]]
            if p == me and my_i not in set(idx.tolist()):
                idx = np.append(idx, my_i)
                w[p][my_i] = max(w[p][my_i], m * self.min_rel)
            keep.append(idx)
        hands = [[combos[i] for i in keep[p]] for p in (0, 1)]
        reach0 = [w[p][keep[p]] / w[p][keep[p]].sum() for p in (0, 1)]
        strength = {}
        for p in (0, 1):
            for c in hands[p]:
                if c not in strength:
                    strength[c] = evaluate(list(c) + list(board))
        s0 = np.array([strength[c] for c in hands[0]])[:, None]
        s1 = np.array([strength[c] for c in hands[1]])[None, :]
        m0 = np.zeros((len(hands[0]), 52), dtype=np.float32)
        m1 = np.zeros((len(hands[1]), 52), dtype=np.float32)
        for i, c in enumerate(hands[0]):
            m0[i, list(c)] = 1
        for j, c in enumerate(hands[1]):
            m1[j, list(c)] = 1
        valid = (m0 @ m1.T == 0).astype(np.float32)          # no shared card
        win = (s0 > s1) * valid
        lose = (s0 < s1) * valid
        tie = (s0 == s1) * valid
        # u0 = c*(win-lose)@r1 - rake*(win+tie/2)@r1 ; u1 = -c*(win-lose).T@r0 - rake*(lose+tie/2).T@r0
        mats = {"D": (win - lose).astype(np.float32), "W": (win + tie / 2).astype(np.float32),
                "L": (lose + tie / 2).astype(np.float32), "V": valid}
        mats["DT"], mats["LT"], mats["VT"] = mats["D"].T.copy(), mats["L"].T.copy(), valid.T.copy()
        r0, r1 = reach0[0].astype(np.float32), reach0[1].astype(np.float32)

        tree = _Node(root)
        for t in range(1, self.iterations + 1):
            self._cfr(tree, r0, r1, t, mats, rake_pct, rake_cap)

        node = tree
        for ch in river_path:
            if ch not in node.actions:
                return None
            node = node.children[node.actions.index(ch)]
        if node.player != me or node.strat is None:
            return None
        row = list(keep[me]).index(my_i)
        st = node.strat[row]
        tot = st.sum()
        probs = st / tot if tot > 0 else np.full(len(node.actions), 1 / len(node.actions))
        info = {"hands": (len(hands[0]), len(hands[1])), "iterations": self.iterations}
        return node.actions, [float(x) for x in probs], info

    def _cfr(self, node: _Node, r0, r1, t, mats, rake_pct, rake_cap):
        s = node.state
        if s.terminal:
            c = s.contrib
            rake = min(rake_cap, rake_pct * (c[0] + c[1])) if rake_pct else 0.0
            if s.folder >= 0:
                f = s.folder
                v0, v1 = mats["V"] @ r1, mats["VT"] @ r0
                if f == 1:   # player 1 folded: player 0 wins what player 1 put in
                    return (c[1] - rake) * v0, -c[1] * v1
                return -c[0] * v0, (c[0] - rake) * v1
            pot_c = c[0]                     # contributions are equal at showdown
            u0 = pot_c * (mats["D"] @ r1)
            u1 = -pot_c * (mats["DT"] @ r0)
            if rake:
                u0 -= rake * (mats["W"] @ r1)
                u1 -= rake * (mats["LT"] @ r0)
            return u0, u1
        p = node.player
        n_a = len(node.actions)
        n_h = len(r0) if p == 0 else len(r1)
        if node.regret is None:
            node.regret = np.zeros((n_h, n_a), dtype=np.float32)
            node.strat = np.zeros((n_h, n_a), dtype=np.float32)
        pos = np.maximum(node.regret, 0)
        tot = pos.sum(axis=1, keepdims=True)
        sigma = np.where(tot > 0, pos / np.where(tot > 0, tot, 1), 1.0 / n_a)
        u_mine = np.zeros((n_h, n_a), dtype=np.float32)
        u_other = None
        for a, child in enumerate(node.children):
            if p == 0:
                u0, u1 = self._cfr(child, r0 * sigma[:, a], r1, t, mats, rake_pct, rake_cap)
                u_mine[:, a] = u0
                u_other = u1 if u_other is None else u_other + u1
            else:
                u0, u1 = self._cfr(child, r0, r1 * sigma[:, a], t, mats, rake_pct, rake_cap)
                u_mine[:, a] = u1
                u_other = u0 if u_other is None else u_other + u0
        node_u = (sigma * u_mine).sum(axis=1)
        node.regret = np.maximum(node.regret + u_mine - node_u[:, None], 0)   # CFR+
        reach = r0 if p == 0 else r1
        node.strat += t * reach[:, None] * sigma                               # linear averaging
        return (node_u, u_other) if p == 0 else (u_other, node_u)
