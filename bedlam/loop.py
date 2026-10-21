"""The Bedlam loop, headless.

Per cycle: formulate queries -> live search -> label results by layer ->
route to a specialist -> synthesise candidates -> select one fault under
blast-radius and history constraints -> inject it -> probe and classify ->
wait for the patch -> remove the fault -> restart the api with the patch ->
inject the same fault again and read through the app to see whether the
patch held -> remove it -> analyse the patch.

Two cycles, then the trade-off escalation: Bedlam presents two options and
the developer chooses; the cost of the chosen one is then shown live, once.
Faults are strictly sequential: one fault, one layer, removed before the
next one. Probes run concurrently; they are read-only.

Run: python -m bedlam.loop --headless [--choice a|b]
"""

from __future__ import annotations

import argparse
import asyncio
import functools
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from dotenv import load_dotenv

from bedlam import seed as seeding
from bedlam.diff import DiffAnalysis, analyse
from bedlam.escalation import KEYS, ChoiceSource, ScriptedChoice, decision_record, escalate
from bedlam.faults.toxiproxy import ToxiproxyClient
from bedlam.history import FaultRecord
from bedlam.logging import get_logger, log_event
from bedlam.models.client import ModelCallError, ModelClient, OpenAITransport
from bedlam.patches import (
    DEFAULT_PATCH_DIR,
    DEFAULT_TARGET,
    PatchSource,
    ScriptedPatchSource,
    deploy,
)
from bedlam.probes import HealthStatus, ProbeResult, snapshot
from bedlam.probes.app import AppProbe, AppResult, held
from bedlam.probes.classify import Symptom
from bedlam.probes.classify import classify as classify_probe
from bedlam.replay import (
    Recording,
    RecordingSearchBackend,
    RecordingTransport,
    recording_app_probe,
    recording_probe,
)
from bedlam.router import classify_results, route
from bedlam.search.manifest import Dependency, load_manifest
from bedlam.search.query import formulate
from bedlam.search.tavily import SearchBackend, SearchClient, TavilyBackend, merge
from bedlam.select import select_fault
from bedlam.specialists import SPECIALISTS, Candidate
from bedlam.specialists.catalog import FaultOption
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
    # The developer's side of the trade-off. None: present it and stop
    # there -- Bedlam never fills in a choice it was not given.
    choices: ChoiceSource | None = None
    # The read through the app that judges each patch, and the restart that
    # puts the patch in the api. None: the patch is analysed but not checked.
    app_probe: Callable[[], Awaitable[AppResult]] | None = None
    deploy: Callable[[], Awaitable[None]] | None = None


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
    if deps.app_probe is not None:
        app_baseline = await deps.app_probe()
        trace.app_baseline = app_baseline.to_dict()
        if not app_baseline.ok:
            raise StackUnhealthyError(
                f"the read through the app failed before any fault: {app_baseline.error}"
            )

    history: list[FaultRecord] = []
    symptom: Symptom | None = None
    analysis: DiffAnalysis | None = None
    previous_queries: list[str] = []
    analyses: list[DiffAnalysis] = []
    symptoms: list[Symptom] = []

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
            "routed",
            {
                "cycle": cycle,
                "routing": record["routing"],
                "specialist": specialist.name,
                "results": record["results"],
            },
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
        app_before: AppResult | None = None
        try:
            # Inside the try: a create that lands on the server but times out
            # on the client must still be removed. Removing a toxic that was
            # never created is a 404, which delete_toxic treats as done.
            await fault.apply(deps.faults)
            emit("probing", {"cycle": cycle})
            if deps.app_probe is None:
                during = await deps.probe()
            else:
                # Read-only, so concurrent with the layer probes.
                during, app_before = await asyncio.gather(deps.probe(), deps.app_probe())
                record["app_under_fault"] = app_before.to_dict()
            record["probe_during_fault"] = snapshot_to_dict(during)
            emit("probed", {"cycle": cycle, "snapshot": record["probe_during_fault"]})
            symptom = await classify_probe(deps.models, during)
            record["symptom"] = symptom.to_dict()
            emit("symptom", {"cycle": cycle, "symptom": record["symptom"]})
            emit("awaiting_patch", {"cycle": cycle})
            patch = await deps.patches.wait_for_patch(cycle, option.id)
            record["patch"] = {"source": patch.source, "chars": len(patch.diff)}
            emit("patched", {"cycle": cycle, "patch": record["patch"]})
        finally:
            await fault.remove(deps.faults)
        if app_before is not None:
            await _check_patch(deps, cycle, record, option, app_before)
        emit("probing", {"cycle": cycle})
        record["probe_after_removal"] = snapshot_to_dict(await deps.probe())
        emit("fault_removed", {"cycle": cycle, "snapshot": record["probe_after_removal"]})

        # 5. Read the patch.
        fault_record = FaultRecord(cycle, option.id, option.layer, option.kind, specialist.name)
        analysis = await analyse(deps.models, diff=patch.diff, fault=fault_record, symptom=symptom)
        record["diff_analysis"] = analysis.to_dict()
        analyses.append(analysis)
        symptoms.append(symptom)
        emit("analysed", {"cycle": cycle, "analysis": record["diff_analysis"]})
        history.append(fault_record)
        log_event(_LOG, "cycle finished", cycle=cycle, fault=option.id, symptom=symptom.kind.value)

    deps.models.set_cycle(None)
    await _escalate(deps, trace, history, analyses, symptoms)
    trace.outcome = "completed"
    emit("finished", {"escalation": trace.escalation})
    return trace


