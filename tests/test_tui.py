"""The TUI, offline: the full loop drives it at exactly 82 columns."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fakes import (
    FakeSearchBackend,
    FakeToxiproxy,
    FakeTransport,
    default_search_results,
    plausible_model,
    probe_for,
)
from textual.widgets import RichLog

from bedlam.loop import MAX_CYCLES, LoopDeps, run
from bedlam.models.client import ModelClient
from bedlam.patches import ScriptedPatchSource
from bedlam.search.manifest import load_manifest
from bedlam.search.tavily import SearchClient
from bedlam.trace import Trace
from bedlam.tui import WIDTH, BedlamApp, GatedPatchSource

SIZE = (WIDTH, 30)
LAYERS = ("api", "db", "cache")


def _app() -> BedlamApp:
    async def launch(app: BedlamApp) -> int:
        toxiproxy = FakeToxiproxy()
        models = ModelClient(FakeTransport(plausible_model()), root_seed=1729, backoff_s=0.0)
        search = SearchClient(FakeSearchBackend(default_search_results()))
        app.attach(models, search)
        manifest = load_manifest()
        deps = LoopDeps(
            models=models,
            search=search,
            faults=toxiproxy,  # type: ignore[arg-type]
            probe=probe_for(toxiproxy),
            patches=app.patches,
            manifest=manifest,
            root_seed=1729,
            on_event=app.on_loop_event,
        )
        trace = await run(deps, Trace(root_seed=1729, manifest=manifest))
        return 0 if trace.outcome == "completed" else 1

    return BedlamApp(1729, ScriptedPatchSource(), launch)


async def _drive(app: BedlamApp, pilot, screenshot: Path | None = None) -> None:
    patches_sent = 0
    for _ in range(500):
        if app.exit_code is not None:
            break
        if app.patches.waiting:
            await pilot.press("p")
            patches_sent += 1
        await asyncio.sleep(0.01)
    await pilot.pause(0.3)
    assert patches_sent == MAX_CYCLES
    if screenshot is not None:
        app.save_screenshot(filename=screenshot.name, path=str(screenshot.parent))


def test_a_full_run_renders_inside_82_columns(tmp_path: Path) -> None:
    async def scenario() -> BedlamApp:
        app = _app()
        async with app.run_test(size=SIZE) as pilot:
            await _drive(app, pilot, tmp_path / "tui.svg")
            for log in app.query(RichLog):
                inner = log.scrollable_content_region.width
                widest = max((strip.cell_length for strip in log.lines), default=0)
                assert widest <= inner, f"{log.id} line is {widest} cells, room for {inner}"
            assert app.query_one("#frame").size.width == WIDTH
        return app

    app = asyncio.run(scenario())
    assert app.exit_code == 0


def test_every_model_call_shows_the_model_that_answered(tmp_path: Path) -> None:
    async def scenario() -> list[str]:
        app = _app()
        async with app.run_test(size=SIZE) as pilot:
            await _drive(app, pilot)
            return [strip.text for strip in app.query_one("#agent", RichLog).lines]

    lines = asyncio.run(scenario())
    searches = [line for line in lines if line.split()[1] == "tavily"]
    model_lines = [line for line in lines if line not in searches]
    assert model_lines
    assert all(line.split()[2] in ("Nano", "Super") for line in model_lines)
    assert len(searches) == 2 * MAX_CYCLES


def test_p_before_a_fault_is_live_does_not_skip_a_patch() -> None:
    async def scenario() -> None:
        gate = GatedPatchSource(ScriptedPatchSource())
        assert not gate.release(), "nothing was waiting"
        waiter = asyncio.create_task(gate.wait_for_patch(1))
        await asyncio.sleep(0.05)
        assert not waiter.done(), "an early p must not pre-approve the next patch"
        assert gate.release()
        patch = await asyncio.wait_for(waiter, timeout=1)
        assert patch.cycle == 1

    asyncio.run(scenario())


def test_probes_fill_together_then_settle_on_their_results() -> None:
    def rows(app: BedlamApp) -> list[str]:
        strips = app.screen._compositor.render_strips()
        return [s.text for s in strips if any(f" {layer} " in s.text for layer in LAYERS)]

    async def scenario() -> None:
        app = BedlamApp(1729, ScriptedPatchSource(), lambda app: asyncio.sleep(3600))
        async with app.run_test(size=SIZE) as pilot:
            app.on_loop_event("probing", {"cycle": 1})
            await pilot.pause(0.3)
            checking = [row for row in rows(app) if "checking" in row]
            assert len(checking) == len(LAYERS), "the three probes should fill together"
            snapshot = {
                layer: {"status": "up", "latency_ms": 5.0, "error": None} for layer in LAYERS
            }
            app.on_loop_event("probed", {"cycle": 1, "snapshot": snapshot})
            await pilot.pause(0.1)
            assert not [row for row in rows(app) if "checking" in row]

    asyncio.run(scenario())
