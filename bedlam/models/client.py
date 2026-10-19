"""Token Factory wrapper: retries, logged fallback, one record per call.

Every model call in Bedlam goes through `ModelClient.json()`. It resolves
the call site's parameters from the model map, tries the primary model,
falls back down the chain (Super -> Nano) when the primary is exhausted, and
records every attempt -- site, model, tokens, latency, outcome -- in
`ModelClient.records`. The trace and the TUI read those records; model
attribution on screen is a deliverable, not debug output.

A fallback is logged as a WARNING event and flagged on its record. It is
never silent.

The network sits behind `ChatTransport` so tests can drive the whole
decision chain with a scripted transport and no API key.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any, Protocol

from openai import AsyncOpenAI

from bedlam import prompts
from bedlam.logging import get_logger, log_event
from bedlam.models.map import CallSite, spec_for

_LOG = get_logger("bedlam.models.client")

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)


class ModelCallError(RuntimeError):
    """Every model in a call site's chain failed or returned unusable output."""


@dataclass(frozen=True, slots=True)
class ChatResponse:
    content: str | None
    prompt_tokens: int | None
    completion_tokens: int | None


class ChatTransport(Protocol):
    async def __call__(
        self,
        *,
        site: CallSite,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        seed: int | None,
        thinking: bool,
    ) -> ChatResponse: ...


class OpenAITransport:
    """The real transport: Nebius Token Factory's OpenAI-compatible endpoint."""

    def __init__(
        self, api_key: str | None = None, base_url: str | None = None, timeout_s: float = 90.0
    ) -> None:
        key = api_key or os.environ.get("NEBIUS_API_KEY")
        if not key:
            raise RuntimeError("NEBIUS_API_KEY is not set. Copy .env.example to .env.")
        self._client = AsyncOpenAI(
            api_key=key,
            base_url=base_url
            or os.environ.get("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1/"),
            timeout=timeout_s,
            # Retries are ModelClient's job, so each attempt gets its own record.
            max_retries=0,
        )

    async def __call__(
        self,
        *,
        site: CallSite,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        seed: int | None,
        thinking: bool,
    ) -> ChatResponse:
        resp = await self._client.chat.completions.create(
            model=model,
            messages=messages,  # type: ignore[arg-type]
            temperature=temperature,
            max_tokens=max_tokens,
            seed=seed,
            extra_body={"chat_template_kwargs": {"enable_thinking": thinking}},
        )
        usage = resp.usage
        return ChatResponse(
            content=resp.choices[0].message.content,
            prompt_tokens=usage.prompt_tokens if usage else None,
            completion_tokens=usage.completion_tokens if usage else None,
        )

    async def aclose(self) -> None:
        await self._client.close()


@dataclass(frozen=True, slots=True)
class CallRecord:
    """One attempt against one model. A retried call leaves several records."""

    index: int
    cycle: int | None
    site: str
    model: str
    requested_model: str
    fallback: bool
    attempt: int
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_ms: float
    outcome: str  # "ok" | "error" | "invalid"
    error: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def extract_json(content: str | None) -> Any:
    """The first JSON value in a model reply.

    Tolerates a leaked `<think>` block, markdown fences and prose before the
    object -- all things a reasoning model emits even when asked not to.
    """
    if not content:
        raise ValueError("empty reply")
    text = _THINK_BLOCK.sub("", content)
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[1]
    starts = [i for i in (text.find("{"), text.find("[")) if i != -1]
    if not starts:
        raise ValueError("no JSON value in reply")
    value, _ = json.JSONDecoder().raw_decode(text[min(starts) :])
    return value


