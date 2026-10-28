"""Container load per layer (CPU, memory), read with the Docker CLI.

Display only: the TUI shows how each part of the target stack is loaded
while a fault is live. Nothing here feeds a decision, so it never touches
determinism. It uses the `docker` command that `make up` already needs, so
it adds no dependency.

Containers are found through `docker compose ps` in the repo root, so other
containers on the machine are never counted.
"""

from __future__ import annotations

import asyncio
import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from bedlam.topology import COMPOSE_SERVICES, Layer

_REPO_ROOT: Final = Path(__file__).resolve().parents[1]
_UNITS: Final = {
    "b": 1,
    "kb": 1000,
    "mb": 1000**2,
    "gb": 1000**3,
    "kib": 1024,
    "mib": 1024**2,
    "gib": 1024**3,
}
_AMOUNT: Final = re.compile(r"^\s*([0-9.]+)\s*([a-z]+)\s*$", re.IGNORECASE)

# Runs a command and returns its stdout. Swapped out in tests.
Runner = Callable[[Sequence[str]], str]


class StatsUnavailable(RuntimeError):
    """Docker could not be asked, or the stack is not running."""


@dataclass(frozen=True, slots=True)
class ContainerStats:
    cpu_percent: float
    memory_bytes: int


def parse_bytes(text: str) -> int:
    """`219.7MiB` -> bytes. Accepts the units `docker stats` prints."""
    match = _AMOUNT.match(text)
    if match is None or match.group(2).lower() not in _UNITS:
        raise ValueError(f"not a memory amount: {text!r}")
    return round(float(match.group(1)) * _UNITS[match.group(2).lower()])


def _run(args: Sequence[str]) -> str:
    try:
        result = subprocess.run(
            list(args),
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=_REPO_ROOT,
            check=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise StatsUnavailable(f"{args[0]} {args[1]}: {exc}") from exc
    return result.stdout


def read(run: Runner = _run) -> dict[Layer, ContainerStats]:
    """One sample for every layer whose container is running."""
    services = {}
    for line in run(["docker", "compose", "ps", "--format", "{{.Service}}\t{{.ID}}"]).splitlines():
        service, _, container = line.partition("\t")
        services[service.strip()] = container.strip()
    ids = {layer: services[name] for layer, name in COMPOSE_SERVICES.items() if name in services}
    if not ids:
        raise StatsUnavailable("no target containers are running. Run `make up`.")
    out = run(
        ["docker", "stats", "--no-stream", "--format", "{{.ID}}\t{{.CPUPerc}}\t{{.MemUsage}}"]
        + list(ids.values())
    )
    by_id: dict[str, ContainerStats] = {}
    for line in out.splitlines():
        container, cpu, memory = (part.strip() for part in line.split("\t"))
        used = memory.split("/")[0]
        try:
            by_id[container] = ContainerStats(float(cpu.rstrip("%")), parse_bytes(used))
        except ValueError as exc:
            # Docker prints `--` for a container it has no sample of yet.
            raise StatsUnavailable(f"docker stats: {exc}") from exc
    stats = {}
    for layer, container in ids.items():
        # Compose and stats can print IDs of different lengths; match on prefix.
        found = [s for c, s in by_id.items() if c.startswith(container) or container.startswith(c)]
        if found:
            stats[layer] = found[0]
    return stats


async def sample(run: Runner = _run) -> dict[Layer, ContainerStats]:
    """`read`, off the event loop. A `docker stats` call takes a few seconds."""
    return await asyncio.to_thread(read, run)
