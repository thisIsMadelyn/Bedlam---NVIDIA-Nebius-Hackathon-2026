"""Real patch mode: the developer's own edits, read with git."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from bedlam.patches import GitPatchSource, Patch
from bedlam.tui import GatedPatchSource


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "test")
    _git(tmp_path, "config", "core.autocrlf", "false")
    (tmp_path / "redis.py").write_text("timeout = None\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text(".env\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "start")
    return tmp_path


def test_each_round_sees_only_what_changed_since_the_last(repo: Path) -> None:
    source = GitPatchSource(repo)
    (repo / "redis.py").write_text("timeout = 2\n", encoding="utf-8")
    first = asyncio.run(source.wait_for_patch(1))
    assert "+timeout = 2" in first.diff and first.source == "git diff: redis.py"

    (repo / "pool.py").write_text("max_size = 10\n", encoding="utf-8")  # a new file
    (repo / ".env").write_text("SECRET=x\n", encoding="utf-8")  # ignored
    second = asyncio.run(source.wait_for_patch(2))
    assert "+max_size = 10" in second.diff
    assert "timeout" not in second.diff, "round 2 repeated round 1's change"
    assert "SECRET" not in second.diff, "an ignored file was read"


def test_edits_made_before_bedlam_started_are_not_the_patch(repo: Path) -> None:
    (repo / "redis.py").write_text("timeout = 5\n", encoding="utf-8")
    source = GitPatchSource(repo)
    assert asyncio.run(source.wait_for_patch(1)).diff == ""


def test_the_developers_staging_area_is_never_touched(repo: Path) -> None:
    source = GitPatchSource(repo)
    (repo / "redis.py").write_text("timeout = 2\n", encoding="utf-8")
    asyncio.run(source.wait_for_patch(1))
    assert _git(repo, "diff", "--cached", "--name-only") == "", "something was staged"
    assert _git(repo, "status", "--porcelain").strip() == "M redis.py"


def test_a_folder_that_is_not_a_git_checkout_is_refused(tmp_path: Path) -> None:
    with pytest.raises((ValueError, subprocess.CalledProcessError)):
        GitPatchSource(tmp_path / "missing")


class _Replies:
    def __init__(self, *diffs: str) -> None:
        self._diffs = iter(diffs)

    async def wait_for_patch(self, cycle: int) -> Patch:
        return Patch(cycle=cycle, source="git diff", diff=next(self._diffs))


def test_p_with_no_changes_says_so_and_keeps_waiting() -> None:
    async def scenario() -> None:
        gate = GatedPatchSource(_Replies("", "+fixed\n"))
        empties: list[int] = []
        gate.on_empty = lambda: empties.append(1)
        waiter = asyncio.create_task(gate.wait_for_patch(1))
        await asyncio.sleep(0.01)
        assert gate.release()
        await asyncio.sleep(0.01)
        assert empties == [1] and not waiter.done() and gate.waiting
        assert gate.release()
        patch = await asyncio.wait_for(waiter, timeout=1)
        assert patch.diff == "+fixed\n"

    asyncio.run(scenario())