class ModelClient:
    """Calls a site's model chain and keeps a record of every attempt."""

    def __init__(
        self,
        transport: ChatTransport,
        *,
        root_seed: int,
        attempts_per_model: int = 2,
        backoff_s: float = 0.5,
    ) -> None:
        self._transport = transport
        self._root_seed = root_seed
        self._attempts = attempts_per_model
        self._backoff_s = backoff_s
        self._cycle: int | None = None
        self.records: list[CallRecord] = []

    def set_cycle(self, cycle: int | None) -> None:
        """Tag subsequent records with the loop cycle they belong to."""
        self._cycle = cycle

    async def json[T](
        self,
        site: CallSite,
        *,
        system: str,
        user: str,
        parse: Callable[[Any], T],
    ) -> T:
        """Call `site`, decode the reply as JSON and validate it with `parse`.

        `parse` raises `ValueError` (or `KeyError`/`TypeError`) on output that
        does not fit the site's contract; that counts as a failed attempt and
        is retried, then falls back, exactly like a transport error. The
        retry carries the rejected reply and the reason it was rejected: at
        temperature 0 a bare retry repeats the same request and usually gets
        the same invalid answer back.

        Raises:
            ModelCallError: if every model in the chain is exhausted.
        """
        spec = spec_for(site, root_seed=self._root_seed)
        chain = [spec.model] + ([spec.fallback] if spec.fallback else [])
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        last_error = "no attempt made"

        for position, model in enumerate(chain):
            is_fallback = position > 0
            if is_fallback:
                _LOG.warning(
                    "model fallback",
                    extra={
                        "fields": {
                            "site": site.value,
                            "from_model": chain[position - 1],
                            "to_model": model,
                            "reason": last_error,
                        }
                    },
                )
            # A correction is for the model that produced the bad reply; a
            # fallback model starts from the original request.
            attempt_messages = messages
            for attempt in range(1, self._attempts + 1):
                started = time.perf_counter()
                response: ChatResponse | None = None
                try:
                    response = await self._transport(
                        site=site,
                        model=model,
                        messages=attempt_messages,
                        temperature=spec.temperature,
                        max_tokens=spec.max_tokens,
                        seed=spec.seed,
                        thinking=spec.thinking,
                    )
                    value = parse(extract_json(response.content))
                except (ValueError, KeyError, TypeError) as exc:
                    last_error = f"invalid output: {exc}"
                    self._record(
                        site,
                        model,
                        spec.model,
                        is_fallback,
                        attempt,
                        response,
                        started,
                        "invalid",
                        last_error,
                    )
                    if response is not None:
                        attempt_messages = [
                            *messages,
                            {"role": "assistant", "content": response.content},
                            {
                                "role": "user",
                                "content": f"{prompts.load('invalid_output_retry')}\n\n"
                                f"Reason: {exc}",
                            },
                        ]
                    continue
                except Exception as exc:  # noqa: BLE001 - any transport failure is retried
                    last_error = f"{type(exc).__name__}: {exc}"
                    self._record(
                        site,
                        model,
                        spec.model,
                        is_fallback,
                        attempt,
                        None,
                        started,
                        "error",
                        last_error,
                    )
                    await asyncio.sleep(self._backoff_s * attempt)
                    continue
                self._record(
                    site, model, spec.model, is_fallback, attempt, response, started, "ok", None
                )
                return value

        raise ModelCallError(f"{site.value}: every model in {chain} failed ({last_error})")

    def _record(
        self,
        site: CallSite,
        model: str,
        requested_model: str,
        fallback: bool,
        attempt: int,
        response: ChatResponse | None,
        started: float,
        outcome: str,
        error: str | None,
    ) -> None:
        record = CallRecord(
            index=len(self.records),
            cycle=self._cycle,
            site=site.value,
            model=model,
            requested_model=requested_model,
            fallback=fallback,
            attempt=attempt,
            prompt_tokens=response.prompt_tokens if response else None,
            completion_tokens=response.completion_tokens if response else None,
            latency_ms=round((time.perf_counter() - started) * 1000, 1),
            outcome=outcome,
            error=error,
        )
        self.records.append(record)
        log_event(_LOG, "model call", **record.to_dict())
