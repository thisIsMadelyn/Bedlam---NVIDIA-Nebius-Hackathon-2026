"""The shared result shape every probe returns.

One shape across api/db/cache means the TUI and the trace writer (Phase 2+)
never special-case a layer to read its health.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from bedlam.topology import Layer

# A probe must return promptly even while a fault (e.g. a timeout toxic set
# to block forever) is live on the layer it's checking -- that is the signal
# being measured, not a reason to hang.
DEFAULT_TIMEOUT_S: Final[float] = 2.0


class HealthStatus(StrEnum):
    UP = "up"
    DOWN = "down"


@dataclass(frozen=True, slots=True)
class ProbeResult:
    layer: Layer
    status: HealthStatus
    latency_ms: float | None
    error: str | None = None
