"""The Bedlam loop, headless.

Per cycle: formulate queries -> live search -> label results by layer ->
route to a specialist -> synthesise candidates -> select one fault under
blast-radius and history constraints -> inject it -> probe and classify ->
wait for the patch -> remove the fault -> analyse the patch.

Two cycles, then the escalation hand-off (Phase 4). Faults are strictly
sequential: one fault, one layer, removed before the next cycle selects.
Probes run concurrently; they are read-only.

Run: python -m bedlam.loop --headless
"""

from __future__ import annotations

import argparse
import asyncio
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from dotenv import load_dotenv

from bedlam import seed as seeding
from bedlam.diff import DiffAnalysis, analyse
from bedlam.faults.toxiproxy import ToxiproxyClient
from bedlam.history import FaultRecord
from bedlam.logging import get_logger, log_event
from bedlam.models.client import ModelCallError, ModelClient, OpenAITransport
from bedlam.patches import DEFAULT_PATCH_DIR, PatchSource, ScriptedPatchSource
from bedlam.probes import HealthStatus, ProbeResult, snapshot
from bedlam.probes.classify import Symptom
from bedlam.probes.classify import classify as classify_probe
from bedlam.replay import Recording, RecordingSearchBackend, RecordingTransport, recording_probe
from bedlam.router import classify_results, route
from bedlam.search.manifest import Dependency, load_manifest
from bedlam.search.query import formulate
from bedlam.search.tavily import SearchBackend, SearchClient, TavilyBackend, merge
from bedlam.select import select_fault
from bedlam.specialists import SPECIALISTS, Candidate
from bedlam.topology import TOPOLOGY, Layer
from bedlam.trace import Trace, snapshot_to_dict

_LOG = get_logger("bedlam.loop")

# Scope cap from CLAUDE.md: two cycles, then one trade-off escalation.
MAX_CYCLES: Final = 2
_REPO_ROOT: Final = Path(__file__).resolve().parents[1]


class StackUnhealthyError(RuntimeError):
    """The target stack was not healthy before the first fault."""


# A loop step as it happens: (kind, fields). The TUI renders these; headless
# runs pass nothing. Observers only -- an event never feeds a decision.
EventSink = Callable[[str, dict[str, Any]], None]


def _no_events(kind: str, fields: dict[str, Any]) -> None:
    return None


@dataclass
class LoopDeps:
    models: ModelClient
    search: SearchClient
    faults: ToxiproxyClient
    probe: Callable[[], Awaitable[dict[Layer, ProbeResult]]]
    patches: PatchSource
    manifest: tuple[Dependency, ...]
    root_seed: int
    on_event: EventSink = field(default=_no_events)


