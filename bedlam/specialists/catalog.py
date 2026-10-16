"""The fault catalog: every fault Bedlam is able to inject, as discrete options.

Models never invent fault parameters. A specialist proposes catalog ids and
fault selection picks one of them, so every injected fault is one of a
small, known, bounded set -- which is what makes its blast radius computable
up front and a run reproducible. Each option is exactly one primitive on
exactly one layer.

Options are generated for every layer that has a Toxiproxy proxy in front of
it, read from the topology rather than listed by hand.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

from bedlam.faults.primitives import (
    Fault,
    FaultKind,
    bandwidth,
    connection_cut,
    latency,
    timeout,
)
from bedlam.topology import TOPOLOGY, Layer, blast_radius


@dataclass(frozen=True, slots=True)
class FaultOption:
    id: str
    layer: Layer
    kind: FaultKind
    param: int | None
    description: str

    def build(self) -> Fault:
        return _BUILDERS[self.kind](self.layer, self.param)

    @property
    def blast_radius(self) -> frozenset[Layer]:
        return blast_radius(self.layer)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "layer": self.layer.value,
            "kind": self.kind.value,
            "description": self.description,
            "blast_radius": sorted(layer.value for layer in self.blast_radius),
        }


_BUILDERS: Final[dict[FaultKind, Callable[[Layer, int | None], Fault]]] = {
    FaultKind.LATENCY: lambda layer, ms: latency(layer, ms=ms or 0),
    FaultKind.BANDWIDTH: lambda layer, rate: bandwidth(layer, rate_kb_s=rate or 1),
    FaultKind.CONNECTION_CUT: lambda layer, _: connection_cut(layer),
    FaultKind.TIMEOUT: lambda layer, ms: timeout(layer, ms=ms or 0),
}

# (kind, param, description template). One row per variant per layer.
_VARIANTS: Final = (
    (FaultKind.LATENCY, 300, "{layer}: +300ms on every round trip; exposes N+1 and chatty calls"),
    (FaultKind.LATENCY, 2500, "{layer}: +2500ms per round trip; outlasts default client timeouts"),
    (FaultKind.BANDWIDTH, 1, "{layer}: throughput capped at 1 KB/s; large payloads crawl"),
    (FaultKind.CONNECTION_CUT, None, "{layer}: every connection reset by peer immediately"),
    (FaultKind.TIMEOUT, 0, "{layer}: traffic black-holed, connections stay open and hang"),
    (FaultKind.TIMEOUT, 3000, "{layer}: traffic frozen for 3s, then the connection closes"),
)


def _option_id(layer: Layer, kind: FaultKind, param: int | None) -> str:
    return f"{layer.value}.{kind.value}" + (f".{param}" if param is not None else "")


def _build_catalog() -> tuple[FaultOption, ...]:
    faultable = sorted(layer for layer, ep in TOPOLOGY.items() if ep.proxy_name is not None)
    return tuple(
        FaultOption(
            id=_option_id(layer, kind, param),
            layer=layer,
            kind=kind,
            param=param,
            description=template.format(layer=layer.value),
        )
        for layer in faultable
        for kind, param, template in _VARIANTS
    )


CATALOG: Final[tuple[FaultOption, ...]] = _build_catalog()
_BY_ID: Final[dict[str, FaultOption]] = {option.id: option for option in CATALOG}


def option(option_id: str) -> FaultOption:
    """Look up a catalog option by id. Raises `KeyError` for unknown ids."""
    return _BY_ID[option_id]
