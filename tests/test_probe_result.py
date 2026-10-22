"""How a probe's error reads on screen and to the classifier."""

from __future__ import annotations

import httpx

from bedlam.probes.result import describe


def test_a_bare_timeout_says_how_long_the_probe_waited() -> None:
    assert describe(TimeoutError(), 2.0) == "TimeoutError: no answer in 2000 ms"


def test_an_empty_httpx_timeout_says_how_long_the_probe_waited() -> None:
    assert describe(httpx.ReadTimeout(""), 6.0) == "ReadTimeout: no answer in 6000 ms"


def test_a_message_is_kept() -> None:
    assert describe(ConnectionResetError("reset by peer"), 2.0) == (
        "ConnectionResetError: reset by peer"
    )


def test_no_message_leaves_no_trailing_colon() -> None:
    assert describe(ConnectionError(), 2.0) == "ConnectionError"


def test_the_type_comes_first_for_the_classifier() -> None:
    assert describe(TimeoutError(), 2.0).split(":", 1)[0] == "TimeoutError"
