"""The three specialists, keyed by the layer the router selects.

Routing is a lookup in `SPECIALISTS` by the layer that live search results
voted for -- never a branch on a layer name.
"""

from __future__ import annotations

from typing import Final

from bedlam.specialists.api import API
from bedlam.specialists.base import Candidate, Specialist
from bedlam.specialists.cache import CACHE
from bedlam.specialists.catalog import CATALOG, FaultOption, option
from bedlam.specialists.db import DB
from bedlam.topology import Layer

SPECIALISTS: Final[dict[Layer, Specialist]] = {s.layer: s for s in (API, DB, CACHE)}

__all__ = ["CATALOG", "SPECIALISTS", "Candidate", "FaultOption", "Specialist", "option"]
