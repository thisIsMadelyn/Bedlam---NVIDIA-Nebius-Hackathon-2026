"""The TUI, offline: the full loop drives it at exactly 82 columns."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fakes import (
    FakeSearchBackend,
    FakeToxiproxy,
    FakeTransport,
    default_search_results,
    plausible_model,
    probe_for,
)
from textual.widgets import RichLog, Static

from bedlam.guide import EARLY_PRESS
from bedlam.loop import MAX_CYCLES, LoopDeps, run
from bedlam.models.client import ModelClient
from bedlam.patches import ScriptedPatchSource
from bedlam.search.manifest import load_manifest
from bedlam.search.tavily import SearchClient
from bedlam.trace import Trace
from bedlam.tui import ACCENT, WIDTH, BedlamApp, GatedPatchSource
from bedlam.voice import MORAL, SIGN_OFF

SIZE = (WIDTH, 30)
WIDE = (200, 45)
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
            choices=app.choices,
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
        if app.choices.waiting:
            await pilot.press("a")
        await asyncio.sleep(0.01)
    await pilot.pause(0.3)
    assert patches_sent == MAX_CYCLES
    if screenshot is not None:
        app.save_screenshot(filename=screenshot.name, path=str(screenshot.parent))


@pytest.mark.parametrize("size", [SIZE, WIDE], ids=["82 minimum", "wide"])
def test_a_full_run_fills_the_terminal_and_never_clips(tmp_path: Path, size) -> None:
    async def scenario() -> BedlamApp:
        app = _app()
        async with app.run_test(size=size) as pilot:
            await _drive(app, pilot, tmp_path / "tui.svg")
            for log in app.query(RichLog):
                inner = log.scrollable_content_region.width
                widest = max((strip.cell_length for strip in log.lines), default=0)
                assert widest <= inner, f"{log.id} line is {widest} cells, room for {inner}"
            assert app.query_one("#frame").size.width == size[0]
            body = app.query_one("#body")
            side_by_side = size[0] >= 2 * WIDTH + 2
            assert (body.styles.layout.name == "horizontal") == side_by_side
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


def test_bedlam_says_holds_the_latest_line_and_marks_quotes() -> None:
    async def scenario() -> None:
        app = BedlamApp(1729, ScriptedPatchSource(), lambda app: asyncio.sleep(3600))
        async with app.run_test(size=SIZE) as pilot:
            snapshot = {
                layer: {"status": "up", "latency_ms": 5.0, "error": None} for layer in LAYERS
            }
            app.on_loop_event("baseline", {"snapshot": snapshot})
            await pilot.pause(0.1)
            says = app.query_one("#says", Static)
            assert "Why so serious?" in str(says.render())
            assert app._voice.quoted
            app.on_loop_event("cycle_started", {"cycle": 1})
            await pilot.pause(0.1)
            assert "Why so serious?" not in str(says.render())
            assert not app._voice.quoted

    asyncio.run(scenario())


@pytest.mark.parametrize("width", [WIDTH, WIDTH + 10, 200], ids=["82 minimum", "92", "wide"])
def test_the_jester_shows_only_where_the_now_box_keeps_its_width(width: int) -> None:
    async def scenario() -> None:
        app = BedlamApp(1729, ScriptedPatchSource(), lambda app: asyncio.sleep(3600))
        async with app.run_test(size=(width, 30)) as pilot:
            app.on_loop_event(
                "injecting",
                {
                    "cycle": 1,
                    "fault": "db.timeout.0",
                    "layer": "db",
                    "kind": "timeout",
                    "blast_radius": ["db"],
                },
            )
            await pilot.pause(0.1)
            jester = app.query_one("#jester", Static)
            now = app.query_one("#now", Static)
            assert app.mood == "striking"
            assert now.content_region.width >= WIDTH - 4, "the NOW box lost columns"
            assert jester.display == (width >= WIDTH + 11)
            if jester.display:
                assert "(ò▿ó)" in str(jester.render()).split("\n")[2]
                assert jester.region.x >= now.region.right

    asyncio.run(scenario())


def test_bedlam_says_text_is_never_drawn_on_its_own_colour() -> None:
    async def scenario() -> None:
        app = BedlamApp(1729, ScriptedPatchSource(), lambda app: asyncio.sleep(3600))
        async with app.run_test(size=SIZE) as pilot:
            app.on_loop_event("cycle_started", {"cycle": 1})  # a plain, lavender voice line
            await pilot.pause(0.2)
            row = app.query_one("#says").region.y
            strip = app.screen._compositor.render_strips()[row]
            spoken = [s for s in strip if s.text.strip() and "BEDLAM" not in s.text]
            assert spoken, "no voice line on the BEDLAM SAYS row"
            for segment in spoken:
                assert segment.style.color != segment.style.bgcolor, repr(segment.text)
                assert segment.style.bgcolor.name.lower() != ACCENT.lower(), "label bg leaked"

    asyncio.run(scenario())


@pytest.mark.parametrize("size", [SIZE, WIDE], ids=["82 minimum", "wide"])
def test_the_splash_is_centred_and_holds_the_run_until_it_ends(size) -> None:
    started: list[bool] = []

    async def launch(app: BedlamApp) -> int:
        started.append(True)
        await asyncio.sleep(3600)
        return 0

    async def scenario() -> None:
        app = BedlamApp(1729, ScriptedPatchSource(), launch, splash_s=0.3)
        async with app.run_test(size=size) as pilot:
            await pilot.pause(0.1)
            assert app.splashing and not started
            assert not app.query_one("#frame").display
            rows = [s.text for s in app.screen._compositor.render_strips()]
            art = [i for i, row in enumerate(rows) if row.strip()]
            top, bottom = art[0], art[-1]
            assert abs(top - (size[1] - 1 - bottom)) <= 1, "not centred top to bottom"
            left = min(len(row) - len(row.lstrip()) for row in rows if row.strip())
            right = min(len(row) - len(row.rstrip()) for row in rows if row.strip())
            assert abs(left - right) <= 1, "not centred left to right"
            assert "▀▀  ▀▀▀ ▀▀  ▀▀▀" in rows[bottom]
            await pilot.pause(0.4)
            assert not app.splashing and started
            assert app.query_one("#frame").display

    asyncio.run(scenario())


@pytest.mark.parametrize("size", [SIZE, WIDE], ids=["82 minimum", "wide"])
def test_a_completed_run_ends_on_the_moral_and_a_key_returns_to_the_frame(size) -> None:
    async def scenario() -> None:
        app = _app()
        async with app.run_test(size=size) as pilot:
            app.splash_s = 0.1  # past the launch splash: only the end one shows
            await _drive(app, pilot)
            assert app.splashing and not app.query_one("#frame").display
            rows = [s.text for s in app.screen._compositor.render_strips()]
            art = [row for row in rows if row.strip()]
            assert art[-2].strip() == MORAL and art[-1].strip() == SIGN_OFF
            assert all(len(row.rstrip()) <= size[0] for row in rows), "the moral clips"
            left = min(len(row) - len(row.lstrip()) for row in art)
            right = min(len(row) - len(row.rstrip()) for row in art)
            assert abs(left - right) <= 1, "not centred left to right"
            await pilot.press("q")
            await pilot.pause(0.1)
            assert not app.splashing and app.query_one("#frame").display
            assert app.is_running, "the key that left the moral also quit"
            baselines = [row for row in app._timeline_rows if row[1].startswith("baseline:")]
            assert len(baselines) == 1, "leaving the moral started a second run"

    asyncio.run(scenario())


def test_a_failed_run_does_not_end_on_the_moral() -> None:
    async def launch(app: BedlamApp) -> int:
        return 1

    async def scenario() -> None:
        app = BedlamApp(1729, ScriptedPatchSource(), launch, splash_s=0.05)
        async with app.run_test(size=SIZE) as pilot:
            await pilot.press("x")  # past the launch splash
            await pilot.pause(0.3)
            assert app.exit_code == 1 and not app.splashing

    asyncio.run(scenario())


def test_any_key_skips_the_splash_and_does_nothing_else() -> None:
    async def scenario() -> None:
        app = BedlamApp(1729, ScriptedPatchSource(), lambda app: asyncio.sleep(3600), splash_s=60)
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause(0.1)
            assert app.splashing
            await pilot.press("p")
            await pilot.pause(0.1)
            assert not app.splashing
            assert app.now.lines[-1] != EARLY_PRESS, "p reached the app"

    asyncio.run(scenario())
