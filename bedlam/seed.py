"""The single root seed every random decision in Bedlam derives from.

CLAUDE.md: any randomness must be seeded from one configurable root seed.
Nothing in the decision chain calls unseeded `random`, `uuid4` or reads the
wall clock -- it asks this module for a named, derived stream instead.

Derivation goes through sha256, not `hash()`, because `hash()` of a string
is salted per process and would differ between two runs with the same seed.
"""

from __future__ import annotations

import hashlib
import os
import random
from typing import Final

ROOT_SEED_ENV: Final = "BEDLAM_SEED"
DEFAULT_ROOT_SEED: Final = 1729


def root_seed() -> int:
    """The configured root seed (`BEDLAM_SEED`), or the default."""
    return int(os.environ.get(ROOT_SEED_ENV, str(DEFAULT_ROOT_SEED)))


def derive(root: int, stream: str) -> int:
    """A stable 31-bit seed for the named stream, derived from `root`.

    31 bits because inference servers commonly reject seeds outside a signed
    32-bit range.
    """
    digest = hashlib.sha256(f"{root}:{stream}".encode()).digest()
    return int.from_bytes(digest[:4], "big") & 0x7FFFFFFF


def rng(root: int, stream: str) -> random.Random:
    """A private `random.Random` for the named stream. Never the global one."""
    return random.Random(derive(root, stream))
