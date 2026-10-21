"""Where each cycle's patch comes from.

The loop waits on a `PatchSource` between injecting a fault and analysing
the fix. The TUI defaults to `GitPatchSource`: the developer edits the target
in their own editor and Bedlam reads the real `git diff`. Headless runs, the
replay recording and `--scripted` use `ScriptedPatchSource`: the prepared
fix for whichever fault is live, from a small library of real diffs written
against the boilerplate source (`demo/patches/`). Either way the diff feeds
patch analysis as-is, and the patch runs: the api container mounts the
target's source. Live scripted runs apply each fix to the target for the run.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol

import httpx

from bedlam.logging import get_logger, log_event
from bedlam.probes.app import AppResult
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
    # `fault` is the live fault's catalog id; the scripted source picks its
    # fix by it, the developer's own edits ignore it.
    async def wait_for_patch(self, cycle: int, fault: str | None = None) -> Patch: ...


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

    async def wait_for_patch(self, cycle: int, fault: str | None = None) -> Patch:
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


# The prepared fixes. Each is one or more component diffs, one file each, so
# fixes stack across rounds without conflicting. A component already in is
# not applied twice.
FIXES: Final[dict[str, tuple[str, ...]]] = {
    "db-fallback": ("auth-cache", "user-cache", "tiers-cache"),
    # Timeouts alone turn a db hang into a slow error: one request makes
    # several db calls. Failing fast into the fallback is what answers.
    "db-failfast": ("db-timeouts", "auth-cache", "user-cache", "tiers-cache"),
    "session-cache": ("redis-timeouts", "auth-cache"),
}
# Which fix answers which fault: a fallback that still answers, with
# timeouts in front of it where the fault hangs. Every catalog fault has one.
FIX_FOR: Final[dict[str, str]] = {
    "db.latency.300": "db-fallback",
    "db.latency.2500": "db-failfast",
    "db.bandwidth.1": "db-fallback",
    "db.connection_cut": "db-fallback",
    "db.timeout.0": "db-failfast",
    "db.timeout.3000": "db-failfast",
    "cache.latency.300": "session-cache",
    "cache.latency.2500": "session-cache",
    "cache.bandwidth.1": "session-cache",
    "cache.connection_cut": "session-cache",
    "cache.timeout.0": "session-cache",
    "cache.timeout.3000": "session-cache",
}


class ScriptedPatchSource:
    """The prepared fix for the live fault, from `FIX_FOR`.

    Given a `target`, the fix's components are also applied to that
    checkout, so the api, which mounts it, runs them. Use it as a context
    manager: entering reverts any component a killed run left applied,
    leaving reverts every component this run applied. Without a target --
    tests, replay -- the diffs are only read.
    """

    def __init__(self, directory: Path = DEFAULT_PATCH_DIR, target: Path | None = None) -> None:
        self._directory = directory
        self._target = target
        self._applied: list[Path] = []
        # What entering reverted. The api reloads on that change, so the run
        # must wait for it (`settle`) before its baseline.
        self.cleaned: list[str] = []

    def __enter__(self) -> ScriptedPatchSource:
        if self._target is not None:
            for path in sorted(self._directory.glob("*.diff")):
                if self._apply(path, "-R", "--check", check=False):
                    self._apply(path, "-R")
                    self.cleaned.append(path.name)
        return self

    def settle(self) -> None:
        """After cleaning up a killed run, restart the api on the clean code
        and wait until it serves. Nothing to clean: returns at once."""
        if self.cleaned:
            log_event(_LOG, "reverted a killed run's fixes", fixes=self.cleaned)
            asyncio.run(deploy())

    def __exit__(self, *exc: object) -> None:
        self.restore()

    def restore(self) -> None:
        """Revert every component this run applied, newest first."""
        while self._applied:
            self._apply(self._applied.pop(), "-R")

    async def wait_for_patch(self, cycle: int, fault: str | None = None) -> Patch:
        if fault not in FIX_FOR:
            raise KeyError(f"no prepared fix for fault {fault!r}")
        name = FIX_FOR[fault]
        paths = [self._directory / f"{component}.diff" for component in FIXES[name]]
        missing = [path.name for path in paths if not path.is_file()]
        if missing:
            raise FileNotFoundError(f"fix {name} is missing {', '.join(missing)}")
        fresh = paths
        if self._target is not None:
            fresh = [path for path in paths if path not in self._applied]
            for path in fresh:
                await asyncio.to_thread(self._apply, path)
                self._applied.append(path)
        # The diff is what this round adds; a fix already fully in shows whole.
        # The label stays short: it is printed on 82-column lines.
        shown = fresh or paths
        source = f"fix {name}" + ("" if fresh else " (already in)")
        diff = "".join(path.read_text(encoding="utf-8") for path in shown)
        return Patch(cycle=cycle, source=source, diff=diff)

    def _for_target(self, path: Path) -> bytes:
        """The diff with the line endings of the file it patches.

        A Windows clone with autocrlf on can check out the diffs, the
        target, or both with CRLF. `git apply` only matches a CRLF file
        with a CRLF diff, so the diff follows the file. A new file has
        nothing to follow and stays LF.
        """
        diff = path.read_bytes().replace(b"\r\n", b"\n")
        names = [line[6:] for line in diff.split(b"\n") if line.startswith((b"+++ b/", b"--- a/"))]
        patched = Path(self._target or ".") / names[0].decode("utf-8") if names else None
        if patched is not None and patched.is_file() and b"\r\n" in patched.read_bytes():
            return diff.replace(b"\n", b"\r\n")
        return diff

    def _apply(self, path: Path, *flags: str, check: bool = True) -> bool:
        # autocrlf off: git applies the bytes as given, so the file keeps its
        # own line endings and the tree is clean once the diff is reverted.
        result = subprocess.run(
            ["git", "-c", "core.autocrlf=false", "-C", str(self._target), "apply", *flags],
            input=self._for_target(path),
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


async def deploy(warm_up: Callable[[], Awaitable[AppResult]] | None = None) -> None:
    """Restart the api so it runs the patch, and wait until it serves.

    The api reloads by itself when a file changes, but a reload under a
    live fault can fail at startup (the boilerplate connects to Postgres as
    it starts) and then waits for the next change. So the loop removes the
    fault first and restarts the container: the patch starts clean.

    `warm_up` is then read until it answers once, on the healthy stack, the
    way real traffic warms caches between a deploy and the next failure.
    This only waits; nothing it sees feeds a decision.
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
    while warm_up is not None and not (await warm_up()).ok:
        if loop.time() >= give_up:
            raise DeployError("the read through the app never answered after the restart")
        await asyncio.sleep(_DEPLOY_POLL_S)
    log_event(_LOG, "api serving the patch", warmed=warm_up is not None)
