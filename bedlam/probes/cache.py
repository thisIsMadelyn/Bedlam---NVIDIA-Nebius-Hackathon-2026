"""Read-only health probe for the cache layer.

Connects straight through Toxiproxy's redis proxy -- the same path the api
container's cache, rate-limiter and session traffic takes -- so a fault
injected there shows up here.
"""

from __future__ import annotations

import asyncio
import time

import redis.asyncio as redis

from bedlam.probes.result import DEFAULT_TIMEOUT_S, HealthStatus, ProbeResult
from bedlam.topology import Layer, endpoint_for


async def _check(host: str, port: int, timeout_s: float) -> None:
    client = redis.Redis(
        host=host,
        port=port,
        socket_connect_timeout=timeout_s,
        socket_timeout=timeout_s,
    )
    try:
        await client.ping()
    finally:
        await client.aclose()


async def probe(*, timeout_s: float = DEFAULT_TIMEOUT_S) -> ProbeResult:
    """Bounded to `timeout_s` end to end -- see db.py's probe for why."""
    endpoint = endpoint_for(Layer.CACHE)

    started = time.perf_counter()
    try:
        await asyncio.wait_for(_check(endpoint.host, endpoint.port, timeout_s), timeout=timeout_s)
        elapsed_ms = (time.perf_counter() - started) * 1000
        return ProbeResult(layer=Layer.CACHE, status=HealthStatus.UP, latency_ms=elapsed_ms)
    except Exception as exc:  # noqa: BLE001 - any failure means the layer is down
        elapsed_ms = (time.perf_counter() - started) * 1000
        return ProbeResult(
            layer=Layer.CACHE,
            status=HealthStatus.DOWN,
            latency_ms=elapsed_ms,
            error=f"{type(exc).__name__}: {exc}",
        )
