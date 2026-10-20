"""Where each cycle's patch comes from.

The loop waits on a `PatchSource` between injecting a fault and analysing
the fix. The TUI defaults to `GitPatchSource`: the developer edits the target
in their own editor and Bedlam reads the real `git diff`. Headless runs, the
replay recording and `--scripted` use `ScriptedPatchSource`: one unified
diff per cycle (`cycle1.diff`, `cycle2.diff`, ...) written against the real
boilerplate source. Either way the diff feeds patch analysis as-is; it is
not applied to the running container.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol

_REPO_ROOT: Final = Path(__file__).resolve().parents[1]
DEFAULT_PATCH_DIR: Final = _REPO_ROOT / "demo" / "patches"
DEFAULT_TARGET: Final = _REPO_ROOT / "targets" / "fastapi-boilerplate"


@dataclass(frozen=True, slots=True)
class Patch:
    cycle: int
    source: str
    diff: str


class PatchSource(Protocol):
    async def wait_for_patch(self, cycle: int) -> Patch: ...


class GitPatchSource:
    """The developer's own edits to the target, read with git.

    The working tree is snapshotted at start and after every patch; a
    cycle's patch is the diff between the last snapshot and now, so round
    two sees only what changed after round one. Snapshots go through a
    temporary index, so the developer's own staging area is never touched.
    New files count; ignored files do not.

    The edit is read, not deployed: the running container keeps its code.
    """

    def __init__(self, repo: Path = DEFAULT_TARGET) -> None:
        self._repo = repo
        if self._git("rev-parse", "--is-inside-work-tree").strip() != "true":
            raise ValueError(f"not a git working tree: {repo}")
        self._before = self._snapshot()

    async def wait_for_patch(self, cycle: int) -> Patch:
        return await asyncio.to_thread(self._read, cycle)

    def _read(self, cycle: int) -> Patch:
        now = self._snapshot()
        diff = self._git("diff", "--no-color", "--no-ext-diff", self._before, now)
        files = self._git("diff", "--name-only", self._before, now).split()
        self._before = now
        source = f"git diff: {', '.join(files)}" if files else "git diff: no changes"
        return Patch(cycle=cycle, source=source, diff=diff)

    def _snapshot(self) -> str:
        """The working tree as a git tree id, staged through a throwaway index."""
        with tempfile.TemporaryDirectory() as scratch:
            env = {**os.environ, "GIT_INDEX_FILE": str(Path(scratch) / "index")}
            self._git("add", "--all", env=env)
            return self._git("write-tree", env=env).strip()

    def _git(self, *args: str, env: dict[str, str] | None = None) -> str:
        result = subprocess.run(
            ["git", "-C", str(self._repo), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            check=True,
        )
        return result.stdout


class ScriptedPatchSource:
    def __init__(self, directory: Path = DEFAULT_PATCH_DIR) -> None:
        self._directory = directory

    async def wait_for_patch(self, cycle: int) -> Patch:
        path = self._directory / f"cycle{cycle}.diff"
        if not path.is_file():
            raise FileNotFoundError(f"no scripted patch for cycle {cycle}: {path}")
        return Patch(cycle=cycle, source=path.name, diff=path.read_text(encoding="utf-8"))
