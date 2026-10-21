"""The trade-off escalation: a real choice, made by the developer, with a visible cost."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from fakes import FakeTransport, answer_tradeoff_escalation, plausible_model
from test_loop import _run_once
from test_tui import SIZE, _app

from bedlam.escalation import ScriptedChoice, decision_record, escalate
from bedlam.faults.primitives import FaultKind
from bedlam.guide import EARLY_CHOICE, TRADE_OFF
from bedlam.history import FaultRecord
from bedlam.models.client import ModelClient
from bedlam.models.map import CallSite
from bedlam.patches import ScriptedPatchSource
from bedlam.topology import Layer
from bedlam.tui import BedlamApp, GatedChoice, option_cards, postmortem_field

_HISTORY = [
    FaultRecord(1, "db.latency.2500", Layer.DB, FaultKind.LATENCY, "db"),
    FaultRecord(2, "cache.timeout.0", Layer.CACHE, FaultKind.TIMEOUT, "cache"),
]


def _escalate(handler) -> tuple[Any, FakeTransport]:
    transport = FakeTransport({**plausible_model(), CallSite.TRADEOFF_ESCALATION: handler})
    client = ModelClient(transport, root_seed=1729, backoff_s=0.0)
    trade_off = asyncio.run(escalate(client, history=_HISTORY, analyses=[], symptoms=[]))
    return trade_off, transport


def test_wording_that_recommends_a_side_is_rejected_and_retried() -> None:
    replies = iter(["recommend", "fair"])

    def handler(ctx: dict[str, Any], model: str) -> Any:
        answer = answer_tradeoff_escalation(ctx, model)
        if next(replies) == "recommend":
            answer["options"][0]["gain"] = "the safer bet for most teams"
        return answer

    trade_off, transport = _escalate(handler)

    assert trade_off.source == "model"
    retry = transport.messages[-1][-1]["content"]
    assert "recommends a side" in retry and "developer decides" in retry


def test_two_options_with_the_same_cost_are_not_a_trade_off() -> None:
    def handler(ctx: dict[str, Any], model: str) -> Any:
        answer = answer_tradeoff_escalation(ctx, model)
        answer["options"][1]["cost_felt_when"] = answer["options"][0]["cost_felt_when"]
        return answer

    trade_off, _ = _escalate(handler)

    # Every attempt was refused, so the templated pair stands in, logged.
    assert trade_off.source == "templated_fallback"
    a, b = trade_off.options
    assert a.consequence.id != b.consequence.id
    assert a.consequence.layer == b.consequence.layer == Layer.CACHE, "grounded in the last fault"


def test_the_consequence_follows_from_when_the_cost_is_felt() -> None:
    trade_off, _ = _escalate(answer_tradeoff_escalation)

    a, b = trade_off.options
    assert (a.felt_when, a.consequence.id) == ("cache is slow", "cache.latency.2500")
    assert (b.felt_when, b.consequence.id) == ("cache hangs", "cache.timeout.0")


def test_a_condition_or_layer_off_the_list_is_rejected_and_retried(caplog) -> None:
    replies = iter(["condition", "layer", "fair"])

    def handler(ctx: dict[str, Any], model: str) -> Any:
        answer = answer_tradeoff_escalation(ctx, model)
        wrong = next(replies)
        if wrong == "condition":
            answer["options"][0]["cost_felt_when"] = "flaky"
        elif wrong == "layer":
            answer["options"][1]["cost_layer"] = "api"
        return answer

    trade_off, _ = _escalate(handler)

    # Each refusal names what was off the list; the third reply is accepted.
    assert trade_off.source == "model"
    reasons = [r.getMessage() + str(r.__dict__.get("fields")) for r in caplog.records]
    assert any("'flaky' is not one of slow, hangs" in r for r in reasons)
    assert any("'api' cannot be faulted; use one of cache, db" in r for r in reasons)


def test_both_branches_are_reachable_and_cost_something_different(tmp_path: Path) -> None:
    runs = {key: _run_once(1729, tmp_path / f"{key}.json", choice=key) for key in ("a", "b")}

    shown = {}
    for key, (trace, toxiproxy, _) in runs.items():
        escalation = trace["escalation"]
        assert escalation["status"] == "chosen" and escalation["choice"] == key
        assert len(toxiproxy.applied) == 3, "two cycles, then the chosen cost once"
        assert not toxiproxy.active, "the cost was left applied"
        shown[key] = escalation["consequence"]
        assert shown[key]["probe_during"] != shown[key]["probe_after"]
    assert shown["a"]["fault"] != shown["b"]["fault"]
    # Same seed, same inputs: the trade-off itself does not depend on the choice.
    assert runs["a"][0]["escalation"]["trade_off"] == runs["b"][0]["escalation"]["trade_off"]


def test_without_a_choice_bedlam_presents_the_options_and_picks_nothing(tmp_path: Path) -> None:
    events: list[tuple[str, dict]] = []
    trace, toxiproxy, _ = _run_once(1729, tmp_path / "trace.json", events=events, choice=None)

    escalation = trace["escalation"]
    assert escalation["status"] == "no_choice_given"
    assert "choice" not in escalation and "consequence" not in escalation
    assert len(escalation["trade_off"]["options"]) == 2
    assert len(toxiproxy.applied) == 2, "a cost was shown for a choice nobody made"
    kinds = [kind for kind, _ in events]
    assert kinds[-3:] == ["escalating", "trade_off", "finished"]


def test_a_scripted_choice_must_be_a_or_b() -> None:
    for bad in ("", "c", "A "):
        try:
            ScriptedChoice(bad)
        except ValueError:
            continue
        raise AssertionError(f"{bad!r} was accepted")


def test_the_decision_record_marks_the_choice_and_keeps_both_sides(tmp_path: Path) -> None:
    trace, _, _ = _run_once(1729, tmp_path / "trace.json", choice="b")

    record = decision_record(trace["escalation"])

    assert "### A. Fail fast\n" in record
    assert "### B. Wait it out (chosen)" in record
    assert record.count("- Cost: ") == 2
    assert record.count("- Felt when: ") == 2
    assert "The developer chose." in record


def test_a_key_before_the_trade_off_is_refused_not_kept() -> None:
    async def scenario() -> None:
        gate = GatedChoice()
        assert not gate.choose("a"), "nothing was asked yet"
        waiter = asyncio.create_task(gate.wait_for_choice(None))  # type: ignore[arg-type]
        await asyncio.sleep(0.05)
        assert not waiter.done(), "an early key must not pre-answer the trade-off"
        assert not gate.choose("c")
        assert gate.choose("b")
        assert await asyncio.wait_for(waiter, timeout=1) == "b"

    asyncio.run(scenario())


def test_the_trade_off_takes_the_frame_and_fits_at_82_columns() -> None:
    async def scenario() -> None:
        app = _app()
        async with app.run_test(size=SIZE) as pilot:
            app.action_choose("a")
            assert app.now.lines[2] == EARLY_CHOICE
            for _ in range(500):
                if app.patches.waiting:
                    await pilot.press("p")
                if app.choices.waiting:
                    break
                await asyncio.sleep(0.01)
            await pilot.pause(0.2)
            assert app.now is TRADE_OFF
            assert not app.query_one("#system").display, "the trade-off did not take the frame"
            rows = [s.text for s in app.screen._compositor.render_strips()]
            assert all(len(row) == SIZE[0] for row in rows)
            assert " A  option A" in rows[-1] and " P " not in rows[-1], "keys not lit"
            panel = "\n".join(rows)
            for text in (
                "┌─ A ",
                "┌─ B ",
                "Fail fast",
                "Wait it out",
                "│ gain  ",
                "│ pay   ",
                "felt  db is slow",
                "felt  db hangs",
                "live  db.latency.2500",
                "live  db.timeout.0",
                "└─ press A ",
                "└─ press B ",
            ):
                assert text in panel, text
            assert "…" not in panel.split("TRADE-OFF", 1)[1], "a trade-off line was cut"
            shown: list[bool] = []
            on_cost_shown = app._on_cost_shown

            def watch(fields) -> None:
                shown.append(app.query_one("#system").display)
                on_cost_shown(fields)

            app._on_cost_shown = watch  # type: ignore[method-assign]
            await pilot.press("a")
            for _ in range(500):
                if app.exit_code is not None:
                    break
                await asyncio.sleep(0.01)
            await pilot.pause(0.2)
            assert app.exit_code == 0
            assert shown == [True], "YOUR APP must show the cost"
            assert app.query_one("#tradeoff").display, "the run must end on the trade-off"
            assert app.now.title == "DONE"

    asyncio.run(scenario())


def test_the_longest_trade_off_the_parser_allows_still_fits_at_82() -> None:
    def words(n: int) -> str:
        return ("lorem ipsum dolor " * 20)[:n].strip()

    option = {
        "gain": words(120),
        "cost": words(120),
        "felt_when": "cache drops connections",
        "consequence": {"id": "cache.timeout.3000"},
    }
    trade_off = {
        "axis": words(60),
        "why": words(220),
        "options": [{**option, "key": k, "title": words(48)} for k in ("a", "b")],
    }

    async def scenario() -> None:
        app = BedlamApp(1729, ScriptedPatchSource(), lambda app: asyncio.sleep(3600))
        async with app.run_test(size=SIZE) as pilot:
            app.on_loop_event("trade_off", {"trade_off": trade_off})
            await pilot.pause(0.2)
            rows = [s.text for s in app.screen._compositor.render_strips()]
            panel = rows[[i for i, r in enumerate(rows) if "TRADE-OFF" in r][0] :]
            shown = "\n".join(panel)
            assert shown.count("live  cache.timeout.3000") == 2, "a card was cut"
            assert shown.count("└─") == 2, "a card lost its foot"
            assert "…" not in "".join(panel)

    asyncio.run(scenario())


TRADE_OFF_FIELDS = {
    "axis": "fail fast vs wait it out",
    "why": "both rounds hit how the app treats a late db",
    "options": [
        {
            "key": "a",
            "title": "Fail fast",
            "gain": "a hung dependency costs one quick error, not a stuck request",
            "cost": "errors whenever it is merely slow",
            "felt_when": "db is slow",
            "consequence": {"id": "db.latency.2500"},
        },
        {
            "key": "b",
            "title": "Wait it out",
            "gain": "a slow dependency still answers",
            "cost": "requests pile up when it hangs",
            "felt_when": "db hangs",
            "consequence": {"id": "db.timeout.0"},
        },
    ],
}


def test_the_cards_line_their_rows_up_side_by_side_and_fill_the_width() -> None:
    lines = option_cards(TRADE_OFF_FIELDS["options"], 78, waiting=True)
    plain = [line.plain for line in lines]
    assert all(len(row) == 78 for row in plain)
    left = [row[:38] for row in plain]
    right = [row[39:] for row in plain]
    for label in ("gain", "pay", "felt", "live"):
        rows = [i for i, row in enumerate(left) if row.startswith(f"│ {label} ")]
        assert rows == [i for i, row in enumerate(right) if row.startswith(f"│ {label} ")], label


def test_while_the_choice_waits_both_cards_look_the_same() -> None:
    lines = option_cards(TRADE_OFF_FIELDS["options"], 78, waiting=True)
    top = lines[0]
    styles = {str(span.style) for span in top.spans}
    assert len(styles) == 1, "one card is styled differently: a recommendation"
    assert "◀" not in "".join(line.plain for line in lines)


def test_once_chosen_the_card_is_marked_and_the_other_dims() -> None:
    lines = option_cards(TRADE_OFF_FIELDS["options"], 78, chosen="b")
    foot = lines[-1].plain
    assert foot.index("not chosen") < foot.index("◀ you chose this")
    left_edge, right_edge = (str(span.style) for span in lines[0].spans[:2])
    assert left_edge != right_edge


def test_the_replies_get_every_row_the_cards_leave() -> None:
    async def scenario(size: tuple[int, int]) -> tuple[int, list[str]]:
        app = BedlamApp(1729, ScriptedPatchSource(), lambda app: asyncio.sleep(3600))
        async with app.run_test(size=size) as pilot:
            for cycle, fault in ((1, "db.timeout.0"), (2, "cache.connection_cut")):
                app._cycles[cycle] = {"injecting": {"fault": fault}}
            app.on_loop_event("trade_off", {"trade_off": TRADE_OFF_FIELDS})
            await pilot.pause(0.2)
            await pilot.pause(0.2)
            strip = app.query_one("#postmortem")
            rows = [s.text for s in app.screen._compositor.render_strips()]
            assert all(len(row) == size[0] for row in rows)
            return (strip.size.height if strip.display else 0), rows

    small, rows = asyncio.run(scenario(SIZE))
    assert small >= 3, "at 82 x 30 the replies still show"
    tall, rows = asyncio.run(scenario((SIZE[0], 45)))
    assert tall >= 12, "a taller screen goes to the replies, not the cards"
    assert any("how you got here" in row for row in rows)
    assert any("R2  cache.connection_cut" in row for row in rows)


def test_the_field_is_a_thin_band_from_a_to_b_in_two_shades() -> None:
    plain = [line.plain for line in postmortem_field()]
    assert len(plain) == 14 and all(len(row) == 78 for row in plain)
    cells = "".join(plain)
    assert set(cells) <= {" ", "░", "▒", "A", "B"}, "only two shades, never a blob"
    ink = sum(c in "░▒" for c in cells) / len(cells)
    assert 0.25 <= ink <= 0.30
    assert plain[-1][16] == "A" and plain[-1][61] == "B"
    assert plain[-1][14:19] == "  A  " and plain[-1][59:64] == "  B  ", "labels kept clear"
    assert plain[3].rstrip().endswith("▒") and plain[10].startswith("░░▒"), "it rises A to B"


def test_the_field_fills_the_empty_replies_and_the_first_reply_takes_its_place() -> None:
    async def scenario(size: tuple[int, int]) -> tuple[list[str], list[str], bool]:
        app = BedlamApp(1729, ScriptedPatchSource(), lambda app: asyncio.sleep(3600))
        async with app.run_test(size=size) as pilot:
            app.on_loop_event("trade_off", {"trade_off": TRADE_OFF_FIELDS})
            for _ in range(3):
                await pilot.pause(0.2)
            before = [s.text for s in app.screen._compositor.render_strips()]
            await pilot.press("slash", *"cycles", "enter")
            await pilot.pause(0.3)
            after = [s.text for s in app.screen._compositor.render_strips()]
            return before, after, app.query_one("#postmortem").has_class("-field")

    before, after, field_left = asyncio.run(scenario((82, 45)))
    band = [row for row in before if "▒" in row]
    assert band, "the field should show in the empty replies"
    assert all(len(row) == 82 for row in before)
    assert any(row.startswith("│ ░░") or row.startswith("│ ▒▒") for row in before), "│ + space"
    assert not any("▒" in row for row in after) and not field_left, "a reply replaces it"
    small, _, _ = asyncio.run(scenario((82, 30)))
    assert not any("▒" in row for row in small), "5 rows cannot hold a 14-row field"


@pytest.mark.parametrize("rows", [7, 8, 11])
def test_a_shorter_log_gets_the_same_band_scaled(rows: int) -> None:
    plain = [line.plain for line in postmortem_field(rows)]
    assert len(plain) == rows and all(len(row) == 78 for row in plain)
    ink = sum(c in "░▒" for c in "".join(plain)) / (78 * rows)
    assert 0.24 <= ink <= 0.33
    assert plain[-1][16] == "A" and plain[-1][61] == "B"
    assert plain[-1][14:19] == "  A  " and plain[-1][59:64] == "  B  "
