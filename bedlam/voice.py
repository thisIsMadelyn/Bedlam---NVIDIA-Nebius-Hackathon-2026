"""Bedlam's voice: one templated line per loop step, terminal-only.

Templated on purpose, never generated: determinism, zero latency, zero cost.
Lines are picked from a stream derived from the root seed, in event order,
so the same seed says the same things. The voice observes; nothing it says
feeds a decision.

A key is an event kind, optionally refined by what happened
(`injecting:timeout`, `symptom:stalled`, `cycle_started:2`). The most
specific key with lines wins. An event with no lines stays quiet.
"""

from __future__ import annotations

import random
from typing import Any, Final

from bedlam import seed as seeding

LINES: Final[dict[str, tuple[str, ...]]] = {
    "baseline": (
        "everything is green. that is about to be a problem.",
        "all three layers healthy. enjoy it while it lasts.",
        "baseline taken. remember this moment fondly.",
    ),
    "cycle_started:1": (
        "let's begin. I've been reading your lockfile.",
        "first round. nothing personal.",
    ),
    "cycle_started:2": (
        "round two. I read your patch. so did the internet.",
        "you fixed one thing. I counted the others.",
    ),
    "searching": (
        "asking the internet how your dependencies tend to die.",
        "reading other people's incident reports. for research.",
        "your lockfile is very informative.",
    ),
    "routed": (
        "the evidence points at {layer}. sending in the {specialist} specialist.",
        "{layer} keeps turning up in other people's bug reports. noted.",
        "the search results voted. {layer} lost.",
    ),
    "selected": (
        "{fault}. it seemed rude not to.",
        "{fault}. it has precedent.",
        "{fault}. someone online had a very bad day with this.",
    ),
    "injecting:latency": (
        "{layer} will now take its time. a lot of it.",
        "teaching {layer} patience.",
    ),
    "injecting:bandwidth": (
        "{layer} now breathes through a very thin straw.",
        "squeezing {layer} down to a trickle.",
    ),
    "injecting:connection_cut": (
        "{layer} will now hang up on you mid-sentence.",
        "cutting {layer}'s line. politely.",
    ),
    "injecting:timeout": (
        "{layer} will now listen and never answer.",
        "{layer} has taken a vow of silence.",
    ),
    "symptom:stalled": (
        "{layer} stopped answering. everyone upstream is still waiting.",
        "{layer} is thinking about it. forever.",
    ),
    "symptom:slow": (
        "{layer} is slow. not broken. worse.",
        "{layer} still works. eventually.",
    ),
    "symptom:unreachable": (
        "{layer} is gone. it was right here a minute ago.",
        "{layer} has left the building.",
    ),
    "symptom:healthy": (
        "nothing broke. I'm impressed. and a little annoyed.",
        "it held. noted. it won't hold twice.",
    ),
    "awaiting_patch": (
        "your turn. I'll wait. the fault won't.",
        "patch it. I'll be reading the diff.",
    ),
    "fault_removed": (
        "fault lifted. the stack exhales.",
        "I've stopped. for now.",
    ),
    "analysed": (
        "I see what you fixed. more interested in what you didn't.",
        "patch read. my next fault has read it too.",
    ),
    "escalation_pending": (
        "two rounds. breaking more teaches nothing. time to talk trade-offs.",
        "I could keep breaking things. the interesting part is your choice.",
    ),
}


def _refine(kind: str, fields: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    """The specific key for this event and the values its templates use."""
    if kind == "cycle_started":
        return str(fields["cycle"]), {}
    if kind == "routed":
        return None, {"layer": fields["routing"]["layer"], "specialist": fields["specialist"]}
    if kind == "selected":
        return None, {"fault": fields["selection"]["fault"]["id"]}
    if kind == "injecting":
        return fields["kind"], {"layer": fields["layer"]}
    if kind == "symptom":
        symptom = fields["symptom"]
        return symptom["kind"], {"layer": symptom["layer"]}
    return None, {}


class Voice:
    """Says one line per event, never the same line twice in a run."""

    def __init__(self, root_seed: int) -> None:
        self._rng: random.Random = seeding.rng(root_seed, "voice")
        self._used: set[str] = set()

    def say(self, kind: str, fields: dict[str, Any]) -> str | None:
        refinement, values = _refine(kind, fields)
        key = f"{kind}:{refinement}" if refinement else kind
        lines = LINES.get(key) or LINES.get(kind)
        if not lines:
            return None
        fresh = [line for line in lines if line not in self._used] or list(lines)
        line = self._rng.choice(fresh)
        self._used.add(line)
        return line.format(**values)
