"""The command line: "/" to type, Enter to run, Esc to leave; keys still work."""

from __future__ import annotations

import asyncio

from test_tui import SIZE, _app, _drive
from textual.widgets import Input, RichLog

from bedlam.patches import ScriptedPatchSource
from bedlam.tui import COMMANDS, SAY, BedlamApp


def _idle_app() -> BedlamApp:
    return BedlamApp(1729, ScriptedPatchSource(), lambda app: asyncio.sleep(3600))


def _timeline(app: BedlamApp) -> list[str]:
    return [strip.text for strip in app.query_one("#timeline", RichLog).lines]


def test_slash_opens_the_line_and_help_lists_every_command() -> None:
    async def scenario() -> None:
        app = _idle_app()
        async with app.run_test(size=SIZE) as pilot:
            line = app.query_one("#command", Input)
            assert not line.has_focus, "the line must not steal P and Q at start"
            await pilot.press("slash")
            assert line.has_focus and line.value == "/"
            await pilot.press("h", "e", "l", "p", "enter")
            await pilot.pause(0.1)
            text = "\n".join(_timeline(app))
            assert "you › /help" in text
            assert all(f"/{name}" in text for name in COMMANDS)
            assert not line.has_focus and line.value == ""

    asyncio.run(scenario())


def test_typing_p_in_the_line_never_hands_over_a_fix() -> None:
    async def scenario() -> None:
        app = _app()
        async with app.run_test(size=SIZE) as pilot:
            for _ in range(500):
                if app.patches.waiting:
                    break
                await asyncio.sleep(0.01)
            await pilot.press("slash", "p", "a", "p")
            await pilot.pause(0.1)
            assert app.patches.waiting, "a p typed into the command line released the patch"
            assert app.query_one("#command", Input).value == "/pap"
            await pilot.press("escape")
            assert app.query_one("#command", Input).value == ""
            assert not any("patch in:" in line for line in _timeline(app))
            await pilot.press("p")  # back on the screen, P is the key again
            await pilot.pause(0.2)
            assert any("patch in:" in line for line in _timeline(app))

    asyncio.run(scenario())


def test_unknown_commands_say_so() -> None:
    async def scenario() -> None:
        app = _idle_app()
        async with app.run_test(size=SIZE) as pilot:
            await pilot.press("slash", "x", "y", "z", "enter")
            await pilot.pause(0.1)
            assert any("unknown command /xyz" in line for line in _timeline(app))

    asyncio.run(scenario())


def test_help_lines_fit_82_columns() -> None:
    for name, about in COMMANDS.items():
        assert len(f"  /{name:<8} {about}") <= SAY


async def _type(pilot, command: str) -> None:
    await pilot.press("slash", *command, "enter")
    await pilot.pause(0.1)


def _reply(app: BedlamApp, command: str) -> list[str]:
    """What the timeline said after the last echo of `command`."""
    rows = [text for _, text, _ in app._timeline_rows]
    last = max(i for i, text in enumerate(rows) if text == f"you › /{command}")
    return rows[last + 1 :]


def test_before_anything_happens_the_commands_say_so() -> None:
    async def scenario() -> None:
        app = _idle_app()
        async with app.run_test(size=SIZE) as pilot:
            await _type(pilot, "why")
            assert _reply(app, "why") == [
                "  nothing routed yet. /why works once Bedlam has searched"
            ]
            await _type(pilot, "diff")
            assert _reply(app, "diff") == ["  no patch read yet"]
            await _type(pilot, "status")
            assert _reply(app, "status") == [
                "  baseline, before cycle 1 · Bedlam is working",
                "  no fault live",
            ]

    asyncio.run(scenario())


def test_status_names_the_live_fault_while_bedlam_waits_for_a_patch() -> None:
    async def scenario() -> None:
        app = _app()
        async with app.run_test(size=SIZE) as pilot:
            for _ in range(500):
                if app.patches.waiting:
                    break
                await asyncio.sleep(0.01)
            await _type(pilot, "status")
            where, fault = _reply(app, "status")
            assert where == "  cycle 1 of 2 · waiting for your patch"
            assert fault.startswith(f"  live fault: {app._fault} · blast radius: ")

    asyncio.run(scenario())


def test_after_a_run_why_diff_and_seed_explain_it() -> None:
    async def scenario() -> None:
        app = _app()
        async with app.run_test(size=SIZE) as pilot:
            await _drive(app, pilot)
            await _type(pilot, "why")
            why = _reply(app, "why")
            routing = app._routed["routing"]
            assert why[0].startswith(f"  routed to {app._routed['specialist']} (search): ")
            assert why[1] == "  results behind it, strongest first:"
            assert 1 <= len(why[2:]) <= 3
            assert all(row.split()[0] in routing["weights"] for row in why[2:])
            assert not any(row.split()[1].startswith("http") for row in why[2:])
            await _type(pilot, "diff")
            diff = _reply(app, "diff")
            assert diff[0].startswith("  patch: cycle2.diff (")
            assert diff[1].startswith("  defends: ") and diff[2].startswith("  gaps: ")
            await _type(pilot, "seed")
            assert _reply(app, "seed")[:2] == [
                "  root seed 1729 · every seeded choice in this run derives from it",
                "  run it again: make run SEED=1729",
            ]
            await _type(pilot, "status")
            assert _reply(app, "status") == ["  run over", "  no fault live"]
            # Result rows are cut to fit, like every log line; the rest never need to be.
            fixed = why[:2] + diff[:2] + _reply(app, "seed") + _reply(app, "status")
            assert all(len(text) <= SAY for text in fixed)

    asyncio.run(scenario())
