"""Read-only health probe for the db layer.

Connects straight through Toxiproxy's postgres proxy -- the same path the
api container's traffic takes -- so a fault injected there shows up here.
"""

from __future__ import annotations

import asyncio
import time

import asyncpg

from bedlam.probes.result import DEFAULT_TIMEOUT_S, HealthStatus, ProbeResult
from bedlam.topology import Layer, endpoint_for

_USER = "postgres"
_PASSWORD = "postgres"
_DATABASE = "postgres"


async def _check(host: str, port: int, timeout_s: float) -> None:
    conn = await asyncpg.connect(
        host=host,
        port=port,
        user=_USER,
        password=_PASSWORD,
        database=_DATABASE,
        timeout=timeout_s,
    )
    try:
        await conn.fetchval("SELECT 1")
    finally:
        await conn.close()


async def probe(*, timeout_s: float = DEFAULT_TIMEOUT_S) -> ProbeResult:
    """Bounded to `timeout_s` end to end: a fault that stalls the connection
    after it opens (e.g. a `timeout` toxic) must not hang this probe -- that
    stall, reported as DOWN, is exactly the signal being measured.
    """
    endpoint = endpoint_for(Layer.DB)

    started = time.perf_counter()
    try:
        await asyncio.wait_for(_check(endpoint.host, endpoint.port, timeout_s), timeout=timeout_s)
        elapsed_ms = (time.perf_counter() - started) * 1000
        return ProbeResult(layer=Layer.DB, status=HealthStatus.UP, latency_ms=elapsed_ms)
    except Exception as exc:  # noqa: BLE001 - any failure means the layer is down
        elapsed_ms = (time.perf_counter() - started) * 1000
        return ProbeResult(
            layer=Layer.DB,
            status=HealthStatus.DOWN,
            latency_ms=elapsed_ms,
            error=f"{type(exc).__name__}: {exc}",
        )
