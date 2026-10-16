"""Concurrent, per-layer health snapshot.

Probes are read-only, so running all three with `asyncio.gather` is correct
and intended -- the architecture invariant in CLAUDE.md restricts
concurrency to fault injection, not to probing.
"""

from __future__ import annotations

import asyncio

from bedlam.logging import get_logger, log_event
from bedlam.probes import api as _api
from bedlam.probes import cache as _cache
from bedlam.probes import db as _db
from bedlam.probes.result import DEFAULT_TIMEOUT_S, HealthStatus, ProbeResult
from bedlam.topology import Layer

_LOG = get_logger("bedlam.probes")


async def snapshot(*, timeout_s: float = DEFAULT_TIMEOUT_S) -> dict[Layer, ProbeResult]:
    """Probe all three layers concurrently and return one result per layer."""
    results = await asyncio.gather(
        _api.probe(timeout_s=timeout_s),
        _db.probe(timeout_s=timeout_s),
        _cache.probe(timeout_s=timeout_s),
    )
    by_layer = {result.layer: result for result in results}
    log_event(
        _LOG,
        "snapshot taken",
        **{layer.value: result.status.value for layer, result in by_layer.items()},
    )
    return by_layer


__all__ = ["HealthStatus", "ProbeResult", "snapshot"]
