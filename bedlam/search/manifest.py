"""The target's dependency manifest: direct runtime deps at resolved versions.

Tavily queries target dependency names and versions, never the boilerplate's
own name. Names come from the backend's `pyproject.toml`; versions come from
the workspace `uv.lock`, because the `>=` floors in pyproject are not what
actually runs.

Read straight from the submodule checkout -- a dependency, not vendored.
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Final

_REPO_ROOT: Final = Path(__file__).resolve().parents[2]
TARGET_DIR_ENV: Final = "BEDLAM_TARGET_DIR"
_DEFAULT_TARGET_DIR: Final = _REPO_ROOT / "targets" / "fastapi-boilerplate"

_REQUIREMENT_NAME: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")


@dataclass(frozen=True, slots=True)
class Dependency:
    name: str
    version: str


def _canonical(name: str) -> str:
    """PEP 503 normalisation, for lookups only. Never shown or searched."""
    return re.sub(r"[-_.]+", "-", name).lower()


def target_dir() -> Path:
    return Path(os.environ.get(TARGET_DIR_ENV, str(_DEFAULT_TARGET_DIR)))


def load_manifest(root: Path | None = None) -> tuple[Dependency, ...]:
    """Direct runtime dependencies of the target backend, sorted by name.

    Raises:
        FileNotFoundError: if the submodule is not checked out.
    """
    root = root or target_dir()
    backend = tomllib.loads((root / "backend" / "pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))

    resolved = {_canonical(pkg["name"]): pkg["version"] for pkg in lock.get("package", [])}
    deps: dict[str, Dependency] = {}
    for requirement in backend["project"]["dependencies"]:
        match = _REQUIREMENT_NAME.match(requirement)
        if not match:
            continue
        name = match.group(0)
        version = resolved.get(_canonical(name))
        if version:
            deps[_canonical(name)] = Dependency(name=name, version=version)
    return tuple(sorted(deps.values(), key=lambda dep: _canonical(dep.name)))


def lookup(manifest: tuple[Dependency, ...], name: str) -> Dependency | None:
    wanted = _canonical(name)
    return next((dep for dep in manifest if _canonical(dep.name) == wanted), None)
