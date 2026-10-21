"""The trade-off escalation: a real choice, made by the developer, with a visible cost."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fakes import FakeTransport, answer_tradeoff_escalation, plausible_model
from test_loop import _run_once
from test_tui import SIZE, WIDE, _app

from bedlam.escalation import ScriptedChoice, decision_record, escalate
from bedlam.faults.primitives import FaultKind
from bedlam.guide import EARLY_CHOICE, TRADE_OFF
from bedlam.history import FaultRecord
from bedlam.models.client import ModelClient
from bedlam.models.map import CallSite
from bedlam.patches import ScriptedPatchSource
from bedlam.stats import ContainerStats
from bedlam.topology import Layer
from bedlam.tui import LINE, BedlamApp, FaultWindow, GatedChoice, cpu_chart

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
                " A  Fail fast",
                " B  Wait it out",
                "you gain",
                "you pay",
                "felt when db is slow · shown live as db.latency.2500",
                "felt when db hangs · shown live as db.timeout.0",
            ):
                assert text in panel, text
            assert "…" not in panel.split("TRADE-OFF", 1)[1], "a trade-off line was cut"
            await pilot.press("a")
            for _ in range(500):
                if app.exit_code is not None:
                    break
                await asyncio.sleep(0.01)
            await pilot.pause(0.2)
            assert app.exit_code == 0
            assert app.query_one("#system").display, "YOUR APP must show the cost"
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
            assert sum("shown live as" in r for r in panel) == 2, "option B cut off"
            assert "…" not in "".join(panel)

    asyncio.run(scenario())


def _samples(n: int, db: float = 2.0) -> list[dict[Layer, float]]:
    return [{Layer.API: 10.0, Layer.DB: db, Layer.CACHE: 1.0} for _ in range(n)]


def test_the_cpu_chart_fills_its_width_and_keeps_a_spike() -> None:
    for n in (3, 70, 500):
        samples = _samples(n)
        samples[n // 2][Layer.DB] = 95.0  # one spike, whatever the squeeze
        windows = [FaultWindow(n // 3, 2 * n // 3, "R1 db.timeout.0")]
        lines = cpu_chart(samples, windows, LINE, rows=2)
        assert all(len(line.plain) == LINE for line in lines), n
        assert len(lines) == 2 + 2 * len(Layer)
        db_top = lines[2 + 2].plain  # top row of db: api is first
        assert "█" in db_top or "▇" in db_top, f"spike lost at {n} samples"
        assert "R1 db" in lines[1].plain


def test_the_run_so_far_fills_the_spare_height_under_the_trade_off() -> None:
    trade_off = {
        "axis": "fail fast vs wait it out",
        "why": "both rounds hit how the app treats a late db",
        "options": [
            {
                "key": k,
                "title": t,
                "gain": "something",
                "cost": "something else",
                "felt_when": "db hangs",
                "consequence": {"id": "db.timeout.0"},
            }
            for k, t in (("a", "Fail fast"), ("b", "Wait it out"))
        ],
    }
    load = {layer: ContainerStats(5.0, 1 << 20) for layer in Layer}

    async def scenario(size: tuple[int, int], samples: bool) -> list[str]:
        app = BedlamApp(1729, ScriptedPatchSource(), lambda app: asyncio.sleep(3600))
        async with app.run_test(size=size) as pilot:
            if samples:
                for i in range(40):
                    if i == 10:
                        app._cycle = 1
                        app._on_injecting({"fault": "db.timeout.0", "blast_radius": ["api", "db"]})
                    if i == 20:
                        app._on_fault_removed({"snapshot": {}})
                    app.record_load(load)
            app.on_loop_event("trade_off", {"trade_off": trade_off})
            await pilot.pause(0.2)
            rows = [s.text for s in app.screen._compositor.render_strips()]
            assert all(len(row) == size[0] for row in rows)
            return rows

    tall = asyncio.run(scenario(WIDE, samples=True))
    assert any("THE RUN SO FAR" in r for r in tall)
    assert any("R1 db.timeout.0" in r for r in tall)
    assert "…" not in "".join(tall).split("TRADE-OFF", 1)[1]
    # No samples (no Docker): no chart, never a made-up one.
    assert not any("THE RUN SO FAR" in r for r in asyncio.run(scenario(WIDE, samples=False)))
