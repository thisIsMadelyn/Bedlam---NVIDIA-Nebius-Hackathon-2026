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
import re
from dataclasses import dataclass
from typing import Any

from bedlam import prompts
from bedlam.logging import get_logger
from bedlam.models.client import ModelCallError, ModelClient
from bedlam.models.map import CallSite
from bedlam.search.tavily import SearchResult
from bedlam.topology import Layer

_LOG = get_logger("bedlam.router")
_NOT_ALNUM = re.compile(r"[^a-z0-9]")


@dataclass(frozen=True, slots=True)
class ClassifiedResult:
    result: SearchResult
    layer: Layer | None  # None: the result is not about any layer of the stack
    component: str | None = None  # what Nano said failed; recorded, not routed on

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


def _squash(text: str) -> str:
    return _NOT_ALNUM.sub("", text.lower())


def _parser(results: tuple[SearchResult, ...], *, unverified: list[int] | None = None):
    """Parse the batched labels, checking each against its own result.

    A layered label must name a component that appears in its result's
    title, URL or snippet. In one batch Nano can drift by an index where one
    query's results end and the next begin, giving a result its neighbour's
    component and layer, or it can label noise with a plausible library.

    By default a failed check rejects the reply, and the reason goes back to
    Nano on the retry. Given an `unverified` list, the failing labels are
    instead kept as unlabelled and their indices appended to it.
    """
    texts = [_squash(f"{r.title} {r.url} {r.content}") for r in results]

    def parse(value: Any) -> list[tuple[Layer | None, str | None]]:
        labels: dict[int, tuple[Layer | None, str | None]] = {}
        for item in value["labels"]:
            index = int(item["index"])
            if not 0 <= index < len(results):
                raise ValueError(f"label index {index} out of range")
            raw = item["layer"]
            layer = None if raw in (None, "none") else Layer(raw)
            named = str(item.get("component") or "").strip() or None
            if layer is not None and _squash(named or "") not in texts[index]:
                if unverified is not None:
                    unverified.append(index)
                    layer = None
                    labels[index] = (layer, named)
                    continue
                raise ValueError(
                    f"result {index} does not mention component {named!r}. If the label "
                    "belongs to that result, name the component as that result writes it "
                    "(for example `Redis`, not `redis-py`). If it belongs to another "
                    "result, fix the index"
                )
            labels[index] = (layer, named)
        if len(labels) != len(results):
            raise ValueError(f"expected {len(results)} labels, got {len(labels)}")
        return [labels[i] for i in range(len(results))]

    return parse


async def classify_results(
    client: ModelClient, results: tuple[SearchResult, ...]
) -> list[ClassifiedResult]:
    """Label each search result with a layer, in one batched Nano call."""
    if not results:
        return []
    user = prompts.context(
        {
            "results": [
                {"index": i, "title": r.title, "url": r.url, "snippet": r.content}
                for i, r in enumerate(results)
            ]
        }
    )
    system = prompts.load("layer_classification")
    try:
        labels = await client.json(
            CallSite.LAYER_CLASSIFICATION, system=system, user=user, parse=_parser(results)
        )
    except ModelCallError as exc:
        # The site has no fallback model, so a check Nano keeps failing must not
        # fail the run. Keep its reply, but leave the labels that fail the check
        # out of the vote: an unverified label is as likely noise as signal.
        unverified: list[int] = []
        labels = await client.json(
            CallSite.LAYER_CLASSIFICATION,
            system=system,
            user=user,
            parse=_parser(results, unverified=unverified),
        )
        _LOG.warning(
            "unverified labels dropped",
            extra={"fields": {"indices": unverified, "reason": str(exc)}},
        )
    return [
        ClassifiedResult(result=r, layer=layer, component=component)
        for r, (layer, component) in zip(results, labels, strict=True)
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