async def run(deps: LoopDeps, trace: Trace) -> Trace:
    """Run every cycle, filling `trace` as it goes. Returns the same trace."""
    # A run killed mid-fault leaves its toxic live in Toxiproxy. Clear it
    # first: it would skew the baseline, and re-creating the same name is 409.
    for endpoint in TOPOLOGY.values():
        if endpoint.proxy_name is None:
            continue
        leftover = await deps.faults.clear_toxics(endpoint.proxy_name)
        if leftover:
            _LOG.warning(
                "cleared leftover toxics",
                extra={"fields": {"proxy": endpoint.proxy_name, "toxics": leftover}},
            )

    emit = deps.on_event
    emit("probing", {"cycle": None})
    baseline = await deps.probe()
    trace.baseline = snapshot_to_dict(baseline)
    emit("baseline", {"snapshot": trace.baseline})
    down = sorted(layer.value for layer, r in baseline.items() if r.status is not HealthStatus.UP)
    if down:
        raise StackUnhealthyError(f"layers down before any fault: {down}. Run `make up`.")

    history: list[FaultRecord] = []
    symptom: Symptom | None = None
    analysis: DiffAnalysis | None = None
    previous_queries: list[str] = []

    for cycle in range(1, MAX_CYCLES + 1):
        deps.models.set_cycle(cycle)
        log_event(_LOG, "cycle started", cycle=cycle)
        record: dict[str, Any] = {"cycle": cycle}
        trace.cycles.append(record)
        emit("cycle_started", {"cycle": cycle})

        # 1. Search, live. Queries target dependency versions.
        queries = await formulate(
            deps.models,
            manifest=deps.manifest,
            history=history,
            symptom=symptom,
            analysis=analysis,
            previous_queries=previous_queries,
        )
        previous_queries += [q.text for q in queries]
        record["queries"] = [q.to_dict() for q in queries]
        emit("searching", {"cycle": cycle, "queries": record["queries"]})
        batches = await asyncio.gather(*(deps.search.search(q.text) for q in queries))
        results = merge(list(batches))

        # 2. Route on what the search returned.
        classified = await classify_results(deps.models, results)
        # The component goes in the trace only, so synthesis input is unchanged.
        record["results"] = [{**item.to_dict(), "component": item.component} for item in classified]
        routing = route(
            classified,
            symptom_layer=symptom.layer if symptom else None,
            rng=seeding.rng(deps.root_seed, f"route:{cycle}"),
        )
        specialist = SPECIALISTS[routing.layer]
        record["routing"] = routing.to_dict()
        record["specialist"] = specialist.name
        log_event(_LOG, "routed", cycle=cycle, **routing.to_dict(), specialist=specialist.name)
        emit(
            "routed", {"cycle": cycle, "routing": record["routing"], "specialist": specialist.name}
        )

        # 3. Synthesise and select. A failed synthesis leaves selection to
        #    fall back on the specialist's own tools, under the same rules.
        candidates: tuple[Candidate, ...] = ()
        try:
            candidates = await specialist.synthesize(
                deps.models,
                classified=classified,
                symptom=symptom,
                analysis=analysis,
                history=history,
            )
        except ModelCallError as exc:
            _LOG.warning("synthesis failed", extra={"fields": {"cycle": cycle, "error": str(exc)}})
        record["candidates"] = [c.to_dict() for c in candidates]
        selection = await select_fault(
            deps.models,
            candidates=candidates,
            specialist=specialist,
            history=history,
            analysis=analysis,
            rng=seeding.rng(deps.root_seed, f"select:{cycle}"),
        )
        record["selection"] = selection.to_dict()
        emit("selected", {"cycle": cycle, "selection": record["selection"]})

        # 4. Inject. Blast radius is fixed before the toxic exists.
        option = selection.option
        record["blast_radius"] = sorted(layer.value for layer in option.blast_radius)
        fault = option.build()
        log_event(_LOG, "injecting", cycle=cycle, fault=option.id, blast=record["blast_radius"])
        emit(
            "injecting",
            {
                "cycle": cycle,
                "fault": option.id,
                "layer": option.layer.value,
                "kind": option.kind.value,
                "blast_radius": record["blast_radius"],
            },
        )
        try:
            # Inside the try: a create that lands on the server but times out
            # on the client must still be removed. Removing a toxic that was
            # never created is a 404, which delete_toxic treats as done.
            await fault.apply(deps.faults)
            emit("probing", {"cycle": cycle})
            during = await deps.probe()
            record["probe_during_fault"] = snapshot_to_dict(during)
            emit("probed", {"cycle": cycle, "snapshot": record["probe_during_fault"]})
            symptom = await classify_probe(deps.models, during)
            record["symptom"] = symptom.to_dict()
            emit("symptom", {"cycle": cycle, "symptom": record["symptom"]})
            emit("awaiting_patch", {"cycle": cycle})
            patch = await deps.patches.wait_for_patch(cycle)
            record["patch"] = {"source": patch.source, "chars": len(patch.diff)}
            emit("patched", {"cycle": cycle, "patch": record["patch"]})
        finally:
            await fault.remove(deps.faults)
        emit("probing", {"cycle": cycle})
        record["probe_after_removal"] = snapshot_to_dict(await deps.probe())
        emit("fault_removed", {"cycle": cycle, "snapshot": record["probe_after_removal"]})

        # 5. Read the patch.
        fault_record = FaultRecord(cycle, option.id, option.layer, option.kind, specialist.name)
        analysis = await analyse(deps.models, diff=patch.diff, fault=fault_record, symptom=symptom)
        record["diff_analysis"] = analysis.to_dict()
        emit("analysed", {"cycle": cycle, "analysis": record["diff_analysis"]})
        history.append(fault_record)
        log_event(_LOG, "cycle finished", cycle=cycle, fault=option.id, symptom=symptom.kind.value)

    deps.models.set_cycle(None)
    # Phase 4 builds the escalation itself. This is the hand-off point, and
    # it carries the inputs the escalation will reason over.
    trace.escalation = {
        "status": "pending_phase_4",
        "faults": [r.to_dict() for r in history],
        "last_patch": analysis.to_dict() if analysis else None,
    }
    trace.outcome = "completed"
    emit("escalation_pending", {"escalation": trace.escalation})
    return trace


