"""Record a live run's external inputs, and replay them.

Token Factory is not deterministic at temperature 0 with a fixed seed, so
two live runs with one seed can diverge (see SESSION_HISTORY 2026-10-19).
What Bedlam can guarantee is narrower and checkable: given the same model
replies, Tavily results and probe snapshots, it makes the same decisions.

A recording holds everything that crosses the process boundary into a
decision: every model request and its reply, every Tavily query and its raw
response, and every probe snapshot. Replay serves them back, and only to an
identical request. A request the recording does not hold means Bedlam's own
code diverged, and replay fails loudly rather than guessing.

Recording is for the determinism test. It is not a demo path: a live run
always calls Tavily at runtime.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bedlam.models.client import ChatResponse, ChatTransport
from bedlam.models.map import CallSite
from bedlam.probes.result import HealthStatus, ProbeResult
from bedlam.search.tavily import SearchBackend
from bedlam.topology import Layer

Probe = Callable[[], Awaitable[dict[Layer, ProbeResult]]]

FORMAT_VERSION = 1


class ReplayMismatchError(AssertionError):
    """Replay was asked for something the recording does not hold."""


def _request_key(
    site: CallSite,
    model: str,
    messages: list[dict[str, str]],
    temperature: float,
    max_tokens: int,
    seed: int | None,
    thinking: bool,
) -> str:
    body = json.dumps(
        [site.value, model, messages, temperature, max_tokens, seed, thinking],
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


@dataclass
class Recording:
    """Every external input of one run, in the order it arrived."""

    root_seed: int
    fault_sequence: list[str] = field(default_factory=list)
    model_calls: list[dict[str, Any]] = field(default_factory=list)
    searches: list[dict[str, Any]] = field(default_factory=list)
    probes: list[dict[str, Any]] = field(default_factory=list)

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        body = {
            "format_version": FORMAT_VERSION,
            "root_seed": self.root_seed,
            "fault_sequence": self.fault_sequence,
            "model_calls": self.model_calls,
            "searches": self.searches,
            "probes": self.probes,
        }
        path.write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    @classmethod
    def read(cls, path: Path) -> Recording:
        body = json.loads(path.read_text(encoding="utf-8"))
        if body.get("format_version") != FORMAT_VERSION:
            raise ValueError(f"{path}: unsupported recording format {body.get('format_version')}")
        return cls(
            root_seed=body["root_seed"],
            fault_sequence=body["fault_sequence"],
            model_calls=body["model_calls"],
            searches=body["searches"],
            probes=body["probes"],
        )


# --- recording ----------------------------------------------------------------


class RecordingTransport:
    """Passes every call through to `inner` and records request and reply."""

    def __init__(self, inner: ChatTransport, recording: Recording) -> None:
        self._inner = inner
        self._recording = recording

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
        entry: dict[str, Any] = {
            "key": _request_key(site, model, messages, temperature, max_tokens, seed, thinking),
            "site": site.value,
            "model": model,
            "messages": messages,
        }
        try:
            response = await self._inner(
                site=site,
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                seed=seed,
                thinking=thinking,
            )
        except Exception as exc:
            entry["error"] = f"{type(exc).__name__}: {exc}"
            self._recording.model_calls.append(entry)
            raise
        entry["response"] = {
            "content": response.content,
            "prompt_tokens": response.prompt_tokens,
            "completion_tokens": response.completion_tokens,
        }
        self._recording.model_calls.append(entry)
        return response

    async def aclose(self) -> None:
        close = getattr(self._inner, "aclose", None)
        if close is not None:
            await close()


class RecordingSearchBackend:
    """Passes every search through to `inner` and records the raw response."""

    def __init__(self, inner: SearchBackend, recording: Recording) -> None:
        self._inner = inner
        self._recording = recording

    async def search(self, query: str) -> dict[str, Any]:
        raw = await self._inner.search(query)
        self._recording.searches.append({"query": query, "response": raw})
        return raw


def recording_probe(inner: Probe, recording: Recording) -> Probe:
    async def probe() -> dict[Layer, ProbeResult]:
        results = await inner()
        recording.probes.append(
            {
                layer.value: {
                    "status": result.status.value,
                    "latency_ms": result.latency_ms,
                    "error": result.error,
                }
                for layer, result in results.items()
            }
        )
        return results

    return probe


# --- replay -------------------------------------------------------------------


class ReplayTransport:
    """Answers each model request with the reply recorded for it.

    `ModelClient` treats any transport exception as retryable, and synthesis
    survives a failed call by falling back to its tools, so a raised mismatch
    can be absorbed. Every mismatch is also kept in `mismatches`.
    """

    def __init__(self, recording: Recording) -> None:
        self.mismatches: list[str] = []
        self._replies: dict[str, deque[dict[str, Any]]] = defaultdict(deque)
        for entry in recording.model_calls:
            self._replies[entry["key"]].append(entry)

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
        key = _request_key(site, model, messages, temperature, max_tokens, seed, thinking)
        if not self._replies[key]:
            message = (
                f"{site.value} ({model}): request not in the recording. Either the decision "
                "chain diverged, or a prompt or model-map change made the recording stale "
                "(re-record with `make record`)."
            )
            self.mismatches.append(message)
            raise ReplayMismatchError(message)
        entry = self._replies[key].popleft()
        if "error" in entry:
            raise RuntimeError(f"recorded error: {entry['error']}")
        reply = entry["response"]
        return ChatResponse(
            content=reply["content"],
            prompt_tokens=reply["prompt_tokens"],
            completion_tokens=reply["completion_tokens"],
        )

    def unused(self) -> int:
        """Recorded replies replay never asked for. Zero after a faithful replay."""
        return sum(len(queue) for queue in self._replies.values())


class ReplaySearchBackend:
    """Answers each Tavily query with the raw response recorded for it."""

    def __init__(self, recording: Recording) -> None:
        self._responses: dict[str, deque[dict[str, Any]]] = defaultdict(deque)
        for entry in recording.searches:
            self._responses[entry["query"]].append(entry["response"])

    async def search(self, query: str) -> dict[str, Any]:
        if not self._responses[query]:
            raise ReplayMismatchError(f"Tavily query not in the recording: {query!r}")
        return self._responses[query].popleft()

    def unused(self) -> int:
        return sum(len(queue) for queue in self._responses.values())


class ReplayProbe:
    """Returns the recorded probe snapshots, in order."""

    def __init__(self, recording: Recording) -> None:
        self._snapshots = deque(recording.probes)

    async def __call__(self) -> dict[Layer, ProbeResult]:
        if not self._snapshots:
            raise ReplayMismatchError("more probe snapshots requested than were recorded")
        return {
            Layer(layer): ProbeResult(
                Layer(layer), HealthStatus(r["status"]), r["latency_ms"], r["error"]
            )
            for layer, r in self._snapshots.popleft().items()
        }

    def unused(self) -> int:
        return len(self._snapshots)
