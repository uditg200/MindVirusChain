"""Utilities for colorful terminal output and logging."""

import json
import sys
from pathlib import Path
from typing import NamedTuple


def resolve_path(path_str: str, config_dir: Path) -> Path:
    """Resolve a config path.

    - Absolute paths (/...) are used as-is.
    - Paths starting with ../ or ./ are resolved from config_dir.
    - All other paths are resolved from CWD (expected to be repo root).
    """
    p = Path(path_str)
    if p.is_absolute():
        return p
    if path_str.startswith("../") or path_str.startswith("./"):
        return config_dir / p
    return Path.cwd() / p


class PayloadResult(NamedTuple):
    payload: str
    theme: str | None
    ideology: str | None = None
    ideology_questions: list[str] | None = None


def load_payload(config: dict, config_dir: Path) -> PayloadResult:
    """Load payload from a seed_file or payload_file (single JSON with payload + metadata)."""
    sf = config.get("seed_file") or config.get("payload_file")
    if not sf:
        print("\033[31mError: config must have 'seed_file' or 'payload_file' pointing to a JSON file\033[0m")
        sys.exit(1)
    sf = resolve_path(sf, config_dir)
    if not sf.exists():
        print(f"\033[31mError: seed_file not found: {sf}\033[0m")
        sys.exit(1)
    entry = json.loads(sf.read_text())
    theme = entry.get("theme") or entry.get("full_theme") or None
    ideology = entry.get("ideology")
    ideology_questions = entry.get("ideology_questions")
    return PayloadResult(entry["payload"], theme, ideology, ideology_questions)


def short_model_name(model: str) -> str:
    """Normalize a full model string like 'anthropic/claude-haiku-4-5-20251001' to a short name.

    Strips provider prefix, date suffixes, and preview tags while keeping
    enough to uniquely identify the model (e.g. 'claude-haiku-4-5').
    """
    import re
    m = model.strip()
    # Strip provider prefix(es) — keep only the last segment after '/'
    if "/" in m:
        m = m.rsplit("/", 1)[1]
    # Strip date suffixes like -20251001
    m = re.sub(r"-\d{8,}$", "", m)
    # Strip -preview, -latest tags
    m = re.sub(r"-(preview|latest)$", "", m)
    return m


class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"

    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"
    BRIGHT_WHITE = "\033[97m"


def colorize(text: str, color: str, bold: bool = False) -> str:
    prefix = f"{Colors.BOLD}{color}" if bold else color
    return f"{prefix}{text}{Colors.RESET}"


def log_message(from_agent: str, to_agent: str, content_preview: str) -> None:
    pass


def log_compaction(agent_id: str, old_tokens: int, new_tokens: int) -> None:
    agent_label = colorize(f"[{agent_id}]", Colors.BRIGHT_MAGENTA, bold=True)
    reduction = colorize(f"{old_tokens} → {new_tokens} tokens", Colors.YELLOW)
    print(f"  {agent_label} Context compacted: {reduction}", file=sys.stderr)


def log_error(agent_id: str, error: str) -> None:
    agent_label = colorize(f"[{agent_id}]", Colors.BRIGHT_RED, bold=True)
    error_text = colorize(f"ERROR: {error}", Colors.RED)
    print(f"  {agent_label} {error_text}", file=sys.stderr)


def is_garbled(text: str) -> bool:
    """Detect encrypted/encoded reasoning blocks."""
    if len(text) < 100:
        return False
    space_ratio = sum(c in ' \n\t' for c in text) / len(text)
    return space_ratio < 0.02


def clean_reasoning(block) -> str | None:
    """Extract readable reasoning from a ContentReasoning block."""
    redacted = getattr(block, 'redacted', False)
    reasoning = str(block.reasoning) if block.reasoning else ""
    summary = getattr(block, 'summary', None)

    if redacted or is_garbled(reasoning):
        if summary:
            return f"[summary] {summary}"
        return "[encrypted]"

    return reasoning or None
