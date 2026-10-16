"""The api specialist: the request path itself.

The API layer has no proxy of its own, so this specialist breaks it from
underneath: it attacks the request path through the backends every request
waits on. Its tools are the faults that make a request *wait* -- latency
and timeouts on any proxied layer -- because waiting is what starves
workers, exhausts the event loop and surfaces missing request timeouts.
"""

from __future__ import annotations

from typing import Final

from bedlam.faults.primitives import FaultKind
from bedlam.specialists.base import Specialist
from bedlam.specialists.catalog import CATALOG
from bedlam.topology import Layer

_REQUEST_PATH_KINDS: Final = frozenset({FaultKind.LATENCY, FaultKind.TIMEOUT})

API: Final = Specialist(
    name="api",
    layer=Layer.API,
    prompt="specialists/api",
    tools=tuple(option for option in CATALOG if option.kind in _REQUEST_PATH_KINDS),
)
