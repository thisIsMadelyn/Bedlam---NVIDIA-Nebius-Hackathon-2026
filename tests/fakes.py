"""Offline stand-ins for Token Factory, Tavily, Toxiproxy and the probes.

The fake model answers each call site from the JSON context it receives, the
way a well-behaved model would, so the loop's real parsing, validation and
routing code runs unchanged. Nothing here touches the network.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from bedlam.models.client import ChatResponse
from bedlam.models.map import CallSite
from bedlam.probes.app import AppResult
from bedlam.probes.result import HealthStatus, ProbeResult
from bedlam.topology import Layer

Handler = Callable[[dict[str, Any], str], Any]


class FakeTransport:
    """Answers per call site. A handler returning an Exception raises it."""

    def __init__(self, handlers: dict[CallSite, Handler]) -> None:
        self._handlers = handlers
        self.calls: list[tuple[CallSite, str, int | None]] = []
        self.messages: list[list[dict[str, str]]] = []

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
        self.calls.append((site, model, seed))
        self.messages.append(messages)
        answer = self._handlers[site](json.loads(messages[1]["content"]), model)
        if isinstance(answer, Exception):
            raise answer
        content = answer if isinstance(answer, str) else json.dumps(answer)
        return ChatResponse(content=content, prompt_tokens=100, completion_tokens=20)


# --- a plausible model, site by site ---------------------------------------

_LAYER_WORDS = {
    "cache": ("redis", "taskiq", "cache"),
    "db": ("asyncpg", "sqlalchemy", "postgres", "pool"),
    "api": ("uvicorn", "starlette", "fastapi"),
}


def _label_of(text: str) -> tuple[str, str]:
    """(component, layer): the first known component the text mentions."""
    low = text.lower()
    for layer, words in _LAYER_WORDS.items():
        for word in words:
            if word in low:
                return word, layer
    return "unknown", "none"


def answer_query_formulation(ctx: dict[str, Any], _model: str) -> Any:
    used = {q.split(" ", 1)[0] for q in ctx["previous_queries"]}
    preferred = ["redis", "asyncpg", "sqlalchemy", "uvicorn", "taskiq-redis"]
    picks = [d for d in preferred if d in ctx["dependencies"] and d not in used]
    return {
        "queries": [
            {"dependency": dep, "failure_term": "connection hangs under timeout"}
            for dep in picks[: ctx["query_count"]]
        ]
    }


def answer_layer_classification(ctx: dict[str, Any], _model: str) -> Any:
    return {
        "labels": [
            {"index": r["index"], "component": component, "layer": layer}
            for r in ctx["results"]
            for component, layer in [_label_of(r["title"] + " " + r["snippet"])]
        ]
    }


def answer_synthesis(ctx: dict[str, Any], _model: str) -> Any:
    done = {f["fault_id"] for f in ctx["faults_so_far"]}
    url = ctx["evidence"][0]["url"]
    return {
        "candidates": [
            {
                "fault_id": tool["id"],
                "hypothesis": f"evidence suggests {tool['id']}",
                "evidence": [url],
            }
            for tool in ctx["tools"]
            if tool["id"] not in done
        ][:3]
    }


def answer_fault_selection(ctx: dict[str, Any], _model: str) -> Any:
    return {"fault_id": ctx["eligible"][0]["id"], "rationale": "first eligible"}


def answer_probe_classification(ctx: dict[str, Any], _model: str) -> Any:
    for entry in ctx["snapshot"]:
        if entry["status"] == "down":
            return {"symptom": "stalled", "layer": entry["layer"], "summary": "probe timed out"}
    return {"symptom": "healthy", "layer": "none", "summary": "all up"}


def answer_diff_analysis(ctx: dict[str, Any], _model: str) -> Any:
    defended = []
    if "socket_connect_timeout" in ctx["diff"]:
        defended.append({"layer": "cache", "kind": "timeout"})
    if "pool_timeout" in ctx["diff"]:
        defended.append({"layer": "db", "kind": "timeout"})
    return {
        "touched_layers": sorted({d["layer"] for d in defended}) or ["api"],
        "defended": defended,
        "summary": "adds client timeouts",
        "gaps": ["no retry budget on the asyncpg pool"],
    }


def answer_tradeoff_escalation(ctx: dict[str, Any], _model: str) -> Any:
    layer = ctx["faults_so_far"][-1]["layer"]
    return {
        "axis": "fail fast vs wait it out",
        "why": f"both rounds hit how the app treats a late {layer}",
        "options": [
            {
                "title": "Fail fast",
                "gain": "a hung dependency costs one quick error",
                "cost": "errors whenever it is merely slow",
                "cost_layer": layer,
                "cost_felt_when": "slow",
            },
            {
                "title": "Wait it out",
                "gain": "a slow dependency still answers",
                "cost": "requests pile up when it hangs",
                "cost_layer": layer,
                "cost_felt_when": "hangs",
            },
        ],
    }


def plausible_model() -> dict[CallSite, Handler]:
    return {
        CallSite.TAVILY_QUERY_FORMULATION: answer_query_formulation,
        CallSite.LAYER_CLASSIFICATION: answer_layer_classification,
        CallSite.TAVILY_SYNTHESIS: answer_synthesis,
        CallSite.FAULT_SELECTION: answer_fault_selection,
        CallSite.PROBE_CLASSIFICATION: answer_probe_classification,
        CallSite.DIFF_ANALYSIS: answer_diff_analysis,
        CallSite.TRADEOFF_ESCALATION: answer_tradeoff_escalation,
    }


# --- Tavily -----------------------------------------------------------------


def tavily_hit(url: str, title: str, score: float, content: str = "") -> dict[str, Any]:
    return {"url": url, "title": title, "score": score, "content": content or title}


class FakeSearchBackend:
    """Returns canned results keyed on the dependency a query starts with."""

    def __init__(self, by_dependency: dict[str, list[dict[str, Any]]]) -> None:
        self._by_dependency = by_dependency
        self.queries: list[str] = []

    async def search(self, query: str) -> dict[str, Any]:
        self.queries.append(query)
        return {"results": self._by_dependency.get(query.split(" ", 1)[0], [])}


def default_search_results() -> dict[str, list[dict[str, Any]]]:
    return {
        "redis": [
            tavily_hit(
                "https://github.com/redis/redis-py/issues/1", "redis-py hangs on connect", 0.9
            ),
            tavily_hit("https://github.com/redis/redis-py/issues/2", "redis pool exhausted", 0.8),
        ],
        "asyncpg": [
            tavily_hit("https://github.com/MagicStack/asyncpg/issues/3", "asyncpg pool stuck", 0.7),
        ],
        "sqlalchemy": [
            tavily_hit(
                "https://github.com/sqlalchemy/sqlalchemy/issues/4", "sqlalchemy pool", 0.95
            ),
            tavily_hit("https://github.com/sqlalchemy/sqlalchemy/issues/5", "postgres hang", 0.9),
        ],
        "uvicorn": [
            tavily_hit("https://github.com/encode/uvicorn/issues/6", "uvicorn workers starve", 0.5),
        ],
    }


# --- Toxiproxy and probes ---------------------------------------------------


class FakeToxiproxy:
    """Records toxics and fails loudly if two are ever live at once."""

    def __init__(self) -> None:
        self.active: dict[str, str] = {}  # toxic name -> proxy
        self.applied: list[str] = []

    async def list_toxics(self, proxy: str) -> list[dict[str, Any]]:
        return [{"name": name} for name, p in self.active.items() if p == proxy]

    async def create_toxic(self, proxy: str, *, name: str, **_: Any) -> dict[str, Any]:
        # Real Toxiproxy answers 409 Conflict for a name already in use.
        assert name not in self.active, f"409 Conflict: toxic {name} already exists"
        assert not self.active, f"concurrent faults: {self.active} + {name}"
        self.active[name] = proxy
        self.applied.append(name)
        return {}

    async def delete_toxic(self, proxy: str, name: str) -> None:
        self.active.pop(name, None)

    async def clear_toxics(self, proxy: str) -> list[str]:
        names = [t["name"] for t in await self.list_toxics(proxy)]
        for name in names:
            await self.delete_toxic(proxy, name)
        return names


def probe_for(toxiproxy: FakeToxiproxy):
    proxy_layer = {"postgres": Layer.DB, "redis": Layer.CACHE}

    async def probe() -> dict[Layer, ProbeResult]:
        faulted = {proxy_layer[p] for p in toxiproxy.active.values()}
        return {
            layer: (
                ProbeResult(layer, HealthStatus.DOWN, 2001.0, "TimeoutError: ")
                if layer in faulted
                else ProbeResult(layer, HealthStatus.UP, 5.0)
            )
            for layer in Layer
        }

    return probe


def app_probe_for(toxiproxy: FakeToxiproxy, *, patched: Callable[[], bool] = lambda: False):
    """The read through the app: hangs under any fault, unless `patched()`
    says the patch is in, when it fails fast instead."""

    async def probe() -> AppResult:
        if not toxiproxy.active:
            return AppResult(True, 20.0, 200)
        if patched():
            return AppResult(False, 150.0, 503, "HTTP 503")
        return AppResult(False, 6001.0, None, "ReadTimeout: ")

    return probe