async def execute(
    root_seed: int,
    patches: PatchSource,
    trace_path: Path,
    record_path: Path | None = None,
    on_event: EventSink = _no_events,
    on_clients: Callable[[ModelClient, SearchClient], None] | None = None,
) -> int:
    """One live run against the local stack. Returns the process exit code.

    `on_clients` hands the live model and search clients to an observer (the
    TUI reads their call logs); `on_event` receives each loop step.
    """
    transport = OpenAITransport()
    models = ModelClient(transport, root_seed=root_seed)
    backend: SearchBackend = TavilyBackend()
    probe: Callable[[], Awaitable[dict[Layer, ProbeResult]]] = snapshot
    # Recording wraps the live calls; it never replaces them.
    recording = Recording(root_seed=root_seed) if record_path else None
    if recording is not None:
        models = ModelClient(RecordingTransport(transport, recording), root_seed=root_seed)
        backend = RecordingSearchBackend(backend, recording)
        probe = recording_probe(snapshot, recording)
    search = SearchClient(backend)
    if on_clients is not None:
        on_clients(models, search)
    manifest = load_manifest()
    trace = Trace(root_seed=root_seed, manifest=manifest)
    try:
        async with ToxiproxyClient() as faults:
            deps = LoopDeps(
                models=models,
                search=search,
                faults=faults,
                probe=probe,
                patches=patches,
                manifest=manifest,
                root_seed=root_seed,
                on_event=on_event,
            )
            await run(deps, trace)
    except Exception as exc:
        trace.outcome = "failed"
        trace.error = f"{type(exc).__name__}: {exc}"
        _LOG.exception("run failed")
    finally:
        trace.write(trace_path, models, search)
        if recording is not None and record_path is not None:
            recording.fault_sequence = trace.to_dict(models, search)["fault_sequence"]
            recording.write(record_path)
        await transport.aclose()
    log_event(
        _LOG,
        "run finished",
        outcome=trace.outcome,
        trace=str(trace_path),
        fault_sequence=[c.get("selection", {}).get("fault", {}).get("id") for c in trace.cycles],
        model_calls=len(models.records),
        search_calls=len(search.calls),
    )
    return 0 if trace.outcome == "completed" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bedlam.loop", description=__doc__.splitlines()[0])
    parser.add_argument("--headless", action="store_true", help="run the loop without a UI")
    parser.add_argument("--seed", type=int, default=None, help="root seed (default: BEDLAM_SEED)")
    parser.add_argument("--patches", type=Path, default=DEFAULT_PATCH_DIR)
    parser.add_argument("--trace", type=Path, default=None, help="trace output path")
    parser.add_argument(
        "--record", type=Path, default=None, help="also write a replay recording to this path"
    )
    args = parser.parse_args(argv)

    if not args.headless:
        parser.error("the TUI is `python -m bedlam.tui`; this entry point is --headless only")

    load_dotenv(_REPO_ROOT / ".env")
    root_seed = args.seed if args.seed is not None else seeding.root_seed()
    os.environ[seeding.ROOT_SEED_ENV] = str(root_seed)
    trace_path = args.trace or _REPO_ROOT / "traces" / f"headless-seed{root_seed}.json"
    patches = ScriptedPatchSource(args.patches)
    return asyncio.run(execute(root_seed, patches, trace_path, args.record))


if __name__ == "__main__":
    raise SystemExit(main())
