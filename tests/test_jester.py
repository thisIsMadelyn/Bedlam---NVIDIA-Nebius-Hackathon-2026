"""The jester: one mood per voice event, every frame the same size."""

from __future__ import annotations

import pytest
from rich.cells import cell_len

from bedlam import jester
from bedlam.jester import Mood, mood_for
from bedlam.voice import event_key

COLOURS = {role: "#000000" for role in ("accent", "ink", "muted", "go", "soft", "text")}


@pytest.mark.parametrize("mood", list(Mood))
def test_every_mood_is_three_rows_of_the_same_width(mood: Mood) -> None:
    rows = jester.render(mood, COLOURS).plain.split("\n")
    assert len(rows) == 3
    assert [cell_len(row) for row in rows] == [jester.WIDTH] * 3


@pytest.mark.parametrize(
    ("kind", "fields", "mood"),
    [
        ("baseline", {"snapshot": {}}, Mood.IDLE),
        ("injecting", {"kind": "timeout", "layer": "db"}, Mood.STRIKING),
        ("symptom", {"symptom": {"kind": "stalled", "layer": "db"}}, Mood.GLOATING),
        ("symptom", {"symptom": {"kind": "healthy", "layer": None}}, Mood.SULKING),
        ("awaiting_patch", {"cycle": 1}, Mood.YOUR_TURN),
        ("trade_off", {}, Mood.TWO_FACED),
    ],
)
def test_the_mood_follows_the_voice_event_key(kind: str, fields: dict, mood: Mood) -> None:
    assert mood_for(event_key(kind, fields), Mood.SCHEMING) == mood


def test_an_event_without_a_mood_keeps_the_last_one() -> None:
    assert mood_for("probing", Mood.GLOATING) is Mood.GLOATING


def test_the_splash_is_the_jester_with_the_wordmark_centred_under_it() -> None:
    rows = jester.splash({**COLOURS, "background": "#000000"}).plain.split("\n")
    assert len(rows) == jester.SPLASH_HEIGHT
    assert all(cell_len(row) <= jester.SPLASH_WIDTH for row in rows)
    art, wordmark = rows[:15], rows[-3:]
    assert all(cell_len(row) == jester.SPLASH_WIDTH for row in art)
    assert rows[15] == ""
    left = len(wordmark[0]) - len(wordmark[0].lstrip())
    assert left == (jester.SPLASH_WIDTH - len(wordmark[0].strip())) // 2
