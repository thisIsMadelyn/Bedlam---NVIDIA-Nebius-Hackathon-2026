"""The full two-cycle loop, offline: sequencing, trace shape, determinism."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fakes import (
    FakeSearchBackend,
    FakeToxiproxy,
    FakeTransport,
    default_search_results,
    plausible_model,
    probe_for,
)

from bedlam.loop import MAX_CYCLES, LoopDeps, run
from bedlam.models.client import ModelClient
from bedlam.patches import ScriptedPatchSource
from bedlam.search.manifest import load_manifest
from bedlam.search.tavily import SearchClient
from bedlam.trace import Trace


def _run_once(root_seed: int, trace_path: Path) -> tuple[dict, FakeToxiproxy, FakeSearchBackend]:
    toxiproxy = FakeToxiproxy()
    backend = FakeSearchBackend(default_search_results())
    models = ModelClient(FakeTransport(plausible_model()), root_seed=root_seed, backoff_s=0.0)
    search = SearchClient(backend)
    manifest = load_manifest()
    deps = LoopDeps(
        models=models,
        search=search,
        faults=toxiproxy,  # type: ignore[arg-type]
        probe=probe_for(toxiproxy),
        patches=ScriptedPatchSource(),
        manifest=manifest,
        root_seed=root_seed,
    )
    trace = asyncio.run(run(deps, Trace(root_seed=root_seed, manifest=manifest)))
    trace.write(trace_path, models, search)
    return json.loads(trace_path.read_text(encoding="utf-8")), toxiproxy, backend


def test_two_cycles_complete_and_write_a_structured_trace(tmp_path: Path) -> None:
    trace, toxiproxy, _ = _run_once(1729, tmp_path / "trace.json")

    assert trace["outcome"] == "completed"
    assert len(trace["cycles"]) == MAX_CYCLES
    assert len(trace["fault_sequence"]) == MAX_CYCLES
    assert len(set(trace["fault_sequence"])) == MAX_CYCLES, "a cycle repeated a fault"
    assert not toxiproxy.active, "a fault was left behind"
    assert trace["escalation"]["status"] == "pending_phase_4"
    for cycle in trace["cycles"]:
        assert cycle["routing"]["basis"] == "search"
        assert cycle["blast_radius"]
        assert cycle["diff_analysis"]["summary"]


def test_every_model_call_is_in_the_trace_with_site_and_model(tmp_path: Path) -> None:
    trace, _, _ = _run_once(1729, tmp_path / "trace.json")
    calls = trace["model_calls"]
    sites = {c["site"] for c in calls}
    assert {"tavily_query_formulation", "layer_classification", "tavily_synthesis",
            "probe_classification", "diff_analysis"} <= sites  # fmt: skip
    assert all(c["model"].startswith("nvidia/") and c["cycle"] in (1, 2) for c in calls)
    assert len(trace["search_calls"]) == 2 * MAX_CYCLES


def test_cycle_two_searches_away_from_what_cycle_one_searched(tmp_path: Path) -> None:
    _, _, backend = _run_once(1729, tmp_path / "trace.json")
    first, second = backend.queries[:2], backend.queries[2:]
    assert not set(first) & set(second)


def test_same_seed_same_fault_sequence_three_times(tmp_path: Path) -> None:
    sequences = [_run_once(1729, tmp_path / f"run{i}.json")[0]["fault_sequence"] for i in range(3)]
    assert sequences[0] == sequences[1] == sequences[2]
