"""The command line: "/" to type, Enter to run, Esc to leave; keys still work."""

from __future__ import annotations

import asyncio

from test_tui import SIZE, _app, _drive
from textual.widgets import Input, RichLog

from bedlam.patches import ScriptedPatchSource
from bedlam.tui import COMMANDS, SAY, BedlamApp
from bedlam.voice import SUDO, SUDO_CHOOSE


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
            seed = _reply(app, "seed")
            assert seed[:2] == [
                "  root seed 1729 · every seeded choice in this run derives from it",
                "  run it again: make run SEED=1729",
            ]
            await _type(pilot, "status")
            status = _reply(app, "status")
            assert status == ["  run over", "  no fault live"]
            # Result rows are cut to fit, like every log line; the rest never need to be.
            fixed = why[:2] + diff[:2] + seed + status
            assert all(len(text) <= SAY for text in fixed)

    asyncio.run(scenario())


def test_tab_takes_the_completion_and_never_leaves_the_line() -> None:
    async def scenario() -> None:
        app = _idle_app()
        async with app.run_test(size=SIZE) as pilot:
            line = app.query_one("#command", Input)
            await pilot.press("slash", "w", "h", "tab")
            assert line.value == "/why" and line.has_focus
            await pilot.press("escape", "slash", "z", "o", "o", "m", "space", "a", "tab")
            assert line.value == "/zoom agent"
            await pilot.press("escape", "slash", "x", "x", "tab")
            assert line.value == "/xx" and line.has_focus

    asyncio.run(scenario())


def test_the_slash_is_the_only_command_line() -> None:
    assert BedlamApp.ENABLE_COMMAND_PALETTE is False


def test_grep_filters_the_timeline_but_never_hides_commands() -> None:
    async def scenario() -> None:
        app = _idle_app()
        async with app.run_test(size=SIZE) as pilot:
            for text in ("tavily  asyncpg pool", "routed to db", "tavily  redis timeout"):
                app._say(text)
            await _type(pilot, "grep TAVILY")
            shown = _timeline(app)
            assert [row for row in shown if "routed" in row] == []
            assert sum("tavily  " in row for row in shown) == 2
            assert any("you › /grep TAVILY" in row for row in shown)
            assert any("2 lines match" in row for row in shown)
            await _type(pilot, "status")  # a reply under a filter still shows
            assert any("no fault live" in row for row in _timeline(app))
            app._say("routed to cache")  # a new non-match stays hidden
            assert not any("routed to cache" in row for row in _timeline(app))
            await _type(pilot, "grep")
            assert sum("routed to" in row for row in _timeline(app)) == 2

    asyncio.run(scenario())


def test_zoom_fills_the_screen_with_one_log_and_zoom_alone_ends_it() -> None:
    async def scenario() -> None:
        app = _idle_app()
        async with app.run_test(size=SIZE) as pilot:
            timeline, agent = app.query_one("#timeline"), app.query_one("#agent")
            system = app.query_one("#system")
            await _type(pilot, "zoom agent")
            assert agent.display and not timeline.display and not system.display
            assert agent.has_focus, "a hidden log kept the focus"
            await _type(pilot, "zoom timeline")
            assert timeline.display and not agent.display
            await _type(pilot, "zoom")
            assert timeline.display and agent.display and system.display
            await _type(pilot, "zoom everything")
            assert any("zoom what?" in row for row in _timeline(app))

    asyncio.run(scenario())


def test_copy_takes_the_last_reply_or_the_shown_timeline() -> None:
    copied: list[str] = []

    async def scenario() -> None:
        app = _idle_app()
        app.copy_to_clipboard = copied.append  # type: ignore[method-assign]
        async with app.run_test(size=SIZE) as pilot:
            await _type(pilot, "copy")
            assert copied == [] and any("nothing to copy" in row for row in _timeline(app))
            await _type(pilot, "status")
            await _type(pilot, "copy")
            assert copied[-1] == "  baseline, before cycle 1 · Bedlam is working\n  no fault live"
            await _type(pilot, "copy")  # /copy never copies its own reply
            assert copied[-1] == copied[-2]
            app._say("routed to db")
            await _type(pilot, "grep routed")
            await _type(pilot, "copy timeline")
            assert "-- routed to db" in copied[-1].split("\n")
            assert "-- you › /status" in copied[-1].split("\n"), "pinned rows are shown"

    asyncio.run(scenario())


def test_save_and_shot_write_beside_the_trace(tmp_path) -> None:
    async def scenario() -> None:
        app = _idle_app()
        app.trace_file = tmp_path / "tui-seed1729.json"
        async with app.run_test(size=SIZE) as pilot:
            app._say("routed to db")
            await _type(pilot, "save")
            await _type(pilot, "shot")
            await _type(pilot, "shot")

    asyncio.run(scenario())
    text = (tmp_path / "tui-seed1729.txt").read_text(encoding="utf-8").splitlines()
    assert text[0] == "BEDLAM · seed 1729" and "-- routed to db" in text
    assert (tmp_path / "tui-seed1729-shot1.svg").is_file()
    assert (tmp_path / "tui-seed1729-shot2.svg").is_file()


def test_save_without_a_trace_file_says_so() -> None:
    async def scenario() -> None:
        app = _idle_app()
        async with app.run_test(size=SIZE) as pilot:
            await _type(pilot, "save")
            assert any("no trace file" in row for row in _timeline(app))

    asyncio.run(scenario())


def test_sudo_is_hidden_and_never_runs_what_follows() -> None:
    async def scenario() -> None:
        app = _app()
        async with app.run_test(size=SIZE) as pilot:
            for _ in range(2000):
                if app.patches.waiting:
                    await pilot.press("p")
                if app.choices.waiting:
                    break
                await asyncio.sleep(0.01)
            await _type(pilot, "sudo choose a")
            assert _reply(app, "sudo choose a") == [f"» {SUDO_CHOOSE}"]
            assert app.choices.waiting, "sudo made the choice"
            await _type(pilot, "sudo make me a sandwich")
            assert _reply(app, "sudo make me a sandwich") == [f"» {SUDO}"]
            await pilot.press("a")
            await pilot.pause(0.3)

    asyncio.run(scenario())
    assert "sudo" not in COMMANDS
