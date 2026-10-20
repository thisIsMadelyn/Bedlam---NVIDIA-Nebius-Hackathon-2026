"""The Bedlam terminal UI. 82 columns, never wider.

The loop runs inside the app as a worker and reports each step through its
event hook. The TUI only observes: nothing on screen feeds a decision, and
the developer's one input to the loop is saying the patch is in.

Top to bottom: header (round, step, seed); NOW, a plain-language guide to
what is happening, where to look and whether to act (`bedlam/guide.py`);
YOUR APP (per-layer health and the live fault); WHAT BEDLAM DID (each step
in order, with Bedlam's voice); AI MODELS (every model call with the model
that answered it, and every Tavily call); the key legend.

Run: python -m bedlam.tui
"""

from __future__ import annotations

import argparse
import asyncio
import math
import os
import textwrap
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Final

from dotenv import load_dotenv
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Vertical
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
from bedlam.logging import redirect
from bedlam.loop import MAX_CYCLES, execute
from bedlam.models.client import ModelClient
from bedlam.models.map import LABELS
from bedlam.patches import DEFAULT_PATCH_DIR, Patch, PatchSource, ScriptedPatchSource
from bedlam.search.tavily import SearchClient
from bedlam.topology import Layer
from bedlam.voice import Voice

WIDTH: Final = 82
# Border (2) + horizontal padding (2) + scrollbar (1), with one column spare.
LINE: Final = WIDTH - 6
_BAR: Final = 20
_BAR_CEILING_MS: Final = 2000.0
_REPO_ROOT: Final = Path(__file__).resolve().parents[1]


def fit(text: str, width: int = LINE) -> str:
    """One line, cut to `width` with an ellipsis. Nothing on screen wraps."""
    return text if len(text) <= width else text[: width - 1] + "…"


# A timeline line after its "c1 " cycle prefix.
SAY: Final = LINE - 3


def wrap(text: str, indent: int, width: int = SAY) -> list[str]:
    """Hanging-indent wrap for prose the loop produced (rationales, summaries)."""
    lines = textwrap.wrap(" ".join(text.split()), width=width, subsequent_indent=" " * indent)
    return lines or [""]


