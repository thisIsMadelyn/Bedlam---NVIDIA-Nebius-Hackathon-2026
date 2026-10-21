"""The command line: "/" to type, Enter to run, Esc to leave; keys still work."""

from __future__ import annotations

import asyncio

import pytest
from test_tui import SIZE, WIDE, _app, _drive
from textual.widgets import Input, RichLog, Static

from bedlam.patches import ScriptedPatchSource
from bedlam.topology import Layer
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
    """What the last command said, wherever it said it; it must be `command`."""
    assert app._last_command == f"/{command}"
    return app._last_reply


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


def _page(app: BedlamApp) -> list[str]:
    return [strip.text for strip in app.query_one("#postmortem", RichLog).lines]


@pytest.mark.parametrize("size", [SIZE, WIDE], ids=["82 minimum", "wide"])
def test_the_run_ends_on_the_decided_trade_off_with_a_post_mortem_log(size) -> None:
    async def scenario() -> None:
        app = _app()
        async with app.run_test(size=size) as pilot:
            await _drive(app, pilot)
            page = app.query_one("#postmortem", RichLog)
            assert app.query_one("#tradeoff").display and page.display
            assert not app.query_one("#system").display and not app.query_one("#body").display
            assert page.has_focus
            rows = [s.text for s in app.screen._compositor.render_strips()]
            assert any("◀ you chose this" in row for row in rows)
            assert any("cost shown live:" in row for row in rows)
            before = len(app._timeline_rows)
            for command in ("cycles", "cycle 1", "why 1", "calls", "cost", "help"):
                await _type(pilot, command)
            assert len(app._timeline_rows) == before, "replies leaked into the hidden timeline"
            widest = max(strip.cell_length for strip in page.lines)
            assert widest <= page.scrollable_content_region.width
            assert "you › /cycles" in _page(app)

    asyncio.run(scenario())


def test_the_post_mortem_commands_tell_the_run_back() -> None:
    async def scenario() -> None:
        app = _app()
        async with app.run_test(size=SIZE) as pilot:
            await _drive(app, pilot)
            await _type(pilot, "cycles")
            cycles = _reply(app, "cycles")
            assert [row.split()[0] for row in cycles] == ["c1", "c2", "tf"]
            assert cycles[2].endswith(f"you chose A: {app._trade_off['options'][0]['title']}")
            await _type(pilot, "cycle 1")
            labels = [row.split()[0] for row in _reply(app, "cycle 1") if row[2] != " "]
            for label in ("cycle", "searched", "routed", "pool", "picked", "injected",
                          "under", "symptom", "patch", "after", "defends", "gaps"):  # fmt: skip
                assert label in labels, label
            await _type(pilot, "cycle 9")
            assert _reply(app, "cycle 9") == ["  no cycle 9 in this run. try /cycle 1 or /cycle 2"]
            await _type(pilot, "why 1")
            named = [r for r in app._cycles[1]["routed"]["results"] if r["layer"]]
            assert len(_reply(app, "why 1")) == 2 + len(named)
            await _type(pilot, "diff 1")
            assert _reply(app, "diff 1")[0].startswith("  patch: cycle1.diff (")
            await _type(pilot, "calls")
            calls = _reply(app, "calls")
            sites = {record.site for record in app._models.records}
            assert len(calls) == len(sites) + 2
            assert calls[-2].split()[:2] == ["search", "Tavily"]
            assert calls[-1].startswith("  total: ")
            await _type(pilot, "cost")
            labels = [row.split()[0] for row in _reply(app, "cost") if row[2] != " "]
            assert labels[:4] == ["you", "you", "felt", "shown"]
            assert labels[4:] == ["before", "under", "after"]
            await _type(pilot, "cpu")
            assert _reply(app, "cpu") == [
                "  no cpu samples in this run: docker stats were not read"
            ]
            app._run_cpu = [{layer: 10.0 * i for layer in Layer} for i in range(20)]
            await _type(pilot, "cpu")
            assert len(_reply(app, "cpu")) == 2 + len(Layer) * 2

    asyncio.run(scenario())


def test_log_switches_between_the_page_and_the_run_log() -> None:
    async def scenario() -> None:
        app = _app()
        async with app.run_test(size=SIZE) as pilot:
            await _type(pilot, "log")
            assert _reply(app, "log") == ["  the run log is already on screen"]
            await _drive(app, pilot)
            await _type(pilot, "zoom agent")
            assert _reply(app, "zoom agent") == ["  /zoom works on the run log. /log shows it"]
            await _type(pilot, "log")
            assert app.query_one("#timeline").display and app.query_one("#body").display
            assert not app.query_one("#tradeoff").display
            assert app.query_one("#timeline").has_focus
            await _type(pilot, "status")
            assert "  run over" in _timeline(app)[-2]
            await _type(pilot, "log")
            assert app.query_one("#tradeoff").display and app.query_one("#postmortem").has_focus

    asyncio.run(scenario())


def test_while_choosing_the_strip_takes_replies_when_there_is_room() -> None:
    async def scenario() -> None:
        app = _app()
        async with app.run_test(size=WIDE) as pilot:
            for _ in range(2000):
                if app.patches.waiting:
                    await pilot.press("p")
                if app.choices.waiting:
                    break
                await asyncio.sleep(0.01)
            await pilot.pause(0.2)
            assert app.query_one("#postmortem").display, "no strip at 200 x 45"
            await _type(pilot, "cycles")
            assert any("you › /cycles" in row for row in _page(app))
            assert app.choices.waiting, "a command made the choice"
            await pilot.press("a")
            await pilot.pause(0.3)

    asyncio.run(scenario())


def test_once_the_run_is_over_the_footer_offers_no_p() -> None:
    async def scenario() -> None:
        app = _app()
        async with app.run_test(size=SIZE) as pilot:
            assert " P " in str(app.query_one("#footer", Static).render())
            await _drive(app, pilot)
            footer = str(app.query_one("#footer", Static).render())
            assert " P " not in footer and " Q " in footer and " / " in footer

    asyncio.run(scenario())


def test_grep_filters_the_post_mortem_log_but_never_the_reply_just_asked_for() -> None:
    async def scenario() -> None:
        app = _app()
        async with app.run_test(size=SIZE) as pilot:
            await _drive(app, pilot)
            await _type(pilot, "cycles")
            await _type(pilot, "grep c1")
            shown = _page(app)
            assert sum(row.lstrip().startswith(("c1 ", "c2 ", "tf ")) for row in shown) == 1
            assert any(row.lstrip().startswith("c1 ") for row in shown)
            assert "you › /cycles" in shown, "an echo was filtered out"
            assert _reply(app, "grep c1") == ["  1 lines match. /grep alone shows all"]
            assert "/grep c1" in app.query_one("#postmortem", RichLog).border_title
            await _type(pilot, "cycle 2")  # the latest reply shows in full
            assert any("cycle 2 of 2" in row for row in _page(app))
            assert any("defends" in row for row in _page(app))
            await _type(pilot, "status")  # and the one before it is filtered now
            assert not any("cycle 2 of 2" in row for row in _page(app))
            await _type(pilot, "grep")
            shown = _page(app)
            assert any("cycle 2 of 2" in row for row in shown)
            assert sum(row.lstrip().startswith(("c1 ", "c2 ", "tf ")) for row in shown) == 3

    asyncio.run(scenario())
