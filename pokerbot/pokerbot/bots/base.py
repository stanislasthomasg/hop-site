"""Agent interface shared by every bot and by the human player."""
from __future__ import annotations

from ..engine.actions import Action
from ..engine.records import HandRecord
from ..engine.state import PlayerView


class Agent:
    """Subclass and implement ``act``. The hooks are optional."""

    def __init__(self, name: str | None = None) -> None:
        self.name = name or type(self).__name__
        self.table_names: list[str] = []   # names of every seat, set by the table each hand

    def act(self, view: PlayerView) -> Action:  # pragma: no cover - abstract
        raise NotImplementedError

    def on_hand_start(self, seat: int, view: PlayerView) -> None:
        """Called once per hand before any decision (view of own seat)."""

    def on_hand_end(self, seat: int, record: HandRecord) -> None:
        """Called with the full record once the hand is over (learning hook)."""
