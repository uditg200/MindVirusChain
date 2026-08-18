"""Docker container operations — replaces inspect_ai.util.sandbox()."""

import asyncio
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ContainerRef:
    compose_path: Path
    project_name: str
    service_name: str


@dataclass
class ExecResult:
    stdout: str
    stderr: str
    returncode: int


def _compose_cmd(ref: ContainerRef, *args: str) -> list[str]:
    return [
        "docker", "compose",
        "-f", str(ref.compose_path),
        "-p", ref.project_name,
        *args,
    ]


async def container_exec(
    ref: ContainerRef, cmd: list[str], timeout: int = 60,
) -> ExecResult:
    proc = await asyncio.create_subprocess_exec(
        *_compose_cmd(ref, "exec", "-T", ref.service_name, *cmd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return ExecResult("", f"Timeout after {timeout}s", 1)
    return ExecResult(
        stdout.decode(errors="replace"),
        stderr.decode(errors="replace"),
        proc.returncode or 0,
    )


async def container_read_file(ref: ContainerRef, path: str) -> str:
    result = await container_exec(ref, ["cat", path])
    if result.returncode != 0:
        raise FileNotFoundError(f"{path}: {result.stderr.strip()}")
    return result.stdout


async def container_write_file(ref: ContainerRef, path: str, content: str) -> None:
    parent = str(Path(path).parent)
    await container_exec(ref, ["mkdir", "-p", parent])
    proc = await asyncio.create_subprocess_exec(
        *_compose_cmd(ref, "exec", "-T", ref.service_name, "tee", path),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate(content.encode())
    if proc.returncode:
        raise OSError(f"write_file {path}: {stderr.decode(errors='replace').strip()}")


async def start_containers(compose_path: Path, project_name: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        "docker", "compose", "-f", str(compose_path), "-p", project_name,
        "up", "-d", "--wait",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode:
        raise RuntimeError(
            f"docker compose up failed: {stderr.decode(errors='replace').strip()}"
        )


async def stop_containers(compose_path: Path, project_name: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        "docker", "compose", "-f", str(compose_path), "-p", project_name,
        "down", "--volumes", "--remove-orphans",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()
