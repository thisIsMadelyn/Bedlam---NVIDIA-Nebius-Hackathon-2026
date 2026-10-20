"""The NOW box: every step says where to look, inside 82 columns."""

from __future__ import annotations

import asyncio
from pathlib import Path

from test_loop import _run_once
from test_tui import SIZE, _app
from textual.widgets import Static

from bedlam.faults.primitives import FaultKind
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
    STOPPED,
    TRADE_OFF,
    YOUR_TURN_REAL,
    YOUR_TURN_SCRIPTED,
    guidance,
)
from bedlam.specialists.catalog import CATALOG
from bedlam.tui import LINE


def _all_guidance(tmp_path: Path) -> list:
    events: list[tuple[str, dict]] = []
    _run_once(1729, tmp_path / "trace.json", events=events)
    found = [g for kind, fields in events if (g := guidance(kind, fields))]
    longest_fault = max(CATALOG, key=lambda option: len(option.id))
    for kind in FaultKind:  # every attack verb, with the widest blast radius
        fields = {"layer": "cache", "kind": kind.value, "blast_radius": ["api", "cache"]}
        found.append(guidance("injecting", fields))
    found.append(guidance("selected", {"selection": {"fault": {"id": longest_fault.id}}}))
    fixed = [STARTING, STOPPED, PRESSED_REAL, PRESSED_SCRIPTED, NO_CHANGES]
    turns = [YOUR_TURN_REAL, YOUR_TURN_SCRIPTED, TRADE_OFF]
    longest_title = {"choice": "a", "option": {"title": "x" * 48}}
    found += [guidance("chosen", longest_title), guidance("finished", {"escalation": None})]
    return [*found, *fixed, *turns, STARTING.nudged(EARLY_PRESS), STARTING.nudged(EARLY_CHOICE)]


def test_every_guide_line_fits_and_points_somewhere(tmp_path: Path) -> None:
    for item in _all_guidance(tmp_path):
        for line in item.lines:
            assert len(line) <= LINE, f"{item.title}: {len(line)} > {LINE}: {line}"
        where, you = item.lines[1], item.lines[2]
        assert you.startswith("You") or item.your_turn, f"{item.title} never says what to do"
        pointed = any(name in where for name in (APP, LOG, MODELS))
        assert pointed or item.your_turn or item.title == "DONE", f"{item.title}: look where?"


def test_your_turn_is_loud_and_p_is_acknowledged() -> None:
    async def scenario() -> None:
        app = _app()
        async with app.run_test(size=SIZE) as pilot:
            for _ in range(500):
                if app.patches.waiting:
                    break
                await asyncio.sleep(0.01)
            await pilot.pause(0.1)
            assert app.now.title == "YOUR TURN"
            assert app.query_one("#now", Static).has_class("your-turn")
            app.action_patch()  # synchronous: the loop cannot move in between
            assert app.now is PRESSED_SCRIPTED
            assert not app.query_one("#now", Static).has_class("your-turn")

    asyncio.run(scenario())


def test_p_too_early_says_so_instead_of_doing_nothing_silently() -> None:
    async def scenario() -> None:
        app = _app()
        async with app.run_test(size=SIZE):
            app.patches.waiting = False
            app.action_patch()
            assert app.now.lines[2] == EARLY_PRESS

    asyncio.run(scenario())


def test_your_turn_names_the_mode_it_is_in() -> None:
    assert guidance("awaiting_patch", {}, real=True) is YOUR_TURN_REAL
    assert guidance("awaiting_patch", {}) is YOUR_TURN_SCRIPTED
    assert "git diff" in " ".join(YOUR_TURN_REAL.lines)
    assert "not reloaded" in " ".join(YOUR_TURN_REAL.lines)
    assert "prepared fix" in " ".join(YOUR_TURN_SCRIPTED.lines)
