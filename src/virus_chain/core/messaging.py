"""Message queue for inter-agent communication."""

from dataclasses import dataclass
from typing import Any


@dataclass
class Message:
    """A message sent from one agent to another."""

    from_agent: str
    to_agent: str
    content: str
    turn_sent: int
    turn_delivered: int | None = None

    def format_for_display(self) -> str:
        return f"""📨 **Message from agent {self.from_agent}:**

{self.content}

---
Automatic reminder: to send a response, use the `send_message` tool."""


class MessageQueue:
    """Manages message delivery between agents (next-turn delivery)."""

    def __init__(self, delivery_mode: str = "next_turn"):
        self.delivery_mode = delivery_mode
        self.pending_messages: dict[str, list[Message]] = {}
        self.all_messages: list[Message] = []

    def send_message(self, message: Message) -> None:
        recipient = message.to_agent
        if recipient not in self.pending_messages:
            self.pending_messages[recipient] = []
        self.pending_messages[recipient].append(message)
        self.all_messages.append(message)

    def get_messages(self, agent_id: str, current_turn: int) -> list[Message]:
        """Get messages ready for delivery (sent before current turn)."""
        if agent_id not in self.pending_messages:
            return []

        pending = self.pending_messages[agent_id]
        to_deliver = [m for m in pending if m.turn_sent < current_turn]

        for msg in to_deliver:
            msg.turn_delivered = current_turn

        self.pending_messages[agent_id] = [
            m for m in pending if m.turn_sent >= current_turn
        ]
        return to_deliver

    def peek_unread(self, agent_id: str, current_turn: int) -> list[Message]:
        """Return unread messages without consuming them."""
        if agent_id not in self.pending_messages:
            return []
        return [m for m in self.pending_messages[agent_id] if m.turn_sent < current_turn]

    def count_unread(self, agent_id: str, current_turn: int) -> int:
        return len(self.peek_unread(agent_id, current_turn))

    def format_inbox(self, messages: list[Message]) -> str:
        if not messages:
            return ""
        count = len(messages)
        plural = "s" if count > 1 else ""
        header = f"📬 You have {count} new message{plural}:\n\n"
        formatted = [msg.format_for_display() for msg in messages]
        return header + "\n\n".join(formatted)

    def format_notification(self, messages: list[Message]) -> str:
        """Short notification listing senders, without message content."""
        if not messages:
            return ""
        senders = sorted(set(m.from_agent for m in messages))
        total = len(messages)
        plural = "s" if total > 1 else ""
        lines = [f"📬 You have {total} unread message{plural}."]
        for sender in senders:
            n = sum(1 for m in messages if m.from_agent == sender)
            if n == 1:
                lines.append(f"  - Just received a message from {sender}.")
            else:
                lines.append(f"  - {n} messages from {sender}.")
        lines.append("Use the `read_messages` tool to read them.")
        return "\n".join(lines)

    def get_messages_to(self, agent_id: str) -> list[Message]:
        """Get all messages sent to a specific agent (delivered or not)."""
        return [m for m in self.all_messages if m.to_agent == agent_id]

    def get_stats(self) -> dict[str, Any]:
        total_sent = len(self.all_messages)
        total_delivered = sum(1 for m in self.all_messages if m.turn_delivered is not None)
        return {
            "total_sent": total_sent,
            "total_delivered": total_delivered,
            "total_pending": total_sent - total_delivered,
            "messages": [
                {
                    "from": m.from_agent,
                    "to": m.to_agent,
                    "turn_sent": m.turn_sent,
                    "turn_delivered": m.turn_delivered,
                    "content_preview": m.content[:100] + "..." if len(m.content) > 100 else m.content,
                    "content": m.content,
                }
                for m in self.all_messages
            ],
        }
