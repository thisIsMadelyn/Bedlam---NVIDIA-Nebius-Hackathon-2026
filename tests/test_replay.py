"""Determinism given recorded inputs: replay a run, get the same fault sequence.

Live runs with one seed can diverge because Token Factory is not
deterministic at temperature 0. The guarantee Bedlam owns is that the same
model replies, Tavily results and probe snapshots produce the same decisions.
`tests/fixtures/replay-seed1729.json` is one live run, recorded with
`make record`. Replay answers only requests identical to the recorded ones,
so any divergence in Bedlam's own code fails here.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from fakes import (
    FakeSearchBackend,
    FakeToxiproxy,
    FakeTransport,
    default_search_results,
    plausible_model,
    probe_for,
)

from bedlam.loop import LoopDeps, run
from bedlam.models.client import ModelCallError, ModelClient
from bedlam.patches import ScriptedPatchSource
from bedlam.replay import (
    Recording,
    RecordingSearchBackend,
    RecordingTransport,
    ReplayProbe,
    ReplaySearchBackend,
    ReplayTransport,
    recording_probe,
)
from bedlam.search.manifest import load_manifest
from bedlam.search.tavily import SearchClient
from bedlam.trace import Trace

LIVE_RECORDING = Path(__file__).parent / "fixtures" / "replay-seed1729.json"


def _replay(recording: Recording) -> tuple[list[str], int, list[str]]:
    """Replay once: the fault sequence, recorded inputs left unused, mismatches."""
    transport = ReplayTransport(recording)
    backend = ReplaySearchBackend(recording)
    probe = ReplayProbe(recording)
    models = ModelClient(transport, root_seed=recording.root_seed, backoff_s=0.0)
    search = SearchClient(backend)
    manifest = load_manifest()
    deps = LoopDeps(
        models=models,
        search=search,
        faults=FakeToxiproxy(),  # type: ignore[arg-type]
        probe=probe,
        patches=ScriptedPatchSource(),
        manifest=manifest,
        root_seed=recording.root_seed,
    )
    trace = Trace(root_seed=recording.root_seed, manifest=manifest)
    try:
        asyncio.run(run(deps, trace))
    except ModelCallError:
        pass  # the mismatch that caused it is in `transport.mismatches`
    sequence = trace.to_dict(models, search)["fault_sequence"]
    unused = transport.unused() + backend.unused() + probe.unused()
    return sequence, unused, transport.mismatches


def _record_offline(root_seed: int) -> Recording:
    recording = Recording(root_seed=root_seed)
    toxiproxy = FakeToxiproxy()
    transport = RecordingTransport(FakeTransport(plausible_model()), recording)
    models = ModelClient(transport, root_seed=root_seed, backoff_s=0.0)
    search = SearchClient(
        RecordingSearchBackend(FakeSearchBackend(default_search_results()), recording)
    )
    manifest = load_manifest()
    deps = LoopDeps(
        models=models,
        search=search,
        faults=toxiproxy,  # type: ignore[arg-type]
        probe=recording_probe(probe_for(toxiproxy), recording),
        patches=ScriptedPatchSource(),
        manifest=manifest,
        root_seed=root_seed,
    )
    trace = asyncio.run(run(deps, Trace(root_seed=root_seed, manifest=manifest)))
    recording.fault_sequence = trace.to_dict(models, search)["fault_sequence"]
    return recording


def test_recorded_live_run_replays_to_the_same_fault_sequence_three_times() -> None:
    recording = Recording.read(LIVE_RECORDING)
    assert recording.fault_sequence, "the recorded live run selected no fault"

    for _ in range(3):
        sequence, unused, mismatches = _replay(recording)
        assert not mismatches
        assert sequence == recording.fault_sequence
        assert unused == 0, "replay skipped recorded inputs, so it took a different path"


def test_offline_recording_round_trips_through_a_file(tmp_path: Path) -> None:
    recording = _record_offline(1729)
    path = tmp_path / "recording.json"
    recording.write(path)

    sequence, unused, mismatches = _replay(Recording.read(path))

    assert not mismatches
    assert sequence == recording.fault_sequence
    assert unused == 0


def test_a_request_the_recording_does_not_hold_fails_loudly() -> None:
    recording = _record_offline(1729)
    # Stands in for a change in Bedlam's own code: a different first request.
    recording.model_calls[0]["key"] = "0" * 64

    _, _, mismatches = _replay(recording)

    assert mismatches
    assert "tavily_query_formulation" in mismatches[0]
    assert "not in the recording" in mismatches[0]
