"""The trade-off escalation (Super): after two cycles, Bedlam stops breaking things.

Breaking a third layer would teach the developer little that the first two
did not. What is left is a decision only the developer can make: two
options, each with a gain and a cost, grounded in this run's faults and
patches. Bedlam presents them; the developer chooses. Nothing in this
module picks a side.

Each option says when its cost is felt: a layer and one of a few plain
conditions (`FELT_WHEN`). Code, not the model, turns that pair into the
catalog fault that is the option's consequence, so the fault always matches
the condition the option names. After the choice, the loop applies that one
fault once, probes, and removes it, so the developer sees the cost they
accepted live. That is the escalation's own step, not a third cycle: no
search, no selection, no patch.

Hard rules are enforced here in code, not left to the prompt: exactly two
options, two different consequences from the eligible pool, text short
enough for the 82-column screen, and no recommendation in the wording.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final, Protocol

from bedlam import prompts
from bedlam.diff import DiffAnalysis
from bedlam.faults.primitives import FaultKind
from bedlam.history import FaultRecord
from bedlam.logging import get_logger
from bedlam.models.client import ModelCallError, ModelClient
from bedlam.models.map import CallSite
from bedlam.probes.classify import Symptom
from bedlam.select import DEFAULT_MAX_BLAST_RADIUS
from bedlam.specialists.catalog import CATALOG, FaultOption

_LOG = get_logger("bedlam.escalation")

KEYS: Final = ("a", "b")

# Lengths that keep the trade-off screen readable at 82 columns without
# scrolling: a title on one line, gain and cost on two lines each.
_MAX_AXIS: Final = 60
_MAX_WHY: Final = 220
_MAX_TITLE: Final = 48
_MAX_SIDE: Final = 120


@dataclass(frozen=True, slots=True)
class Condition:
    kind: FaultKind
    param: int | None
    shown: str  # "{layer} is slow": how the screen says when the cost is felt
    meaning: str  # what the model reads when picking a condition


# When an option's cost is felt, in words a developer uses. Each condition is
# exactly one fault kind, so the consequence follows from the words.
FELT_WHEN: Final[dict[str, Condition]] = {
    "slow": Condition(FaultKind.LATENCY, 2500, "{layer} is slow", "answers, but 2.5 s late"),
    "hangs": Condition(
        FaultKind.TIMEOUT, 0, "{layer} hangs", "never answers; connections stay open"
    ),
    "stalls then drops": Condition(
        FaultKind.TIMEOUT, 3000, "{layer} stalls, then drops", "freezes 3 s, then closes"
    ),
    "drops connections": Condition(
        FaultKind.CONNECTION_CUT, None, "{layer} drops connections", "resets every connection"
    ),
    "crawls": Condition(FaultKind.BANDWIDTH, 1, "{layer} crawls", "answers at 1 KB/s"),
}

# Wording that turns a choice into a recommendation. The framing must stay
# a trade-off, so this is checked in code and a match is retried.
_RECOMMENDS: Final = re.compile(
    r"\b(recommend\w*|advis\w+|you should|we suggest|i suggest|best (?:option|choice)"
    r"|better (?:option|choice)|safer bet|clearly|obviously|the right (?:choice|call))\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class Option:
    key: str
    title: str
    gain: str
    cost: str
    felt_when: str  # "cache is slow"
    consequence: FaultOption

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "gain": self.gain,
            "cost": self.cost,
            "felt_when": self.felt_when,
            "consequence": self.consequence.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class TradeOff:
    axis: str
    why: str
    options: tuple[Option, Option]
    source: str  # "model" | "templated_fallback"

    def option(self, key: str) -> Option:
        for candidate in self.options:
            if candidate.key == key:
                return candidate
        raise ValueError(f"no option {key!r}: choose one of {', '.join(KEYS)}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "axis": self.axis,
            "why": self.why,
            "options": [o.to_dict() for o in self.options],
            "source": self.source,
        }


class ChoiceSource(Protocol):
    async def wait_for_choice(self, trade_off: TradeOff) -> str:
        """The developer's choice: one of `KEYS`."""
        ...


