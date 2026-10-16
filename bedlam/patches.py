"""Where each cycle's patch comes from.

The loop waits on a `PatchSource` between injecting a fault and analysing
the fix. Headless runs use `ScriptedPatchSource`: one unified diff per
cycle (`cycle1.diff`, `cycle2.diff`, ...) written against the real
boilerplate source. The diff feeds patch analysis as-is; it is not applied to
the running container. Phase 5 turns these into real commits.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol

_REPO_ROOT: Final = Path(__file__).resolve().parents[1]
DEFAULT_PATCH_DIR: Final = _REPO_ROOT / "demo" / "patches"


@dataclass(frozen=True, slots=True)
class Patch:
    cycle: int
    source: str
    diff: str


class PatchSource(Protocol):
    async def wait_for_patch(self, cycle: int) -> Patch: ...


class ScriptedPatchSource:
    def __init__(self, directory: Path = DEFAULT_PATCH_DIR) -> None:
        self._directory = directory

    async def wait_for_patch(self, cycle: int) -> Patch:
        path = self._directory / f"cycle{cycle}.diff"
        if not path.is_file():
            raise FileNotFoundError(f"no scripted patch for cycle {cycle}: {path}")
        return Patch(cycle=cycle, source=path.name, diff=path.read_text(encoding="utf-8"))
