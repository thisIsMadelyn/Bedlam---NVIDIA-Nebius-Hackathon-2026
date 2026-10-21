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
import math
import os
import subprocess
import textwrap
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from dotenv import load_dotenv
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.css.query import NoMatches
from textual.widget import Widget
from textual.widgets import Input, RichLog, Static

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
    GitPatchSource,
    Patch,
    PatchSource,
    ScriptedPatchSource,
)
from bedlam.probes.result import DEFAULT_TIMEOUT_S
from bedlam.search.tavily import SearchCall, SearchClient
from bedlam.stats import ContainerStats, StatsUnavailable
from bedlam.stats import sample as sample_stats
from bedlam.topology import Layer
from bedlam.voice import Voice

# The minimum width. Every template is checked to fit at this size.
WIDTH: Final = 82
# Border (2) + horizontal padding (2) + scrollbar (1), with one column spare.
LINE: Final = WIDTH - 6
# A timeline line after its "c1 " cycle prefix, at the minimum width.
SAY: Final = LINE - 3
# Side by side only when each half is still at least the minimum width.
_WIDE: Final = 2 * WIDTH + 2

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
# "    you gain  ": the hanging indent of a trade-off option's gain and cost.
_SIDE_INDENT: Final = 14
_BAR_CEILING_MS: Final = 2000.0
# The run-so-far chart under the trade-off: "cache " before each row, at
# most eight rows per container, and a blank line, a title and the fault
# labels above the rows. Drawn only in height the options leave spare.
_CHART_LABEL: Final = 6
_CHART_MAX_ROWS: Final = 8
_CHART_FRAME: Final = 3
# CPU samples kept for the whole run: hours of sampling, far past a demo.
_RUN_SAMPLES: Final = 4000
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
    """A log-scaled bar: 1 ms is empty, 2 s and over is full."""
    if latency_ms is None:
        return "·" * size
    scale = math.log10(max(latency_ms, 1.0)) / math.log10(_BAR_CEILING_MS)
    filled = max(1, min(size, round(scale * size)))
    return "█" * filled + "░" * (size - filled)


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

    async def wait_for_patch(self, cycle: int) -> Patch:
        while True:
            self.waiting = True
            try:
                await self._released.wait()
            finally:
                self.waiting = False
                self._released.clear()
            patch = await self._inner.wait_for_patch(cycle)
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


@dataclass(slots=True)
class FaultWindow:
    """The CPU samples taken while one fault was live: [start, end)."""

    start: int
    end: int | None
    label: str


Launch = Callable[["BedlamApp"], Awaitable[int]]

StatsSource = Callable[[], Awaitable[dict[Layer, ContainerStats]]]

# The command line's commands: name -> what /help says. Each one is a
# `_command_<name>` method on the app. None may decide the trade-off for the
# developer: a command that picks a side is a bug (CLAUDE.md).
COMMANDS: Final = {
    "help": "list these commands",
    "patch": "hand over your fix, same as P",
    "choose": "your side of the trade-off: /choose a or /choose b",
    "quit": "leave Bedlam, same as Q",
}