async def _check_patch(
    deps: LoopDeps, cycle: int, record: dict[str, Any], option: FaultOption, before: AppResult
) -> None:
    """Same fault, patched app: read through it again and judge the patch.

    The fault is already removed: the api restarts with the patch on a
    healthy stack, then the same fault goes back in, alone, for one read.
    """
    assert deps.app_probe is not None
    emit = deps.on_event
    emit("deploying", {"cycle": cycle})
    if deps.deploy is not None:
        await deps.deploy()
    fault = option.build()
    emit(
        "retesting",
        {
            "cycle": cycle,
            "fault": option.id,
            "layer": option.layer.value,
            "blast_radius": record["blast_radius"],
        },
    )
    try:
        await fault.apply(deps.faults)
        emit("probing", {"cycle": cycle})
        after = await deps.app_probe()
    finally:
        await fault.remove(deps.faults)
    check = {"before": before.to_dict(), "after": after.to_dict(), "held": held(before, after)}
    record["patch_check"] = check
    log_event(_LOG, "patch checked", cycle=cycle, held=check["held"])
    emit("patch_checked", {"cycle": cycle, "check": check})


async def _escalate(
    deps: LoopDeps,
    trace: Trace,
    history: list[FaultRecord],
    analyses: list[DiffAnalysis],
    symptoms: list[Symptom],
) -> None:
    """Present the trade-off, take the developer's choice, show its cost once."""
    emit = deps.on_event
    emit("escalating", {})
    trade_off = await escalate(deps.models, history=history, analyses=analyses, symptoms=symptoms)
    escalation: dict[str, Any] = {
        "status": "awaiting_choice",
        "faults": [r.to_dict() for r in history],
        "trade_off": trade_off.to_dict(),
    }
    trace.escalation = escalation
    log_event(_LOG, "trade-off presented", axis=trade_off.axis, source=trade_off.source)
    emit("trade_off", {"trade_off": escalation["trade_off"]})
    if deps.choices is None:
        escalation["status"] = "no_choice_given"
        return

    key = await deps.choices.wait_for_choice(trade_off)
    chosen = trade_off.option(key)
    escalation.update(status="chosen", choice=key)
    log_event(_LOG, "trade-off chosen", choice=key, title=chosen.title)
    emit("chosen", {"choice": key, "option": chosen.to_dict()})

    # The cost, live: the chosen option's consequence, applied once.
    consequence = chosen.consequence
    fault = consequence.build()
    shown: dict[str, Any] = {"fault": consequence.id}
    escalation["consequence"] = shown
    emit(
        "showing_cost",
        {
            "fault": consequence.id,
            "layer": consequence.layer.value,
            "kind": consequence.kind.value,
            "blast_radius": sorted(layer.value for layer in consequence.blast_radius),
        },
    )
    try:
        await fault.apply(deps.faults)
        emit("probing", {"cycle": None})
        shown["probe_during"] = snapshot_to_dict(await deps.probe())
        emit("cost_shown", {"snapshot": shown["probe_during"]})
    finally:
        await fault.remove(deps.faults)
    emit("probing", {"cycle": None})
    shown["probe_after"] = snapshot_to_dict(await deps.probe())
    emit("cost_removed", {"snapshot": shown["probe_after"]})