class ScriptedChoice:
    """A choice given up front (`--choice`), for headless runs.

    The developer still makes it -- on the command line, before the run.
    """

    def __init__(self, key: str) -> None:
        if key not in KEYS:
            raise ValueError(f"choice must be one of {', '.join(KEYS)}, not {key!r}")
        self.key = key

    async def wait_for_choice(self, trade_off: TradeOff) -> str:
        return self.key


def consequence_pool(max_blast_radius: int = DEFAULT_MAX_BLAST_RADIUS) -> tuple[FaultOption, ...]:
    """Faults an option may name as its consequence: the catalog, under the blast cap."""
    return tuple(o for o in CATALOG if len(o.blast_radius) <= max_blast_radius)


def _text(value: Any, field: str, limit: int) -> str:
    text = " ".join(str(value).split())
    if not text:
        raise ValueError(f"{field} is empty")
    if len(text) > limit:
        raise ValueError(
            f"{field} is {len(text)} characters; the screen allows {limit}. "
            f"Cut at least {len(text) - limit} characters."
        )
    if match := _RECOMMENDS.search(text):
        raise ValueError(
            f"{field} says {match.group(0)!r}: that recommends a side. "
            "Describe what each option gains and costs; the developer decides"
        )
    return text


def _consequence(
    pool: tuple[FaultOption, ...], layer: str, felt_when: str
) -> tuple[str, FaultOption] | None:
    """The fault under which a cost is felt, and how the screen says it."""
    condition = FELT_WHEN.get(felt_when)
    if condition is None:
        return None
    for candidate in pool:
        if (candidate.layer.value, candidate.kind, candidate.param) == (
            layer,
            condition.kind,
            condition.param,
        ):
            return condition.shown.format(layer=layer), candidate
    return None


def _layers(pool: tuple[FaultOption, ...]) -> list[str]:
    return sorted({o.layer.value for o in pool})


def _parser(pool: tuple[FaultOption, ...]):
    def parse(value: Any) -> TradeOff:
        if "recommendation" in value or "recommended" in value:
            raise ValueError("the reply carries a recommendation; the developer decides")
        raw = value["options"]
        if not isinstance(raw, list) or len(raw) != len(KEYS):
            raise ValueError(f"need exactly {len(KEYS)} options")
        options = []
        for key, item in zip(KEYS, raw, strict=True):
            layer, felt_when = str(item["cost_layer"]), str(item["cost_felt_when"])
            if layer not in _layers(pool):
                raise ValueError(
                    f"option {key}: cost_layer {layer!r} cannot be faulted; "
                    f"use one of {', '.join(_layers(pool))}"
                )
            found = _consequence(pool, layer, felt_when)
            if found is None:
                raise ValueError(
                    f"option {key}: cost_felt_when {felt_when!r} is not one of "
                    f"{', '.join(FELT_WHEN)}"
                )
            shown, consequence = found
            options.append(
                Option(
                    key=key,
                    title=_text(item["title"], f"option {key} title", _MAX_TITLE),
                    gain=_text(item["gain"], f"option {key} gain", _MAX_SIDE),
                    cost=_text(item["cost"], f"option {key} cost", _MAX_SIDE),
                    felt_when=shown,
                    consequence=consequence,
                )
            )
        a, b = options
        if a.consequence.id == b.consequence.id:
            raise ValueError(
                "both options name the same cost_layer and cost_felt_when; their costs must differ"
            )
        if a.title.lower() == b.title.lower():
            raise ValueError("both options have the same title")
        return TradeOff(
            axis=_text(value["axis"], "axis", _MAX_AXIS),
            why=_text(value["why"], "why", _MAX_WHY),
            options=(a, b),
            source="model",
        )

    return parse


