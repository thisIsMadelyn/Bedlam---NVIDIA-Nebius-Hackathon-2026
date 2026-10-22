"""Read-only health probe for the API layer.

Hits the boilerplate's own `/health` endpoint directly over HTTP. The API
layer has no Toxiproxy proxy in front of it in Phase 1 (see topology.py), so
this probe measures the app process's own liveness, not a faulted path.
"""

from __future__ import annotations

import time

import httpx

from bedlam.probes.result import DEFAULT_TIMEOUT_S, HealthStatus, ProbeResult, describe
from bedlam.topology import Layer, endpoint_for


async def probe(*, timeout_s: float = DEFAULT_TIMEOUT_S) -> ProbeResult:
    endpoint = endpoint_for(Layer.API)
    url = f"{endpoint.base_url}/health"

    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.get(url)
        elapsed_ms = (time.perf_counter() - started) * 1000
        if resp.status_code == 200:
            return ProbeResult(layer=Layer.API, status=HealthStatus.UP, latency_ms=elapsed_ms)
        return ProbeResult(
            layer=Layer.API,
            status=HealthStatus.DOWN,
            latency_ms=elapsed_ms,
            error=f"HTTP {resp.status_code}",
        )
    except Exception as exc:  # noqa: BLE001 - any failure means the layer is down
        elapsed_ms = (time.perf_counter() - started) * 1000
        return ProbeResult(
            layer=Layer.API,
            status=HealthStatus.DOWN,
            latency_ms=elapsed_ms,
            error=describe(exc, timeout_s),
        )
