"""Bedlam's voice: templated, seeded, and inside 82 columns."""

from __future__ import annotations

from pathlib import Path

from test_loop import _run_once

from bedlam.faults.primitives import FaultKind
from bedlam.probes.classify import SymptomKind
from bedlam.specialists import SPECIALISTS
from bedlam.specialists.catalog import CATALOG
from bedlam.topology import Layer
from bedlam.tui import SAY
from bedlam.voice import LINES, Voice

EVENTS = {
    "probing", "baseline", "cycle_started", "searching", "routed", "selected", "injecting",
    "probed", "symptom", "awaiting_patch", "patched", "fault_removed", "analysed",
    "escalation_pending",
}  # fmt: skip


def test_every_line_fits_one_timeline_row_with_the_longest_values() -> None:
    longest = {
        "layer": max((layer.value for layer in Layer), key=len),
        "specialist": max((s.name for s in SPECIALISTS.values()), key=len),
        "fault": max((option.id for option in CATALOG), key=len),
    }
    for key, lines in LINES.items():
        for line in lines:
            shown = "» " + line.format(**longest)
            assert len(shown) <= SAY, f"{key}: {len(shown)} > {SAY}: {shown}"


def test_keys_name_real_events_and_cover_every_kind() -> None:
    assert {key.split(":")[0] for key in LINES} <= EVENTS
    assert {f"injecting:{kind.value}" for kind in FaultKind} <= LINES.keys()
    assert {f"symptom:{kind.value}" for kind in SymptomKind} <= LINES.keys()


def _spoken(root_seed: int, tmp_path: Path) -> list[str]:
    events: list[tuple[str, dict]] = []
    _run_once(1729, tmp_path / "trace.json", events=events)
    voice = Voice(root_seed)
    return [line for kind, fields in events if (line := voice.say(kind, fields))]


def test_same_seed_same_lines_and_none_repeats(tmp_path: Path) -> None:
    first = _spoken(1729, tmp_path)
    assert first == _spoken(1729, tmp_path)
    assert len(first) == len(set(first)), "a line repeated within one run"
    assert first != _spoken(7, tmp_path), "the voice ignored the seed"
    assert "{" not in "".join(first), "a template placeholder leaked"


def test_an_event_without_lines_stays_quiet() -> None:
    assert Voice(1729).say("probed", {"cycle": 1, "snapshot": {}}) is None
