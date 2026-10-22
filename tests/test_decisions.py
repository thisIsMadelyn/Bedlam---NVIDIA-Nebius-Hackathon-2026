"""Model map seeds, manifest, query rules, catalog and selection constraints."""

from __future__ import annotations

import asyncio
import random

import pytest
from fakes import FakeTransport

from bedlam.diff import DiffAnalysis
from bedlam.faults.primitives import FaultKind
from bedlam.history import FaultRecord
from bedlam.models.client import ModelCallError, ModelClient
from bedlam.models.map import CALL_SITES, CallSite, spec_for
from bedlam.search.manifest import load_manifest, lookup
from bedlam.search.query import formulate
from bedlam.select import select_fault
from bedlam.specialists import CATALOG, SPECIALISTS, Candidate, option
from bedlam.topology import Layer

# --- model map ---------------------------------------------------------------


def test_every_site_seed_derives_from_the_root_seed() -> None:
    for site in CALL_SITES:
        assert spec_for(site, root_seed=1729).seed == spec_for(site, root_seed=1729).seed
        assert spec_for(site, root_seed=1729).seed != spec_for(site, root_seed=1730).seed
    assert spec_for(CallSite.FAULT_SELECTION, root_seed=1).temperature == 0.0


# --- manifest and queries ---------------------------------------------------


def test_manifest_versions_come_from_the_lockfile() -> None:
    manifest = load_manifest()
    asyncpg = lookup(manifest, "asyncpg")
    assert asyncpg is not None and asyncpg.version == "0.31.0"
    assert lookup(manifest, "fastapi-boilerplate") is None


def _formulate(answer: dict) -> tuple:
    transport = FakeTransport({CallSite.TAVILY_QUERY_FORMULATION: lambda _c, _m: answer})
    client = ModelClient(transport, root_seed=1, backoff_s=0.0)
    return asyncio.run(
        formulate(
            client,
            manifest=load_manifest(),
            history=[],
            symptom=None,
            analysis=None,
            previous_queries=[],
            rng=random.Random(1),
        )
    )


def test_query_version_is_filled_from_the_manifest_not_the_model() -> None:
    queries = _formulate(
        {
            "queries": [
                {"dependency": "asyncpg", "failure_term": "pool exhaustion not recovering"},
                {"dependency": "redis", "failure_term": "socket connect hangs forever"},
            ]
        }
    )
    assert queries[0].text == "asyncpg 0.31.0 pool exhaustion not recovering"
    assert queries[1].text.startswith("redis 7.4.0 ")


@pytest.mark.parametrize(
    "bad",
    [
        {"dependency": "fastapi-boilerplate", "failure_term": "random bug in prod"},
        {"dependency": "asyncpg", "failure_term": "boilerplate pool bug"},
        {"dependency": "notadep", "failure_term": "pool exhaustion here"},
    ],
)
def test_queries_never_target_the_boilerplate_or_unknown_deps(bad: dict) -> None:
    good = {"dependency": "redis", "failure_term": "socket connect hangs forever"}
    queries = _formulate({"queries": [bad, good]})
    assert [q.templated for q in queries] == [True], "the whole reply is rejected"
    assert not any("boilerplate" in q.text or "notadep" in q.text for q in queries)


def test_a_repeated_query_is_named_in_the_rejection_so_the_retry_can_fix_it() -> None:
    previous = "asyncpg 0.31.0 pool exhaustion not recovering"
    repeat = {"dependency": "asyncpg", "failure_term": "pool exhaustion not recovering"}
    redis = {"dependency": "redis", "failure_term": "socket connect hangs forever"}
    fixed = {"dependency": "asyncpg", "failure_term": "prepared statement cache invalid"}
    replies = iter([{"queries": [repeat, redis, dict(redis)]}, {"queries": [fixed, redis]}])
    transport = FakeTransport({CallSite.TAVILY_QUERY_FORMULATION: lambda _c, _m: next(replies)})
    client = ModelClient(transport, root_seed=1, backoff_s=0.0)
    queries = asyncio.run(
        formulate(
            client,
            manifest=load_manifest(),
            history=[],
            symptom=None,
            analysis=None,
            previous_queries=[previous],
            rng=random.Random(1),
        )
    )

    assert [q.dependency for q in queries] == ["asyncpg", "redis"]
    retry = " ".join(m["content"] for m in transport.messages[1])
    assert "`asyncpg` + `pool exhaustion not recovering` was already searched" in retry
    assert "two queries target `redis`" in retry


def _formulate_with(reply: dict, previous: list[str]):
    transport = FakeTransport({CallSite.TAVILY_QUERY_FORMULATION: lambda _c, _m: reply})
    client = ModelClient(transport, root_seed=1, backoff_s=0.0)
    return asyncio.run(
        formulate(
            client,
            manifest=load_manifest(),
            history=[],
            symptom=None,
            analysis=None,
            previous_queries=previous,
            rng=random.Random(1),
        )
    )


