"""The Bedlam terminal UI. Fills the terminal; fully readable at 82 columns.

The loop runs inside the app as a worker and reports each step through its
event hook. The TUI only observes: nothing on screen feeds a decision, and
the developer's one input to the loop is saying the patch is in.

Top to bottom: header (round, step, seed); NOW, a plain-language guide to
what is happening, where to look and whether to act (`bedlam/guide.py`);
BEDLAM SAYS (the latest voice line, held still); YOUR APP (per-layer health
and the live fault); WHAT BEDLAM DID (each step in order, with Bedlam's
voice); AI MODELS (every model call with the model that answered it, and
every Tavily call); the key legend. From `_WIDE` columns up, WHAT BEDLAM DID
and AI MODELS sit side by side.

Run: python -m bedlam.tui
"""

from __future__ import annotations

import argparse
import asyncio
import math
import os
import textwrap
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Final

from dotenv import load_dotenv
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.css.query import NoMatches
from textual.widget import Widget
from textual.widgets import RichLog, Static

from bedlam import seed as seeding
from bedlam.guide import (
    APP,
    EARLY_PRESS,
    LOG,
    MODELS,
    PRESSED,
    STARTING,
    STEPS,
    STOPPED,
    Guidance,
    guidance,
)
from bedlam.logging import get_logger, log_event, redirect
from bedlam.loop import MAX_CYCLES, execute
from bedlam.models.client import CallRecord, ModelClient
from bedlam.models.map import LABELS
from bedlam.patches import DEFAULT_PATCH_DIR, Patch, PatchSource, ScriptedPatchSource
from bedlam.probes.result import DEFAULT_TIMEOUT_S
from bedlam.search.tavily import SearchCall, SearchClient
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
_BAR_MAX: Final = 60
_BAR_CEILING_MS: Final = 2000.0
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
    """Holds the scripted patch back until the developer says it is in."""

    def __init__(self, inner: PatchSource) -> None:
        self._inner = inner
        self._released = asyncio.Event()
        self.waiting = False

    async def wait_for_patch(self, cycle: int) -> Patch:
        self.waiting = True
        try:
            await self._released.wait()
        finally:
            self.waiting = False
            self._released.clear()
        return await self._inner.wait_for_patch(cycle)

    def release(self) -> bool:
        if not self.waiting:
            return False
        self._released.set()
        return True


Launch = Callable[["BedlamApp"], Awaitable[int]]


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
    #footer {{ height: 1; }}
    """
    BINDINGS = [("p", "patch", "apply the prepared fix"), ("q", "quit", "quit")]

    def __init__(self, root_seed: int, patches: PatchSource, launch: Launch) -> None:
        super().__init__()
        self.root_seed = root_seed
        self.patches = GatedPatchSource(patches)
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
        self.exit_code: int | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="frame"):
            yield Static(id="header")
            now = Static(id="now")
            now.border_title = "NOW"
            yield now
            yield Static(id="says")
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
            yield Static(id="footer")

    def on_mount(self) -> None:
        self._render_chrome()
        self.set_interval(0.05, self._tick)
        self.run_worker(self._run(), exclusive=True)

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

    def action_patch(self) -> None:
        self.now = PRESSED if self.patches.release() else self.now.nudged(EARLY_PRESS)
        self._render_chrome()

    # -- loop events ----------------------------------------------------------

    def on_loop_event(self, kind: str, fields: dict[str, Any]) -> None:
        # Drain first: calls made since the last event belong to the cycle
        # in effect before this one, and a cycle can outrun the poll timer.
        self._drain_calls()
        if kind == "cycle_started":
            self._cycle = fields["cycle"]
        self.now = guidance(kind, fields) or self.now
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
        self._say("waiting for your fix. press p to apply the prepared one", style=f"bold {GO}")

    def _on_patched(self, fields: dict[str, Any]) -> None:
        patch = fields["patch"]
        self._say(f"patch in: {patch['source']} ({patch['chars']} chars)")

    def _on_fault_removed(self, fields: dict[str, Any]) -> None:
        self._probing_since = None
        self._health = fields["snapshot"]
        self._fault, self._blast = None, []
        self._say("fault removed: " + self._health_line(), style=GO)

    def _on_analysed(self, fields: dict[str, Any]) -> None:
        analysis = fields["analysis"]
        defended = ", ".join(f"{d['layer']}/{d['kind']}" for d in analysis["defended"]) or "none"
        self._say(f"patch defends: {defended}")
        if analysis["gaps"]:
            gaps = "gaps: " + "; ".join(analysis["gaps"])
            for line in wrap(gaps, indent=6, width=self._say_width()):
                self._say(line, style=_SOFT)

    def _on_escalation_pending(self, fields: dict[str, Any]) -> None:
        self._say("two cycles done. the trade-off escalation is next", style=f"bold {ACCENT}")

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
        keys.append(" P ", style=lit if now.your_turn else f"{_TEXT} on {MUTED}")
        keys.append(" apply the prepared fix    ", style=f"bold {GO}" if now.your_turn else _SOFT)
        keys.append(" Q ", style=f"{_TEXT} on {MUTED}")
        keys.append(" quit", style=_SOFT)
        self.query_one("#footer", Static).update(keys)

        self._render_system()

    def _render_system(self) -> None:
        panel = self.query_one("#system", Static)
        width = _inner(panel)
        size = max(_BAR_MIN, min(_BAR_MAX, width - (LINE - _BAR_MIN)))
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
            if result.get("error") and width - used > 4:
                system.append(fit(f"  {result['error']}", width - used), style=_SOFT)
            system.append("\n")
        fault = f"{self._fault} live, blast {', '.join(self._blast)}" if self._fault else "none"
        style = f"bold {DAMAGE}" if self._fault else MUTED
        system.append(fit(f"fault  {fault}", width), style=style)
        panel.update(system)

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
        row = (f"c{self._cycle}" if self._cycle else "--", text, style)
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


def _voice_style(quoted: bool) -> str:
    return f"bold italic {GO}" if quoted else f"italic {ACCENT}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bedlam.tui", description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=None, help="root seed (default: BEDLAM_SEED)")
    parser.add_argument("--patches", type=Path, default=DEFAULT_PATCH_DIR)
    parser.add_argument("--trace", type=Path, default=None, help="trace output path")
    args = parser.parse_args(argv)

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
        )

    app = BedlamApp(root_seed, ScriptedPatchSource(args.patches), launch)
    app.run()
    return app.exit_code if app.exit_code is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
