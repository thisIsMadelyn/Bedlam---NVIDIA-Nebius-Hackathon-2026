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

from bedlam import loop
from bedlam.escalation import ScriptedChoice
from bedlam.loop import MAX_CYCLES, LoopDeps, run
from bedlam.models.client import ModelClient
from bedlam.patches import ScriptedPatchSource
from bedlam.search.manifest import load_manifest
from bedlam.search.tavily import SearchClient
from bedlam.trace import Trace


def _run_once(
    root_seed: int,
    trace_path: Path,
    toxiproxy: FakeToxiproxy | None = None,
    events: list[tuple[str, dict]] | None = None,
    choice: str | None = "a",
) -> tuple[dict, FakeToxiproxy, FakeSearchBackend]:
    toxiproxy = toxiproxy or FakeToxiproxy()
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
        choices=ScriptedChoice(choice) if choice else None,
    )
    if events is not None:
        deps.on_event = lambda kind, fields: events.append((kind, fields))
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
    assert trace["escalation"]["status"] == "chosen"
    assert trace["escalation"]["choice"] == "a"
    for cycle in trace["cycles"]:
        assert cycle["routing"]["basis"] == "search"
        assert all(r["component"] for r in cycle["results"] if r["layer"])
        assert cycle["blast_radius"]
        assert cycle["diff_analysis"]["summary"]


def test_every_model_call_is_in_the_trace_with_site_and_model(tmp_path: Path) -> None:
    trace, _, _ = _run_once(1729, tmp_path / "trace.json")
    calls = trace["model_calls"]
    sites = {c["site"] for c in calls}
    assert {"tavily_query_formulation", "layer_classification", "tavily_synthesis",
            "probe_classification", "diff_analysis", "tradeoff_escalation"} <= sites  # fmt: skip
    assert all(c["model"].startswith("nvidia/") for c in calls)
    # The escalation comes after the cycles, so it belongs to none of them.
    assert all(c["cycle"] in (1, 2) for c in calls if c["site"] != "tradeoff_escalation")
    assert [c["cycle"] for c in calls if c["site"] == "tradeoff_escalation"] == [None]
    assert len(trace["search_calls"]) == 2 * MAX_CYCLES


def test_events_follow_the_loop_in_order(tmp_path: Path) -> None:
    events: list[tuple[str, dict]] = []
    trace, _, _ = _run_once(1729, tmp_path / "trace.json", events=events)

    cycle_steps = ["cycle_started", "searching", "routed", "selected", "injecting", "probing",
                   "probed", "symptom", "awaiting_patch", "patched", "probing", "fault_removed",
                   "analysed"]  # fmt: skip
    assert [kind for kind, _ in events] == [
        "probing",
        "baseline",
        *cycle_steps * MAX_CYCLES,
        "escalating", "trade_off", "chosen", "showing_cost", "probing", "cost_shown",
        "probing", "cost_removed", "finished",
    ]  # fmt: skip
    injected = [fields["fault"] for kind, fields in events if kind == "injecting"]
    assert injected == trace["fault_sequence"]


def test_cycle_two_searches_away_from_what_cycle_one_searched(tmp_path: Path) -> None:
    _, _, backend = _run_once(1729, tmp_path / "trace.json")
    first, second = backend.queries[:2], backend.queries[2:]
    assert not set(first) & set(second)


def test_same_seed_same_fault_sequence_three_times(tmp_path: Path) -> None:
    sequences = [_run_once(1729, tmp_path / f"run{i}.json")[0]["fault_sequence"] for i in range(3)]
    assert sequences[0] == sequences[1] == sequences[2]


def test_toxic_left_by_a_killed_run_is_cleared_before_the_baseline(tmp_path: Path) -> None:
    clean, first, _ = _run_once(1729, tmp_path / "clean.json")
    # A killed run leaves the toxic the same seed is about to re-create.
    killed = FakeToxiproxy()
    killed.active[first.applied[0]] = "postgres" if first.applied[0].startswith("db") else "redis"

    trace, toxiproxy, _ = _run_once(1729, tmp_path / "rerun.json", toxiproxy=killed)

    assert trace["outcome"] == "completed"
    assert trace["fault_sequence"] == clean["fault_sequence"]
    assert all(r["status"] == "up" for r in trace["baseline"].values())
    assert not toxiproxy.active


class _ClosingTransport(FakeTransport):
    closed = False

    async def aclose(self) -> None:
        self.closed = True


class _FailingSearchBackend:
    async def search(self, query: str) -> dict:
        raise RuntimeError("tavily is down")


class _ToxiproxyContext(FakeToxiproxy):
    async def __aenter__(self) -> _ToxiproxyContext:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


def test_failure_mid_cycle_still_writes_a_failed_trace(tmp_path: Path, monkeypatch) -> None:
    transport = _ClosingTransport(plausible_model())
    toxiproxy = _ToxiproxyContext()
    monkeypatch.setattr(loop, "OpenAITransport", lambda: transport)
    monkeypatch.setattr(loop, "TavilyBackend", _FailingSearchBackend)
    monkeypatch.setattr(loop, "ToxiproxyClient", lambda: toxiproxy)
    monkeypatch.setattr(loop, "snapshot", probe_for(toxiproxy))
    trace_path = tmp_path / "trace.json"

    code = asyncio.run(loop.execute(1729, ScriptedPatchSource(), trace_path))

    assert code == 1
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    assert trace["outcome"] == "failed"
    assert trace["error"] == "RuntimeError: tavily is down"
    assert len(trace["cycles"]) == 1, "the partial cycle belongs in the trace"
    assert trace["fault_sequence"] == []
    assert transport.closed
