"""Tavily output decides the specialist: change the results, change the route."""

from __future__ import annotations

import asyncio
import random

from fakes import FakeSearchBackend, FakeTransport, plausible_model, tavily_hit

from bedlam.models.client import ModelClient
from bedlam.models.map import CallSite
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


# The live misalignment, 20 Oct: one batch, two queries' results, and Nano's
# labels drifted one index at the boundary. The phpredis issue got "httpx".
_REDIS = SearchResult("q1", "https://github.com/phpredis/phpredis/issues/1726",
                      "Redis->auth() freezes", "phpredis hangs on auth", 0.64)  # fmt: skip
_HTTPX = SearchResult("q2", "https://github.com/encode/httpx/discussions/3215",
                      "httpx client is slow", "httpx concurrency", 0.63)  # fmt: skip
_DRIFTED = {"labels": [{"index": 0, "component": "httpx", "layer": "api"},
                       {"index": 1, "component": "httpx", "layer": "api"}]}  # fmt: skip
_ALIGNED = {"labels": [{"index": 0, "component": "phpredis", "layer": "cache"},
                       {"index": 1, "component": "httpx", "layer": "api"}]}  # fmt: skip


def _classify_with(replies: list[dict]) -> tuple[list[ClassifiedResult], FakeTransport]:
    queue = list(replies)
    transport = FakeTransport({CallSite.LAYER_CLASSIFICATION: lambda ctx, model: queue.pop(0)})
    models = ModelClient(transport, root_seed=1, backoff_s=0.0)
    return asyncio.run(classify_results(models, (_REDIS, _HTTPX))), transport


def test_a_label_naming_a_component_its_result_never_mentions_is_retried() -> None:
    classified, transport = _classify_with([_DRIFTED, _ALIGNED])

    assert [c.layer for c in classified] == [Layer.CACHE, Layer.API]
    assert [c.component for c in classified] == ["phpredis", "httpx"]
    retry = transport.messages[1][-1]["content"]
    assert "result 0 does not mention component 'httpx'" in retry


def test_a_label_that_keeps_failing_the_check_is_left_out_not_fatal() -> None:
    # Both checked attempts rejected. The run goes on: the reply is kept, but
    # the label that fails the check no longer votes.
    classified, transport = _classify_with([_DRIFTED, _DRIFTED, _DRIFTED])

    assert [c.layer for c in classified] == [None, Layer.API]
    assert [c.component for c in classified] == ["httpx", "httpx"]
    assert len(transport.calls) == 3


def test_component_check_ignores_case_and_punctuation() -> None:
    reply = {"labels": [{"index": 0, "component": "PHPRedis", "layer": "cache"},
                        {"index": 1, "component": "HTTPX", "layer": "api"}]}  # fmt: skip
    classified, transport = _classify_with([reply])

    assert [c.layer for c in classified] == [Layer.CACHE, Layer.API]
    assert len(transport.calls) == 1