def test_a_query_repeated_on_every_attempt_leaves_the_run_one_live_search() -> None:
    previous = "asyncpg 0.31.0 pool exhaustion not recovering"
    repeat = {"dependency": "asyncpg", "failure_term": "pool exhaustion not recovering"}
    redis = {"dependency": "redis", "failure_term": "socket connect hangs forever"}

    queries = _formulate_with({"queries": [repeat, redis]}, [previous])

    assert [q.text.split()[0] for q in queries] == ["redis"]
    assert all(q.short for q in queries), "a short round must say so in the trace"


def test_no_usable_query_on_any_attempt_searches_one_templated_query() -> None:
    previous = "asyncpg 0.31.0 pool exhaustion not recovering"
    repeat = {"dependency": "asyncpg", "failure_term": "pool exhaustion not recovering"}

    queries = _formulate_with({"queries": [repeat]}, [previous])

    assert len(queries) == 1 and queries[0].templated, "the trace must say it was templated"
    assert lookup(load_manifest(), queries[0].dependency).version == queries[0].version
    assert queries[0].text not in {previous}
    assert queries == _formulate_with({"queries": [repeat]}, [previous]), "seeded, not random"


def test_a_model_outage_stops_the_run_instead_of_templating() -> None:
    async def down(**_kw):
        raise ConnectionError("401 Unauthorized")

    with pytest.raises(ModelCallError, match="401") as caught:
        asyncio.run(
            formulate(
                ModelClient(down, root_seed=1, backoff_s=0.0),
                manifest=load_manifest(),
                history=[],
                symptom=None,
                analysis=None,
                previous_queries=[],
                rng=random.Random(1),
            )
        )
    assert not caught.value.replied


def test_a_templated_query_is_never_one_already_searched() -> None:
    import bedlam.search.query as query_module

    manifest = load_manifest()
    every = [
        f"{dep} {lookup(manifest, dep).version} {term}" for dep, term in query_module._TEMPLATES
    ]
    repeat = {"dependency": "asyncpg", "failure_term": "pool exhaustion not recovering"}
    previous = ["asyncpg 0.31.0 pool exhaustion not recovering", *every[1:]]

    queries = _formulate_with({"queries": [repeat]}, previous)
    assert [q.text for q in queries] == every[:1]

    with pytest.raises(ModelCallError, match="already searched"):
        _formulate_with({"queries": [repeat]}, [*previous, every[0]])


# --- catalog and specialists ------------------------------------------------


def test_catalog_options_are_unique_single_layer_and_buildable() -> None:
    assert len({o.id for o in CATALOG}) == len(CATALOG)
    for o in CATALOG:
        fault = o.build()
        assert fault.layer is o.layer and fault.kind is o.kind
        assert o.blast_radius == frozenset({o.layer, Layer.API})


def test_each_layer_has_exactly_one_specialist_with_tools() -> None:
    assert set(SPECIALISTS) == set(Layer)
    assert all(s.tools for s in SPECIALISTS.values())
    assert {o.kind for o in SPECIALISTS[Layer.API].tools} == {FaultKind.LATENCY, FaultKind.TIMEOUT}


# --- selection constraints --------------------------------------------------


def _select(candidate_ids, *, history=(), analysis=None, answer=None, seed=0):
    specialist = SPECIALISTS[Layer.CACHE]
    candidates = tuple(Candidate(option(i), "h", ("https://x",)) for i in candidate_ids)
    handler = (lambda _c, _m: answer) if answer is not None else (lambda c, _m: {"fault_id": "?"})
    client = ModelClient(
        FakeTransport({CallSite.FAULT_SELECTION: handler}), root_seed=1, backoff_s=0
    )
    return asyncio.run(
        select_fault(
            client,
            candidates=candidates,
            specialist=specialist,
            history=list(history),
            analysis=analysis,
            rng=random.Random(seed),
        )
    )


def test_selection_rejects_repeats_and_defended_directions() -> None:
    history = [FaultRecord(1, "cache.latency.300", Layer.CACHE, FaultKind.LATENCY, "cache")]
    analysis = DiffAnalysis(
        frozenset({Layer.CACHE}), frozenset({(Layer.CACHE, FaultKind.TIMEOUT)}), "s", ()
    )
    picked = _select(
        ["cache.latency.2500", "cache.timeout.0", "cache.bandwidth.1"],
        history=history,
        analysis=analysis,
    )
    assert picked.option.id == "cache.bandwidth.1"
    assert picked.source == "only_option"
    assert set(picked.rejected) == {"cache.latency.2500", "cache.timeout.0"}


def test_selection_widens_to_specialist_tools_when_no_candidate_survives() -> None:
    history = [FaultRecord(1, "cache.timeout.0", Layer.CACHE, FaultKind.TIMEOUT, "cache")]
    picked = _select(
        ["cache.timeout.3000"], history=history, answer={"fault_id": "cache.bandwidth.1"}
    )
    assert picked.pool == "specialist_tools"
    assert picked.option.id == "cache.bandwidth.1"
    assert all(not i.startswith("cache.timeout") for i in picked.eligible)


def test_unusable_model_answer_falls_back_to_a_seeded_draw() -> None:
    ids = ["cache.latency.300", "cache.bandwidth.1", "cache.connection_cut"]
    first = _select(ids, seed=42)
    again = _select(ids, seed=42)
    assert first.source == "seeded_fallback"
    assert first.option.id == again.option.id
