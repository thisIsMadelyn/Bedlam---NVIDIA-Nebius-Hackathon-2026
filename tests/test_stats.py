"""Container load: parsed from the Docker CLI, shown per layer, display only."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

import pytest
from test_tui import LAYERS, SIZE

from bedlam.patches import ScriptedPatchSource
from bedlam.stats import ContainerStats, StatsUnavailable, parse_bytes, read
from bedlam.topology import Layer
from bedlam.tui import BedlamApp, sparkline

_PS = "api\t28765a0497ad\npostgres\tafb51edad80a\nredis\t50b85514b38e\ntoxiproxy\td3bd10bc13ee\n"
_STATS = (
    "28765a0497ad\t0.86%\t219.7MiB / 7.57GiB\n"
    "afb51edad80a\t0.00%\t33.48MiB / 7.57GiB\n"
    "50b85514b38e\t112.40%\t3.41MiB / 7.57GiB\n"
)


def _runner(ps: str = _PS, stats: str = _STATS):
    calls: list[list[str]] = []

    def run(args: Sequence[str]) -> str:
        calls.append(list(args))
        return ps if args[1] == "compose" else stats

    return run, calls


@pytest.mark.parametrize(
    ("text", "expected"),
    [("219.7MiB", round(219.7 * 1024**2)), ("3.41MiB", round(3.41 * 1024**2)),
     ("1.5GiB", round(1.5 * 1024**3)), ("512kB", 512_000), ("0B", 0)],
)  # fmt: skip
def test_memory_amounts_parse_in_every_unit_docker_prints(text: str, expected: int) -> None:
    assert parse_bytes(text) == expected


def test_only_the_target_stacks_containers_are_asked_and_mapped_to_layers() -> None:
    run, calls = _runner()
    stats = read(run)
    asked = calls[1][5:]
    assert asked == ["28765a0497ad", "afb51edad80a", "50b85514b38e"], "toxiproxy or others asked"
    assert stats[Layer.API] == ContainerStats(0.86, round(219.7 * 1024**2))
    assert stats[Layer.CACHE].cpu_percent == 112.4


def test_no_running_stack_is_reported_not_crashed() -> None:
    run, _ = _runner(ps="")
    with pytest.raises(StatsUnavailable, match="make up"):
        read(run)


def test_a_container_without_a_sample_is_reported_not_crashed() -> None:
    run, _ = _runner(stats="28765a0497ad\t--\t-- / --\n")
    with pytest.raises(StatsUnavailable, match="docker stats"):
        read(run)


def test_sparkline_tops_out_at_one_core_or_the_peak() -> None:
    assert sparkline([]) == ""
    assert sparkline([0.0, 100.0]) == "▁█"
    assert sparkline([50.0, 200.0])[-1] == "█"


def _app(source) -> BedlamApp:
    return BedlamApp(1729, ScriptedPatchSource(), lambda app: asyncio.sleep(3600), stats=source)


def _system_rows(app: BedlamApp) -> list[str]:
    strips = app.screen._compositor.render_strips()
    return [s.text for s in strips if s.text[2:].split(" ")[0] in LAYERS]


def test_each_layer_line_shows_cpu_and_memory_inside_82_columns() -> None:
    async def fake() -> dict[Layer, ContainerStats]:
        return {layer: ContainerStats(12.3, 230 * 1024**2) for layer in Layer}

    async def scenario() -> None:
        app = _app(fake)
        async with app.run_test(size=SIZE) as pilot:
            slow = {"status": "up", "latency_ms": 2001.0, "error": "Timeout"}
            snapshot = {layer: slow for layer in LAYERS}
            app.on_loop_event("baseline", {"snapshot": snapshot})
            await pilot.pause(0.3)
            rows = _system_rows(app)
            assert len(rows) == len(LAYERS)
            for row in rows:
                assert "cpu  12.3%" in row and "mem  230M" in row, row
                assert len(row) == SIZE[0]
            assert "docker stats" in str(app.query_one("#system").border_subtitle)

    asyncio.run(scenario())


def test_docker_unavailable_says_so_and_keeps_the_panel() -> None:
    async def broken() -> dict[Layer, ContainerStats]:
        raise StatsUnavailable("docker: not found")

    async def scenario() -> None:
        app = _app(broken)
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause(0.3)
            assert "unavailable" in str(app.query_one("#system").border_subtitle)
            assert not any("cpu" in row for row in _system_rows(app))

    asyncio.run(scenario())
