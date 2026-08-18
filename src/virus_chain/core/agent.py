"""Agent state — simplified, dict-based messages (no inspect-ai ChatMessage types)."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentState:
    agent_id: str
    system_prompt: str
    conversation_history: list[dict] = field(default_factory=list)
    total_tokens: int = 0
    turns_taken: int = 0
    messages_sent: int = 0
    messages_received: int = 0

    def __post_init__(self):
        if not self.conversation_history:
            self.conversation_history = [
                {"role": "system", "content": self.system_prompt}
            ]

    def add_user_message(self, content: str) -> None:
        self.conversation_history.append({"role": "user", "content": content})

    def add_message(self, message: dict) -> None:
        self.conversation_history.append(message)

    def get_metadata(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "total_tokens": self.total_tokens,
            "turns_taken": self.turns_taken,
            "messages_sent": self.messages_sent,
            "messages_received": self.messages_received,
        }
