"""Fault primitives: latency, bandwidth, connection cut, timeout.

Each primitive is a Toxiproxy toxic under the hood. A `Fault` names exactly
one toxic on exactly one proxy -- one fault, one layer, per the architecture
invariant in CLAUDE.md. The toxic name is deterministic (`f"{layer}_{kind}"`),
never a uuid, so a run is reproducible and a second injection on the same
layer replaces the first instead of stacking.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from bedlam.faults.toxiproxy import ToxiproxyClient
from bedlam.logging import get_logger, log_event
from bedlam.topology import Layer, endpoint_for

_LOG = get_logger("bedlam.faults.primitives")


class FaultKind(StrEnum):
    LATENCY = "latency"
    BANDWIDTH = "bandwidth"
    CONNECTION_CUT = "connection_cut"
    TIMEOUT = "timeout"


# Fault kind -> Toxiproxy toxic type. Connection cut maps to `reset_peer`:
# a TCP reset fired after `timeout` ms, the closest Toxiproxy has to an
# abrupt drop rather than a slow failure.
_TOXIC_TYPE: dict[FaultKind, str] = {
    FaultKind.LATENCY: "latency",
    FaultKind.BANDWIDTH: "bandwidth",
    FaultKind.CONNECTION_CUT: "reset_peer",
    FaultKind.TIMEOUT: "timeout",
}


@dataclass(frozen=True, slots=True)
class Fault:
    """One fault: one layer, one toxic, one proxy."""

    layer: Layer
    kind: FaultKind
    proxy: str
    toxic_name: str
    attributes: dict[str, int]
    stream: str = "downstream"

    async def apply(self, client: ToxiproxyClient) -> None:
        await client.create_toxic(
            self.proxy,
            name=self.toxic_name,
            kind=_TOXIC_TYPE[self.kind],
            stream=self.stream,
            toxicity=1.0,
            attributes=self.attributes,
        )
        log_event(
            _LOG,
            "fault applied",
            layer=self.layer.value,
            kind=self.kind.value,
            proxy=self.proxy,
            attributes=self.attributes,
        )

    async def remove(self, client: ToxiproxyClient) -> None:
        await client.delete_toxic(self.proxy, self.toxic_name)
        log_event(
            _LOG, "fault removed", layer=self.layer.value, kind=self.kind.value, proxy=self.proxy
        )


def _require_proxy(layer: Layer) -> str:
    proxy = endpoint_for(layer).proxy_name
    if proxy is None:
        raise ValueError(f"layer {layer.value!r} has no Toxiproxy proxy in front of it")
    return proxy


def _toxic_name(layer: Layer, kind: FaultKind) -> str:
    return f"{layer.value}_{kind.value}"


def latency(layer: Layer, *, ms: int, jitter_ms: int = 0) -> Fault:
    """Delay traffic through the layer's proxy by `ms`, +/- `jitter_ms`."""
    proxy = _require_proxy(layer)
    return Fault(
        layer=layer,
        kind=FaultKind.LATENCY,
        proxy=proxy,
        toxic_name=_toxic_name(layer, FaultKind.LATENCY),
        attributes={"latency": ms, "jitter": jitter_ms},
    )


def bandwidth(layer: Layer, *, rate_kb_s: int) -> Fault:
    """Cap throughput through the layer's proxy to `rate_kb_s` KB/s."""
    proxy = _require_proxy(layer)
    return Fault(
        layer=layer,
        kind=FaultKind.BANDWIDTH,
        proxy=proxy,
        toxic_name=_toxic_name(layer, FaultKind.BANDWIDTH),
        attributes={"rate": rate_kb_s},
    )


def connection_cut(layer: Layer) -> Fault:
    """Reset every connection through the layer's proxy immediately."""
    proxy = _require_proxy(layer)
    return Fault(
        layer=layer,
        kind=FaultKind.CONNECTION_CUT,
        proxy=proxy,
        toxic_name=_toxic_name(layer, FaultKind.CONNECTION_CUT),
        attributes={"timeout": 0},
    )


def timeout(layer: Layer, *, ms: int) -> Fault:
    """Freeze traffic through the layer's proxy for `ms`, then close it.

    `ms=0` blocks forever without closing -- Toxiproxy's own semantics for
    this toxic, not a Bedlam convention.
    """
    proxy = _require_proxy(layer)
    return Fault(
        layer=layer,
        kind=FaultKind.TIMEOUT,
        proxy=proxy,
        toxic_name=_toxic_name(layer, FaultKind.TIMEOUT),
        attributes={"timeout": ms},
    )
