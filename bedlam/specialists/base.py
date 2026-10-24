"""What a specialist is: a prompt plus a tool set, turning evidence into faults.

Synthesis (Super, temp 0.0) reads the live search results the router sent
this specialist's way and proposes candidate faults, each grounded in a
cited result and drawn only from the specialist's own tools. Anything
outside the tool set, or citing a URL that was not in the evidence, is
dropped in code -- the model proposes, the catalog disposes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from bedlam import prompts
from bedlam.diff import DiffAnalysis
from bedlam.history import FaultRecord
from bedlam.models.client import ModelClient
from bedlam.models.map import CallSite
from bedlam.probes.classify import Symptom
from bedlam.router import ClassifiedResult
from bedlam.specialists.catalog import FaultOption
from bedlam.topology import Layer

MAX_CANDIDATES: Final = 4
_MAX_EVIDENCE: Final = 8


@dataclass(frozen=True, slots=True)
class Candidate:
    option: FaultOption
    hypothesis: str
    evidence: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "fault_id": self.option.id,
            "hypothesis": self.hypothesis,
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True, slots=True)
class Specialist:
    name: str
    layer: Layer
    prompt: str  # path under bedlam/prompts/, without the .md
    tools: tuple[FaultOption, ...]

    def evidence(self, classified: list[ClassifiedResult]) -> list[ClassifiedResult]:
        """Results about this specialist's layer first, then the rest, capped."""
        own = [item for item in classified if item.layer == self.layer]
        rest = [item for item in classified if item.layer != self.layer]
        return (own + rest)[:_MAX_EVIDENCE]

    async def synthesize(
        self,
        client: ModelClient,
        *,
        classified: list[ClassifiedResult],
        symptom: Symptom | None,
        analysis: DiffAnalysis | None,
        history: list[FaultRecord],
    ) -> tuple[Candidate, ...]:
        evidence = self.evidence(classified)
        return await client.json(
            CallSite.TAVILY_SYNTHESIS,
            system=prompts.load("synthesis") + "\n\n" + prompts.load(self.prompt),
            user=prompts.context(
                {
                    "specialist": self.name,
                    "tools": [option.to_dict() for option in self.tools],
                    "evidence": [
                        {**item.to_dict(), "snippet": item.result.content} for item in evidence
                    ],
                    "last_symptom": symptom.to_dict() if symptom else None,
                    "last_patch": analysis.to_dict() if analysis else None,
                    "faults_so_far": [record.to_dict() for record in history],
                    "max_candidates": MAX_CANDIDATES,
                }
            ),
            parse=self._parser(evidence),
        )

    def _parser(self, evidence: list[ClassifiedResult]):
        tools = {option.id: option for option in self.tools}
        layer_of = {item.result.url: item.layer for item in evidence}
        # A fault is backed by a result about the layer it hits. Only when the
        # search found nothing about any layer these tools hit does other
        # evidence do, so a round is never left without candidates.
        grounded = {option.layer for option in self.tools} & set(layer_of.values())

        def parse(value: Any) -> tuple[Candidate, ...]:
            candidates: list[Candidate] = []
            off_layer: list[str] = []
            for item in value["candidates"]:
                option = tools.get(str(item["fault_id"]))
                cited = tuple(url for url in item.get("evidence", []) if url in layer_of)
                hypothesis = " ".join(str(item.get("hypothesis", "")).split())
                if option is None or not cited or not hypothesis:
                    continue
                if grounded and all(layer_of[url] != option.layer for url in cited):
                    off_layer.append(option.id)
                    continue
                if any(c.option.id == option.id for c in candidates):
                    continue
                candidates.append(Candidate(option, hypothesis[:400], cited[:3]))
            if not candidates and off_layer:
                layers = ", ".join(sorted(layer.value for layer in grounded))
                raise ValueError(
                    f"{', '.join(off_layer)} cite no result about the layer they fault. "
                    f"Back each fault with a result labelled with its own layer; "
                    f"evidence has results for: {layers}"
                )
            if not candidates:
                raise ValueError("no candidate used this specialist's tools with cited evidence")
            return tuple(candidates[:MAX_CANDIDATES])

        return parse