class BedlamApp(App[int]):
    HORIZONTAL_BREAKPOINTS = [(0, "-narrow"), (_WIDE, "-wide")]
    CSS = f"""
    Screen {{ background: {_BACKGROUND}; color: {_TEXT}; }}
    #frame {{ width: 100%; min-width: {WIDTH}; height: 100%; }}
    #header {{ height: 1; background: {INK}; color: {_TEXT}; }}
    #now {{
        height: 5; border: round {ACCENT}; padding: 0 1; background: {_SURFACE};
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
    #tradeoff {{ display: none; height: 1fr; border: heavy {GO}; }}
    #frame.-escalation #tradeoff {{ display: block; }}
    #frame.-escalation #system, #frame.-escalation #body {{ display: none; }}
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

    def __init__(
        self,
        root_seed: int,
        patches: PatchSource,
        launch: Launch,
        *,
        real: bool = False,
        stats: StatsSource | None = None,
    ) -> None:
        super().__init__()
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
        self.now: Guidance = STARTING
        self._said: tuple[str, bool] | None = None
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
        self._run_cpu: list[dict[Layer, float]] = []
        self._windows: list[FaultWindow] = []
        self.choices = GatedChoice()
        self.choices.on_ask = self._render_chrome
        self._trade_off: dict[str, Any] | None = None
        self._escalated = False
        # Where the run's decision record is written, said once it exists.
        self.decision_file: Path | None = None
        self.exit_code: int | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="frame"):
            yield Static(id="header")
            now = Static(id="now")
            now.border_title = "NOW"
            yield now
            yield Static(id="says")
            tradeoff = Static(id="tradeoff", classes="panel")
            tradeoff.border_title = "TRADE-OFF · you choose, Bedlam does not"
            yield tradeoff
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
            yield Input(
                id="command",
                placeholder="press / to type a command, /help lists them",
                select_on_focus=False,
            )
            yield Static(id="footer")

    def on_mount(self) -> None:
        self._render_chrome()
        self.set_interval(0.05, self._tick)
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
        self._render_chrome()

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
        self.query_one("#timeline", RichLog).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        self.action_leave_command()
        if not text:
            return
        name, *rest = text.lstrip("/").split(maxsplit=1) or [""]
        self._say(f"you › {text}", style=f"bold {_TEXT}")
        command = COMMANDS.get(name.lower())
        if command is None:
            self._say(f"unknown command /{name}. /help lists them", style=_SOFT)
            return
        getattr(self, f"_command_{name.lower()}")(rest[0].strip() if rest else "")

    def _command_help(self, arg: str) -> None:
        for name, about in COMMANDS.items():
            self._say(f"  /{name:<8} {about}", style=_SOFT)

    def _command_patch(self, arg: str) -> None:
        self.action_patch()

    def _command_choose(self, arg: str) -> None:
        key = arg.lower()
        if key not in KEYS:
            self._say("choose a or b, e.g. /choose a", style=_SOFT)
            return
        self.action_choose(key)

    def _command_quit(self, arg: str) -> None:
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
        self.now = guidance(kind, fields, real=self.real) or self.now
        handler = getattr(self, f"_on_{kind}", None)
        if handler is not None:
            handler(fields)
        line = self._voice.say(kind, fields)
        if line:
            quoted = self._voice.quoted
            for part in wrap("» " + line, indent=2, width=self._say_width()):
                self._say(part, style=_voice_style(quoted))
            # The timeline scrolls; BEDLAM SAYS holds the line until the next.
            self._said = (line, quoted)
            log_event(_LOG, "voice", kind=kind, cycle=self._cycle, line=line, quote=quoted)
        self._render_chrome()

    def _on_probing(self, fields: dict[str, Any]) -> None:
        self._probing_since = time.monotonic()

    def _on_baseline(self, fields: dict[str, Any]) -> None:
        self._probing_since = None
        self._health = fields["snapshot"]
        self._say("baseline: " + self._health_line(), style=GO)

    def _on_cycle_started(self, fields: dict[str, Any]) -> None:
        rule = f"── cycle {fields['cycle']} of {MAX_CYCLES} "
        self._say(rule + "─" * (self._say_width() - len(rule)), style=f"bold {ACCENT}")

    def _on_searching(self, fields: dict[str, Any]) -> None:
        for query in fields["queries"]:
            self._say(f"tavily  {query['text']}", style=ACCENT)

    def _on_routed(self, fields: dict[str, Any]) -> None:
        routing = fields["routing"]
        weights = " · ".join(f"{k} {v:.2f}" for k, v in routing["weights"].items())
        self._say(f"routed to {fields['specialist']} ({routing['basis']}: {weights})")

    def _on_selected(self, fields: dict[str, Any]) -> None:
        selection = fields["selection"]
        self._say(f"picked {selection['fault']['id']} from {len(selection['eligible'])} eligible")
        if selection.get("rationale"):
            for line in wrap("why: " + selection["rationale"], indent=5, width=self._say_width()):
                self._say(line, style=_SOFT)

    def _on_injecting(self, fields: dict[str, Any]) -> None:
        self._fault, self._blast = fields["fault"], fields["blast_radius"]
        self._windows.append(FaultWindow(len(self._run_cpu), None, f"R{self._cycle} {self._fault}"))
        blast = ", ".join(self._blast)
        self._say(f"injecting {self._fault}, blast radius {blast}", style=f"bold {DAMAGE}")

    def _on_probed(self, fields: dict[str, Any]) -> None:
        self._probing_since = None
        self._health = fields["snapshot"]
        self._say("under fault: " + self._health_line(), style=DAMAGE)

    def _on_symptom(self, fields: dict[str, Any]) -> None:
        symptom = fields["symptom"]
        where = f" on {symptom['layer']}" if symptom["layer"] else ""
        text = f"symptom: {symptom['kind']}{where}. {symptom['summary']}"
        for line in wrap(text, indent=9, width=self._say_width()):
            self._say(line, style=DAMAGE)

    def _on_awaiting_patch(self, fields: dict[str, Any]) -> None:
        if self.real:
            text = f"waiting for your fix in {TARGET}. press p when it is saved"
        else:
            text = "waiting for your fix. press p to apply the prepared one"
        self._say(text, style=f"bold {GO}")

    def _on_patched(self, fields: dict[str, Any]) -> None:
        patch = fields["patch"]
        self._say(f"patch in: {patch['source']} ({patch['chars']} chars)")

    def _on_fault_removed(self, fields: dict[str, Any]) -> None:
        self._probing_since = None
        self._health = fields["snapshot"]
        self._fault, self._blast = None, []
        if self._windows and self._windows[-1].end is None:
            self._windows[-1].end = len(self._run_cpu)
        self._say("fault removed: " + self._health_line(), style=GO)

    def _on_analysed(self, fields: dict[str, Any]) -> None:
        analysis = fields["analysis"]
        defended = ", ".join(f"{d['layer']}/{d['kind']}" for d in analysis["defended"]) or "none"
        self._say(f"patch defends: {defended}")
        if analysis["gaps"]:
            gaps = "gaps: " + "; ".join(analysis["gaps"])
            for line in wrap(gaps, indent=6, width=self._say_width()):
                self._say(line, style=_SOFT)

    def _on_escalating(self, fields: dict[str, Any]) -> None:
        self._escalated = True
        rule = "── trade-off "
        self._say(rule + "─" * (self._say_width() - len(rule)), style=f"bold {ACCENT}")

    def _on_trade_off(self, fields: dict[str, Any]) -> None:
        self._trade_off = fields["trade_off"]
        self._say(f"trade-off: {self._trade_off['axis']}", style=f"bold {ACCENT}")
        for item in self._trade_off["options"]:
            self._say(f"  {item['key'].upper()}  {item['title']}")
        self.query_one("#frame").add_class("-escalation")

    def _on_chosen(self, fields: dict[str, Any]) -> None:
        self.query_one("#frame").remove_class("-escalation")
        text = f"you chose {fields['choice'].upper()}: {fields['option']['title']}"
        self._say(text, style=f"bold {GO}")

    def _on_showing_cost(self, fields: dict[str, Any]) -> None:
        self._fault, self._blast = fields["fault"], fields["blast_radius"]
        blast = ", ".join(self._blast)
        self._say(f"showing the cost: {self._fault}, blast radius {blast}", style=f"bold {DAMAGE}")

    def _on_cost_shown(self, fields: dict[str, Any]) -> None:
        self._probing_since = None
        self._health = fields["snapshot"]
        self._say("under the cost: " + self._health_line(), style=DAMAGE)

    def _on_cost_removed(self, fields: dict[str, Any]) -> None:
        self._probing_since = None
        self._health = fields["snapshot"]
        self._fault, self._blast = None, []
        self._say("cost removed: " + self._health_line(), style=GO)

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
        widths = (_inner(timeline), _inner(agent))
        if widths == self._flowed:
            return
        self._flowed = widths
        timeline.clear()
        for row in self._timeline_rows:
            timeline.write(self._timeline_line(*row))
        agent.clear()
        for row in self._agent_rows:
            agent.write(self._agent_line(*row, width=widths[1]))

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
        self.query_one("#header", Static).update(header)

        box = self.query_one("#now", Static)
        box.set_class(now.your_turn, "your-turn")
        body = Text()
        for i, line in enumerate(now.lines):
            last = i == len(now.lines) - 1
            style = "bold" if i == 0 else f"bold {GO}" if last and now.your_turn else _SOFT
            body.append(fit(line, _inner(box)) + ("" if last else "\n"), style=style)
        box.update(body)

        says = Text.assemble((_SAYS, f"bold {_BACKGROUND} on {ACCENT}"))
        if self._said is not None:
            line, quoted = self._said
            says.append(" " + fit(line, full - 3 - len(_SAYS)), style=_voice_style(quoted))
        self.query_one("#says", Static).update(says)

        keys = Text(" ")
        lit = f"bold {_BACKGROUND} on {GO}"
        if self.choices.waiting:
            for key in KEYS:
                keys.append(f" {key.upper()} ", style=lit)
                keys.append(f" option {key.upper()}    ", style=f"bold {GO}")
        else:
            keys.append(" P ", style=lit if now.your_turn else f"{_TEXT} on {MUTED}")
            action = " read my fix    " if self.real else " apply the prepared fix    "
            keys.append(action, style=f"bold {GO}" if now.your_turn else _SOFT)
        keys.append(" Q ", style=f"{_TEXT} on {MUTED}")
        keys.append(" quit    ", style=_SOFT)
        keys.append(" / ", style=f"{_TEXT} on {MUTED}")
        keys.append(" command", style=_SOFT)
        self.query_one("#footer", Static).update(keys)

        self._render_system()
        if self._trade_off is not None:
            self._render_trade_off()

    def _render_trade_off(self) -> None:
        """Both options with equal weight: same layout, same colours, A then B."""
        assert self._trade_off is not None
        panel = self.query_one("#tradeoff", Static)
        width = _inner(panel)
        trade_off = self._trade_off
        body = Text()
        body.append(fit(trade_off["axis"], width) + "\n", style=f"bold {ACCENT}")
        for line in textwrap.wrap(trade_off["why"], width=width):
            body.append(line + "\n", style=_SOFT)
        badge = f"bold {_BACKGROUND} on {GO}" if self.choices.waiting else f"{_TEXT} on {MUTED}"
        for item in trade_off["options"]:
            body.append("\n")
            body.append(f" {item['key'].upper()} ", style=badge)
            body.append(" " + fit(item["title"], width - 4) + "\n", style="bold")
            for label, text in (("you gain", item["gain"]), ("you pay", item["cost"])):
                lines = textwrap.wrap(text, width=width - _SIDE_INDENT) or [""]
                for i, line in enumerate(lines):
                    head = f"    {label:<9} " if i == 0 else " " * _SIDE_INDENT
                    body.append(head, style=_SOFT)
                    body.append(line + "\n", style=GO if label == "you gain" else DAMAGE)
            # When the cost is felt and the fault that shows it: one line, so
            # the longest trade-off still fits at 82 x 30. At most 74 columns.
            body.append(f"    {'felt when':<9} ", style=_SOFT)
            body.append(item["felt_when"], style=DAMAGE)
            live = f" · shown live as {item['consequence']['id']}"
            body.append(
                fit(live, width - _SIDE_INDENT - len(item["felt_when"])) + "\n", style=_SOFT
            )
        # The run so far, in whatever height the options leave. Real samples
        # only: without any, there is no chart.
        spare = panel.content_region.height - body.plain.count("\n")
        if self._run_cpu and spare >= _CHART_FRAME + len(Layer):
            rows = min(_CHART_MAX_ROWS, (spare - _CHART_FRAME) // len(Layer))
            body.append("\n")
            for line in cpu_chart(self._run_cpu, self._windows, width, rows):
                body.append_text(line)
                body.append("\n")
        panel.update(body)

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
            hit = layer.value in self._blast
            system.append(latency_bar(latency, size), style=DAMAGE if hit else GO)
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
        panel.update(system)
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
        """Keep one CPU sample: for the sparklines and the run-so-far chart."""
        for layer, stats in load.items():
            self._cpu[layer].append(stats.cpu_percent)
        if len(self._run_cpu) < _RUN_SAMPLES:
            self._run_cpu.append({layer: stats.cpu_percent for layer, stats in load.items()})

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
        parts = []
        for layer, result in self._health.items():
            latency = result["latency_ms"]
            value = f"{latency:.0f}ms" if latency is not None else "-"
            parts.append(f"{layer} {result['status']} {value}")
        return ", ".join(parts)

    def _say_width(self) -> int:
        return _inner(self.query_one("#timeline", RichLog)) - 3

    def _say(self, text: str, style: str = "") -> None:
        tag = "tf" if self._escalated else f"c{self._cycle}" if self._cycle else "--"
        row = (tag, text, style)
        self._timeline_rows.append(row)
        self.query_one("#timeline", RichLog).write(self._timeline_line(*row))

    def _timeline_line(self, cycle: str, text: str, style: str) -> Text:
        line = Text.assemble((f"{cycle} ", MUTED))
        line.append(fit(text, self._say_width()), style=style)
        return line


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


def cpu_chart(
    samples: list[dict[Layer, float]], windows: list[FaultWindow], width: int, rows: int
) -> list[Text]:
    """CPU per container over the whole run, fault windows marked, in `width` columns.

    The samples stretch or squeeze to fill the columns; a column covering
    several samples shows their peak, so a spike is never averaged away.
    One scale for all containers: 100% (one full core) or the run's peak.
    """
    cols = width - _CHART_LABEL
    n = len(samples)
    spans = [range(c * n // cols, max(c * n // cols + 1, (c + 1) * n // cols)) for c in range(cols)]
    top = max(100.0, *(v for sample in samples for v in sample.values()))

    def window_of(column: int) -> int | None:
        first = spans[column].start
        for i, window in enumerate(windows):
            end = window.end if window.end is not None else n
            if window.start <= first < end:
                return i
        return None

    owner = [window_of(c) for c in range(cols)]
    title = "THE RUN SO FAR · cpu per container, docker stats, 100% = one core"
    lines = [Text(f"{fit(title, width):<{width}}", style=_SOFT)]
    labels = Text(" " * _CHART_LABEL)
    c = 0
    while c < cols:
        if owner[c] is None:
            labels.append(" ")
            c += 1
            continue
        span = 1
        while c + span < cols and owner[c + span] == owner[c]:
            span += 1
        labels.append(f"{windows[owner[c]].label[:span]:<{span}}", style=f"bold {DAMAGE}")
        c += span
    lines.append(labels)
    for layer in Layer:
        # Eighths of a cell: an idle container still shows its baseline.
        levels = [
            max(1, round(max(samples[i].get(layer, 0.0) for i in span) / top * rows * 8))
            for span in spans
        ]
        for row in range(rows):
            floor = (rows - 1 - row) * 8
            line = Text(f"{layer.value:<{_CHART_LABEL}}" if row == rows - 1 else " " * _CHART_LABEL)
            line.stylize(_SOFT)
            for column, level in enumerate(levels):
                fill = min(8, level - floor)
                cell = _SPARK[fill - 1] if fill > 0 else " "
                line.append(cell, style=f"dim {DAMAGE}" if owner[column] is not None else MUTED)
            lines.append(line)
    return lines


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
        patches = ScriptedPatchSource(args.patches)
    else:
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

    app = BedlamApp(root_seed, patches, launch, real=not args.scripted, stats=sample_stats)
    app.decision_file = decision_path(trace_path)
    app.run()
    return app.exit_code if app.exit_code is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
