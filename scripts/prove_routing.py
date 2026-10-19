"""Phase 2 gate: live Tavily output decides which specialist handles a cycle.

Runs the loop's real search -> classify -> route path (live Tavily, live
Nano, the router's own `route()`), holding the model side fixed: one root
seed, one prompt, one client. Only what Tavily returns differs.

A. Three searches that target dependencies on different layers. Each
   result set is labelled and routed on its own; different search output
   should reach different specialists.
B. A counterfactual on the merged real results: drop every result labelled
   with the winning layer and route again. The route moves with the
   evidence, not with the query that fetched it.

Writes the evidence to traces/routing-proof.json.

Run: make prove-routing
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from bedlam import seed as seeding
from bedlam.models.client import ModelClient, OpenAITransport
from bedlam.router import ClassifiedResult, classify_results, route
from bedlam.search.manifest import load_manifest, lookup
from bedlam.search.tavily import SearchClient, TavilyBackend
from bedlam.specialists import SPECIALISTS

# One query per layer. Versions come from the manifest, never typed here.
_QUERIES = (
    ("redis", "connection hangs after socket timeout"),
    ("asyncpg", "connection pool exhaustion not recovering"),
    ("fastapi", "request hangs worker blocked"),
)
_TRACE = Path(__file__).resolve().parents[1] / "traces" / "routing-proof.json"


def _decide(classified: list[ClassifiedResult], root_seed: int) -> dict[str, Any]:
    # No symptom: routing must come from the search results alone.
    decision = route(classified, symptom_layer=None, rng=seeding.rng(root_seed, "route:proof"))
    return {**decision.to_dict(), "specialist": SPECIALISTS[decision.layer].name}


def _show(title: str, classified: list[ClassifiedResult], decision: dict[str, Any]) -> None:
    print(title)
    for item in classified:
        layer = item.layer.value if item.layer else "-"
        print(f"  {layer:>5}  {item.result.score:.3f}  {item.result.url[:66]}")
    print(f"  weights {decision['weights']}  basis={decision['basis']}")
    print(f"  -> specialist: {decision['specialist']}")
    print()


async def _prove(root_seed: int) -> dict[str, Any]:
    manifest = load_manifest()
    transport = OpenAITransport()
    models = ModelClient(transport, root_seed=root_seed)
    search = SearchClient(TavilyBackend())
    evidence: dict[str, Any] = {"root_seed": root_seed, "runs": []}
    merged: list[ClassifiedResult] = []
    try:
        for name, term in _QUERIES:
            dep = lookup(manifest, name)
            if dep is None:
                raise RuntimeError(f"{name} is not in the target's manifest")
            query = f"{dep.name} {dep.version} {term}"
            classified = await classify_results(models, await search.search(query))
            decision = _decide(classified, root_seed)
            _show(f"A. {query}", classified, decision)
            evidence["runs"].append(
                {"query": query, "results": [c.to_dict() for c in classified], **decision}
            )
            merged += classified

        before = _decide(merged, root_seed)
        winner = before["layer"]
        without = [c for c in merged if c.layer is None or c.layer.value != winner]
        after = _decide(without, root_seed)
        print(f"B. merged results ({len(merged)}) -> {before['specialist']}")
        dropped = len(merged) - len(without)
        print(f"   without the {dropped} {winner} results -> {after['specialist']}")
        print(f"   weights before {before['weights']}  after {after['weights']}")
        evidence["counterfactual"] = {"merged": before, "without_winner": after}
    finally:
        await transport.aclose()

    evidence["model_calls"] = [r.to_dict() for r in models.records]
    evidence["search_calls"] = [asdict(c) for c in search.calls]
    return evidence


def main() -> int:
    load_dotenv()
    root_seed = seeding.root_seed()
    evidence = asyncio.run(_prove(root_seed))

    specialists = [run["specialist"] for run in evidence["runs"]]
    distinct = len(set(specialists))
    moved = (
        evidence["counterfactual"]["merged"]["specialist"]
        != evidence["counterfactual"]["without_winner"]["specialist"]
    )
    evidence["verdict"] = {"distinct_specialists": distinct, "counterfactual_moved": moved}
    _TRACE.parent.mkdir(exist_ok=True)
    _TRACE.write_text(json.dumps(evidence, indent=2), encoding="utf-8")

    print()
    print(f"A: {distinct} distinct specialists from {len(specialists)} searches: {specialists}")
    print(f"B: counterfactual moved the route: {moved}")
    print(f"evidence: {_TRACE}")
    return 0 if distinct > 1 and moved else 1


if __name__ == "__main__":
    sys.exit(main())
