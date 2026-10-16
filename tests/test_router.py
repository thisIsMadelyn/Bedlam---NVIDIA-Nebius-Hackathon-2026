"""Tavily output decides the specialist: change the results, change the route."""

from __future__ import annotations

import asyncio
import random

from fakes import FakeSearchBackend, FakeTransport, plausible_model, tavily_hit

from bedlam.models.client import ModelClient
from bedlam.router import ClassifiedResult, classify_results, route
from bedlam.search.tavily import SearchClient, SearchResult, merge
from bedlam.specialists import SPECIALISTS
from bedlam.topology import Layer

QUERY = "redis 7.4.0 connection hangs under timeout"


def _route_for(hits: list[dict]) -> str:
    """The real search -> classify -> route path, over a given Tavily reply."""

    async def go() -> str:
        search = SearchClient(FakeSearchBackend({"redis": hits}))
        results = merge([await search.search(QUERY)])
        models = ModelClient(FakeTransport(plausible_model()), root_seed=1)
        classified = await classify_results(models, results)
        decision = route(classified, symptom_layer=None, rng=random.Random(0))
        return SPECIALISTS[decision.layer].name

    return asyncio.run(go())


def test_same_query_different_search_output_routes_to_different_specialists() -> None:
    cache_heavy = [
        tavily_hit("https://github.com/redis/redis-py/issues/1", "redis-py hangs", 0.9),
        tavily_hit("https://github.com/sqlalchemy/sqlalchemy/issues/2", "sqlalchemy pool", 0.3),
    ]
    db_heavy = [
        tavily_hit("https://github.com/redis/redis-py/issues/1", "redis-py hangs", 0.3),
        tavily_hit("https://github.com/sqlalchemy/sqlalchemy/issues/2", "sqlalchemy pool", 0.6),
        tavily_hit("https://github.com/MagicStack/asyncpg/issues/3", "asyncpg stuck", 0.5),
    ]
    api_heavy = [
        tavily_hit("https://github.com/encode/uvicorn/issues/4", "uvicorn workers starve", 0.9),
    ]
    assert _route_for(cache_heavy) == "cache"
    assert _route_for(db_heavy) == "db"
    assert _route_for(api_heavy) == "api"


def _classified(*pairs: tuple[Layer | None, float]) -> list[ClassifiedResult]:
    return [
        ClassifiedResult(SearchResult("q", f"https://example.com/{i}", "t", "c", score), layer)
        for i, (layer, score) in enumerate(pairs)
    ]


def test_weight_is_summed_relevance_not_the_single_top_hit() -> None:
    decision = route(
        _classified((Layer.CACHE, 0.9), (Layer.DB, 0.5), (Layer.DB, 0.5)),
        symptom_layer=None,
        rng=random.Random(0),
    )
    assert decision.layer is Layer.DB
    assert decision.basis == "search"


def test_tie_breaks_on_strongest_single_result() -> None:
    decision = route(
        _classified((Layer.DB, 0.4), (Layer.DB, 0.4), (Layer.CACHE, 0.8)),
        symptom_layer=None,
        rng=random.Random(0),
    )
    assert decision.layer is Layer.CACHE


def test_no_layered_results_falls_back_to_symptom_then_seed() -> None:
    nothing = _classified((None, 0.9))
    by_symptom = route(nothing, symptom_layer=Layer.DB, rng=random.Random(0))
    assert (by_symptom.layer, by_symptom.basis) == (Layer.DB, "symptom")

    seeded_a = route(nothing, symptom_layer=None, rng=random.Random(7))
    seeded_b = route(nothing, symptom_layer=None, rng=random.Random(7))
    assert seeded_a.basis == "seeded"
    assert seeded_a.layer is seeded_b.layer
