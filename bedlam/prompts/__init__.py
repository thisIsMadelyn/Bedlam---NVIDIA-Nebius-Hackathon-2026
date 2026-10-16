"""Prompt files. Logic never carries a prompt as a string literal.

Each call site's system prompt is a Markdown file in this package. The user
message is always the call's structured context serialised as JSON by the
calling code, so a prompt file holds instructions and an output contract
only -- never data.
"""

from __future__ import annotations

import json
from functools import cache
from importlib.resources import files
from typing import Any


@cache
def load(name: str) -> str:
    """The prompt at `bedlam/prompts/<name>.md`, e.g. `load("specialists/db")`."""
    return files(__package__).joinpath(f"{name}.md").read_text(encoding="utf-8").strip()


def context(payload: dict[str, Any]) -> str:
    """Serialise a call's context deterministically: sorted keys, fixed layout."""
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
