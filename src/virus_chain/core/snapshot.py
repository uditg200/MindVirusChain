"""Snapshot save/restore for agent state + container workspace.

Simplified from original: messages are plain dicts, so no
serialize_message/deserialize_message needed.
"""

import json
from pathlib import Path
from typing import Any

from .agent import AgentState


def save_snapshot(
    agent_state: AgentState,
    workspace_files: dict[str, str],
    extra_files: dict[str, str] | None = None,
    source_info: dict[str, Any] | None = None,
    deleted_home_files: list[str] | None = None,
) -> dict[str, Any]:
    snapshot = {
        "agent_id": agent_state.agent_id,
        "system_prompt": agent_state.system_prompt,
        "conversation_history": agent_state.conversation_history,
        "total_tokens": agent_state.total_tokens,
        "turns_taken": agent_state.turns_taken,
        "messages_sent": agent_state.messages_sent,
        "messages_received": agent_state.messages_received,
        "workspace_files": workspace_files,
        "source_info": source_info or {},
    }
    if extra_files:
        snapshot["extra_files"] = extra_files
    if deleted_home_files:
        snapshot["deleted_home_files"] = deleted_home_files
    return snapshot


def restore_agent_state(
    snapshot: dict[str, Any],
    new_agent_id: str | None = None,
) -> AgentState:
    agent_id = new_agent_id or snapshot["agent_id"]
    return AgentState(
        agent_id=agent_id,
        system_prompt=snapshot["system_prompt"],
        conversation_history=list(snapshot["conversation_history"]),
        total_tokens=snapshot.get("total_tokens", 0),
        turns_taken=snapshot.get("turns_taken", 0),
        messages_sent=snapshot.get("messages_sent", 0),
        messages_received=snapshot.get("messages_received", 0),
    )


def save_snapshot_to_file(snapshot: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, indent=2, default=str))


def load_snapshot_from_file(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())
