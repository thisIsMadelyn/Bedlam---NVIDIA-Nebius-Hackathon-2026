"""The structured JSON trace a headless run writes.

The trace holds every decision the loop made and what it was based on:
queries, live search results with their layer labels, the routing vote,
the specialist, candidates, the selection and its constraints, blast radius,
probe snapshots, the patch and its analysis. It also holds every model call
(site, model, tokens, latency, outcome) and every Tavily call.

`fault_sequence` is the field the determinism check compares across runs.
Timestamps are recorded for the reader and never feed a decision.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bedlam import __version__
from bedlam.models.client import ModelClient
from bedlam.models.map import CALL_SITES, spec_for
from bedlam.probes.result import ProbeResult
from bedlam.search.manifest import Dependency
from bedlam.search.tavily import SearchClient
from bedlam.topology import Layer


def snapshot_to_dict(results: dict[Layer, ProbeResult]) -> dict[str, Any]:
    return {
        layer.value: {
            "status": result.status.value,
            "latency_ms": round(result.latency_ms, 1) if result.latency_ms is not None else None,
            "error": result.error,
        }
        for layer, result in sorted(results.items())
    }


@dataclass
class Trace:
    root_seed: int
    manifest: tuple[Dependency, ...]
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    baseline: dict[str, Any] | None = None
    app_baseline: dict[str, Any] | None = None  # the read through the app, unfaulted
    cycles: list[dict[str, Any]] = field(default_factory=list)
    escalation: dict[str, Any] | None = None
    outcome: str = "running"
    error: str | None = None

    def to_dict(self, models: ModelClient, search: SearchClient) -> dict[str, Any]:
        return {
            "bedlam_version": __version__,
            "root_seed": self.root_seed,
            "started_at": self.started_at,
            "outcome": self.outcome,
            "error": self.error,
            # A failed run can end mid-cycle, before routing or selection ran.
            # Only cycles that reached each step contribute to its sequence.
            "fault_sequence": [
                c["selection"]["fault"]["id"] for c in self.cycles if "selection" in c
            ],
            "specialist_sequence": [c["specialist"] for c in self.cycles if "specialist" in c],
            "model_map": {
                site.value: {
                    "model": spec.model,
                    "fallback": spec.fallback,
                    "temperature": spec.temperature,
                    "seed": spec.seed,
                    "max_tokens": spec.max_tokens,
                }
                for site in CALL_SITES
                for spec in [spec_for(site, root_seed=self.root_seed)]
            },
            "manifest": [asdict(dep) for dep in self.manifest],
            "baseline": self.baseline,
            "app_baseline": self.app_baseline,
            "cycles": self.cycles,
            "escalation": self.escalation,
            "model_calls": [record.to_dict() for record in models.records],
            "search_calls": [asdict(call) for call in search.calls],
        }

    def write(self, path: Path, models: ModelClient, search: SearchClient) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(models, search), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
