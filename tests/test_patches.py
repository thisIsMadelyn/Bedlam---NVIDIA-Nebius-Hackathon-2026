"""Real patch mode: the developer's own edits, read with git."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from bedlam.patches import (
    DEFAULT_PATCH_DIR,
    DEFAULT_TARGET,
    FIX_FOR,
    FIXES,
    GitPatchSource,
    Patch,
    ScriptedPatchSource,
)
from bedlam.specialists.catalog import CATALOG
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

    async def wait_for_patch(self, cycle: int, fault: str | None = None) -> Patch:
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


@pytest.fixture
def diffs(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp("patches")  # outside the repo
    (directory / "redis-timeouts.diff").write_text(
        "--- a/redis.py\n+++ b/redis.py\n@@ -1 +1 @@\n-timeout = None\n+timeout = 2\n",
        encoding="utf-8",
    )
    (directory / "auth-cache.diff").write_text(
        "--- /dev/null\n+++ b/auth_cache.py\n@@ -0,0 +1 @@\n+fresh_s = 30\n",
        encoding="utf-8",
    )
    return directory


def test_the_fix_for_the_live_fault_is_applied_and_reverted_after(repo: Path, diffs: Path) -> None:
    with ScriptedPatchSource(diffs, target=repo) as source:
        patch = asyncio.run(source.wait_for_patch(1, "cache.connection_cut"))
        assert patch.source == "fix session-cache"
        assert "+timeout = 2" in patch.diff and "+fresh_s = 30" in patch.diff
        assert (repo / "redis.py").read_text(encoding="utf-8") == "timeout = 2\n"
    assert _git(repo, "status", "--porcelain") == ""


def test_a_fix_already_in_is_not_applied_twice(repo: Path, diffs: Path) -> None:
    with ScriptedPatchSource(diffs, target=repo) as source:
        asyncio.run(source.wait_for_patch(1, "cache.connection_cut"))
        again = asyncio.run(source.wait_for_patch(2, "cache.timeout.0"))
        assert again.source == "fix session-cache (already in)"
    assert _git(repo, "status", "--porcelain") == ""


def test_a_fix_left_by_a_killed_run_is_reverted_on_entry(repo: Path, diffs: Path) -> None:
    killed = ScriptedPatchSource(diffs, target=repo)
    asyncio.run(killed.wait_for_patch(1, "cache.connection_cut"))  # never restored

    with ScriptedPatchSource(diffs, target=repo):
        assert _git(repo, "status", "--porcelain") == ""


def test_without_a_target_the_diffs_are_only_read(repo: Path, diffs: Path) -> None:
    asyncio.run(ScriptedPatchSource(diffs).wait_for_patch(1, "cache.connection_cut"))
    assert _git(repo, "status", "--porcelain") == ""


def test_every_fault_has_a_prepared_fix() -> None:
    assert set(FIX_FOR) == {option.id for option in CATALOG}
    assert set(FIX_FOR.values()) <= FIXES.keys()


def test_every_component_touches_one_file_and_applies_to_the_target() -> None:
    touched: dict[str, str] = {}
    for component in sorted({c for components in FIXES.values() for c in components}):
        diff = (DEFAULT_PATCH_DIR / f"{component}.diff").read_text(encoding="utf-8")
        files = [line[6:] for line in diff.splitlines() if line.startswith("+++ b/")]
        assert len(files) == 1, f"{component} touches {files}"
        assert files[0] not in touched, f"{component} and {touched.get(files[0])} conflict"
        touched[files[0]] = component
        # Against the committed boilerplate, whatever the working tree holds.
        check = subprocess.run(
            [
                "git",
                "-c",
                "core.autocrlf=false",
                "-C",
                str(DEFAULT_TARGET),
                "apply",
                "--check",
                "--cached",
            ],
            input=diff.encode("utf-8"),
            capture_output=True,
        )
        assert check.returncode == 0, f"{component}: {check.stderr.decode()}"
