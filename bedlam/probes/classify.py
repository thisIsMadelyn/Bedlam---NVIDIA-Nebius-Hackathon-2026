"""Probe classification: a health snapshot in, one symptom enum out (Nano).

The snapshot is reduced to latency *buckets* and error *types* before it
reaches the model. Raw milliseconds and error messages differ between two
runs of the same fault, and feeding them in verbatim would let timing noise
change the symptom -- and through it the next search, the specialist and the
fault. Reproducibility is a deliverable; the buckets keep the signal and
drop the jitter.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

from bedlam import prompts
from bedlam.models.client import ModelClient
from bedlam.models.map import CallSite
from bedlam.probes.result import ProbeResult
from bedlam.topology import Layer

# Upper bounds in ms -> label. Anything above the last bound is "over_2000ms",
# which is also where probes start timing out (DEFAULT_TIMEOUT_S = 2.0).
_LATENCY_BUCKETS: Final = ((50.0, "under_50ms"), (500.0, "50_to_500ms"), (2000.0, "500_to_2000ms"))


class SymptomKind(StrEnum):
    HEALTHY = "healthy"
    SLOW = "slow"
    UNREACHABLE = "unreachable"
    STALLED = "stalled"


@dataclass(frozen=True, slots=True)
class Symptom:
    kind: SymptomKind
    layer: Layer | None  # the layer showing the symptom; None when healthy
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "layer": self.layer.value if self.layer else None,
            "summary": self.summary,
        }


def latency_bucket(latency_ms: float | None) -> str:
    if latency_ms is None:
        return "unknown"
    for bound, label in _LATENCY_BUCKETS:
        if latency_ms < bound:
            return label
    return "over_2000ms"


def observation(results: dict[Layer, ProbeResult]) -> list[dict[str, Any]]:
    """The jitter-free view of a snapshot that the classifier sees."""
    return [
        {
            "layer": layer.value,
            "status": results[layer].status.value,
            "latency": latency_bucket(results[layer].latency_ms),
            "error_type": results[layer].error.split(":", 1)[0] if results[layer].error else None,
        }
        for layer in sorted(results)
    ]


def _parse(value: Any) -> Symptom:
    kind = SymptomKind(value["symptom"])
    raw_layer = value.get("layer")
    layer = None if raw_layer in (None, "none") else Layer(raw_layer)
    if kind is not SymptomKind.HEALTHY and layer is None:
        raise ValueError("a non-healthy symptom must name a layer")
    return Symptom(kind=kind, layer=layer, summary=str(value.get("summary", ""))[:200])


async def classify(client: ModelClient, results: dict[Layer, ProbeResult]) -> Symptom:
    return await client.json(
        CallSite.PROBE_CLASSIFICATION,
        system=prompts.load("probe_classification"),
        user=prompts.context({"snapshot": observation(results)}),
        parse=_parse,
    )
