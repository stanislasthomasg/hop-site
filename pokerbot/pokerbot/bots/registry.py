"""Build agents from short spec strings, e.g. 'abc', 'nit:seed=3', 'bot:v2', 'bot:best'.

Specs (not objects) are passed to worker processes, which build their own agents.
"""
from __future__ import annotations

from .base import Agent
from .profiles import ABC, CallingStation, Maniac, Nit
from .random_bot import RandomBot

SIMPLE = {
    "random": RandomBot,
    "station": CallingStation,
    "nit": Nit,
    "maniac": Maniac,
    "abc": ABC,
}


def make_agent(spec: str, name: str | None = None, seed: int | None = None) -> Agent:
    kind, _, arg = spec.partition(":")
    kwargs = {}
    if kind in SIMPLE:
        for part in filter(None, arg.split(",")):
            k, _, v = part.partition("=")
            kwargs[k] = float(v) if "." in v else int(v)
        if seed is not None:
            kwargs.setdefault("seed", seed)
        return SIMPLE[kind](name=name or spec, **kwargs)
    if kind == "bot":
        from .learner import LearnerBot
        return LearnerBot.from_version(arg or "best", name=name, seed=seed)
    if kind == "slumbot":
        raise ValueError("Slumbot is played through evaluation.slumbot, not as a local agent")
    raise ValueError(f"unknown agent spec: {spec!r}")