def templated(history: list[FaultRecord]) -> TradeOff:
    """The trade-off when every model failed: fail fast or wait it out.

    Grounded in the last layer Bedlam broke. Logged by the caller, and
    marked `templated_fallback` on the trade-off.
    """
    layer = history[-1].layer.value
    pool = consequence_pool()
    slow = _consequence(pool, layer, "slow")
    hangs = _consequence(pool, layer, "hangs")
    assert slow is not None and hangs is not None, f"{layer} has no slow or hang fault"
    return TradeOff(
        axis="fail fast vs wait it out",
        why=f"Both rounds came down to how your app treats a {layer} that answers late "
        "or not at all. A short timeout and a long one fail in different ways.",
        options=(
            Option(
                "a",
                "Fail fast",
                f"a hung {layer} costs one quick error, not a stuck request",
                f"users get errors whenever {layer} is merely slow",
                *slow,
            ),
            Option(
                "b",
                "Wait it out",
                f"a slow {layer} still answers, just late",
                f"when {layer} hangs, requests hang with it and pile up",
                *hangs,
            ),
        ),
        source="templated_fallback",
    )


async def escalate(
    client: ModelClient,
    *,
    history: list[FaultRecord],
    analyses: list[DiffAnalysis],
    symptoms: list[Symptom],
) -> TradeOff:
    """Frame the trade-off this run has earned. Never chooses."""
    pool = consequence_pool()
    try:
        return await client.json(
            CallSite.TRADEOFF_ESCALATION,
            system=prompts.load("tradeoff_escalation"),
            user=prompts.context(
                {
                    "faults_so_far": [record.to_dict() for record in history],
                    "symptoms": [symptom.to_dict() for symptom in symptoms],
                    "patches": [analysis.to_dict() for analysis in analyses],
                    "cost_layers": _layers(pool),
                    "felt_when": {name: c.meaning for name, c in FELT_WHEN.items()},
                    "limits": {
                        "axis": _MAX_AXIS,
                        "why": _MAX_WHY,
                        "title": _MAX_TITLE,
                        "gain": _MAX_SIDE,
                        "cost": _MAX_SIDE,
                    },
                }
            ),
            parse=_parser(pool),
        )
    except ModelCallError as exc:
        _LOG.warning("escalation fallback", extra={"fields": {"error": str(exc)}})
        return templated(history)


def decision_record(escalation: dict[str, Any]) -> str:
    """The developer's decision as Markdown, from the trace's escalation entry."""
    trade_off = escalation["trade_off"]
    chosen = escalation["choice"]
    lines = [
        f"# Decision: {trade_off['axis']}",
        "",
        trade_off["why"],
        "",
        "## Faults that led here",
        "",
        *[f"- cycle {f['cycle']}: `{f['fault_id']}`" for f in escalation["faults"]],
        "",
        "## Options",
        "",
    ]
    for item in trade_off["options"]:
        mark = " (chosen)" if item["key"] == chosen else ""
        lines += [
            f"### {item['key'].upper()}. {item['title']}{mark}",
            "",
            f"- Gain: {item['gain']}",
            f"- Cost: {item['cost']}",
            f"- Felt when: {item['felt_when']}",
            f"- The cost, as a fault: `{item['consequence']['id']}`",
            "",
        ]
    shown = escalation.get("consequence")
    if shown:
        lines += ["## The cost, measured", ""]
        # A run that failed while the cost was going in has no probe to show.
        if "probe_during" in shown:
            during = ", ".join(f"{k} {v['status']}" for k, v in shown["probe_during"].items())
            lines += [f"Under `{shown['fault']}`: {during}.", ""]
        else:
            lines += [f"`{shown['fault']}` could not be measured: the run failed first.", ""]
    lines += ["Bedlam presented the options. The developer chose.", ""]
    return "\n".join(lines)
