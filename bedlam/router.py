"""Specialist routing, driven by live search output.

Nano labels every Tavily result with the layer it is about. Each layer's
weight is the sum of Tavily relevance scores of the results labelled with
it, and the heaviest layer's specialist handles the cycle. Change what the
search returns and the specialist changes with it -- that is what makes
Tavily architectural here rather than decorative.

Ties break on the single strongest result, then on result order (which is
itself stable, see `search.tavily.merge`). Only when no result is about any
layer does routing fall back: first to the layer the probes blamed, then to
a draw from the seeded RNG. Every decision records which basis it used.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from bedlam import prompts
from bedlam.models.client import ModelClient
from bedlam.models.map import CallSite
from bedlam.search.tavily import SearchResult
from bedlam.topology import Layer


@dataclass(frozen=True, slots=True)
class ClassifiedResult:
    result: SearchResult
    layer: Layer | None  # None: the result is not about any layer of the stack

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.result.url,
            "title": self.result.title,
            "score": self.result.score,
            "query": self.result.query,
            "layer": self.layer.value if self.layer else None,
        }


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    layer: Layer
    basis: str  # "search" | "symptom" | "seeded"
    weights: dict[Layer, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "layer": self.layer.value,
            "basis": self.basis,
            "weights": {layer.value: round(w, 4) for layer, w in sorted(self.weights.items())},
        }


def _parser(count: int):
    def parse(value: Any) -> list[Layer | None]:
        labels: dict[int, Layer | None] = {}
        for item in value["labels"]:
            index = int(item["index"])
            if not 0 <= index < count:
                raise ValueError(f"label index {index} out of range")
            raw = item["layer"]
            labels[index] = None if raw in (None, "none") else Layer(raw)
        if len(labels) != count:
            raise ValueError(f"expected {count} labels, got {len(labels)}")
        return [labels[i] for i in range(count)]

    return parse


async def classify_results(
    client: ModelClient, results: tuple[SearchResult, ...]
) -> list[ClassifiedResult]:
    """Label each search result with a layer, in one batched Nano call."""
    if not results:
        return []
    labels = await client.json(
        CallSite.LAYER_CLASSIFICATION,
        system=prompts.load("layer_classification"),
        user=prompts.context(
            {
                "results": [
                    {"index": i, "title": r.title, "url": r.url, "snippet": r.content}
                    for i, r in enumerate(results)
                ]
            }
        ),
        parse=_parser(len(results)),
    )
    return [
        ClassifiedResult(result=r, layer=layer) for r, layer in zip(results, labels, strict=True)
    ]


def route(
    classified: list[ClassifiedResult], *, symptom_layer: Layer | None, rng: random.Random
) -> RoutingDecision:
    """Pick the layer whose specialist handles this cycle."""
    weights: dict[Layer, float] = {}
    strongest: dict[Layer, float] = {}
    first_seen: dict[Layer, int] = {}
    for position, item in enumerate(classified):
        if item.layer is None:
            continue
        weights[item.layer] = weights.get(item.layer, 0.0) + item.result.score
        strongest[item.layer] = max(strongest.get(item.layer, 0.0), item.result.score)
        first_seen.setdefault(item.layer, position)

    if weights:
        winner = min(
            weights, key=lambda layer: (-weights[layer], -strongest[layer], first_seen[layer])
        )
        return RoutingDecision(layer=winner, basis="search", weights=weights)
    if symptom_layer is not None:
        return RoutingDecision(layer=symptom_layer, basis="symptom", weights=weights)
    return RoutingDecision(layer=rng.choice(sorted(Layer)), basis="seeded", weights=weights)
