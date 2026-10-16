"""Patch analysis: what did the developer's patch actually defend against (Super).

The output is structured so the rest of the loop can act on it in code:
`defended` is a list of (layer, fault kind) pairs that fault selection then
refuses to repeat -- the next break comes from a direction the patch did not
cover. `gaps` and `summary` are prose for query formulation, synthesis and,
in Phase 4, the trade-off escalation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from bedlam import prompts
from bedlam.faults.primitives import FaultKind
from bedlam.history import FaultRecord
from bedlam.models.client import ModelClient
from bedlam.models.map import CallSite
from bedlam.probes.classify import Symptom
from bedlam.topology import Layer

# Large diffs are truncated, not summarised by another model call: one call
# site, one model, as the map says.
_MAX_DIFF_CHARS: Final = 12_000


@dataclass(frozen=True, slots=True)
class DiffAnalysis:
    touched_layers: frozenset[Layer]
    defended: frozenset[tuple[Layer, FaultKind]]
    summary: str
    gaps: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "touched_layers": sorted(layer.value for layer in self.touched_layers),
            "defended": [
                {"layer": layer.value, "kind": kind.value} for layer, kind in sorted(self.defended)
            ],
            "summary": self.summary,
            "gaps": list(self.gaps),
        }


def _parse(value: Any) -> DiffAnalysis:
    touched = frozenset(Layer(raw) for raw in value["touched_layers"])
    defended = frozenset(
        (Layer(item["layer"]), FaultKind(item["kind"])) for item in value.get("defended", [])
    )
    summary = str(value["summary"]).strip()
    if not summary:
        raise ValueError("summary is empty")
    gaps = tuple(str(gap).strip()[:200] for gap in value.get("gaps", []) if str(gap).strip())
    return DiffAnalysis(
        touched_layers=touched, defended=defended, summary=summary[:600], gaps=gaps[:4]
    )


async def analyse(
    client: ModelClient, *, diff: str, fault: FaultRecord, symptom: Symptom
) -> DiffAnalysis:
    truncated = len(diff) > _MAX_DIFF_CHARS
    return await client.json(
        CallSite.DIFF_ANALYSIS,
        system=prompts.load("diff_analysis"),
        user=prompts.context(
            {
                "fault_injected": fault.to_dict(),
                "symptom_observed": symptom.to_dict(),
                "diff_truncated": truncated,
                "diff": diff[:_MAX_DIFF_CHARS],
                "fault_kinds": [kind.value for kind in FaultKind],
            }
        ),
        parse=_parse,
    )
