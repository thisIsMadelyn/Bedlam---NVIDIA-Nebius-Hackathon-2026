"""The command line: "/" to type, Enter to run, Esc to leave; keys still work."""

from __future__ import annotations

import asyncio

from test_tui import SIZE, _app
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
