"""The read through the app, and the rule that judges a patch with it."""

from __future__ import annotations

import pytest

from bedlam.probes.app import AppResult, held

HUNG = AppResult(False, 6001.0, None, "ReadTimeout: ")
ERROR_FAST = AppResult(False, 150.0, 503, "HTTP 503")
ERROR_SLOW = AppResult(False, 539.0, 500, "HTTP 500")
ANSWERED = AppResult(True, 180.0, 200)
ANSWERED_SLOW = AppResult(True, 900.0, 200)


@pytest.mark.parametrize(
    ("before", "after", "verdict"),
    [
        (HUNG, ANSWERED, True),  # hanging to answering
        (ERROR_FAST, ANSWERED, True),  # erroring to answering
        (HUNG, ERROR_FAST, True),  # hung, now fails fast: at least twice as fast
        (HUNG, HUNG, False),  # nothing changed
        (ERROR_SLOW, ERROR_FAST, False),  # a faster error is still an error
        (ANSWERED_SLOW, ANSWERED, False),  # a speedup counts only after a hang
        (ANSWERED, ERROR_FAST, False),  # failing where it used to answer is worse
    ],
)
def test_the_held_rule(before: AppResult, after: AppResult, verdict: bool) -> None:
    assert held(before, after) is verdict


def test_text_names_what_happened() -> None:
    assert HUNG.text() == "hung 6001ms"
    assert ERROR_FAST.text() == "503 in 150ms"
    assert ANSWERED.text() == "answered in 180ms"
    assert AppResult(False, 4.0, None, "ConnectError: refused").text() == "failed in 4ms"


def test_a_result_survives_the_trace() -> None:
    assert AppResult.from_dict(ERROR_FAST.to_dict()) == ERROR_FAST
