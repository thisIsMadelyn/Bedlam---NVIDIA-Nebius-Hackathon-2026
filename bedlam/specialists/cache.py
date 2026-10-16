"""The cache specialist: Redis, redis-py, caching, rate limiting, task queues.

Tools: every catalog fault on the cache layer.
"""

from __future__ import annotations

from typing import Final

from bedlam.specialists.base import Specialist
from bedlam.specialists.catalog import CATALOG
from bedlam.topology import Layer

CACHE: Final = Specialist(
    name="cache",
    layer=Layer.CACHE,
    prompt="specialists/cache",
    tools=tuple(option for option in CATALOG if option.layer == Layer.CACHE),
)