async def execute(
    root_seed: int,
    patches: PatchSource,
    trace_path: Path,
    record_path: Path | None = None,
    on_event: EventSink = _no_events,
    on_clients: Callable[[ModelClient, SearchClient], None] | None = None,
    choices: ChoiceSource | None = None,
) -> int:
    """One live run against the local stack. Returns the process exit code.

    `on_clients` hands the live model and search clients to an observer (the
    TUI reads their call logs); `on_event` receives each loop step;
    `choices` is the developer's side of the trade-off. A run that reaches a
    choice also writes it as a decision record next to the trace.
    """
    transport = OpenAITransport()
    models = ModelClient(transport, root_seed=root_seed)
    backend: SearchBackend = TavilyBackend()
    probe: Callable[[], Awaitable[dict[Layer, ProbeResult]]] = snapshot
    live_app_probe = AppProbe()
    app_probe: Callable[[], Awaitable[AppResult]] = live_app_probe
    # Recording wraps the live calls; it never replaces them.
    recording = Recording(root_seed=root_seed) if record_path else None
    if recording is not None:
        models = ModelClient(RecordingTransport(transport, recording), root_seed=root_seed)
        backend = RecordingSearchBackend(backend, recording)
        probe = recording_probe(snapshot, recording)
        app_probe = recording_app_probe(app_probe, recording)
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
                choices=choices,
                app_probe=app_probe,
                # The warm-up reads go unrecorded: they only wait.
                deploy=functools.partial(deploy, warm_up=live_app_probe),
            )
            await run(deps, trace)
    except Exception as exc:
        trace.outcome = "failed"
        trace.error = f"{type(exc).__name__}: {exc}"
        _LOG.exception("run failed")
    finally:
        trace.write(trace_path, models, search)
        if trace.escalation and "choice" in trace.escalation:
            decision_path(trace_path).write_text(
                decision_record(trace.escalation), encoding="utf-8"
            )
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


def decision_path(trace_path: Path) -> Path:
    """Where a run's decision record goes: beside its trace."""
    return trace_path.with_suffix(".decision.md")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bedlam.loop", description=__doc__.splitlines()[0])
    parser.add_argument("--headless", action="store_true", help="run the loop without a UI")
    parser.add_argument("--seed", type=int, default=None, help="root seed (default: BEDLAM_SEED)")
    parser.add_argument("--patches", type=Path, default=DEFAULT_PATCH_DIR)
    parser.add_argument("--trace", type=Path, default=None, help="trace output path")
    parser.add_argument(
        "--record", type=Path, default=None, help="also write a replay recording to this path"
    )
    parser.add_argument(
        "--choice",
        choices=KEYS,
        default=None,
        help="your side of the trade-off; without it the run presents the options and stops",
    )
    args = parser.parse_args(argv)

    if not args.headless:
        parser.error("the TUI is `python -m bedlam.tui`; this entry point is --headless only")

    load_dotenv(_REPO_ROOT / ".env")
    root_seed = args.seed if args.seed is not None else seeding.root_seed()
    os.environ[seeding.ROOT_SEED_ENV] = str(root_seed)
    trace_path = args.trace or _REPO_ROOT / "traces" / f"headless-seed{root_seed}.json"
    choices = ScriptedChoice(args.choice) if args.choice else None
    # The prepared diffs are applied to the target for the run, so the api
    # runs them, and reverted when it ends.
    with ScriptedPatchSource(args.patches, target=DEFAULT_TARGET) as patches:
        return asyncio.run(execute(root_seed, patches, trace_path, args.record, choices=choices))


if __name__ == "__main__":
    raise SystemExit(main())
