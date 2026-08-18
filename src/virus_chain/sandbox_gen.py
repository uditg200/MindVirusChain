"""Dynamic Docker Compose generation for per-agent container isolation."""

import tempfile
from pathlib import Path

import yaml

DEFAULT_IMAGE = "spread-eval-sandbox-no-delete:latest"


def generate_compose(
    agent_count: int,
    sandbox_dir: Path | None = None,
    image: str = DEFAULT_IMAGE,
) -> Path:
    """Generate a compose.yaml with one service per agent.

    Services are named: agent_0, agent_1, ..., agent_N.

    Returns:
        Path to the generated compose.yaml (in a temp directory).
    """
    services = {}
    for i in range(agent_count):
        services[f"agent_{i}"] = {
            "image": image,
            "command": "tail -f /dev/null",
            "init": True,
            "network_mode": "bridge",
            "working_dir": "/workspace",
        }

    compose = {"services": services}
    tmpdir = Path(tempfile.mkdtemp(prefix="virus_chain_compose_"))
    compose_path = tmpdir / "compose.yaml"
    compose_path.write_text(yaml.dump(compose, default_flow_style=False, sort_keys=False))
    return compose_path
