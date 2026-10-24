"""The Bedlam terminal UI. Fills the terminal; fully readable at 82 columns.

The loop runs inside the app as a worker and reports each step through its
event hook. The TUI only observes: nothing on screen feeds a decision. The
developer's inputs to the loop are saying the patch is in and, after round
2, choosing a side of the trade-off.

Top to bottom: header (round, step, seed); NOW, a plain-language guide to
what is happening, where to look and whether to act (`bedlam/guide.py`);
BEDLAM SAYS (the latest voice line, held still); YOUR APP (per-layer health
and the live fault); WHAT BEDLAM DID (each step in order, with Bedlam's
voice); AI MODELS (every model call with the model that answered it, and
every Tavily call); the key legend. From `_WIDE` columns up, WHAT BEDLAM DID
and AI MODELS sit side by side. While the trade-off waits for a choice, a
full-frame TRADE-OFF panel takes the place of the three panels.

Run: python -m bedlam.tui
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import functools
import math
import os
import re
import subprocess
import textwrap
import time
from collections import deque
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Final

from dotenv import load_dotenv
from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.suggester import SuggestFromList
from textual.widget import Widget
from textual.widgets import Input, RichLog, Static

from bedlam import jester
from bedlam import seed as seeding
from bedlam.escalation import KEYS, TradeOff
from bedlam.guide import (
    APP,
    EARLY_CHOICE,
    EARLY_PRESS,
    LOG,
    MODELS,
    NO_CHANGES,
    PRESSED_REAL,
    PRESSED_SCRIPTED,
    STARTING,
    STEPS,
    STOPPED,
    TARGET,
    Guidance,
    guidance,
)
from bedlam.logging import get_logger, log_event, redirect
from bedlam.loop import MAX_CYCLES, decision_path, execute
from bedlam.models.client import CallRecord, ModelClient
from bedlam.models.map import LABELS
from bedlam.patches import (
    DEFAULT_PATCH_DIR,
    DEFAULT_TARGET,
    GitPatchSource,
    Patch,
    PatchSource,
    ScriptedPatchSource,
)
from bedlam.probes.app import AppResult
from bedlam.probes.result import DEFAULT_TIMEOUT_S
from bedlam.search.tavily import (
    CREDITS_PER_SEARCH,
    EXCLUDE_DOMAINS,
    INCLUDE_DOMAINS,
    MAX_RESULTS,
    SearchCall,
    SearchClient,
)
from bedlam.stats import ContainerStats, StatsUnavailable
from bedlam.stats import sample as sample_stats
from bedlam.topology import Layer
from bedlam.voice import MORAL, SIGN_OFF, SUDO, SUDO_CHOOSE, Voice, event_key

# The minimum width. Every template is checked to fit at this size.
WIDTH: Final = 82
# Border (2) + horizontal padding (2) + scrollbar (1), with one column spare.
LINE: Final = WIDTH - 6
# A timeline line after its "c1 " cycle prefix, at the minimum width.
SAY: Final = LINE - 3
# Side by side only when each half is still at least the minimum width.
_WIDE: Final = 2 * WIDTH + 2
# The jester beside the NOW box: its cells plus a column either side. Shown
# only when the NOW box keeps its full width at 82, so it never cuts a line.
_JESTER: Final = jester.WIDTH + 2
_ROOMY: Final = WIDTH + _JESTER

# Palette. The four given colours, plus shades of them for the background
# and text, and one red that marks damage only.
INK: Final = "#48435C"
MUTED: Final = "#5A5766"
ACCENT: Final = "#9792E3"
GO: Final = "#61E786"
DAMAGE: Final = "#E5484D"
_BACKGROUND: Final = "#1C1A24"
_SURFACE: Final = "#23212D"
_TEXT: Final = "#E6E4EF"
_SOFT: Final = "#A29FB2"
# The post-mortem field: dim, but 4:1 on the background, so a laptop panel
# in a lit room still shows it (MUTED, 2.45:1, does not).
_FIELD_INK: Final = "#7B7792"
# Its glow, a lighter ink that swings between A and B: the crest is ACCENT,
# its edges halfway between the two.
_FIELD_GLOW: Final = ACCENT
_FIELD_GLOW_EDGE: Final = "#8984BA"
_JESTER_COLOURS: Final = {
    "accent": ACCENT, "ink": INK, "muted": MUTED, "go": GO, "soft": _SOFT, "text": _TEXT,
}  # fmt: skip
_SPLASH_COLOURS: Final = {**_JESTER_COLOURS, "background": _BACKGROUND}
# How many search results /why lists without a cycle; /why 1 lists them all.
_WHY_RESULTS: Final = 3
# The post-mortem log while the trade-off waits: it takes every row the
# cards leave, and shows once at least 3 rows and its border are left.
_STRIP_ROWS: Final = 5
# A panel's border and horizontal padding, both sides.
_PANEL_EDGES: Final = 4
# Labels in /cycle and /cost: two spaces, the label, a space.
_FIELD: Final = 10
# How long the launch splash holds before the run starts. Any key skips it.
# A completed run stays on its page; Q or /quit brings up the end splash.
SPLASH_S: Final = 2.5

_BAR_MIN: Final = 20
_SPARK: Final = "▁▂▃▄▅▆▇█"
# CPU samples kept per container for its sparkline, and the wait between
# samples (one `docker stats` call itself takes 2-3 s).
_SPARK_LEN: Final = 8
_STATS_PAUSE_S: Final = 0.5
_STATS_RETRY_S: Final = 5.0
# "  cpu  12.3% ▁▂▃▄▅▆▇█ mem  220M": fits next to a minimum bar at 82 columns.
_LOAD_WIDTH: Final = 2 + 3 + 7 + 1 + _SPARK_LEN + 1 + 3 + 6
_BAR_MAX: Final = 60
# A trade-off card: "│ " and " │" around a row, and "gain  " before it.
_CARD_FRAME: Final = 4
_CARD_LABEL: Final = 6
# Rows above and below the trade-off panel and its replies.
_FIXED_ROWS: Final = ("header", "top", "says", "command", "footer")
_BAR_CEILING_MS: Final = 2000.0
# The summed-score bars in /search, at their longest.
_SEARCH_BAR: Final = 24
_REPO_ROOT: Final = Path(__file__).resolve().parents[1]
_LOG = get_logger("bedlam.tui")
_SAYS: Final = " BEDLAM "


def fit(text: str, width: int = LINE) -> str:
    """One line, cut to `width` with an ellipsis. Nothing on screen wraps."""
    return text if len(text) <= width else text[: width - 1] + "…"


def wrap(text: str, indent: int, width: int = SAY) -> list[str]:
    """Hanging-indent wrap for prose the loop produced (rationales, summaries)."""
    lines = textwrap.wrap(" ".join(text.split()), width=width, subsequent_indent=" " * indent)
    return lines or [""]


def latency_bar(latency_ms: float | None, size: int = _BAR_MIN) -> str:
    """A square-root bar: one cell when healthy, 2 s and over is full.

    A log scale drew 318 ms and 2 s nearly alike; square root keeps a few
    milliseconds visible and still tells a slow layer from a hung one."""
    if latency_ms is None:
        return "·" * size
    scale = math.sqrt(max(latency_ms, 0.0) / _BAR_CEILING_MS)
    filled = max(1, min(size, round(scale * size)))
    return "█" * filled + "░" * (size - filled)


def _query_label(query: dict[str, Any]) -> str:
    """A query as shown on screen; a templated one says so."""
    return query["text"] + ("  (templated)" if query.get("templated") else "")


def _defended(analysis: dict[str, Any]) -> str:
    """What a patch defends, as `layer/kind` pairs; empty when nothing."""
    return ", ".join(f"{d['layer']}/{d['kind']}" for d in analysis["defended"])


class GatedPatchSource:
    """Holds the patch back until the developer says it is in.

    An empty patch (P pressed before any edit was saved) is not passed on:
    `on_empty` is told, and the gate waits for the next P.
    """

    def __init__(self, inner: PatchSource) -> None:
        self._inner = inner
        self._released = asyncio.Event()
        self.waiting = False
        self.on_empty: Callable[[], None] = lambda: None

    async def wait_for_patch(self, cycle: int, fault: str | None = None) -> Patch:
        while True:
            self.waiting = True
            try:
                await self._released.wait()
            finally:
                self.waiting = False
                self._released.clear()
            patch = await self._inner.wait_for_patch(cycle, fault)
            if patch.diff.strip():
                return patch
            self.on_empty()

    def release(self) -> bool:
        if not self.waiting:
            return False
        self._released.set()
        return True


class GatedChoice:
    """The developer's side of the trade-off: waits for A or B.

    A key pressed before the trade-off is on screen is refused, never kept
    for later: an early press must not pre-answer a question not yet asked.
    """

    def __init__(self) -> None:
        self._chosen: asyncio.Queue[str] = asyncio.Queue(maxsize=1)
        self.waiting = False
        # Told when the question is open, so the keys can light up.
        self.on_ask: Callable[[], None] = lambda: None

    async def wait_for_choice(self, trade_off: TradeOff) -> str:
        self.waiting = True
        self.on_ask()
        try:
            return await self._chosen.get()
        finally:
            self.waiting = False

    def choose(self, key: str) -> bool:
        if not self.waiting or key not in KEYS or self._chosen.full():
            return False
        self._chosen.put_nowait(key)
        return True


Launch = Callable[["BedlamApp"], Awaitable[int]]

StatsSource = Callable[[], Awaitable[dict[Layer, ContainerStats]]]

# The command line's commands: name -> what /help says. Each one is a
# `_command_<name>` method on the app. None may decide the trade-off for the
# developer: a command that picks a side is a bug (CLAUDE.md).
COMMANDS: Final = {
    "help": "list these commands",
    "status": "where the run is and what Bedlam is waiting for",
    "cycles": "the run in one line per cycle, then the trade-off",
    "cycle": "one cycle step by step: /cycle 1, /cycle 2",
    "why": "why this layer: Tavily weights and results. /why 1: cycle 1",
    "search": "how the search ran, call by call. /search 1: cycle 1",
    "loop": "the seven steps of a round, and where the run is now",
    "diff": "what Bedlam read in your patch. /diff 1: cycle 1's",
    "calls": "model calls per call site: model, tokens, latency",
    "cost": "what your choice cost, measured live",
    "seed": "the root seed, and how to run this again",
    "grep": "show only lines with <text>; /grep alone shows all",
    "zoom": "one log fills the screen: /zoom timeline|agent, /zoom ends it",
    "log": "switch between the trade-off page and the run log",
    "copy": "copy the last command's output; /copy timeline: what's shown",
    "save": "write the timeline and the model log to a text file",
    "shot": "save a screenshot of the screen as SVG",
    "patch": "hand over your fix, same as P",
    "choose": "your side of the trade-off: /choose a or /choose b",
    "quit": "leave Bedlam, same as Q",
}
# /loop: the header's step titles, each with what happens at it.
LOOP_STEPS: Final = (
    ("RESEARCHING", "Tavily searches your dependencies"),
    ("CHOOSING", "a specialist picks one fault"),
    ("BREAKING", "the fault goes in, one layer"),
    ("MEASURING", "probes read the damage"),
    ("YOUR TURN", "you patch it and press P"),
    ("TESTING YOUR FIX", "the same fault, against your patch"),
    ("READING YOUR FIX", "Nemotron reads the diff for gaps"),
)
# The logs /zoom can fill the screen with.
ZOOMS: Final = ("timeline", "agent")
# What Tab completes in the command line: every command, then the
# arguments that have a fixed set of values.
_COMPLETIONS: Final = [
    *(f"/{name}" for name in COMMANDS),
    *(f"/cycle {n}" for n in range(1, MAX_CYCLES + 1)),
    *(f"/zoom {log}" for log in ZOOMS),
    "/copy timeline",
    "/choose a",
    "/choose b",
]


class BedlamApp(App[int]):
    HORIZONTAL_BREAKPOINTS = [(0, "-narrow"), (_ROOMY, "-roomy"), (_WIDE, "-wide")]
    CSS = f"""
    Screen {{ background: {_BACKGROUND}; color: {_TEXT}; }}
    #frame {{ width: 100%; min-width: {WIDTH}; height: 100%; }}
    #header {{ height: 1; background: {INK}; color: {_TEXT}; }}
    #splash {{ display: none; width: 100%; height: 100%; content-align: center middle; }}
    #top {{ height: 5; }}
    #jester {{ display: none; width: {_JESTER}; height: 5; padding: 1 1; }}
    Screen.-roomy #jester, Screen.-wide #jester {{ display: block; }}
    #now {{
        width: 1fr; height: 5; border: round {ACCENT}; padding: 0 1; background: {_SURFACE};
        border-title-color: {ACCENT}; border-title-style: bold;
    }}
    #now.your-turn {{
        border: heavy {GO}; background: {GO} 12%; border-title-color: {GO};
    }}
    #says {{ height: 1; padding: 0 1; }}
    .panel {{
        border: round {MUTED}; padding: 0 1; background: {_SURFACE};
        border-title-color: {ACCENT}; border-subtitle-color: {_SOFT};
    }}
    #system {{ height: 6; }}
    #tradeoff {{ display: none; height: auto; border: heavy {GO}; }}
    #postmortem.-field {{ padding: 0; }}
    #frame.-escalation #tradeoff {{ display: block; }}
    #frame.-escalation #system, #frame.-escalation #body {{ display: none; }}
    #frame.-zoomed #system {{ display: none; }}
    #body.-zoom-timeline #agent, #body.-zoom-agent #timeline {{ display: none; }}
    #body {{ height: 1fr; }}
    #timeline {{ height: 2fr; min-height: 6; }}
    #agent {{ height: 1fr; min-height: 9; }}
    Screen.-wide #body {{ layout: horizontal; }}
    Screen.-wide #timeline {{ width: 1fr; height: 100%; }}
    Screen.-wide #agent {{ width: 1fr; height: 100%; }}
    RichLog {{
        scrollbar-size-vertical: 1; scrollbar-color: {MUTED};
        scrollbar-background: {_SURFACE}; scrollbar-color-hover: {ACCENT};
    }}
    #command {{
        height: 1; border: none; padding: 0 1; background: {_SURFACE}; color: {_TEXT};
    }}
    #command:focus {{ background: {INK}; }}
    #command > .input--placeholder {{ color: {_SOFT}; }}
    #command > .input--cursor {{ background: {GO}; color: {_BACKGROUND}; }}
    #footer {{ height: 1; }}
    """
    BINDINGS = [
        ("p", "patch", "hand over the fix"),
        ("a", "choose('a')", "option A"),
        ("b", "choose('b')", "option B"),
        ("q", "quit", "quit"),
        ("slash", "command", "type a command"),
        ("escape", "leave_command", "leave the command line"),
    ]
    # The logs hold focus so P and Q work as keys; "/" moves to the command
    # line, and Enter or Esc gives focus back.
    AUTO_FOCUS = "#timeline"
    # "/" is the only way into a command line: Textual's own palette is off.
    ENABLE_COMMAND_PALETTE = False

    def __init__(
        self,
        root_seed: int,
        patches: PatchSource,
        launch: Launch,
        *,
        real: bool = False,
        stats: StatsSource | None = None,
        splash_s: float = 0.0,
    ) -> None:
        super().__init__()
        # The jester and the wordmark before the run starts, and with the
        # moral when a completed run is quit; 0 skips both.
        self.splash_s = splash_s
        self._started = False
        self.moral_shown = False
        self.root_seed = root_seed
        # Real patch mode: the developer writes the fix and P reads git diff.
        self.real = real
        self.patches = GatedPatchSource(patches)
        self.patches.on_empty = self._no_changes
        self._voice = Voice(root_seed)
        self._launch = launch
        self._models: ModelClient | None = None
        self._search: SearchClient | None = None
        self._seen_calls = 0
        self._seen_searches = 0
        self._cycle = 0
        self.now: Guidance = STARTING.onboarding()
        self._onboarding = True  # until the first turn, the NOW box says the whole loop
        self._said: tuple[str, bool] | None = None
        self.mood = jester.Mood.IDLE
        self._blast: list[str] = []
        self._fault: str | None = None
        self._health: dict[str, dict[str, Any]] = {}
        # Display only: when the running probes started, for the fill animation.
        self._probing_since: float | None = None
        # Every row each log shows, kept so a resize can redraw at the new width.
        self._timeline_rows: list[tuple[str, str, str]] = []
        self._agent_rows: list[tuple[int, CallRecord | SearchCall]] = []
        self._flowed: tuple[int, int] = (0, 0)
        # Container load, display only. None: not sampled (tests, no Docker).
        self._stats = stats
        self._load: dict[Layer, ContainerStats] = {}
        self._cpu: dict[Layer, deque[float]] = {layer: deque(maxlen=_SPARK_LEN) for layer in Layer}
        self._load_note = "cpu and memory: starting" if stats else ""
        # Every sample of the run, for the chart under the trade-off.
        self.choices = GatedChoice()
        self.choices.on_ask = self._render_chrome
        self._trade_off: dict[str, Any] | None = None
        self._escalated = False
        # The latest of each, for /why and /diff.
        self._routed: dict[str, Any] | None = None
        self._patch: dict[str, Any] | None = None
        self._analysis: dict[str, Any] | None = None
        # /grep's text, None when the timeline shows everything. Rows a
        # command echoed or replied with are pinned: a filter never hides them.
        self._grep: str | None = None
        self._pinned: set[int] = set()
        # While a command runs: what it has said so far. None otherwise.
        self._replying: list[str] | None = None
        # What the last command said, for /copy.
        self._last_reply: list[str] = []
        self._last_command = ""
        # The run as the post-mortem reads it: each cycle's events by kind,
        # and the events outside a cycle (baseline, trade-off, cost).
        self._cycles: dict[int, dict[str, dict[str, Any]]] = {}
        self._run_events: dict[str, dict[str, Any]] = {}
        # The run completed and its trade-off was decided: the trade-off page
        # stays, with the post-mortem log under it.
        self._decided = False
        self._page_rows: list[tuple[str | Text, str]] = []
        self._field_key: tuple[int, int] | None = None  # the log's size while the field shows
        self._glow_frame = 0  # frames of the field's swing so far, at FIELD_FPS
        self._glow = GLOW_FROM  # where the glow is, in percent along the band
        # Where the latest command's rows start in the post-mortem log: /grep
        # never hides what was just asked for.
        self._page_start = 0
        self._shots = 0
        # Where the run's trace is written; /save and /shot write beside it.
        self.trace_file: Path | None = None
        # Where the run's decision record is written, said once it exists.
        self.decision_file: Path | None = None
        self.exit_code: int | None = None

    def compose(self) -> ComposeResult:
        yield Splash(id="splash")
        with Vertical(id="frame"):
            yield Static(id="header")
            with Horizontal(id="top"):
                now = Static(id="now")
                now.border_title = "NOW"
                yield now
                yield Static(id="jester")
            yield Static(id="says")
            tradeoff = Static(id="tradeoff", classes="panel")
            tradeoff.border_title = "TRADE-OFF · you choose, Bedlam does not"
            yield tradeoff
            page = RichLog(id="postmortem", classes="panel", wrap=False)
            page.border_title = "POST-MORTEM · /cycles to start, /help for the rest"
            page.display = False
            yield page
            system = Static(id="system", classes="panel")
            system.border_title = f"{APP} · health of each part"
            yield system
            with Vertical(id="body"):
                timeline = RichLog(id="timeline", classes="panel", wrap=False)
                timeline.border_title = f"{LOG} · newest at the bottom"
                yield timeline
                agent = RichLog(id="agent", classes="panel", wrap=False)
                agent.border_title = f"{MODELS} · which model did each step"
                yield agent
            yield CommandLine(
                id="command",
                placeholder="press / to type a command, /help lists them",
                select_on_focus=False,
                suggester=SuggestFromList(_COMPLETIONS, case_sensitive=False),
            )
            yield Static(id="footer")

    def on_mount(self) -> None:
        self._render_chrome()
        self.set_interval(0.05, self._tick)
        self.set_interval(1 / FIELD_FPS, self._animate_field)
        if self.splash_s <= 0:
            self._start()
            return
        splash = self.query_one("#splash", Splash)
        splash.update(jester.splash(_SPLASH_COLOURS))
        splash.display = True
        self.query_one("#frame").display = False
        splash.focus()
        self.set_timer(self.splash_s, self.end_splash)

    @property
    def splashing(self) -> bool:
        return self.query_one("#splash").display

    def end_splash(self) -> None:
        """Swap the splash for the frame; the first time, start the run."""
        if not self.splashing:
            return
        self.query_one("#splash").display = False
        self.query_one("#frame").display = True
        self._home().focus()
        self.call_after_refresh(self._render_chrome)
        if not self._started:
            self._start()

    def show_moral(self) -> None:
        """The end splash: the jester again, with the moral. Any key quits."""
        self.moral_shown = True
        below = ((MORAL, f"bold italic {_TEXT}"), (SIGN_OFF, _SOFT))
        splash = self.query_one("#splash", Splash)
        splash.update(jester.splash(_SPLASH_COLOURS, below))
        splash.display = True
        self.query_one("#frame").display = False
        splash.focus()

    def _start(self) -> None:
        self._started = True
        self.run_worker(self._run(), exclusive=True)
        if self._stats is not None:
            self.run_worker(self._poll_stats(), group="stats")

    def on_resize(self) -> None:
        self.call_after_refresh(self._render_chrome)

    async def _run(self) -> None:
        try:
            self.exit_code = await self._launch(self)
        except Exception as exc:
            self.exit_code = 1
            self._say(f"run failed: {type(exc).__name__}: {exc}", style=f"bold {DAMAGE}")
        self._drain_calls()
        if self.exit_code != 0:
            self.now = STOPPED
        else:
            if "chosen" in self._run_events:
                self._decided = True
                self.query_one("#frame").add_class("-escalation")
        self._render_chrome()
        if not self.splashing:
            self._home().focus()

    # -- inputs ---------------------------------------------------------------

    def attach(self, models: ModelClient, search: SearchClient) -> None:
        self._models, self._search = models, search

    def action_command(self) -> None:
        line = self.query_one("#command", Input)
        line.value = "/"
        line.focus()
        line.cursor_position = len(line.value)

    def action_leave_command(self) -> None:
        line = self.query_one("#command", Input)
        line.value = ""
        self._home().focus()

    def _home(self) -> RichLog:
        """The log that holds focus between commands: the one on screen."""
        if self._past_choice() and self.query_one("#frame").has_class("-escalation"):
            return self.query_one("#postmortem", RichLog)
        zoomed_agent = self.query_one("#body").has_class("-zoom-agent")
        return self.query_one("#agent" if zoomed_agent else "#timeline", RichLog)

    def _past_choice(self) -> bool:
        """Whether the trade-off page shows decided: the run completed, or
        the chosen cost is still running."""
        return self._decided or ("chosen" in self._run_events and self.exit_code is None)

    def _on_page(self) -> bool:
        """Whether command replies go to the post-mortem log."""
        frame = self.query_one("#frame")
        return frame.has_class("-escalation") and self.query_one("#postmortem").display

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        self.action_leave_command()
        if not text:
            return
        name, *rest = text.lstrip("/").split(maxsplit=1) or [""]
        name, arg = name.lower(), rest[0].strip() if rest else ""
        said: list[str] = []
        self._replying = said
        self._page_start = len(self._page_rows)
        if self._grep is not None:  # the reply before this one is filtered now
            self._redraw_page()
        try:
            self._say(f"you › {text}", style=f"bold {_TEXT}")
            if name == "sudo":
                # Not in /help: an easter egg. It never runs what follows it.
                line = SUDO_CHOOSE if arg.lower().startswith("choose") else SUDO
                self._say(f"» {line}", style=_voice_style(False))
            elif name in COMMANDS:
                getattr(self, f"_command_{name}")(arg)
            else:
                self._reply(f"unknown command /{name}. /help lists them")
        finally:
            self._replying = None
        if name != "copy":
            self._last_command, self._last_reply = text, said[1:]

    def _command_help(self, arg: str) -> None:
        for name, about in COMMANDS.items():
            self._reply(f"  /{name:<8} {about}")

    def _command_status(self, arg: str) -> None:
        if self.exit_code is not None:
            where = "run over" if self.exit_code == 0 else "run stopped"
        elif self._escalated:
            where = "trade-off"
        elif self._cycle:
            where = f"cycle {self._cycle} of {MAX_CYCLES}"
        else:
            where = "baseline, before cycle 1"
        if self.patches.waiting:
            where += " · waiting for your patch"
        elif self.choices.waiting:
            where += " · waiting for your choice: A or B"
        elif self.exit_code is None:
            where += " · Bedlam is working"
        self._reply(f"  {where}")
        if self._fault:
            blast = ", ".join(self._blast)
            self._reply(f"  live fault: {self._fault} · blast radius: {blast}")
        else:
            self._reply("  no fault live")

    def _cycle_arg(self, arg: str, command: str) -> int | None:
        """The cycle `arg` names, or the latest; says why when there is none."""
        seen = sorted(self._cycles)
        if not seen:
            self._reply("  no cycle has started yet")
            return None
        if not arg:
            return seen[-1]
        if arg.isdigit() and int(arg) in self._cycles:
            return int(arg)
        named = " or ".join(f"/{command} {n}" for n in seen)
        self._reply(f"  no cycle {arg} in this run. try {named}")
        return None

    def _command_why(self, arg: str) -> None:
        routed = self._routed
        if arg:
            cycle = self._cycle_arg(arg, "why")
            if cycle is None:
                return
            routed = self._cycles[cycle].get("routed")
        if routed is None:
            self._reply("  nothing routed yet. /why works once Bedlam has searched")
            return
        routing = routed["routing"]
        weights = " · ".join(f"{k} {v:.2f}" for k, v in routing["weights"].items())
        head = f"  routed to {routed['specialist']} ({routing['basis']})"
        self._reply(f"{head}: {weights}" if weights else head)
        if routing["basis"] == "symptom":
            self._reply("  no result named a layer, so the symptom's layer decided")
        elif routing["basis"] == "seeded":
            self._reply("  nothing named a layer, so the root seed decided")
        named = [r for r in routed["results"] if r["layer"]]
        if not named:
            return
        self._reply("  results behind it, strongest first:")
        for result in sorted(named, key=lambda r: -r["score"])[: None if arg else _WHY_RESULTS]:
            where = re.sub(r"^https?://(www\.)?", "", result["url"])
            text = f"    {result['layer']:<5} {result['score']:.2f}  {where}  {result['title']}"
            self._reply(text)

    def _command_search(self, arg: str) -> None:
        """The search behind one cycle, request to routing, from what the
        TUI already holds: the queries, the client's calls, the labels."""
        cycle = self._cycle_arg(arg, "search")
        if cycle is None:
            return
        steps = self._cycles[cycle]
        if "searching" not in steps:
            self._reply(f"  cycle {cycle} has not searched yet")
            return
        queries = steps["searching"]["queries"]
        calls = self._search.calls if self._search is not None else []
        made = [next((c for c in calls if c.query == q["text"]), None) for q in queries]
        live = sum(c is not None and not c.cached for c in made)
        head = f"  cycle {cycle} · {len(queries)} queries · {live} live"
        self._reply(f"{head}, {len(queries) - live} cached · {live * CREDITS_PER_SEARCH} credits")
        width = self._reply_width()
        for i, (query, call) in enumerate(zip(queries, made, strict=True), 1):
            if call is None:
                tail = "searching"
            elif call.cached:
                tail = "cached"
            elif call.outcome != "ok":
                tail = f"failed: {call.error}"
            else:
                tail = f"{call.latency_ms:>5.0f} ms · {call.results} kept"
                tail += f", {call.filtered} cut" if call.filtered else ""
            label = fit(_query_label(query), width - len(tail) - 6)
            self._reply(f"  {i}  {label:<{width - len(tail) - 6}} {tail}")
        self._reply("")
        self._reply(f"     advanced depth · up to {MAX_RESULTS} results a query")
        sites = f"only from {', '.join(INCLUDE_DOMAINS)}"
        for line in wrap(sites, indent=10, width=width - 5):
            self._reply(f"     {line}")
        self._reply(f"     never from {' or '.join(EXCLUDE_DOMAINS)}")
        routed = steps.get("routed")
        if routed is None:
            self._reply("")
            self._reply("  Nano is labelling the results")
            return
        results = routed["results"]
        counts = {layer.value: 0 for layer in Layer}
        for result in results:
            if result["layer"]:
                counts[result["layer"]] += 1
        unnamed = len(results) - sum(counts.values())
        named = " · ".join(f"{layer} {n}" for layer, n in counts.items())
        self._reply("")
        self._reply(f"  Nano labelled {len(results)} results: {named} · none {unnamed}")
        self._reply("")
        weights = routed["routing"]["weights"]
        top = max(weights.values(), default=0.0)
        for layer in Layer:
            weight = weights.get(layer.value, 0.0)
            filled = round(weight / top * _SEARCH_BAR) if top else 0
            bar = "█" * filled + " " * (_SEARCH_BAR - filled)
            self._reply(f"     {layer.value:<6} {bar}  {weight:.2f}")
        self._reply("")
        basis = routed["routing"]["basis"]
        self._reply(
            f"  → {routed['specialist']} specialist ({basis}). /why {cycle} lists the results"
        )

    def _command_loop(self, arg: str) -> None:
        """One round's steps top to bottom, the current one marked."""
        cycle, escalated = self._cycle, self._escalated
        rounds = [
            f"round {n}  " + ("done" if n < cycle or escalated else "now" if n == cycle else "next")
            for n in range(1, MAX_CYCLES + 1)
        ]
        after = "the trade-off  now" if escalated else "then the trade-off"
        self._reply("")
        self._reply("   " + "      ".join([*rounds, after]))
        self._reply("")
        current = 0 if escalated else self.now.step
        for n, (title, about) in enumerate(LOOP_STEPS, 1):
            here = n == current
            line = f"   {n}  {title:<16}{'◀' if here else ' '}   {about}"
            self._say(line, style=f"bold {ACCENT}" if here else _SOFT)
            self._reply("   │")
        if cycle < MAX_CYCLES and not escalated:
            self._reply(f"   └──→  round {cycle + 1} starts at 1, aimed at the gap")
        else:
            self._reply(f"   └──→  no round {MAX_CYCLES + 1}: the trade-off is next")
        self._reply("")
        tail = "   after round 2:   TRADE-OFF  →  YOUR CHOICE  →  THE COST"
        self._say(tail, style=f"bold {ACCENT}" if escalated else _SOFT)

    def _command_diff(self, arg: str) -> None:
        patch, analysis = self._patch, self._analysis
        if arg:
            cycle = self._cycle_arg(arg, "diff")
            if cycle is None:
                return
            steps = self._cycles[cycle]
            patch = steps.get("patched", {}).get("patch")
            analysis = steps.get("analysed", {}).get("analysis")
        if patch is None:
            self._reply("  no patch read yet")
            return
        self._reply(f"  patch: {patch['source']} ({patch['chars']} chars)")
        if analysis is None:
            self._reply("  still reading it")
            return
        defended = _defended(analysis)
        self._reply(f"  defends: {defended or 'none'}")
        gaps = "; ".join(analysis["gaps"]) or "none found"
        for line in wrap(f"gaps: {gaps}", indent=6, width=self._reply_width() - 2):
            self._reply(f"  {line}")

    # -- post-mortem ------------------------------------------------------------

    def _field(self, label: str, value: str) -> None:
        """One labelled line of /cycle or /cost, the value wrapped under itself."""
        indent = 2 + _FIELD + 1
        lines = textwrap.wrap(" ".join(value.split()), width=self._reply_width() - indent)
        for i, line in enumerate(lines or [""]):
            head = f"  {label:<{_FIELD}} " if i == 0 else " " * indent
            self._reply(head + line)

    def _command_cycles(self, arg: str) -> None:
        if not self._cycles:
            self._reply("  no cycle has started yet")
            return
        for cycle, steps in sorted(self._cycles.items()):
            fault = steps.get("injecting", {}).get("fault", "no fault yet")
            symptom = steps.get("symptom", {}).get("symptom")
            seen = "no symptom yet"
            if symptom is not None:
                seen = symptom["kind"] + (f" on {symptom['layer']}" if symptom["layer"] else "")
            analysis = steps.get("analysed", {}).get("analysis")
            read = "patch not read yet"
            if analysis is not None:
                defended = _defended(analysis)
                read = f"defends {defended or 'nothing'} · {len(analysis['gaps'])} gaps"
            self._reply(f"  c{cycle}  {fault} · {seen} → {read}")
        if self._trade_off is not None:
            chosen = self._run_events.get("chosen")
            outcome = "waiting for your choice"
            if chosen is not None:
                outcome = f"you chose {chosen['choice'].upper()}: {chosen['option']['title']}"
            self._reply(f"  tf  {self._trade_off['axis']} → {outcome}")

    def _command_cycle(self, arg: str) -> None:
        cycle = self._cycle_arg(arg, "cycle")
        if cycle is None:
            return
        steps = self._cycles[cycle]
        self._say(f"  cycle {cycle} of {MAX_CYCLES}", style=f"bold {ACCENT}")
        if "searching" in steps:
            queries = " · ".join(_query_label(q) for q in steps["searching"]["queries"])
            self._field("searched", queries)
        if "routed" in steps:
            routed = steps["routed"]
            routing = routed["routing"]
            weights = " · ".join(f"{k} {v:.2f}" for k, v in routing["weights"].items())
            basis = f"{routing['basis']}: {weights}" if weights else routing["basis"]
            self._field(
                "routed", f"{routing['layer']} ({basis}), {routed['specialist']} specialist"
            )
        if "selected" in steps:
            selection = steps["selected"]["selection"]
            eligible = selection["eligible"]
            self._field("pool", f"{len(eligible)} eligible: {', '.join(eligible)}")
            for fault, reason in selection["rejected"].items():
                self._field("passed on", f"{fault}: {reason}")
            rationale = selection.get("rationale") or ""
            picked = selection["fault"]["id"]
            self._field("picked", f"{picked}. {rationale}" if rationale else picked)
        if "injecting" in steps:
            injected = steps["injecting"]
            blast = ", ".join(injected["blast_radius"])
            self._field("injected", f"{injected['fault']} on {injected['layer']} · blast {blast}")
        if "probed" in steps:
            self._field("under it", _health_text(steps["probed"]["snapshot"]))
        if "symptom" in steps:
            symptom = steps["symptom"]["symptom"]
            where = f" on {symptom['layer']}" if symptom["layer"] else ""
            self._field("symptom", f"{symptom['kind']}{where}. {symptom['summary']}")
        if "patched" in steps:
            patch = steps["patched"]["patch"]
            self._field("patch", f"{patch['source']} ({patch['chars']} chars)")
        if "patch_checked" in steps:
            self._field("held?", _check_text(steps["patch_checked"]["check"]))
        if "fault_removed" in steps:
            self._field("after", _health_text(steps["fault_removed"]["snapshot"]))
        if "analysed" in steps:
            analysis = steps["analysed"]["analysis"]
            defended = _defended(analysis)
            self._field("defends", defended or "nothing")
            self._field("gaps", "; ".join(analysis["gaps"]) or "none found")

    def _command_calls(self, arg: str) -> None:
        records = self._models.records if self._models is not None else []
        searches = self._search.calls if self._search is not None else []
        if not records and not searches:
            self._reply("  no model or search calls yet")
            return
        sites: dict[str, list[CallRecord]] = {}
        for record in records:
            sites.setdefault(record.site, []).append(record)
        for site, group in sites.items():
            models = "/".join(sorted({LABELS.get(r.model, "?") for r in group}))
            tokens = sum((r.prompt_tokens or 0) + (r.completion_tokens or 0) for r in group)
            latency = sum(r.latency_ms for r in group) / len(group)
            line = f"  {site:<24} {models:<10} {len(group):>2}× {tokens:>6} tok {latency:>6.0f}ms"
            fallbacks = sum(r.fallback for r in group)
            failed = sum(r.outcome != "ok" for r in group)
            extra = [f"{fallbacks} fallback"] * bool(fallbacks) + [f"{failed} failed"] * bool(
                failed
            )
            self._reply(" · ".join([line, *extra]))
        if searches:
            cached = sum(c.cached for c in searches)
            latency = sum(c.latency_ms for c in searches) / len(searches)
            head = f"  {'search':<24} {'Tavily':<10} {len(searches):>2}×"
            self._reply(f"{head} {cached:>3} cached {latency:>6.0f}ms")
        self._reply(f"  total: {self._usage()}")

    def _command_cost(self, arg: str) -> None:
        chosen = self._run_events.get("chosen")
        if chosen is None:
            self._reply("  no choice made yet. the cost shows once you pick A or B")
            return
        option = chosen["option"]
        self._field("you chose", f"{chosen['choice'].upper()}: {option['title']}")
        self._field("you pay", option["cost"])
        self._field("felt when", option["felt_when"])
        showing = self._run_events.get("showing_cost")
        if showing is not None:
            blast = ", ".join(showing["blast_radius"])
            self._field("shown as", f"{showing['fault']} on {showing['layer']} · blast {blast}")
        last = self._cycles.get(max(self._cycles, default=0), {}).get("fault_removed")
        for label, event in (
            ("before", last),
            ("under it", self._run_events.get("cost_shown")),
            ("after", self._run_events.get("cost_removed")),
        ):
            if event is not None:
                self._field(label, _health_text(event["snapshot"]))

    def _command_log(self, arg: str) -> None:
        frame = self.query_one("#frame")
        if self._trade_off is None or not (self._past_choice() or self.choices.waiting):
            self._reply("  the run log is already on screen")
            return
        frame.toggle_class("-escalation")
        self._render_chrome()
        self._home().focus()
        if frame.has_class("-escalation"):
            self._reply("  back on the trade-off page")
        else:
            self._reply("  the run log. /log goes back to the trade-off")

    def _command_seed(self, arg: str) -> None:
        seed = self.root_seed
        for line in (
            f"  root seed {seed} · every seeded choice in this run derives from it",
            f"  run it again: make run SEED={seed}",
            "  live model replies can still vary; make test replays a run exactly",
        ):
            self._reply(line)

    def _command_grep(self, arg: str) -> None:
        self._grep = arg.lower() or None
        self._redraw_timeline()
        self._redraw_page()
        if self._grep is None:
            return
        if self._on_page():
            rows = range(self._page_start)
            hits = sum(1 for i in rows if not _echo(self._page_rows[i][0]) and self._page_shown(i))
        else:
            rows = range(len(self._timeline_rows))
            hits = sum(1 for i in rows if i not in self._pinned and self._shown(i))
        self._reply(f"  {hits} lines match. /grep alone shows all")

    def _command_zoom(self, arg: str) -> None:
        if self.query_one("#frame").has_class("-escalation"):
            self._reply("  /zoom works on the run log. /log shows it")
            return
        log = arg.lower()
        # /zoom alone ends a zoom; with none on, it would change nothing.
        zoomed = self.query_one("#frame").has_class("-zoomed")
        if (log and log not in ZOOMS) or (not log and not zoomed):
            self._reply("zoom what? /zoom timeline or /zoom agent")
            return
        body = self.query_one("#body")
        body.remove_class(*(f"-zoom-{name}" for name in ZOOMS))
        self.query_one("#frame").set_class(bool(log), "-zoomed")
        if log:
            body.add_class(f"-zoom-{log}")
        self.action_leave_command()
        self.call_after_refresh(self._render_chrome)

    def _command_copy(self, arg: str) -> None:
        if arg.lower() == "timeline":
            lines = [
                f"{tag} {text}"
                for i, (tag, text, _) in enumerate(self._timeline_rows)
                if self._shown(i)
            ]
        elif arg:
            self._reply("copy what? /copy or /copy timeline")
            return
        else:
            lines = self._last_reply
        if not lines:
            self._reply("  nothing to copy yet")
            return
        self.copy_to_clipboard("\n".join(lines))
        self._reply(f"  copied {len(lines)} lines, if your terminal allows it")

    def _command_save(self, arg: str) -> None:
        if self.trace_file is None:
            self._reply("  this run has no trace file to save beside")
            return
        path = self.trace_file.with_suffix(".txt")
        agent = [self._agent_line(*row, width=LINE).plain for row in self._agent_rows]
        text = [
            f"BEDLAM · seed {self.root_seed}",
            "",
            LOG,
            *(f"{tag} {line}" for tag, line, _ in self._timeline_rows),
            "",
            MODELS,
            *agent,
        ]
        if self._page_rows:
            text += ["", "POST-MORTEM", *(str(line) for line, _ in self._page_rows)]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(text) + "\n", encoding="utf-8")
        self._reply(f"  saved {_shown_path(path)}")

    def _command_shot(self, arg: str) -> None:
        if self.trace_file is None:
            self._reply("  this run has no trace file to save beside")
            return
        self._shots += 1
        path = self.trace_file.with_name(f"{self.trace_file.stem}-shot{self._shots}.svg")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.save_screenshot(filename=path.name, path=str(path.parent))
        self._reply(f"  saved {_shown_path(path)}")

    def _command_patch(self, arg: str) -> None:
        self.action_patch()

    def _command_choose(self, arg: str) -> None:
        key = arg.lower()
        if key not in KEYS:
            self._reply("choose a or b, e.g. /choose a")
            return
        self.action_choose(key)

    def _command_quit(self, arg: str) -> None:
        self.action_quit()

    def action_quit(self) -> None:  # type: ignore[override]
        """Leave Bedlam. A completed run says its moral first; the next key quits."""
        if self.exit_code == 0 and self.splash_s > 0 and not self.moral_shown:
            self.show_moral()
            return
        self.exit()

    def action_choose(self, key: str) -> None:
        if not self.choices.choose(key):
            self.now = self.now.nudged(EARLY_CHOICE)
        self._render_chrome()

    def action_patch(self) -> None:
        if self.patches.release():
            self.now = PRESSED_REAL if self.real else PRESSED_SCRIPTED
        else:
            self.now = self.now.nudged(EARLY_PRESS)
        self._render_chrome()

    def _no_changes(self) -> None:
        self.now = NO_CHANGES
        self._say(f"no changes in {TARGET} yet. edit, save, press p", style=f"bold {GO}")
        self._render_chrome()

    # -- loop events ----------------------------------------------------------

    def on_loop_event(self, kind: str, fields: dict[str, Any]) -> None:
        # Drain first: calls made since the last event belong to the cycle
        # in effect before this one, and a cycle can outrun the poll timer.
        self._drain_calls()
        if kind == "cycle_started":
            self._cycle = fields["cycle"]
        if fields.get("cycle"):
            self._cycles.setdefault(fields["cycle"], {})[kind] = fields
        elif kind != "probing":
            self._run_events[kind] = fields
        self.now = guidance(kind, fields, real=self.real) or self.now
        if self.now.your_turn:
            self._onboarding = False
        elif self._onboarding:
            self.now = self.now.onboarding()
        handler = getattr(self, f"_on_{kind}", None)
        if handler is not None:
            handler(fields)
        self.mood = jester.mood_for(event_key(kind, fields), self.mood)
        line = self._voice.say(kind, fields)
        if line:
            quoted = self._voice.quoted
            self._say_wrapped("» " + line, 2, _voice_style(quoted))
            # The timeline scrolls; BEDLAM SAYS holds the line until the next.
            self._said = (line, quoted)
            log_event(_LOG, "voice", kind=kind, cycle=self._cycle, line=line, quote=quoted)
        self._render_chrome()

    def _on_probing(self, fields: dict[str, Any]) -> None:
        self._probing_since = time.monotonic()

    def _on_baseline(self, fields: dict[str, Any]) -> None:
        self._snapshot(fields, "baseline", GO)

    def _on_cycle_started(self, fields: dict[str, Any]) -> None:
        self._rule(f"── cycle {fields['cycle']} of {MAX_CYCLES} ")

    def _on_searching(self, fields: dict[str, Any]) -> None:
        for query in fields["queries"]:
            self._say(f"tavily  {_query_label(query)}", style=ACCENT)

    def _on_routed(self, fields: dict[str, Any]) -> None:
        self._routed = fields
        for text, style in routing_lines(fields, self._say_width()):
            self._say(text, style=style)

    def _on_selected(self, fields: dict[str, Any]) -> None:
        selection = fields["selection"]
        self._say(f"picked {selection['fault']['id']} from {len(selection['eligible'])} eligible")
        if selection.get("rationale"):
            self._say_wrapped("why: " + selection["rationale"], 5, _SOFT)

    def _on_injecting(self, fields: dict[str, Any]) -> None:
        blast = self._hold_fault(fields)
        self._say(f"injecting {self._fault}, blast radius {blast}", style=f"bold {DAMAGE}")

    def _on_probed(self, fields: dict[str, Any]) -> None:
        self._snapshot(fields, "under fault", DAMAGE)

    def _on_symptom(self, fields: dict[str, Any]) -> None:
        symptom = fields["symptom"]
        where = f" on {symptom['layer']}" if symptom["layer"] else ""
        text = f"symptom: {symptom['kind']}{where}. {symptom['summary']}"
        self._say_wrapped(text, 9, DAMAGE)

    def _on_awaiting_patch(self, fields: dict[str, Any]) -> None:
        if self.real:
            text = f"waiting for your fix in {TARGET}. press p when it is saved"
        else:
            text = "waiting for your fix. press p to apply the prepared one"
        self._say(text, style=f"bold {GO}")

    def _on_patched(self, fields: dict[str, Any]) -> None:
        self._patch, self._analysis = fields["patch"], None
        patch = fields["patch"]
        self._say(f"patch in: {patch['source']} ({patch['chars']} chars)")

    def _on_deploying(self, fields: dict[str, Any]) -> None:
        self._fault, self._blast = None, []
        self._say("fault out. your app restarts with the patch")

    def _on_retesting(self, fields: dict[str, Any]) -> None:
        self._hold_fault(fields)
        self._say(f"same fault again: {self._fault}, against your patch", style=f"bold {DAMAGE}")

    def _on_patch_checked(self, fields: dict[str, Any]) -> None:
        self._probing_since = None
        check = fields["check"]
        text = f"through the app: {_check_text(check)}"
        style = f"bold {GO}" if check["held"] else f"bold {DAMAGE}"
        self._say_wrapped(text, 17, style)

    def _on_fault_removed(self, fields: dict[str, Any]) -> None:
        self._snapshot(fields, "fault removed", GO, clear=True)

    def _on_analysed(self, fields: dict[str, Any]) -> None:
        analysis = self._analysis = fields["analysis"]
        defended = _defended(analysis) or "none"
        self._say(f"patch defends: {defended}")
        if analysis["gaps"]:
            gaps = "gaps: " + "; ".join(analysis["gaps"])
            self._say_wrapped(gaps, 6, _SOFT)

    def _on_escalating(self, fields: dict[str, Any]) -> None:
        self._escalated = True
        self._rule("── trade-off ")

    def _on_trade_off(self, fields: dict[str, Any]) -> None:
        self._trade_off = fields["trade_off"]
        self._say(f"trade-off: {self._trade_off['axis']}", style=f"bold {ACCENT}")
        for item in self._trade_off["options"]:
            self._say(f"  {item['key'].upper()}  {item['title']}")
        self.query_one("#frame").add_class("-escalation")
        # The strip's room depends on the panel's height, known after layout.
        self.call_after_refresh(self._render_chrome)

    def _on_chosen(self, fields: dict[str, Any]) -> None:
        self.query_one("#frame").remove_class("-escalation")
        text = f"you chose {fields['choice'].upper()}: {fields['option']['title']}"
        self._say(text, style=f"bold {GO}")

    def _on_showing_cost(self, fields: dict[str, Any]) -> None:
        blast = self._hold_fault(fields)
        self._say(f"showing the cost: {self._fault}, blast radius {blast}", style=f"bold {DAMAGE}")

    def _say_wrapped(self, text: str, indent: int, style: str = "") -> None:
        """Say prose that may run long, wrapped to the timeline with a hanging indent."""
        for line in wrap(text, indent=indent, width=self._say_width()):
            self._say(line, style=style)

    def _rule(self, text: str) -> None:
        """A section rule across the timeline: `text` then dashes to the edge."""
        self._say(text + "─" * (self._say_width() - len(text)), style=f"bold {ACCENT}")

    def _hold_fault(self, fields: dict[str, Any]) -> str:
        """Hold the live fault for the panels; returns its blast radius, joined."""
        self._fault, self._blast = fields["fault"], fields["blast_radius"]
        return ", ".join(self._blast)

    def _on_cost_shown(self, fields: dict[str, Any]) -> None:
        self._snapshot(fields, "under the cost", DAMAGE)

    def _on_cost_removed(self, fields: dict[str, Any]) -> None:
        self._snapshot(fields, "cost removed", GO, clear=True)

    def _snapshot(
        self, fields: dict[str, Any], label: str, style: str, *, clear: bool = False
    ) -> None:
        """Hold a probe snapshot for the panels and say it; `clear` drops the fault."""
        self._probing_since = None
        self._health = fields["snapshot"]
        if clear:
            self._fault, self._blast = None, []
        self._say(f"{label}: " + self._health_line(), style=style)

    def _on_finished(self, fields: dict[str, Any]) -> None:
        escalation = fields.get("escalation") or {}
        if escalation.get("status") == "chosen" and self.decision_file is not None:
            self._say(f"decision record: {_shown_path(self.decision_file)}", style=f"bold {GO}")

    # -- agent panel ----------------------------------------------------------

    def _drain_calls(self) -> None:
        agent = self.query_one("#agent", RichLog)
        new: list[tuple[int, CallRecord | SearchCall]] = []
        if self._models is not None:
            new += [(r.cycle or 0, r) for r in self._models.records[self._seen_calls :]]
            self._seen_calls = len(self._models.records)
        if self._search is not None:
            new += [(self._cycle, c) for c in self._search.calls[self._seen_searches :]]
            self._seen_searches = len(self._search.calls)
        self._agent_rows += new
        for row in new:
            agent.write(self._agent_line(*row, width=_inner(agent)))
        agent.border_subtitle = self._usage()

    def _agent_line(self, cycle: int, item: CallRecord | SearchCall, width: int) -> Text:
        tag = f"c{cycle}" if cycle else "--"
        if isinstance(item, SearchCall):
            hits = "cached" if item.cached else f"{item.results} hits"
            timing = f" {hits:>7} {item.latency_ms:>6.0f}ms"
            head = f"{tag} tavily "
            room = width - len(head) - len(timing)
            line = Text.assemble((head, f"bold {GO}"))
            line.append(f"{fit(item.query, room):<{room}}", style=GO)
            line.append(timing, style=_SOFT)
            return line
        tokens = f"{item.prompt_tokens or 0:>5}→{item.completion_tokens or 0:<5}"
        flag = " fallback" if item.fallback else ""
        line = Text.assemble((f"{tag} {item.site:<24} ", _SOFT))
        line.append(f"{LABELS.get(item.model, '?'):<5}", style=f"bold {ACCENT}")
        rest = f" {tokens} {item.latency_ms:>6.0f}ms {item.outcome}{flag}"
        failed = item.outcome != "ok"
        style = DAMAGE if failed else f"bold {ACCENT}" if item.fallback else ""
        line.append(fit(rest, width - len(line.plain)), style=style)
        return line

    def _usage(self) -> str:
        counts: dict[str, int] = {}
        tokens = 0
        for record in self._models.records if self._models else []:
            label = LABELS.get(record.model, "?")
            counts[label] = counts.get(label, 0) + 1
            tokens += (record.prompt_tokens or 0) + (record.completion_tokens or 0)
        searches = len(self._search.calls) if self._search else 0
        parts = [f"{label} {n}" for label, n in sorted(counts.items(), reverse=True)]
        return " · ".join([*parts, f"Tavily {searches}", f"{tokens / 1000:.1f}k tok"])

    # -- rendering ------------------------------------------------------------

    def _reflow(self) -> None:
        """Redraw both logs if their width changed (resize, layout switch)."""
        timeline = self.query_one("#timeline", RichLog)
        agent = self.query_one("#agent", RichLog)
        page = self.query_one("#postmortem", RichLog)
        widths = (_inner(timeline), _inner(agent), _inner(page))
        if widths == self._flowed:
            return
        self._flowed = widths
        self._redraw_timeline()
        agent.clear()
        for row in self._agent_rows:
            agent.write(self._agent_line(*row, width=widths[1]))
        self._redraw_page()

    def _redraw_timeline(self) -> None:
        timeline = self.query_one("#timeline", RichLog)
        timeline.clear()
        for index, row in enumerate(self._timeline_rows):
            if self._shown(index):
                timeline.write(self._timeline_line(*row))
        title = f"{LOG} · newest at the bottom"
        if self._grep is not None:
            title = f"{LOG} · /grep {self._grep} · /grep alone shows all"
        timeline.border_title = fit(title, LINE)

    def _page_shown(self, index: int) -> bool:
        """Whether post-mortem row `index` passes /grep.

        Every row there is a command's, so only the echoes and the latest
        command's reply always show; earlier replies are filtered.
        """
        text = self._page_rows[index][0]
        if self._grep is None or index >= self._page_start or _echo(text):
            return True
        return self._grep in str(text).lower()

    def _redraw_page(self) -> None:
        page = self.query_one("#postmortem", RichLog)
        page.clear()
        width = _inner(page)
        for index, (text, style) in enumerate(self._page_rows):
            if self._page_shown(index):
                page.write(_fitted(text, width, style))
        self._field_key = None
        height = page.scrollable_content_region.height
        if not self._page_rows and not page.has_class("-field"):
            # The field needs the log's padding: drop it, draw once laid out.
            page.add_class("-field")
            self.call_after_refresh(self._render_chrome)
            return
        # The field may use the log's whole content row: "│ ", 78, " │" at 82.
        room = page.scrollable_content_region.width
        if page.has_class("-field") and room > FIELD_WIDTH and height >= FIELD_MIN_HEIGHT:
            left = " " * ((room - FIELD_WIDTH + 1) // 2)  # a space off the border
            rows = min(height, FIELD_HEIGHT)
            for _ in range((height - rows) // 2):
                page.write(Text(""))
            for line in postmortem_field(rows, round(self._glow)):
                page.write(Text.assemble(left, line))
            self._field_key = (width, height)
        title = "POST-MORTEM · /cycles to start, /help for the rest"
        if self._grep is not None:
            title = f"POST-MORTEM · /grep {self._grep} · /grep alone shows all"
        page.border_title = fit(title, LINE)

    def _render_chrome(self) -> None:
        self._reflow()
        now = self.now
        full = max(self.query_one("#frame").size.width, WIDTH)

        where = f"round {self._cycle} of {MAX_CYCLES}" if self._cycle else "not started"
        if self._escalated:
            where = "trade-off"
        step = f"step {now.step} of {STEPS}: " if now.step else ""
        right = f"seed {self.root_seed} "
        header = Text.assemble((" BEDLAM ", f"bold {_BACKGROUND} on {ACCENT}"))
        middle = fit(f"  {where}   {step}{now.title}", full - len(header) - len(right))
        header.append(middle.ljust(full - len(header) - len(right)), style="bold")
        header.append(right, style=_SOFT)
        _show(self.query_one("#header", Static), header)

        box = self.query_one("#now", Static)
        box.set_class(now.your_turn, "your-turn")
        body = Text()
        for i, line in enumerate(now.lines):
            last = i == len(now.lines) - 1
            style = "bold" if i == 0 else f"bold {GO}" if last and now.your_turn else _SOFT
            body.append(fit(line, _inner(box)) + ("" if last else "\n"), style=style)
        _show(box, body)
        _show(self.query_one("#jester", Static), jester.render(self.mood, _JESTER_COLOURS))

        says = Text.assemble((_SAYS, f"bold {_BACKGROUND} on {ACCENT}"))
        if self._said is not None:
            line, quoted = self._said
            says.append(" " + fit(line, full - 3 - len(_SAYS)), style=_voice_style(quoted))
        _show(self.query_one("#says", Static), says)

        keys = Text(" ")
        lit = f"bold {_BACKGROUND} on {GO}"
        if self.choices.waiting:
            for key in KEYS:
                keys.append(f" {key.upper()} ", style=lit)
                keys.append(f" option {key.upper()}    ", style=f"bold {GO}")
        elif self.exit_code is None:  # P means nothing once the run is over
            keys.append(" P ", style=lit if now.your_turn else f"{_TEXT} on {MUTED}")
            action = " read my fix    " if self.real else " apply the prepared fix    "
            keys.append(action, style=f"bold {GO}" if now.your_turn else _SOFT)
        keys.append(" Q ", style=f"{_TEXT} on {MUTED}")
        keys.append(" quit    ", style=_SOFT)
        keys.append(" / ", style=f"{_TEXT} on {MUTED}")
        keys.append(" command", style=_SOFT)
        _show(self.query_one("#footer", Static), keys)

        self._render_system()
        if not self.query_one("#frame").has_class("-escalation"):
            self.query_one("#postmortem").display = False
        elif self._past_choice():
            self._render_decided()
        elif self._trade_off is not None:
            self._render_trade_off()
        self._refresh_field()

    def _refresh_field(self) -> None:
        """Redraw the empty reply log when its size changed, so the field
        fits and centres in it."""
        page = self.query_one("#postmortem", RichLog)
        if self._page_rows or not page.display:
            return
        size = (_inner(page), page.scrollable_content_region.height)
        if size != self._field_key:
            self._redraw_page()

    def _animate_field(self) -> None:
        """Move the field's glow one frame: it swings between A and B while
        the choice waits, then travels to the chosen letter and rests there.
        Display only, driven by a frame counter."""
        try:
            page = self.query_one("#postmortem", RichLog)
        except NoMatches:
            return  # shutting down
        if self._field_key is None or not page.display or self.splashing:
            return
        chosen = self._run_events.get("chosen")
        if chosen is None:
            self._glow_frame += 1
            glow = glow_at(self._glow_frame)
        else:
            rest = GLOW_REST[chosen["choice"]]
            step = (GLOW_TO - GLOW_FROM) / GLOW_FRAMES
            glow = (
                rest
                if abs(rest - self._glow) <= step
                else self._glow + math.copysign(step, rest - self._glow)
            )
        moved = round(glow) != round(self._glow)
        self._glow = glow
        if moved:
            self._redraw_page()

    def _trade_off_width(self) -> int:
        """Columns inside the trade-off panel. Hidden or not yet laid out it
        measures nothing, so take them from the frame it fills: the cards
        are then built at the width they are shown at, and never resize."""
        panel = self.query_one("#tradeoff", Static)
        if panel.content_region.width > 0:
            return _inner(panel)
        return max(self.query_one("#frame").size.width - _PANEL_EDGES, LINE)

    def _render_trade_off(self) -> None:
        """Both options with equal weight: two cards, same rows, same colours."""
        assert self._trade_off is not None
        panel = self.query_one("#tradeoff", Static)
        width = self._trade_off_width()
        trade_off = self._trade_off
        body = Text()
        body.append(fit(trade_off["axis"], width) + "\n", style=f"bold {ACCENT}")
        for line in textwrap.wrap(trade_off["why"], width=width):
            body.append(line + "\n", style=_SOFT)
        body.append("\n")
        for line in option_cards(trade_off["options"], width, waiting=self.choices.waiting):
            body.append_text(line)
            body.append("\n")
        # How you got here, while the screen has room for it and the replies.
        recap = self._recap(width)
        strip = self.query_one("#postmortem", RichLog)
        # The panel and the replies share what the fixed rows leave.
        fixed = sum(self.query_one(f"#{name}").outer_size.height for name in _FIXED_ROWS)
        room = self.query_one("#frame").size.height - fixed
        used = body.plain.count("\n") + 2
        left = room - used - 1 - len(recap)  # the replies' rows beside the recap
        # The empty replies show the field: the recap gives way when only
        # leaving it out makes room for the field (borders and band rows).
        field = FIELD_MIN_HEIGHT + 2
        yields = not self._page_rows and left < field <= room - used
        if recap and left >= _STRIP_ROWS and not yields:
            body.append("\n")
            for line in recap:
                body.append_text(line)
                body.append("\n")
            used += 1 + len(recap)
        body.rstrip()
        fits = room - used >= _STRIP_ROWS
        strip.styles.height = "1fr"
        panel.border_subtitle = "" if fits else "replies: /log"
        if strip.display != fits:
            strip.display = fits
            self.call_after_refresh(self._render_chrome)
        _show(panel, body)

    def _recap(self, width: int) -> list[Text]:
        """How you got here: one line per round, the fault and whether the
        patch held under it, measured."""
        lines = [Text("how you got here", style="bold")] if self._cycles else []
        for cycle, steps in sorted(self._cycles.items()):
            fault = steps.get("injecting", {}).get("fault")
            if fault is None:
                continue
            line = Text(f"  R{cycle}  {fault:<21} ", style=_SOFT)
            check = steps.get("patch_checked", {}).get("check")
            if check is None:
                symptom = steps.get("symptom", {}).get("symptom")
                line.append(f"symptom {symptom['kind']}" if symptom else "no check", style=_SOFT)
            else:
                before = AppResult.from_dict(check["before"])
                after = AppResult.from_dict(check["after"])
                line.append(f"{before.text()} → {after.text()}  ", style=_SOFT)
                verdict = "held" if check["held"] else "did not hold"
                line.append(verdict, style=f"bold {GO if check['held'] else DAMAGE}")
            line.truncate(width)
            lines.append(line)
        return lines if len(lines) > 1 else []

    def _render_decided(self) -> None:
        """The trade-off page once chosen: the choice, its cost, and the
        record once the run is over."""
        assert self._trade_off is not None
        panel = self.query_one("#tradeoff", Static)
        page = self.query_one("#postmortem", RichLog)
        panel.styles.height = "auto"
        page.styles.height = "1fr"
        page.display = True
        panel.border_title = "TRADE-OFF · decided, by you"
        panel.border_subtitle = ""
        width = self._trade_off_width()
        chosen = self._run_events["chosen"]["choice"]
        body = Text()
        body.append(fit(self._trade_off["axis"], width) + "\n", style=f"bold {ACCENT}")
        for line in option_cards(self._trade_off["options"], width, chosen=chosen):
            body.append_text(line)
            body.append("\n")
        shown = self._run_events.get("cost_shown")
        showing = self._run_events.get("showing_cost")
        if shown is not None and showing is not None:
            before = self._cycles.get(max(self._cycles, default=0), {}).get("fault_removed")
            readings = (before, shown, self._run_events.get("cost_removed"))
            cost = f"the cost, live: {showing['fault']} · {_cost_text(showing['layer'], readings)}"
            body.append(fit(cost, width) + "\n", style=DAMAGE)
        if self._decided and self.decision_file is not None:  # written as the run ends
            record = f"decision record: {_shown_path(self.decision_file)}"
            body.append(fit(record, width) + "\n", style=GO)
        body.rstrip()
        _show(panel, body)

    def _render_system(self) -> None:
        panel = self.query_one("#system", Static)
        width = _inner(panel)
        # Room for the load columns comes out of the bar, down to its minimum.
        spare = _LOAD_WIDTH if self._load else 0
        size = max(_BAR_MIN, min(_BAR_MAX, width - (LINE - _BAR_MIN) - spare))
        system = Text()
        if self._probing_since is not None:
            # The three probes run at once, so their lines fill together, on
            # the latency bar's own scale: each settles where its result lands.
            elapsed = min(time.monotonic() - self._probing_since, DEFAULT_TIMEOUT_S)
            for layer in Layer:
                system.append(f"{layer.value:<6} {'...':<5} ", style=ACCENT)
                system.append(latency_bar(elapsed * 1000, size), style=ACCENT)
                system.append(f" {elapsed * 1000:>8.0f} ms  checking\n", style=ACCENT)
        for layer in Layer if self._probing_since is None else ():
            result = self._health.get(layer.value)
            if result is None:
                system.append(f"{layer.value:<6} {'-':<5} {'·' * size}\n", style=MUTED)
                continue
            up = result["status"] == "up"
            latency = result["latency_ms"]
            shown = f"{latency:>8.1f} ms" if latency is not None else "      -   "
            system.append(f"{layer.value:<6} ")
            system.append(f"{result['status'].upper():<5} ", style=f"bold {GO if up else DAMAGE}")
            # The bar follows the status beside it; the fault row names the blast.
            system.append(latency_bar(latency, size), style=GO if up else DAMAGE)
            system.append(f" {shown}")
            used = 6 + 1 + 6 + size + 1 + len(shown)
            load = self._load_text(layer)
            if load is not None and used + len(load) <= width:
                system.append(load[:2])
                system.append(load[2:], style=ACCENT)
                used += len(load)
            if result.get("error") and width - used > 4:
                system.append(fit(f"  {result['error']}", width - used), style=_SOFT)
            system.append("\n")
        fault = f"{self._fault} live, blast {', '.join(self._blast)}" if self._fault else "none"
        style = f"bold {DAMAGE}" if self._fault else MUTED
        system.append(fit(f"fault  {fault}", width), style=style)
        _show(panel, system)
        panel.border_subtitle = self._load_note

    async def _poll_stats(self) -> None:
        """Sample container load until the app closes. Never feeds a decision."""
        assert self._stats is not None
        while True:
            try:
                self._load = await self._stats()
            except StatsUnavailable as exc:
                self._load = {}
                self._load_note = "cpu and memory unavailable: is Docker running?"
                _LOG.warning("container stats unavailable", extra={"fields": {"error": str(exc)}})
                await asyncio.sleep(_STATS_RETRY_S)
                continue
            self.record_load(self._load)
            self._load_note = "cpu and memory: docker stats"
            try:
                self._render_system()
                if self._trade_off is not None:
                    self._render_trade_off()
            except NoMatches:
                return  # shutting down
            await asyncio.sleep(_STATS_PAUSE_S)

    def record_load(self, load: dict[Layer, ContainerStats]) -> None:
        """Keep one CPU sample for the sparklines."""
        for layer, stats in load.items():
            self._cpu[layer].append(stats.cpu_percent)

    def _load_text(self, layer: Layer) -> str | None:
        load = self._load.get(layer)
        if load is None:
            return None
        spark = f"{sparkline(self._cpu[layer]):<{_SPARK_LEN}}"
        memory = _memory(load.memory_bytes)
        return f"  cpu{load.cpu_percent:>6.1f}% {spark} mem{memory:>6}"

    def _tick(self) -> None:
        try:
            self._drain_calls()
            if self._probing_since is not None:
                self._render_system()
        except NoMatches:
            return  # shutting down: the panels are already gone

    def _health_line(self) -> str:
        return _health_text(self._health)

    def _say_width(self) -> int:
        return _inner(self.query_one("#timeline", RichLog)) - 3

    def _reply_width(self) -> int:
        """Columns a command reply may use, wherever it is going."""
        if self._on_page():
            return _inner(self.query_one("#postmortem", RichLog))
        return self._say_width()

    def _reply(self, text: str | Text) -> None:
        """One line of a command's reply, in the soft style replies share."""
        self._say(text, style=_SOFT)

    def _say(self, text: str | Text, style: str = "") -> None:
        if self._replying is not None:
            self._replying.append(str(text))
            if self._on_page():
                page = self.query_one("#postmortem", RichLog)
                if page.has_class("-field"):  # the first reply takes the field's place
                    page.clear()
                    page.remove_class("-field")
                    self._field_key = None
                self._page_rows.append((text, style))
                page.write(_fitted(text, _inner(page), style))
                return
        tag = "tf" if self._escalated else f"c{self._cycle}" if self._cycle else "--"
        row = (tag, text, style)
        if self._replying is not None:
            self._pinned.add(len(self._timeline_rows))
        self._timeline_rows.append(row)
        if self._shown(len(self._timeline_rows) - 1):
            self.query_one("#timeline", RichLog).write(self._timeline_line(*row))

    def _shown(self, index: int) -> bool:
        """Whether timeline row `index` passes /grep. Command rows always do."""
        if self._grep is None or index in self._pinned:
            return True
        tag, text, _ = self._timeline_rows[index]
        return self._grep in f"{tag} {text}".lower()

    def _timeline_line(self, cycle: str, text: str | Text, style: str) -> Text:
        line = Text.assemble((f"{cycle} ", MUTED))
        line.append_text(_fitted(text, self._say_width(), style))
        return line


class CommandLine(Input):
    """The command line. Tab takes the grey completion; it never moves focus."""

    BINDINGS = [("tab", "complete", "complete the command")]

    def action_complete(self) -> None:
        self.cursor_position = len(self.value)
        self.action_cursor_right()


class Splash(Static, can_focus=True):
    """The launch and end splash. It holds focus, so any key leaves it, and only that."""

    def on_key(self, event: events.Key) -> None:
        event.stop()
        event.prevent_default()
        if self.app.moral_shown:  # type: ignore[attr-defined]
            self.app.exit()
            return
        self.app.end_splash()  # type: ignore[attr-defined]


def _fitted(text: str | Text, width: int, style: str = "") -> Text:
    """A log line cut to `width`: plain text styled, or styled text as it is."""
    if isinstance(text, Text):
        line = text.copy()
        line.truncate(width, overflow="ellipsis")
        return line
    return Text(fit(text, width), style=style)


def _echo(text: str | Text) -> bool:
    """Whether a log row is the echo of a typed command."""
    return str(text).startswith("you › ")


def _health_text(snapshot: dict[str, dict[str, Any]]) -> str:
    """One probe snapshot in a line: api ok 12ms, db slow 812ms, cache ok 2ms."""
    parts = []
    for layer, result in snapshot.items():
        latency = result["latency_ms"]
        value = f"{latency:.0f}ms" if latency is not None else "-"
        parts.append(f"{layer} {result['status']} {value}")
    return ", ".join(parts)


def _show(panel: Static, content: Text) -> None:
    """Put `content` in `panel`, repainting only what changed.

    A plain update lays the whole screen out again, which a terminal shows
    as a flicker. Unchanged text is skipped; text with the same rows is
    repainted in place.
    """
    old = panel.content
    if isinstance(old, Text) and old == content:
        return
    same_rows = isinstance(old, Text) and old.plain.count("\n") == content.plain.count("\n")
    panel.update(content, layout=not same_rows)


def _inner(widget: Widget) -> int:
    """Columns a line may use inside `widget`, never less than at 82 wide."""
    if isinstance(widget, RichLog):
        width = widget.scrollable_content_region.width - 1
    else:
        width = widget.content_region.width
    return max(width, LINE)


def sparkline(values: deque[float] | list[float]) -> str:
    """Recent CPU, oldest first. 100% (one full core) or the run's peak is the top."""
    if not values:
        return ""
    top = max(100.0, *values)
    return "".join(_SPARK[min(len(_SPARK) - 1, int(v / top * len(_SPARK)))] for v in values)


def _memory(size: int) -> str:
    """Bytes in four characters or so: 3.8M, 220M, 1.2G."""
    for unit, scale in (("G", 1024**3), ("M", 1024**2), ("K", 1024)):
        if size >= scale:
            value = size / scale
            return f"{value:.1f}{unit}" if value < 10 else f"{value:.0f}{unit}"
    return f"{size}B"


def _shown_path(path: Path) -> str:
    """A path relative to the repo when it is inside it, as the developer types it."""
    try:
        return path.resolve().relative_to(_REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


# Results shown per routing, strongest first; the rest are counted by label.
_ROUTING_RESULTS: Final = 4
_TITLE_MIN: Final = 15
_ROUTING_BASIS: Final = {
    "symptom": "routed by the symptom: no result named a layer",
    "seeded": "routed by the seeded draw: no result named a layer, no symptom yet",
}


def routing_lines(fields: dict[str, Any], width: int) -> list[tuple[str, str]]:
    """The routing moment: what Tavily returned, how Nano labelled it, and
    the summed scores that picked the specialist. Display only."""
    results = sorted(fields["results"], key=lambda r: -r["score"])
    routing, specialist = fields["routing"], fields["specialist"]
    lines: list[tuple[str, str]] = []
    if results:
        lines.append((f"{len(results)} results. Nano labels each one by layer:", ""))
        shown = results[:_ROUTING_RESULTS]
        component_w = max(len(r.get("component") or "") for r in shown)
        for result in shown:
            where = re.sub(r"^https?://(www\.)?", "", result["url"])
            text = (
                f"  {result['layer'] or '·':<5} {result['score']:.2f}  "
                f"{(result.get('component') or ''):<{component_w}}  {where}"
            )
            # A title only where enough of it fits to read; never a stub.
            if width - len(text) - 2 >= _TITLE_MIN:
                text += f"  {result['title']}"
            lines.append((fit(text, width), _SOFT))
        rest = results[_ROUTING_RESULTS:]
        if rest:
            counts = [
                f"{n} {layer.value}"
                for layer in Layer
                if (n := sum(r["layer"] == layer.value for r in rest))
            ]
            if unlabelled := sum(r["layer"] is None for r in rest):
                counts.append(f"{unlabelled} about no layer")
            lines.append((f"  … {len(rest)} more: {', '.join(counts)}", _SOFT))
    else:
        lines.append(("no results came back", _SOFT))
    lines.append(("score per layer, summed:", ""))
    weights = {layer.value: routing["weights"].get(layer.value, 0.0) for layer in Layer}
    top = max(weights.values()) or 1.0
    bar_w = max(10, min(40, width - 42))
    for layer, weight in weights.items():
        bar = "█" * round(bar_w * weight / top) if weight else ""
        won = layer == routing["layer"]
        text = f"  {layer:<6} {bar:<{bar_w}}  {weight:.2f}"
        if won:
            text += f"  ◀ {specialist} specialist"
        lines.append((text, ACCENT if won else _SOFT))
    closing = _ROUTING_BASIS.get(
        routing["basis"], f"routed by search: Tavily's results picked the {specialist} specialist"
    )
    lines.append((closing, f"bold {ACCENT}"))
    return lines


FIELD_WIDTH: Final = 78
FIELD_HEIGHT: Final = 14
# Below this the band crowds the labels and turns into a blob.
FIELD_MIN_HEIGHT: Final = 7
# The glow's swing: positions in percent along the band, past both ends so
# it fades out at each, about 3 s one way at 10 frames a second.
FIELD_FPS: Final = 10
GLOW_FROM: Final = -5
GLOW_TO: Final = 105
GLOW_FRAMES: Final = 30
# Where the glow rests once chosen: over the letter.
GLOW_REST: Final = {"a": 15, "b": 83}
# How far along the band the glow lights, in percent: crest, then edge.
_GLOW_CREST: Final = 3
_GLOW_EDGE: Final = 7


def glow_at(frame: int) -> float:
    """The glow's position at `frame`: A to B and back, easing at each end."""
    swing = frame % (2 * GLOW_FRAMES) / GLOW_FRAMES
    x = swing if swing <= 1 else 2 - swing
    return GLOW_FROM + (GLOW_TO - GLOW_FROM) * (1 - math.cos(math.pi * x)) / 2


@functools.cache
def postmortem_field(height: int = FIELD_HEIGHT, glow: int | None = None) -> tuple[Text, ...]:
    """The post-mortem field: a thin band rising from A to B, abstract, no
    figures. Each cell's shade is a gaussian of its distance from one line;
    only two shades, so it reads as a band and not a blob (27% ink). Drawn
    for 14 rows; a shorter log gets the same band, its line and width
    scaled to the rows it has. `glow`, in percent along the band, lights
    the cells near it in a lighter ink; the shades stay the same."""
    k = height / FIELD_HEIGHT
    (x1, y1), (x2, y2), sigma = (6.0, 10.5 * k), (72.0, 3.0 * k), max(0.6, 1.25 * k)
    dx, dy = x2 - x1, y2 - y1
    rows = []
    for row in range(height):
        cells = []
        for col in range(FIELD_WIDTH):
            t = ((col - x1) * dx + (row - y1) * dy) / (dx * dx + dy * dy)
            dist2 = (col - x1 - t * dx) ** 2 + (row - y1 - t * dy) ** 2
            density = math.exp(-dist2 / (2 * sigma * sigma))
            cells.append("▒" if density >= 0.72 else "░" if density >= 0.30 else " ")
        rows.append(cells)
    labels = {16: "A", 61: "B"}
    for col in labels:  # cleared first, or the band swallows the letter
        rows[-1][col - 2 : col + 3] = [" "] * 5
    lines = []
    for index, cells in enumerate(rows):
        line = Text()
        for col, cell in enumerate(cells):
            label = labels.get(col) if index == height - 1 else None
            if label:
                line.append(label, style=_SOFT)
                continue
            ink = _FIELD_INK
            if glow is not None:
                t = ((col - x1) * dx + (index - y1) * dy) / (dx * dx + dy * dy)
                away = abs(t * 100 - glow)
                ink = (
                    _FIELD_GLOW
                    if away <= _GLOW_CREST
                    else _FIELD_GLOW_EDGE
                    if away <= _GLOW_EDGE
                    else ink
                )
            line.append(cell, style=ink)
        lines.append(line)
    return tuple(lines)


def option_cards(
    options: list[dict[str, Any]], width: int, *, waiting: bool = False, chosen: str | None = None
) -> list[Text]:
    """A and B as two cards side by side, their rows aligned so gain sits
    beside gain and cost beside cost. While the choice waits both look the
    same; once made, the chosen card is marked and the other dims."""
    card_w = (width - 1) // 2
    text_w = card_w - _CARD_FRAME - _CARD_LABEL
    rows = ("title", "gain", "pay", "felt", "live")

    def cells(item: dict[str, Any]) -> dict[str, list[str]]:
        return {
            "title": textwrap.wrap(item["title"], card_w - _CARD_FRAME) or [""],
            "gain": textwrap.wrap(item["gain"], text_w) or [""],
            "pay": textwrap.wrap(item["cost"], text_w) or [""],
            "felt": textwrap.wrap(item["felt_when"], text_w) or [""],
            "live": textwrap.wrap(item["consequence"]["id"], text_w) or [""],
        }

    wrapped = [cells(item) for item in options]
    heights = {row: max(len(c[row]) for c in wrapped) for row in rows}
    colours = {"gain": GO, "pay": DAMAGE, "felt": DAMAGE, "live": _SOFT}

    def card(item: dict[str, Any], cell: dict[str, list[str]], w: int) -> list[Text]:
        # Both cards wrap at the same width, so their rows align; a card
        # given an odd spare column pads to it.
        spare = w - card_w
        key = item["key"]
        mine = chosen is not None and key == chosen
        dim = chosen is not None and not mine
        edge = GO if mine else MUTED if dim else ACCENT
        top = f"┌─ {key.upper()} "
        out = [Text(top + "─" * (w - len(top) - 1) + "┐", style=f"bold {edge}")]
        for row in rows:
            for i in range(heights[row]):
                text = cell[row][i] if i < len(cell[row]) else ""
                line = Text("│ ", style=edge)
                if row == "title":
                    line.append(f"{text:<{w - _CARD_FRAME}}", style=_SOFT if dim else "bold")
                else:
                    line.append(f"{row if i == 0 else '':<{_CARD_LABEL}}", style=_SOFT)
                    line.append(f"{text:<{text_w + spare}}", style=_SOFT if dim else colours[row])
                line.append(" │", style=edge)
                out.append(line)
        foot = (
            "◀ you chose this"
            if mine
            else "not chosen"
            if dim
            else f"press {key.upper()}"
            if waiting
            else ""
        )
        tail = f"─ {foot} " if foot else ""
        out.append(Text("└" + tail + "─" * (w - len(tail) - 2) + "┘", style=edge))
        return out

    first, second = options
    left = card(first, wrapped[0], card_w)
    right = card(second, wrapped[1], width - 1 - card_w)
    return [Text.assemble(a, " ", b) for a, b in zip(left, right, strict=True)]


def _cost_text(layer: str, readings: tuple[dict[str, Any] | None, ...]) -> str:
    """`cache 15ms → 2513ms → 15ms`: the layer the cost hit, before, under
    the cost and after, from whichever readings exist."""
    shown = []
    for event in readings:
        reading = (event or {}).get("snapshot", {}).get(layer)
        if reading is not None:
            latency = reading.get("latency_ms")
            shown.append(f"{latency:.0f}ms" if latency is not None else reading["status"])
    return f"{layer} " + " → ".join(shown)


def _check_text(check: dict[str, Any]) -> str:
    """`hung 6000ms → answered in 180ms · patch held`, from a patch check."""
    before, after = AppResult.from_dict(check["before"]), AppResult.from_dict(check["after"])
    verdict = "patch held" if check["held"] else "patch did not hold"
    return f"{before.text()} → {after.text()} · {verdict}"


def _voice_style(quoted: bool) -> str:
    return f"bold italic {GO}" if quoted else f"italic {ACCENT}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bedlam.tui", description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=None, help="root seed (default: BEDLAM_SEED)")
    parser.add_argument(
        "--scripted",
        action="store_true",
        help="apply the prepared diffs instead of reading your own edits",
    )
    parser.add_argument("--patches", type=Path, default=DEFAULT_PATCH_DIR)
    parser.add_argument("--trace", type=Path, default=None, help="trace output path")
    args = parser.parse_args(argv)

    patches: PatchSource
    if args.scripted:
        # Applied to the target as each round asks, reverted when the TUI exits.
        patches = scripted = ScriptedPatchSource(args.patches, target=DEFAULT_TARGET)
    else:
        scripted = None
        try:
            patches = GitPatchSource()
        except (ValueError, OSError, subprocess.CalledProcessError) as exc:
            parser.error(f"real patch mode needs the target as a git checkout: {exc}")

    load_dotenv(_REPO_ROOT / ".env")
    root_seed = args.seed if args.seed is not None else seeding.root_seed()
    os.environ[seeding.ROOT_SEED_ENV] = str(root_seed)
    trace_path = args.trace or _REPO_ROOT / "traces" / f"tui-seed{root_seed}.json"
    # The TUI owns the terminal: JSON logs go next to the trace instead.
    redirect(trace_path.with_suffix(".log"))

    def launch(app: BedlamApp) -> Awaitable[int]:
        return execute(
            root_seed,
            app.patches,
            trace_path,
            on_event=app.on_loop_event,
            on_clients=app.attach,
            choices=app.choices,
        )

    app = BedlamApp(
        root_seed, patches, launch, real=not args.scripted, stats=sample_stats, splash_s=SPLASH_S
    )
    app.decision_file = decision_path(trace_path)
    app.trace_file = trace_path
    with scripted or contextlib.nullcontext():
        if scripted is not None:
            scripted.settle()
            scripted.revert_on_console_close()
        app.run()
    return app.exit_code if app.exit_code is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
