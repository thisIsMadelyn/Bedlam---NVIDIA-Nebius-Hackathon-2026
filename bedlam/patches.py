"""Where each cycle's patch comes from.

The loop waits on a `PatchSource` between injecting a fault and analysing
the fix. The TUI defaults to `GitPatchSource`: the developer edits the target
in their own editor and Bedlam reads the real `git diff`. Headless runs, the
replay recording and `--scripted` use `ScriptedPatchSource`: one unified
diff per cycle (`cycle1.diff`, `cycle2.diff`, ...) written against the real
boilerplate source. Either way the diff feeds patch analysis as-is, and the
patch runs: the api container mounts the target's source. Live scripted
runs apply each diff to the target for the run.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol

import httpx

from bedlam.logging import get_logger, log_event
from bedlam.topology import Layer, endpoint_for

_REPO_ROOT: Final = Path(__file__).resolve().parents[1]
DEFAULT_PATCH_DIR: Final = _REPO_ROOT / "demo" / "patches"
DEFAULT_TARGET: Final = _REPO_ROOT / "targets" / "fastapi-boilerplate"
_LOG = get_logger("bedlam.patches")
_DEPLOY_TIMEOUT_S: Final = 60.0
_DEPLOY_POLL_S: Final = 0.5


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

    The edit is live as soon as it is saved: the api mounts this checkout
    and reloads.
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
    """The prepared diffs, one per cycle.

    Given a `target`, each diff is also applied to that checkout, so the
    api, which mounts it, runs the patch. Use it as a context manager:
    entering reverts any diff a killed run left applied, leaving reverts
    every diff this run applied. Without a target -- tests, replay -- the
    diffs are only read.
    """

    def __init__(self, directory: Path = DEFAULT_PATCH_DIR, target: Path | None = None) -> None:
        self._directory = directory
        self._target = target
        self._applied: list[Path] = []

    def __enter__(self) -> ScriptedPatchSource:
        if self._target is not None:
            for path in sorted(self._directory.glob("cycle*.diff"), reverse=True):
                if self._apply(path, "-R", "--check", check=False):
                    self._apply(path, "-R")
        return self

    def __exit__(self, *exc: object) -> None:
        self.restore()

    def restore(self) -> None:
        """Revert every diff this run applied, newest first."""
        while self._applied:
            self._apply(self._applied.pop(), "-R")

    async def wait_for_patch(self, cycle: int) -> Patch:
        path = self._directory / f"cycle{cycle}.diff"
        if not path.is_file():
            raise FileNotFoundError(f"no scripted patch for cycle {cycle}: {path}")
        if self._target is not None:
            await asyncio.to_thread(self._apply, path)
            self._applied.append(path)
        return Patch(cycle=cycle, source=path.name, diff=path.read_text(encoding="utf-8"))

    def _apply(self, path: Path, *flags: str, check: bool = True) -> bool:
        # autocrlf off: the diffs and the checkout are LF, and a Windows git
        # with autocrlf on would write CRLF back and leave the tree dirty.
        result = subprocess.run(
            ["git", "-c", "core.autocrlf=false", "-C", str(self._target), "apply", *flags],
            input=path.read_bytes(),
            capture_output=True,
            check=False,
        )
        if check and result.returncode != 0:
            raise RuntimeError(
                f"git apply {' '.join(flags)} {path.name} failed: "
                f"{result.stderr.decode('utf-8', 'replace').strip()}"
            )
        return result.returncode == 0


class DeployError(RuntimeError):
    """The api did not come back serving after the restart."""


async def deploy() -> None:
    """Restart the api so it runs the patch, and wait until it serves.

    The api reloads by itself when a file changes, but a reload under a
    live fault can fail at startup (the boilerplate connects to Postgres as
    it starts) and then waits for the next change. So the loop removes the
    fault first and restarts the container: the patch starts clean. This
    only waits; nothing it sees feeds a decision.
    """
    await asyncio.to_thread(
        subprocess.run,
        ["docker", "compose", "restart", "api"],
        capture_output=True,
        cwd=_REPO_ROOT,
        check=True,
        timeout=_DEPLOY_TIMEOUT_S,
    )
    base_url = endpoint_for(Layer.API).base_url
    loop = asyncio.get_running_loop()
    give_up = loop.time() + _DEPLOY_TIMEOUT_S
    async with httpx.AsyncClient(base_url=base_url, timeout=2.0) as client:
        while True:
            try:
                if (await client.get("/health")).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if loop.time() >= give_up:
                raise DeployError("the api did not come back after the restart")
            await asyncio.sleep(_DEPLOY_POLL_S)
    log_event(_LOG, "api serving the patch")
