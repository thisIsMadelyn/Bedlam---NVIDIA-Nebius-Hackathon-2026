"""Bedlam's face: a 3-row jester docked right of the NOW box.

Display only, like the voice. The mood follows the same event keys the
voice speaks on (`symptom:healthy`, `injecting:timeout`), most specific
first, and an event with no mood keeps the last one. Nothing here is
random and nothing feeds a decision.

Colours are passed in by role so the palette stays in one place (the TUI).
The bells light up GO on your turn, the same as lit keys; the trade-off
splits the hat and the eyes, ACCENT for option A and GO for option B.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from rich.text import Text

# 9 cells wide, 3 rows: exactly the NOW box's inner height.
WIDTH: Final = 9


class Mood(StrEnum):
    IDLE = "idle"
    SCHEMING = "scheming"
    READING = "reading"
    STRIKING = "striking"
    GLOATING = "gloating"
    SULKING = "sulking"
    YOUR_TURN = "your turn"
    TWO_FACED = "two-faced"


MOODS: Final[dict[str, Mood]] = {
    "baseline": Mood.IDLE,
    "cycle_started": Mood.SCHEMING,
    "searching": Mood.SCHEMING,
    "routed": Mood.SCHEMING,
    "selected": Mood.STRIKING,
    "injecting": Mood.STRIKING,
    "symptom": Mood.GLOATING,
    "symptom:healthy": Mood.SULKING,
    "awaiting_patch": Mood.YOUR_TURN,
    "patched": Mood.READING,
    "analysed": Mood.READING,
    "escalating": Mood.SCHEMING,
    "trade_off": Mood.TWO_FACED,
    "chosen": Mood.IDLE,
    "showing_cost": Mood.GLOATING,
    "cost_removed": Mood.IDLE,
    "finished": Mood.IDLE,
}


def mood_for(key: str, current: Mood) -> Mood:
    """The mood for an event key (`kind` or `kind:refinement`)."""
    kind = key.split(":", 1)[0]
    return MOODS.get(key) or MOODS.get(kind) or current


@dataclass(frozen=True)
class _Face:
    eyes: tuple[str, str]
    mouth: str
    bells: str = "muted"
    left: str = "accent"
    right: str = "ink"
    eye_colours: tuple[str, str] = ("accent", "accent")


_FACES: Final[dict[Mood, _Face]] = {
    Mood.IDLE: _Face(("◕", "◕"), "‿"),
    Mood.SCHEMING: _Face(("¬", "¬"), "‿"),
    Mood.READING: _Face(("◉", "◉"), "_"),
    Mood.STRIKING: _Face(("ò", "ó"), "▿", bells="accent"),
    Mood.GLOATING: _Face(("^", "^"), "▽", bells="accent"),
    Mood.SULKING: _Face(("-", "-"), "_", left="muted", eye_colours=("soft", "soft")),
    Mood.YOUR_TURN: _Face(("•", "•"), "‿", bells="go", eye_colours=("go", "go")),
    Mood.TWO_FACED: _Face(("◐", "◑"), "‿", bells="go", right="go", eye_colours=("accent", "go")),
}


# The launch splash, as pixels: two pixel rows per terminal row, drawn with
# half blocks. "." is empty; the letters are colour roles (below).
_SPLASH_PIXELS: Final = """
.GG............................GG.
GGGG..........................GGGG
.GG............................GG.
..AA..........................II..
..AAA........................III..
...AAA......................III...
...AAAA....................IIII...
....AAAAA................IIIII....
....AAAAAA..............IIIIII....
.....AAAAAAA..........IIIIIII.....
.....AAAAAAAAA......IIIIIIIII.....
......AAAAAAAAAA..IIIIIIIIII......
......AAAAAAAAAAIIIIIIIIIIII......
.......MMMMMMMMMMMMMMMMMMMM.......
.......MMAMMMMMMMAMMMMMMMAM.......
.......TTTTTTTTTTTTTTTTTTTT.......
......TTTTTTTTTTTTTTTTTTTTTT......
......TTKKTTTTTTTTTTTTTTKKTT......
......TTTTKKTTTTTTTTTTKKTTTT......
......TTTKKKKTTTTTTTTKKKKTTT......
......STTTAKATTTTTTTTAKATTTS......
......STTTTATTTTTTTTTTATTTTS......
......STKTTTTTTTTTTTTTTTTKTS......
.......STKKTTTTTTTTTTTTKKTS.......
........STTKKKKKKKKKKKKTTS........
.........SSTTTTTTTTTTTTSS.........
...........SSSSSSSSSSSS...........
.....AAII..AAIISSSSAAII..AAII.....
......AAIIAAIIAAIIAAIIAAIIAAII....
.......AI..AI..AI..AI..AI..AI.....
"""
_PIXEL_ROLES: Final = {
    "A": "accent", "I": "ink", "M": "muted", "G": "go", "T": "text", "S": "soft", "K": "background",
}  # fmt: skip
_WORDMARK: Final = (
    "█▀▄ █▀▀ █▀▄ █   ▄▀▄ █▄ ▄█",
    "█▀▄ █▀  █ █ █   █▀█ █ ▀ █",
    "▀▀  ▀▀▀ ▀▀  ▀▀▀ ▀ ▀ ▀   ▀",
)
SPLASH_WIDTH: Final = 34
# The jester, a blank line, then the wordmark.
SPLASH_HEIGHT: Final = 15 + 1 + len(_WORDMARK)


def splash(colours: dict[str, str]) -> Text:
    """The big jester with BEDLAM centred underneath, SPLASH_WIDTH wide.

    `colours` maps the roles of `render` plus background, the screen's own
    colour, which the eyes and the grin are cut out of.
    """
    rows = _SPLASH_PIXELS.strip("\n").split("\n")
    if len(rows) % 2:
        rows.append("." * SPLASH_WIDTH)
    art = Text()
    for top, bottom in zip(rows[0::2], rows[1::2], strict=True):
        for upper, lower in zip(top, bottom, strict=True):
            fg, bg = _PIXEL_ROLES.get(upper), _PIXEL_ROLES.get(lower)
            if fg and bg:
                art.append("▀", style=f"{colours[fg]} on {colours[bg]}")
            elif fg or bg:
                art.append("▀" if fg else "▄", style=colours[fg or bg])  # type: ignore[index]
            else:
                art.append(" ")
        art.append("\n")
    art.append("\n")
    indent = " " * ((SPLASH_WIDTH - len(_WORDMARK[0])) // 2)
    art.append("\n".join(indent + line for line in _WORDMARK), style=f"bold {colours['accent']}")
    return art


def render(mood: Mood, colours: dict[str, str]) -> Text:
    """The jester in `mood`, three lines of WIDTH cells.

    `colours` maps the roles accent, ink, muted, go, soft and text to colours.
    """
    face = _FACES[mood]
    bell, left, right = colours[face.bells], colours[face.left], colours[face.right]
    eye_l, eye_r = (colours[role] for role in face.eye_colours)
    soft, text = colours["soft"], colours["text"]
    return Text.assemble(
        ("●", bell), ("▄", left), "     ", ("▄", right), ("●", bell), "\n",
        " ", ("▀█▄", left), " ", ("▄█▀", right), " \n",
        "  ", ("(", soft), (face.eyes[0], eye_l), (face.mouth, text),
        (face.eyes[1], eye_r), (")", soft), "  ",
    )  # fmt: skip
