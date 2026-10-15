"""The model map: the single source of truth for which model runs where.

No model id, temperature or seed is written anywhere else in this codebase.
Every call site resolves its parameters through `spec_for()`.

Model ids below are copied verbatim from Nebius Token Factory. Casing is
inconsistent between models and is NOT normalised -- the API rejects
normalised ids.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

SUPER: Final = "nvidia/nemotron-3-super-120b-a12b"
NANO: Final = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"

# Deliberately unused. A third model is scope creep, not an improvement.
# Lightning: no call site needs 1M context.
# Ultra: excluded on latency grounds in a sub-3-minute demo.
_LIGHTNING_UNUSED: Final = "nvidia/Nemotron-3_5-Lightning"
_ULTRA_UNUSED: Final = "nvidia/Nemotron-3-Ultra-550b-a55b"

MODELS: Final = (SUPER, NANO)
ALL_KNOWN_MODELS: Final = (SUPER, NANO, _LIGHTNING_UNUSED, _ULTRA_UNUSED)


class CallSite(StrEnum):
    """Every place in the loop that calls a model.

    Bedlam's voice is absent on purpose: it is templated, not generated.
    Determinism, zero latency, zero cost.
    """

    PROBE_CLASSIFICATION = "probe_classification"
    TAVILY_QUERY_FORMULATION = "tavily_query_formulation"
    LAYER_CLASSIFICATION = "layer_classification"
    DIFF_ANALYSIS = "diff_analysis"
    TAVILY_SYNTHESIS = "tavily_synthesis"
    FAULT_SELECTION = "fault_selection"
    TRADEOFF_ESCALATION = "tradeoff_escalation"


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """Resolved parameters for one call site."""

    model: str
    temperature: float
    max_tokens: int
    rationale: str
    seed: int | None = None
    fallback: str | None = None


CALL_SITES: Final[dict[CallSite, ModelSpec]] = {
    CallSite.PROBE_CLASSIFICATION: ModelSpec(
        model=NANO,
        temperature=0.0,
        max_tokens=256,
        fallback=None,
        rationale="Enum output from a health snapshot. No judgement required.",
    ),
    CallSite.TAVILY_QUERY_FORMULATION: ModelSpec(
        model=NANO,
        temperature=0.0,
        max_tokens=256,
        fallback=None,
        rationale="Structured extraction: dependency plus version plus failure term.",
    ),
    CallSite.LAYER_CLASSIFICATION: ModelSpec(
        model=NANO,
        temperature=0.0,
        max_tokens=256,
        fallback=None,
        rationale="Routes live search results to a specialist. Classification, not reasoning.",
    ),
    CallSite.DIFF_ANALYSIS: ModelSpec(
        model=SUPER,
        temperature=0.1,
        max_tokens=2048,
        fallback=NANO,
        rationale="Reasoning over code. What did the patch actually defend against.",
    ),
    CallSite.TAVILY_SYNTHESIS: ModelSpec(
        model=SUPER,
        temperature=0.3,
        max_tokens=2048,
        fallback=NANO,
        rationale="Messy prose from GitHub issues into candidate faults. Needs some latitude.",
    ),
    CallSite.FAULT_SELECTION: ModelSpec(
        model=SUPER,
        temperature=0.0,
        max_tokens=1024,
        seed=1729,
        fallback=NANO,
        rationale="Must reproduce: a judge running this build sees what the video shows.",
    ),
    CallSite.TRADEOFF_ESCALATION: ModelSpec(
        model=SUPER,
        temperature=0.4,
        max_tokens=2048,
        fallback=NANO,
        rationale="The differentiating feature, and the part a judge reads closely.",
    ),
}


def spec_for(site: CallSite) -> ModelSpec:
    """Resolve the parameters for a call site.

    Raises:
        KeyError: if a call site has no entry. Adding a call site without
            adding its spec here is a bug, not a default.
    """
    return CALL_SITES[site]
