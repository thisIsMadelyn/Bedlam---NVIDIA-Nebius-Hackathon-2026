"""Fault selection, constrained by blast radius and cycle history (Super).

Hard constraints are enforced here in code, before the model sees anything.
A candidate is eligible only if:

- its blast radius, computed from the static topology *before* injection,
  is no wider than `max_blast_radius` layers;
- it is not a direction already taken this run (same layer and kind);
- the last patch does not already defend against it.

Super (temp 0.0, seeded) then picks one eligible fault. If synthesis left no
eligible candidate, the pool widens to the specialist's whole tool set under
the same constraints. If the model's answer is unusable, a draw from the
seeded RNG stream picks instead -- logged, and marked on the selection.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Final

from bedlam import prompts
from bedlam.diff import DiffAnalysis
from bedlam.history import FaultRecord
from bedlam.logging import get_logger
from bedlam.models.client import ModelCallError, ModelClient
from bedlam.models.map import CallSite
from bedlam.specialists.base import Candidate, Specialist
from bedlam.specialists.catalog import FaultOption

_LOG = get_logger("bedlam.select")

DEFAULT_MAX_BLAST_RADIUS: Final = 2
# The rationale is the "why:" line under the picked fault: about three
# lines of the timeline at 82 columns.
_MAX_RATIONALE: Final = 240


@dataclass(frozen=True, slots=True)
class Selection:
    option: FaultOption
    rationale: str
    source: str  # "model" | "only_option" | "seeded_fallback"
    pool: str  # "candidates" | "specialist_tools"
    eligible: tuple[str, ...]
    rejected: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fault": self.option.to_dict(),
            "rationale": self.rationale,
            "source": self.source,
            "pool": self.pool,
            "eligible": list(self.eligible),
            "rejected": dict(sorted(self.rejected.items())),
        }


def ineligibility(
    option: FaultOption,
    *,
    history: list[FaultRecord],
    analysis: DiffAnalysis | None,
    max_blast_radius: int,
) -> str | None:
    """Why `option` may not be injected next, or `None` if it may."""
    if len(option.blast_radius) > max_blast_radius:
        return f"blast radius {len(option.blast_radius)} exceeds cap {max_blast_radius}"
    if any(r.layer == option.layer and r.kind == option.kind for r in history):
        return "direction already taken this run"
    if analysis and (option.layer, option.kind) in analysis.defended:
        return "the last patch defends against it"
    return None


def _parser(pool: dict[str, Any]):
    def parse(value: Any) -> tuple[str, str]:
        fault_id = str(value["fault_id"])
        if fault_id not in pool:
            raise ValueError(f"{fault_id!r} is not an eligible fault")
        rationale = " ".join(str(value.get("rationale", "")).split())
        if len(rationale) > _MAX_RATIONALE:
            raise ValueError(
                f"rationale is {len(rationale)} characters; the screen allows {_MAX_RATIONALE}. "
                f"Cut at least {len(rationale) - _MAX_RATIONALE} characters."
            )
        return fault_id, rationale

    return parse


async def select_fault(
    client: ModelClient,
    *,
    candidates: tuple[Candidate, ...],
    specialist: Specialist,
    history: list[FaultRecord],
    analysis: DiffAnalysis | None,
    rng: random.Random,
    max_blast_radius: int = DEFAULT_MAX_BLAST_RADIUS,
) -> Selection:
    def check(option: FaultOption) -> str | None:
        return ineligibility(
            option, history=history, analysis=analysis, max_blast_radius=max_blast_radius
        )

    rejected = {c.option.id: reason for c in candidates if (reason := check(c.option))}
    pool_name = "candidates"
    pool: dict[str, dict[str, Any]] = {
        c.option.id: {
            **c.option.to_dict(),
            "hypothesis": c.hypothesis,
            "evidence": list(c.evidence),
        }
        for c in candidates
        if c.option.id not in rejected
    }
    if not pool:
        pool_name = "specialist_tools"
        pool = {o.id: o.to_dict() for o in specialist.tools if check(o) is None}
    if not pool:
        raise RuntimeError(f"no eligible fault left for the {specialist.name} specialist")

    by_id = {o.id: o for o in specialist.tools}
    eligible = tuple(sorted(pool))

    if len(eligible) == 1:
        return Selection(
            by_id[eligible[0]], "only eligible fault", "only_option", pool_name, eligible, rejected
        )

    try:
        fault_id, rationale = await client.json(
            CallSite.FAULT_SELECTION,
            system=prompts.load("fault_selection"),
            user=prompts.context(
                {
                    "eligible": [pool[i] for i in eligible],
                    "faults_so_far": [record.to_dict() for record in history],
                    "last_patch": analysis.to_dict() if analysis else None,
                }
            ),
            parse=_parser(pool),
        )
        source = "model"
    except ModelCallError as exc:
        fault_id = rng.choice(eligible)
        rationale = "seeded fallback: model selection failed"
        source = "seeded_fallback"
        _LOG.warning(
            "fault selection fallback",
            extra={"fields": {"chosen": fault_id, "eligible": list(eligible), "error": str(exc)}},
        )

    return Selection(by_id[fault_id], rationale, source, pool_name, eligible, rejected)
