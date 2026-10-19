"""Model client: retries, logged fallback, records, JSON extraction."""

from __future__ import annotations

import asyncio
import logging

import pytest
from fakes import FakeTransport

from bedlam.models.client import ModelCallError, ModelClient, extract_json
from bedlam.models.map import NANO, SUPER, CallSite, spec_for


def _client(handler) -> tuple[ModelClient, FakeTransport]:
    transport = FakeTransport({site: handler for site in CallSite})
    return ModelClient(transport, root_seed=1729, backoff_s=0.0), transport


def _ask(client: ModelClient, site: CallSite = CallSite.DIFF_ANALYSIS):
    return asyncio.run(client.json(site, system="s", user="{}", parse=lambda v: v["ok"]))


def test_super_failure_falls_back_to_nano_and_says_so(caplog: pytest.LogCaptureFixture) -> None:
    def handler(_ctx, model):
        return RuntimeError("503") if model == SUPER else {"ok": True}

    client, transport = _client(handler)
    logger = logging.getLogger("bedlam.models.client")
    logger.addHandler(caplog.handler)
    try:
        assert _ask(client) is True
    finally:
        logger.removeHandler(caplog.handler)

    assert [m for _, m, _ in transport.calls] == [SUPER, SUPER, NANO]
    assert [(r.model, r.outcome, r.fallback) for r in client.records] == [
        (SUPER, "error", False),
        (SUPER, "error", False),
        (NANO, "ok", True),
    ]
    assert all(r.site == "diff_analysis" for r in client.records)
    assert any(rec.getMessage() == "model fallback" for rec in caplog.records)


def test_invalid_output_is_retried_like_an_error() -> None:
    replies = iter(["not json at all", {"ok": 1}])
    client, _ = _client(lambda _ctx, _model: next(replies))
    assert _ask(client, CallSite.PROBE_CLASSIFICATION) == 1
    assert [r.outcome for r in client.records] == ["invalid", "ok"]


def test_retry_after_invalid_output_carries_the_rejection_reason() -> None:
    # At temperature 0 a bare retry gets the same bad answer back, so the
    # retry must show the model its reply and why it was rejected.
    replies = iter([{"ok": "first"}, {"ok": "second"}])

    def parse(value):
        if value["ok"] == "first":
            raise ValueError("need 2 new queries on distinct dependencies")
        return value["ok"]

    client, transport = _client(lambda _ctx, _model: next(replies))
    result = asyncio.run(
        client.json(CallSite.TAVILY_QUERY_FORMULATION, system="s", user="{}", parse=parse)
    )

    assert result == "second"
    first, retry = transport.messages
    assert len(first) == 2
    assert retry[:2] == first
    assert retry[2] == {"role": "assistant", "content": '{"ok": "first"}'}
    assert retry[3]["role"] == "user"
    assert "need 2 new queries on distinct dependencies" in retry[3]["content"]


def test_fallback_model_gets_the_original_request_not_the_correction() -> None:
    def handler(_ctx, model):
        return "not json" if model == SUPER else {"ok": True}

    client, transport = _client(handler)
    assert _ask(client) is True
    assert [len(m) for m in transport.messages] == [2, 4, 2]


def test_nano_site_has_no_fallback_and_raises_when_exhausted() -> None:
    client, transport = _client(lambda _ctx, _model: {"wrong": 1})
    with pytest.raises(ModelCallError):
        _ask(client, CallSite.LAYER_CLASSIFICATION)
    assert {m for _, m, _ in transport.calls} == {NANO}


def test_every_call_carries_the_seed_from_the_map() -> None:
    client, transport = _client(lambda _ctx, _model: {"ok": 1})
    _ask(client, CallSite.FAULT_SELECTION)
    assert transport.calls[0][2] == spec_for(CallSite.FAULT_SELECTION, root_seed=1729).seed


@pytest.mark.parametrize(
    "reply",
    [
        '{"a": 1}',
        '<think>maybe {"a": 2}</think>{"a": 1}',
        'reasoning... </think>\n```json\n{"a": 1}\n```',
        'Sure! Here it is: {"a": 1} hope that helps',
    ],
)
def test_extract_json_tolerates_reasoning_model_habits(reply: str) -> None:
    assert extract_json(reply) == {"a": 1}
