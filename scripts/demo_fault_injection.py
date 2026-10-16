"""Phase 1 manual proof: inject Redis latency, watch the stack degrade,
remove it, watch it recover. Zero changes to the boilerplate's source --
every step here goes through Toxiproxy's control API or a direct probe.

Requires the stack running: `make up`.

Run: python scripts/demo_fault_injection.py
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

from bedlam.faults import ToxiproxyClient, latency  # noqa: E402
from bedlam.probes import snapshot  # noqa: E402
from bedlam.topology import Layer, blast_radius  # noqa: E402

FAULT_LATENCY_MS = 1500


def _print_snapshot(label: str, results: dict) -> None:
    print(f"-- {label} --")
    for layer in Layer:
        result = results[layer]
        latency_str = f"{result.latency_ms:.0f}ms" if result.latency_ms is not None else "n/a"
        line = f"  {layer.value:<5} {result.status.value:<4} {latency_str}"
        if result.error:
            line += f"  ({result.error})"
        print(line)
    print()


async def main() -> int:
    load_dotenv()

    affected = sorted(layer.value for layer in blast_radius(Layer.CACHE))
    print(f"blast radius of a cache-layer fault: {affected}")
    print()

    baseline = await snapshot()
    _print_snapshot("before fault", baseline)

    fault = latency(Layer.CACHE, ms=FAULT_LATENCY_MS, jitter_ms=0)
    async with ToxiproxyClient() as client:
        await fault.apply(client)
        try:
            print(f"injected: {fault.kind.value} on {fault.layer.value} ({fault.attributes})")
            print()

            degraded = await snapshot()
            _print_snapshot("during fault", degraded)
        finally:
            await fault.remove(client)
            print("fault removed")
            print()

    recovered = await snapshot()
    _print_snapshot("after removal", recovered)

    cache_degraded = (
        degraded[Layer.CACHE].latency_ms is not None
        and baseline[Layer.CACHE].latency_ms is not None
        and degraded[Layer.CACHE].latency_ms > baseline[Layer.CACHE].latency_ms
    )
    cache_recovered = (
        recovered[Layer.CACHE].status.value == "up"
        and recovered[Layer.CACHE].latency_ms is not None
        and recovered[Layer.CACHE].latency_ms < degraded[Layer.CACHE].latency_ms
    )

    if cache_degraded and cache_recovered:
        print("PASS  cache layer degraded under fault and recovered after removal.")
        return 0
    print("FAIL  did not observe the expected degrade/recover pattern.")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