def latency_bar(latency_ms: float | None) -> str:
    """A log-scaled bar: 1 ms is empty, 2 s and over is full."""
    if latency_ms is None:
        return "·" * _BAR
    scale = math.log10(max(latency_ms, 1.0)) / math.log10(_BAR_CEILING_MS)
    filled = max(1, min(_BAR, round(scale * _BAR)))
    return "█" * filled + "░" * (_BAR - filled)


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
    CSS = f"""
    Screen {{ align: center top; }}
    #frame {{ width: {WIDTH}; height: 100%; }}
    #header {{ height: 1; background: $error; color: $text; text-style: bold; }}
    #now {{ height: 5; border: round $accent; padding: 0 1; }}
    #now.your-turn {{ border: heavy $warning; background: $warning 20%; }}
    .panel {{ border: round $panel-lighten-2; padding: 0 1; }}
    #system {{ height: 6; }}
    #timeline {{ height: 1fr; min-height: 6; }}
    #agent {{ height: 9; }}
    RichLog {{ scrollbar-size-vertical: 1; }}
    #footer {{ height: 1; color: $text-muted; }}
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
        self._blast: list[str] = []
        self._fault: str | None = None
        self._health: dict[str, dict[str, Any]] = {}
        self.exit_code: int | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="frame"):
            yield Static(id="header")
            now = Static(id="now")
            now.border_title = "NOW"
            yield now
            system = Static(id="system", classes="panel")
            system.border_title = f"{APP} · health of each part"
            yield system
            timeline = RichLog(id="timeline", classes="panel", wrap=False)
            timeline.border_title = f"{LOG} · newest at the bottom"
            yield timeline
            agent = RichLog(id="agent", classes="panel", wrap=False)
            agent.border_title = f"{MODELS} · which model did each step"
            yield agent
            yield Static(id="footer")

    def on_mount(self) -> None:
        self._render_chrome()
        self.set_interval(0.2, self._drain_calls)
        self.run_worker(self._run(), exclusive=True)

    async def _run(self) -> None:
        try:
            self.exit_code = await self._launch(self)
        except Exception as exc:
            self.exit_code = 1
            self._say(f"run failed: {type(exc).__name__}: {exc}", style="bold red")
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
            for part in wrap("» " + line, indent=2):
                self._say(part, style="italic magenta")
        self._render_chrome()

    def _on_baseline(self, fields: dict[str, Any]) -> None:
        self._health = fields["snapshot"]
        self._say("baseline: " + self._health_line(), style="green")

    def _on_cycle_started(self, fields: dict[str, Any]) -> None:
        self._say(f"── cycle {fields['cycle']} of {MAX_CYCLES} " + "─" * 40, style="bold")

    def _on_searching(self, fields: dict[str, Any]) -> None:
        for query in fields["queries"]:
            self._say(f"tavily  {query['text']}", style="cyan")

    def _on_routed(self, fields: dict[str, Any]) -> None:
        routing = fields["routing"]
        weights = " · ".join(f"{k} {v:.2f}" for k, v in routing["weights"].items())
        self._say(f"routed to {fields['specialist']} ({routing['basis']}: {weights})")

    def _on_selected(self, fields: dict[str, Any]) -> None:
        selection = fields["selection"]
        self._say(f"picked {selection['fault']['id']} from {len(selection['eligible'])} eligible")
        if selection.get("rationale"):
            for line in wrap("why: " + selection["rationale"], indent=5):
                self._say(line, style="dim")

    def _on_injecting(self, fields: dict[str, Any]) -> None:
        self._fault, self._blast = fields["fault"], fields["blast_radius"]
        self._say(f"injecting {self._fault}, blast radius {', '.join(self._blast)}", "bold red")

    def _on_probed(self, fields: dict[str, Any]) -> None:
        self._health = fields["snapshot"]
        self._say("under fault: " + self._health_line(), style="yellow")

    def _on_symptom(self, fields: dict[str, Any]) -> None:
        symptom = fields["symptom"]
        where = f" on {symptom['layer']}" if symptom["layer"] else ""
        for line in wrap(f"symptom: {symptom['kind']}{where}. {symptom['summary']}", indent=9):
            self._say(line, style="yellow")

    def _on_awaiting_patch(self, fields: dict[str, Any]) -> None:
        self._say("waiting for your fix. press p to apply the prepared one", style="bold")

    def _on_patched(self, fields: dict[str, Any]) -> None:
        patch = fields["patch"]
        self._say(f"patch in: {patch['source']} ({patch['chars']} chars)")

    def _on_fault_removed(self, fields: dict[str, Any]) -> None:
        self._health = fields["snapshot"]
        self._fault, self._blast = None, []
        self._say("fault removed: " + self._health_line(), style="green")

    def _on_analysed(self, fields: dict[str, Any]) -> None:
        analysis = fields["analysis"]
        defended = ", ".join(f"{d['layer']}/{d['kind']}" for d in analysis["defended"]) or "none"
        self._say(f"patch defends: {defended}")
        if analysis["gaps"]:
            for line in wrap("gaps: " + "; ".join(analysis["gaps"]), indent=6):
                self._say(line, style="dim")

    def _on_escalation_pending(self, fields: dict[str, Any]) -> None:
        self._say("two cycles done. the trade-off escalation is next", style="bold")

    # -- agent panel ----------------------------------------------------------

    def _drain_calls(self) -> None:
        agent = self.query_one("#agent", RichLog)
        if self._models is not None:
            for record in self._models.records[self._seen_calls :]:
                tokens = f"{record.prompt_tokens or 0:>5}→{record.completion_tokens or 0:<5}"
                flag = " fallback" if record.fallback else ""
                cycle = f"c{record.cycle}" if record.cycle else "--"
                line = (
                    f"{cycle} {record.site:<24} {LABELS.get(record.model, '?'):<5} {tokens} "
                    f"{record.latency_ms:>6.0f}ms {record.outcome}{flag}"
                )
                style = "red" if record.outcome != "ok" else "yellow" if record.fallback else ""
                agent.write(Text(fit(line), style=style))
            self._seen_calls = len(self._models.records)
        if self._search is not None:
            for call in self._search.calls[self._seen_searches :]:
                hits = "cached" if call.cached else f"{call.results} hits"
                timing = f" {hits:>7} {call.latency_ms:>6.0f}ms"
                head = f"c{self._cycle} tavily "
                query = fit(call.query, LINE - len(head) - len(timing))
                width = LINE - len(head) - len(timing)
                agent.write(Text(f"{head}{query:<{width}}{timing}", style="cyan"))
            self._seen_searches = len(self._search.calls)
        agent.border_subtitle = self._usage()

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

    def _render_chrome(self) -> None:
        now = self.now
        where = f"round {self._cycle} of {MAX_CYCLES}" if self._cycle else "not started"
        step = f"step {now.step} of {STEPS}: " if now.step else ""
        right = f"seed {self.root_seed} "
        left = fit(f" BEDLAM   {where}   {step}{now.title}", WIDTH - len(right))
        self.query_one("#header", Static).update(Text(left.ljust(WIDTH - len(right)) + right))

        box = self.query_one("#now", Static)
        box.set_class(now.your_turn, "your-turn")
        body = Text()
        for i, line in enumerate(now.lines):
            last = i == len(now.lines) - 1
            style = "bold" if i == 0 else "bold yellow" if last and now.your_turn else ""
            body.append(fit(line) + ("" if last else "\n"), style=style)
        box.update(body)

        keys = Text(" ")
        keys.append(" P ", style="bold reverse" if now.your_turn else "dim reverse")
        keys.append(" apply the prepared fix    ", style="bold" if now.your_turn else "dim")
        keys.append(" Q ", style="dim reverse")
        keys.append(" quit", style="dim")
        self.query_one("#footer", Static).update(keys)

        system = Text()
        for layer in Layer:
            result = self._health.get(layer.value)
            if result is None:
                system.append(f"{layer.value:<6} {'-':<5} {'·' * _BAR}\n", style="dim")
                continue
            up = result["status"] == "up"
            latency = result["latency_ms"]
            shown = f"{latency:>8.1f} ms" if latency is not None else "      -   "
            system.append(f"{layer.value:<6} ")
            system.append(f"{result['status'].upper():<5} ", style="green" if up else "bold red")
            hit = layer.value in self._blast
            system.append(latency_bar(latency), style="red" if hit else "green")
            system.append(f" {shown}")
            if result.get("error"):
                system.append(fit(f"  {result['error']}", LINE - 42), style="dim")
            system.append("\n")
        fault = f"{self._fault} live, blast {', '.join(self._blast)}" if self._fault else "none"
        system.append(fit(f"fault  {fault}"), style="bold red" if self._fault else "dim")
        self.query_one("#system", Static).update(system)

    def _health_line(self) -> str:
        parts = []
        for layer, result in self._health.items():
            latency = result["latency_ms"]
            value = f"{latency:.0f}ms" if latency is not None else "-"
            parts.append(f"{layer} {result['status']} {value}")
        return ", ".join(parts)

    def _say(self, text: str, style: str = "") -> None:
        cycle = f"c{self._cycle}" if self._cycle else "--"
        line = Text(f"{cycle} ", style="dim")
        line.append(fit(text, SAY), style=style)
        self.query_one("#timeline", RichLog).write(line)


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
