"""Live Tavily search, cached within one run and never across runs.

The call happens at runtime, during the loop -- there are no pre-fetched
fixtures on the demo path, so a judge sees the live call happen. Each
`SearchClient` owns a fresh cache; a new run builds a new client.

Domains: GitHub issues and PRs plus blogs, Q&A and changelogs, where failure
narratives live. Structured vulnerability databases are excluded on purpose:
they hold CVEs, not "why the pool never recovers".
"""

from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass
from typing import Any, Final, Protocol

from tavily import AsyncTavilyClient

from bedlam.logging import get_logger, log_event

_LOG = get_logger("bedlam.search.tavily")

INCLUDE_DOMAINS: Final = (
    "github.com",
    "stackoverflow.com",
    "dev.to",
    "medium.com",
    "readthedocs.io",
    "sqlalchemy.org",
    "redis.io",
)
EXCLUDE_DOMAINS: Final = ("nvd.nist.gov", "osv.dev")

# Source-file and commit links are code, not failure narratives.
_NOISE_PATH_MARKERS: Final = ("/commit/", "/blob/")
_SNIPPET_CHARS: Final = 600
MAX_RESULTS: Final = 5
# What one live call costs at search_depth="advanced"; a cached one is free.
CREDITS_PER_SEARCH: Final = 2


@dataclass(frozen=True, slots=True)
class SearchResult:
    query: str
    url: str
    title: str
    content: str
    score: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SearchCall:
    query: str
    cached: bool
    latency_ms: float
    results: int
    filtered: int
    outcome: str
    error: str | None


class SearchBackend(Protocol):
    async def search(self, query: str) -> dict[str, Any]: ...


class TavilyBackend:
    """The real backend: one Tavily search per call."""

    def __init__(self, api_key: str | None = None) -> None:
        key = api_key or os.environ.get("TAVILY_API_KEY")
        if not key:
            raise RuntimeError("TAVILY_API_KEY is not set. Copy .env.example to .env.")
        self._client = AsyncTavilyClient(api_key=key)

    async def search(self, query: str) -> dict[str, Any]:
        return await self._client.search(
            query=query,
            search_depth="advanced",
            max_results=MAX_RESULTS,
            include_domains=list(INCLUDE_DOMAINS),
            exclude_domains=list(EXCLUDE_DOMAINS),
        )


class SearchClient:
    """Searches through a backend, with a cache scoped to this instance."""

    def __init__(self, backend: SearchBackend) -> None:
        self._backend = backend
        self._cache: dict[str, tuple[SearchResult, ...]] = {}
        self.calls: list[SearchCall] = []

    async def search(self, query: str) -> tuple[SearchResult, ...]:
        if query in self._cache:
            self._log(SearchCall(query, True, 0.0, len(self._cache[query]), 0, "ok", None))
            return self._cache[query]

        started = time.perf_counter()
        try:
            raw = await self._backend.search(query)
        except Exception as exc:
            self._log(
                SearchCall(query, False, _elapsed(started), 0, 0, "error", type(exc).__name__)
            )
            raise
        results, filtered = _parse(query, raw)
        self._cache[query] = results
        self._log(SearchCall(query, False, _elapsed(started), len(results), filtered, "ok", None))
        return results

    def _log(self, call: SearchCall) -> None:
        self.calls.append(call)
        log_event(_LOG, "tavily search", **asdict(call))


def _elapsed(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


def _parse(query: str, raw: dict[str, Any]) -> tuple[tuple[SearchResult, ...], int]:
    kept: list[SearchResult] = []
    filtered = 0
    for item in raw.get("results", []):
        url = str(item.get("url", ""))
        if not url or any(marker in url for marker in _NOISE_PATH_MARKERS):
            filtered += 1
            continue
        kept.append(
            SearchResult(
                query=query,
                url=url,
                title=str(item.get("title", "")),
                content=" ".join(str(item.get("content") or "").split())[:_SNIPPET_CHARS],
                score=round(float(item.get("score") or 0.0), 4),
            )
        )
    return tuple(kept), filtered


def merge(batches: list[tuple[SearchResult, ...]]) -> tuple[SearchResult, ...]:
    """Dedupe by URL (highest score wins), then a stable order: score, then URL.

    A stable order matters: the same results in the same order give the same
    classifier input, and so the same routing, on the next run.
    """
    best: dict[str, SearchResult] = {}
    for batch in batches:
        for result in batch:
            if result.url not in best or result.score > best[result.url].score:
                best[result.url] = result
    return tuple(sorted(best.values(), key=lambda r: (-r.score, r.url)))
