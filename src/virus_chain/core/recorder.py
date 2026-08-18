"""Recording system for simulation events."""

from dataclasses import dataclass, field, asdict
from typing import Any
import json


@dataclass
class TurnRecord:
    """Record of a single agent turn."""

    agent_id: str
    turn_number: int
    agent_turn_number: int
    input_prompt: str
    output: str
    estimated_tokens: int
    messages_received: int
    episode: int = 0
    events: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    generate_time: float = 0.0
    tool_time: float = 0.0
    compaction_time: float = 0.0


@dataclass
class CompactionRecord:
    """Record of a context compaction event."""

    agent_id: str
    turn_number: int
    old_token_count: int
    new_token_count: int
    messages_before: int
    messages_after: int


class SimulationRecorder:
    """Records all events during a multi-agent simulation."""

    def __init__(self):
        self.turns: list[TurnRecord] = []
        self.compactions: list[CompactionRecord] = []
        self.start_time: float | None = None
        self.end_time: float | None = None

    def record_turn(self, turn: TurnRecord) -> None:
        self.turns.append(turn)

    def record_compaction(self, compaction: CompactionRecord) -> None:
        self.compactions.append(compaction)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_turns": len(self.turns),
            "total_compactions": len(self.compactions),
            "turns": [asdict(t) for t in self.turns],
            "compactions": [asdict(c) for c in self.compactions],
            "duration_seconds": (
                (self.end_time - self.start_time) if (self.start_time and self.end_time) else None
            ),
        }
