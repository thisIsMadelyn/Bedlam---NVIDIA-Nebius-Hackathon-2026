"""The NOW box: where the loop is, where to look, what to do.

The voice is Bedlam's personality; this is the plain-language guide for
someone who has never seen the tool. Every loop event maps to three lines:
what is happening, which panel shows it, and whether the viewer has to do
anything. Templated, like the voice, and observer-only.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Final

# Panel names. The guide points at panels by name, so the TUI titles its
# panels with these.
APP: Final = "YOUR APP"
LOG: Final = "WHAT BEDLAM DID"
MODELS: Final = "AI MODELS"

# Steps inside one round, as the header counts them.
STEPS: Final = 7

_NOTHING: Final = "You: nothing to do. Just watch."
_VERB: Final = {
    "latency": "slowing down",
    "bandwidth": "throttling",
    "connection_cut": "cutting the connection to",
    "timeout": "freezing",
}
_DAMAGE: Final = {"stalled": "not answering", "slow": "slow", "unreachable": "unreachable"}


@dataclass(frozen=True, slots=True)
class Guidance:
    step: int  # 1..STEPS inside a round; 0 outside one
    title: str
    lines: tuple[str, str, str]
    your_turn: bool = False

    def nudged(self, line: str) -> Guidance:
        """The same guidance with its last line replaced."""
        return replace(self, lines=(self.lines[0], self.lines[1], line))


STARTING: Final = Guidance(
    0,
    "STARTING",
    (
        "Checking that your app is healthy before Bedlam attacks it.",
        f"Look at {APP}: one line per part of your app.",
        _NOTHING,
    ),
)
# Where the developer edits in real patch mode, as shown on screen.
TARGET: Final = "targets/fastapi-boilerplate"

YOUR_TURN_REAL: Final = Guidance(
    5,
    "YOUR TURN",
    (
        f"Your app is broken. Fix it in {TARGET} and save.",
        "Bedlam reads your git diff. The running app is not reloaded.",
        "You: press P when your fix is saved.",
    ),
    your_turn=True,
)
YOUR_TURN_SCRIPTED: Final = Guidance(
    5,
    "YOUR TURN",
    (
        "Your app is broken. In real use you would write a fix now.",
        "This demo ships a prepared fix for this round (--scripted).",
        "You: press P to apply it.",
    ),
    your_turn=True,
)
PRESSED_REAL: Final = Guidance(
    6,
    "GOT IT",
    (
        "You pressed P. Bedlam is reading your git diff.",
        f"Look at {LOG}: 'patch in' lists the files you changed.",
        _NOTHING,
    ),
)
PRESSED_SCRIPTED: Final = Guidance(
    6,
    "GOT IT",
    (
        "You pressed P. Bedlam is applying the prepared fix.",
        f"Look at {LOG}: 'patch in' confirms it arrived.",
        _NOTHING,
    ),
)
NO_CHANGES: Final = Guidance(
    5,
    "YOUR TURN",
    (
        f"No changes found in {TARGET} since the last round.",
        "Edit a file there and save it. Bedlam reads your git diff.",
        "You: press P again when your fix is saved.",
    ),
    your_turn=True,
)
EARLY_PRESS: Final = "You pressed P, but there is nothing to fix yet. Keep watching."
EARLY_CHOICE: Final = "You: nothing to choose yet. A and B work once the trade-off is up."
TRADE_OFF: Final = Guidance(
    0,
    "YOUR CHOICE",
    (
        "Bedlam stops breaking things. Each option below costs you something.",
        "Read both sides. Bedlam will not choose for you.",
        "You: press A or B.",
    ),
    your_turn=True,
)
STOPPED: Final = Guidance(
    0,
    "STOPPED",
    ("The run stopped with an error.", f"Look at {LOG}: the red line says why.", "You: Q quits."),
)


def guidance(kind: str, fields: dict[str, Any], *, real: bool = False) -> Guidance | None:
    """What the NOW box says after a loop event. None keeps the current one.

    `real` is real patch mode: the developer writes the fix.
    """
    if kind == "baseline":
        return Guidance(
            0,
            "READY",
            (
                "Every part of your app is healthy. Bedlam is about to attack.",
                f"Look at {APP}: green means healthy.",
                _NOTHING,
            ),
        )
    if kind == "searching":
        return Guidance(
            1,
            "RESEARCHING",
            (
                "Bedlam searches the web for real bugs in your app's libraries.",
                f"Look at {MODELS}: the cyan 'tavily' lines are live web searches.",
                _NOTHING,
            ),
        )
    if kind == "routed":
        layer = fields["routing"]["layer"]
        return Guidance(
            2,
            "CHOOSING",
            (
                f"The search results point at your {layer}. A {layer} expert takes over.",
                f"Look at {LOG}: the score for each part of your app.",
                _NOTHING,
            ),
        )
    if kind == "selected":
        return Guidance(
            2,
            "CHOOSING",
            (
                f"Bedlam picked its attack: {fields['selection']['fault']['id']}.",
                f"Look at {LOG}: the 'why' line explains the pick.",
                _NOTHING,
            ),
        )
    if kind == "injecting":
        layer, blast = fields["layer"], " and ".join(fields["blast_radius"])
        return Guidance(
            3,
            "BREAKING",
            (
                f"Bedlam is {_VERB[fields['kind']]} your {layer} on purpose.",
                f"Look at {APP}: watch the {blast} lines.",
                _NOTHING,
            ),
        )
    if kind == "probed":
        return Guidance(
            4,
            "MEASURING",
            (
                "Bedlam checks how badly the attack hurt your app.",
                f"Look at {APP}: red means damaged.",
                _NOTHING,
            ),
        )
    if kind == "symptom":
        symptom = fields["symptom"]
        damage = _DAMAGE.get(symptom["kind"])
        what = f"Your {symptom['layer']} is {damage}." if damage else "Your app survived it."
        return Guidance(
            4,
            "MEASURING",
            (f"{what} That is the damage to fix.", f"Look at {APP}: red means damaged.", _NOTHING),
        )
    if kind == "awaiting_patch":
        return YOUR_TURN_REAL if real else YOUR_TURN_SCRIPTED
    if kind == "fault_removed":
        return Guidance(
            6,
            "RECOVERING",
            (
                "Bedlam removed its attack. Your app should turn green again.",
                f"Look at {APP}: back to green.",
                _NOTHING,
            ),
        )
    if kind == "analysed":
        return Guidance(
            7,
            "READING YOUR FIX",
            (
                "Bedlam read your fix to find what it still leaves open.",
                f"Look at {LOG}: 'gaps' is what the next round goes after.",
                _NOTHING,
            ),
        )
    return _escalation(kind, fields)


def _escalation(kind: str, fields: dict[str, Any]) -> Guidance | None:
    """The NOW box after round 2: the trade-off and the cost of the choice."""
    if kind == "escalating":
        return Guidance(
            0,
            "TRADE-OFF",
            (
                "Two rounds done. Breaking more would teach nothing new.",
                f"Look at {MODELS}: Super is writing your trade-off.",
                _NOTHING,
            ),
        )
    if kind == "trade_off":
        return TRADE_OFF
    if kind == "chosen":
        return Guidance(
            0,
            "YOUR CHOICE",
            (
                f"You chose {fields['choice'].upper()}: {fields['option']['title']}.",
                f"Bedlam now applies what it costs, once. Look at {APP}.",
                _NOTHING,
            ),
        )
    if kind == "showing_cost":
        layer, blast = fields["layer"], " and ".join(fields["blast_radius"])
        return Guidance(
            0,
            "THE COST",
            (
                f"Bedlam is {_VERB[fields['kind']]} your {layer}: the cost you accepted.",
                f"Look at {APP}: watch the {blast} lines.",
                _NOTHING,
            ),
        )
    if kind == "cost_shown":
        return Guidance(
            0,
            "THE COST",
            (
                "This is what your choice costs when it bites.",
                f"Look at {APP}: red is the cost you accepted.",
                _NOTHING,
            ),
        )
    if kind == "cost_removed":
        return Guidance(
            0,
            "THE COST",
            (
                "Bedlam removed it. Your app should turn green again.",
                f"Look at {APP}: back to green.",
                _NOTHING,
            ),
        )
    if kind == "finished":
        chosen = (fields.get("escalation") or {}).get("status") == "chosen"
        return Guidance(
            0,
            "DONE",
            (
                "Run finished. Your choice is in the trace and a decision record."
                if chosen
                else "Run finished. The options are in the trace; nobody chose.",
                f"Look at {LOG}: {'where the decision record is' if chosen else 'both options'}.",
                "You: Q quits.",
            ),
        )
    return None
