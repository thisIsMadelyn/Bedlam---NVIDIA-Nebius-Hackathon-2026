"""The db specialist: Postgres, asyncpg and the SQLAlchemy engine and pool.

Tools: every catalog fault on the db layer.
"""

from __future__ import annotations

from typing import Final

from bedlam.specialists.base import Specialist
from bedlam.specialists.catalog import CATALOG
from bedlam.topology import Layer

DB: Final = Specialist(
    name="db",
    layer=Layer.DB,
    prompt="specialists/db",
    tools=tuple(option for option in CATALOG if option.layer == Layer.DB),
)
